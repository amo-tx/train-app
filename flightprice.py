# -*- coding: utf-8 -*-
"""携程机票最低价按需查询(用户搜索线路时才查该线路, 不做全量)。

接口: GET https://flights.ctrip.com/itinerary/api/12808/lowestPrice
      ?flightWay=Oneway&dcity=<出发城市代码>&acity=<到达城市代码>&direct=true
返回(约): {"data": {"oneWayPrice": [{"2026-10-20": 500, ...30天}], ...}}
一次请求返回整月每日最低价 → 查询一次即可覆盖方案页 + 价格日历。

注意: 携程 whaleguard WAF 会封数据中心 IP; 家用宽带直连通常正常。
被拦/失败时返回 None, 上层自动回退估算价。
"""
import json
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

# ctrip 城市代码与机场三字码不同的特例(城市级代码)
CITY_CODE_OVERRIDE = {
    "北京": "BJS", "上海": "SHA", "南京": "NKG", "杭州": "HGH",
    "广州": "CAN", "深圳": "SZX", "成都": "CTU", "重庆": "CKG",
    "武汉": "WUH", "西安": "SIA", "长沙": "CSX", "厦门": "XMN",
    "青岛": "TAO", "大连": "DLC", "昆明": "KMG", "三亚": "SYX",
    "海口": "HAK", "哈尔滨": "HRB", "沈阳": "SHE", "郑州": "CGO",
    "天津": "TSN", "贵阳": "KWE", "南宁": "NNG", "福州": "FOC",
    "兰州": "LHW", "乌鲁木齐": "URC", "拉萨": "LXA", "呼和浩特": "HET",
    "银川": "INC", "西宁": "XNN", "济南": "TNA", "太原": "TYN",
    "合肥": "HFE", "南昌": "KHN", "贵阳": "KWE", "南宁": "NNG",
}

CACHE_TTL = 6 * 3600  # 整月最低价缓存 6 小时
NEG_TTL = 600         # 负缓存(接口不可达标记)仅 10 分钟, 避免长期不重试


def _city_codes(cur, city):
    """城市 -> 候选 ctrip 城市代码(先查该城市机场, 城市代码特例优先)。"""
    codes = []
    ov = CITY_CODE_OVERRIDE.get(city)
    if ov:
        codes.append(ov)
    rows = cur.execute(
        "SELECT iata FROM airports_full WHERE cn_city=? OR city=?",
        (city, city)).fetchall()
    for r in rows:
        if r["iata"] and r["iata"] not in codes:
            codes.append(r["iata"])
    return codes[:3]


def _http(dcode, acode):
    q = urllib.parse.urlencode({
        "flightWay": "Oneway", "dcity": dcode, "acity": acode,
        "direct": "true", "army": "false"})
    url = "https://flights.ctrip.com/itinerary/api/12808/lowestPrice?" + q
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://flights.ctrip.com/itinerary/oneway/",
        "Accept": "application/json, text/plain, */*"})
    with urllib.request.urlopen(req, timeout=10, context=_ctx) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_month_prices(from_city, to_city):
    """整月每日最低价 {date: int元}。失败返回 None。"""
    d = _http(from_city, to_city)
    data = (d.get("data") or {})
    arr = data.get("oneWayPrice") or []
    if not arr or not isinstance(arr[0], dict):
        return None
    out = {}
    for k, v in arr[0].items():
        try:
            dv = int(v)
            if dv > 0:
                out[k] = dv
        except (TypeError, ValueError):
            continue
    return out or None


# ---------------------------------------------------------------- 缓存
def _ensure_table(con):
    con.execute("""CREATE TABLE IF NOT EXISTS flight_price_cache (
        from_city TEXT NOT NULL, to_city TEXT NOT NULL,
        fetched_at REAL NOT NULL, data TEXT NOT NULL,
        PRIMARY KEY (from_city, to_city))""")
    con.commit()


def _cache_get(con, fc, tc):
    r = con.execute("SELECT fetched_at, data FROM flight_price_cache "
                    "WHERE from_city=? AND to_city=?", (fc, tc)).fetchone()
    if not r:
        return None
    age = time.time() - r["fetched_at"]
    data = json.loads(r["data"])
    if data == {}:
        # 负缓存: 短 TTL, 过期后重试
        return {} if age < NEG_TTL else None
    return data if age < CACHE_TTL else None


def _cache_put(con, fc, tc, data):
    con.execute("INSERT OR REPLACE INTO flight_price_cache VALUES (?,?,?,?)",
                (fc, tc, time.time(), json.dumps(data, ensure_ascii=False)))
    con.commit()


def month_prices(cur, con, from_city, to_city):
    """带缓存的整月最低价(按需触发网络请求)。不可得返回 None。"""
    if not from_city or not to_city or from_city == to_city:
        return None
    _ensure_table(con)
    hit = _cache_get(con, from_city, to_city)
    if hit is not None:
        return hit
    for dcode in _city_codes(cur, from_city):
        for acode in _city_codes(cur, to_city):
            if dcode == acode:
                continue
            try:
                data = fetch_month_prices(dcode, acode)
            except Exception:  # noqa: BLE001
                data = None
            if data:
                _cache_put(con, from_city, to_city, data)
                return data
    # 标记一次负缓存, 避免 15s 内反复打被拦的接口
    _cache_put(con, from_city, to_city, {})
    return None


def price_on(cur, con, from_city, to_city, date_s):
    """某日真实最低价(元) 或 None。"""
    m = month_prices(cur, con, from_city, to_city)
    if not m:
        return None
    return m.get(date_s)


if __name__ == "__main__":
    # 自测(仅在未被 WAF 拦的网络下有效)
    import sys
    fc = sys.argv[1] if len(sys.argv) > 1 else "北京"
    tc = sys.argv[2] if len(sys.argv) > 2 else "上海"
    try:
        r = fetch_month_prices(CITY_CODE_OVERRIDE.get(fc, fc), CITY_CODE_OVERRIDE.get(tc, tc))
    except Exception as e:  # noqa: BLE001
        print("接口不可达:", type(e).__name__, e)
        sys.exit(0)
    if r is None:
        print("接口不可达(WAF 拦截或网络问题)")
    else:
        items = sorted(r.items())[:5]
        print(fc, "->", tc, "整月天数:", len(r), "样例:", items)
