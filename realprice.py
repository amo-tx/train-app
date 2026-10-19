# -*- coding: utf-8 -*-
"""12306 官方余票/票价接口: 按日期返回各席别真实票价(含浮动折扣)。

价格串格式(每 10 字符一组): <席别字母><5位价格(分)><4位计数>
  例: 9199500019M092900021O055300021D127700021O055303088
  -> 商务座1995.0 一等座929.0 二等座553.0 优选一等座1277.0 二等座553.0
折扣串格式: <席别字母><3位折扣>  例 M0073 = 一等座7.3折
"""
import json
import re
import sqlite3
import ssl
import time
import urllib.parse
import urllib.request
from datetime import date as _date, datetime, timedelta

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 席别字母 -> 中文名
SEAT_CN = {
    "9": "商务座", "P": "特等座", "M": "一等座", "O": "二等座", "D": "优选一等座",
    "W": "无座", "A": "高级软卧", "F": "动卧", "4": "软卧/一等卧", "3": "硬卧/二等卧",
    "1": "硬座", "2": "软座", "6": "高级软卧", "E": "特等座",
}
# 展示优先级: 越靠前越"基础"(定价锚)
SEAT_PRIORITY = ["O", "1", "M", "3", "9", "4", "P", "D", "W", "2", "F", "A", "6", "E"]

_PRICE_RE = re.compile(r"([A-Z0-9])(\d{5})(\d{4})")
_DISC_RE = re.compile(r"([A-Z0-9])(\d{4})")

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE
_cookie = {"value": None, "ts": 0.0}


def _get_cookie():
    """拿 12306 会话 Cookie, 1 小时刷新。"""
    if _cookie["value"] and time.time() - _cookie["ts"] < 3600:
        return _cookie["value"]
    req = urllib.request.Request("https://kyfw.12306.cn/otn/leftTicket/init",
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=10, context=_ctx) as r:
        setc = r.headers.get_all("Set-Cookie") or []
    pairs = []
    for c in setc:
        kv = c.split(";")[0].strip()
        if kv:
            pairs.append(kv)
    val = "; ".join(pairs) or "_uab_collina=1"
    _cookie["value"], _cookie["ts"] = val, time.time()
    return val


def _http_query(date_s, from_tc, to_tc):
    q = urllib.parse.urlencode({
        "leftTicketDTO.train_date": date_s,
        "leftTicketDTO.from_station": from_tc,
        "leftTicketDTO.to_station": to_tc,
        "purpose_codes": "ADULT",
    })
    url = "https://kyfw.12306.cn/otn/leftTicket/queryG?" + q
    headers = {"User-Agent": UA, "Referer": "https://kyfw.12306.cn/otn/leftTicket/init?linktypeid=dc",
               "Cookie": _get_cookie(), "Accept": "application/json"}
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12, context=_ctx) as r:
                body = r.read().decode("utf-8", "replace")
            # 302 跳转响应体是 {"c_url":"leftTicket/queryZ"...} → 换端点重试
            d = json.loads(body)
            if "c_url" in d:
                global _ENDPOINT
                _ENDPOINT = d["c_url"].split("/")[-1]
                url = "https://kyfw.12306.cn/otn/leftTicket/" + _ENDPOINT + "?" + q
                continue
            return d
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(0.6)
    raise RuntimeError(f"12306 查询失败: {last_err}")


_ENDPOINT = "queryG"


def _parse_row(row):
    f = row.split("|")
    if len(f) < 40:
        return None
    code = f[3]
    dep, arr, dur = f[8], f[9], f[10]
    can_buy = f[11] == "Y"
    # 余票: 26=无座 28=硬座 29=软座? 30=二等座 31=一等座 ... 只取有用几列
    seats_left = {"二等座": f[30], "一等座": f[31], "商务座": f[32],
                  "硬座": f[28], "硬卧": f[27], "软卧": f[23]}
    prices = {}
    ps = f[39] if len(f) > 39 else ""
    for cls, fen, _cnt in _PRICE_RE.findall(ps):
        yuan = int(fen) / 10
        name = SEAT_CN.get(cls)
        if not name:
            continue
        # 同席别取最低价(普速同席别可能多段)
        prices[name] = min(prices.get(name, 1e9), yuan)
    # 折扣(字段 54)
    disc = {}
    ds = f[54] if len(f) > 54 else ""
    for cls, d4 in _DISC_RE.findall(ds):
        name = SEAT_CN.get(cls)
        if name and name in prices:
            disc[name] = int(d4) / 100  # 0084 -> 0.84 (8.4折)
    return {"code": code, "dep": dep, "arr": arr, "dur": dur, "can_buy": can_buy,
            "prices": prices, "discount": disc, "left": seats_left}


def fetch_day(date_s, from_tc, to_tc):
    """查询某日某站间所有车次真实票价。返回 {code: {...}}。"""
    d = _http_query(date_s, from_tc, to_tc)
    out = {}
    for row in (d.get("data") or {}).get("result") or []:
        p = _parse_row(row)
        if p and p["prices"]:
            out[p["code"]] = p
    return out


# ---------------------------------------------------------------- 缓存层
CACHE_TTL = 3600 * 3  # 3 小时


def _ensure_table(con):
    con.execute("""CREATE TABLE IF NOT EXISTS price_cache (
        date_s TEXT NOT NULL, from_tc TEXT NOT NULL, to_tc TEXT NOT NULL,
        fetched_at REAL NOT NULL, data TEXT NOT NULL,
        PRIMARY KEY (date_s, from_tc, to_tc))""")
    con.commit()


def _cache_get(con, date_s, from_tc, to_tc):
    r = con.execute("SELECT fetched_at, data FROM price_cache "
                    "WHERE date_s=? AND from_tc=? AND to_tc=?",
                    (date_s, from_tc, to_tc)).fetchone()
    if r and time.time() - r["fetched_at"] < CACHE_TTL:
        return json.loads(r["data"])
    return None


def _cache_put(con, date_s, from_tc, to_tc, data):
    con.execute("INSERT OR REPLACE INTO price_cache VALUES (?,?,?,?,?)",
                (date_s, from_tc, to_tc, time.time(), json.dumps(data, ensure_ascii=False)))
    con.commit()


def get_prices(con, date_s, from_tc, to_tc):
    """带缓存查询。返回 {code: {...}} 或 None(查询失败/超预售期)。"""
    if not from_tc or not to_tc:
        return None
    _ensure_table(con)
    hit = _cache_get(con, date_s, from_tc, to_tc)
    if hit is not None:
        return hit
    try:
        data = fetch_day(date_s, from_tc, to_tc)
    except Exception:  # noqa: BLE001
        return None
    _cache_put(con, date_s, from_tc, to_tc, data)
    time.sleep(0.25)  # 温和限速
    return data


def get_prices_multi(date_list, from_tc, to_tc, workers=4):
    """多日期并行查询(日历用)。每线程独立 SQLite 连接。返回 {date_s: data|None}。"""
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import db as _dbmod
    _tls = threading.local()
    out = {}

    def work(d):
        if not getattr(_tls, "con", None):
            _tls.con = _dbmod.connect()
        return d, get_prices(_tls.con, d, from_tc, to_tc)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for d, r in ex.map(work, date_list):
            out[d] = r
    return out


def best_train_price(train_info, codes=None):
    """从 fetch 结果挑某车次的展示价: 基础席别(二等/硬座)优先。"""
    if not train_info:
        return None
    prices = train_info["prices"]
    if not prices:
        return None
    for cls in SEAT_PRIORITY:
        name = SEAT_CN.get(cls)
        if name in prices:
            return {"seat": name, "price": prices[name],
                    "discount": train_info.get("discount", {}).get(name),
                    "left": train_info.get("left", {}).get(name)}
    return None


def real_prices_for_plan(con, plan, date_s, tele_of):
    """给一个方案挂真实票价。tele_of: sid -> telecode 映射函数。
    直接改写 plan 里的 legs (board_tc/alight_tc/real_price 字段)。"""
    hit = miss = 0
    for l in plan.get("legs") or []:
        if l.get("kind") != "train":
            continue
        ftc, ttc = tele_of(l.get("board_sid")), tele_of(l.get("alight_sid"))
        if not ftc or not ttc:
            continue
        data = get_prices(con, date_s, ftc, ttc)
        if not data:
            miss += 1
            continue
        hit += 1
        info = data.get(l.get("code"))
        if info:
            b = best_train_price(info)
            if b:
                l["real_price"] = b
        l["board_tc"], l["alight_tc"] = ftc, ttc
    return hit, miss


def presale_limit():
    """12306 当前预售期(天)。查询越界会返回空。"""
    return 15


def valid_dates():
    return [(_date.today() + timedelta(days=i)).isoformat()
            for i in range(presale_limit())]


if __name__ == "__main__":
    # 自测: 北京南 VNP -> 上海虹桥 AOH
    d = (_date.today() + timedelta(days=1)).isoformat()
    res = fetch_day(d, "VNP", "AOH")
    print(d, "VNP->AOH 车次数:", len(res))
    for code, info in list(res.items())[:5]:
        b = best_train_price(info)
        print(code, info["dep"], "->", info["arr"], b)
