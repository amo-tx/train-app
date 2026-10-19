# -*- coding: utf-8 -*-
"""import_flights.py — 导入国内机场与航线（OpenFlights 开放数据）。

数据源: https://openflights.org/data.html (CC-BY 许可)
  airports.dat / airlines.dat / routes.dat → 过滤中国国内航线
产出表:
  airports_full(iata, name, city, cn_city, lat, lon)
  flights(airline, flight_no, src_iata, dst_iata, src_city, dst_city, km, duration_min, price_est)
说明: OpenFlights 无航班时刻与票价, duration/price 为按距离的估算值(界面标注)。
用法: python import_flights.py [--redownload]
"""
import csv
import json
import math
import os
import ssl
import sys
import time
import urllib.request

from db import BASE_DIR, DB_PATH, connect

DATA_DIR = os.path.join(BASE_DIR, "data")
BASE_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data"
FILES = ["airports.dat", "airlines.dat", "routes.dat"]

# OpenFlights 无中文城市名: IATA -> 中文城市 映射(国内主要机场)
IATA_CN_CITY = {
    "PEK": "北京", "PKX": "北京", "NAY": "北京", "SHA": "上海", "PVG": "上海",
    "CAN": "广州", "SZX": "深圳", "CTU": "成都", "TFU": "成都", "HGH": "杭州",
    "NKG": "南京", "XIY": "西安", "CGO": "郑州", "CSX": "长沙", "WUH": "武汉",
    "TAO": "青岛", "TNA": "济南", "SYX": "三亚", "HAK": "海口", "KMG": "昆明",
    "HRB": "哈尔滨", "CKG": "重庆", "FOC": "福州", "XMN": "厦门", "ZUH": "珠海",
    "DLC": "大连", "SHE": "沈阳", "TSN": "天津", "URC": "乌鲁木齐", "KWL": "桂林",
    "NNG": "南宁", "LHW": "兰州", "INC": "银川", "XNN": "西宁", "HET": "呼和浩特",
    "LJG": "丽江", "JHG": "西双版纳", "DXJ": "大理", "DLU": "大理", "HGH2": "",
    "WUX": "无锡", "NGB": "宁波", "HYN": "台州", "WNZ": "温州", "JJN": "泉州",
    "BAV": "包头", "CIH": "长治", "DAT": "大同", "YNT": "烟台", "WEH": "威海",
    "RIZ": "日照", "LYG": "连云港", "XUZ": "徐州", "HIA": "淮安", "YTY": "扬州",
    "CZX": "常州", "NTG": "南通", "SQD": "宿迁", "BHY": "北海", "LZH": "柳州",
    "WUZ": "梧州", "YIN": "延安", "HZH": "湖州", "UYN": "榆林", "JDG": "张家界",
    "DYG": "张家界", "YYA": "岳阳", "CSX2": "", "HNY": "衡阳", "LLF": "永州",
    "OHH": "怀化", "TXN": "黄山", "JUH": "九华山", "FUG": "阜阳", "ANC": "",
    "LXA": "拉萨", "BPX": "昌都", "NQZ": "那曲", "AKU": "阿克苏", "KRL": "库尔勒",
    "KHG": "喀什", "HTN": "和田", "YIN2": "", "YLC": "榆林", "BPL": "巴彦淖尔",
    "HLH": "乌兰浩特", "HLD": "呼伦贝尔", "NZH": "满洲里", "NDG": "齐齐哈尔",
    "MDG": "牡丹江", "JMU": "佳木斯", "HRB2": "", "DQA": "大庆", "JGD": "加格达奇",
    "CNI": "长海", "DLC2": "", "YNJ": "延吉", "JIL": "吉林", "CGQ": "长春",
    "SHE2": "", "DDG": "丹东", "JNZ": "锦州", "CHG": "朝阳", "BXJ": "本溪",
    "IQM": "且末", "KCA": "库车", "HTN2": "", "ZAT": "昭通", "LZO": "泸州",
    "YBP": "宜宾", "NAY2": "", "JZH": "九寨沟", "GYS": "广元", "NAO": "南充",
    "DAX": "达州", "BZX": "巴中", "WXN": "万州", "YIH": "宜昌", "ENH": "恩施",
    "SHS": "荆州", "KHN": "南昌", "JIU": "九江", "GMP": "上饶", "YIC": "宜春",
    "GZX": "赣州", "FUO": "佛山", "MXZ": "梅州", "SWA": "揭阳", "ZHA": "湛江",
    "CJU": "湛江", "IQT": "", "NLH": "荔波", "KJH": "凯里", "BFJ": "毕节",
    "ZYI": "遵义", "TEN": "铜仁", "AVA": "安顺", "LDS": "伊春", "HBB": "红原",
    "GXH": "固原", "LFQ": "临汾", "YCU": "运城", "JGS": "井冈山",
}

# 主要中国航司: IATA -> 中文名
AIRLINE_CN = {
    "CA": "中国国际航空", "MU": "中国东方航空", "CZ": "中国南方航空",
    "HU": "海南航空", "MF": "厦门航空", "FM": "上海航空", "ZH": "深圳航空",
    "3U": "四川航空", "SC": "山东航空", "9C": "春秋航空", "KN": "中国联航",
    "GJ": "长龙航空", "HO": "吉祥航空", "GS": "天津航空", "JD": "首都航空",
    "TV": "西藏航空", "PN": "西部航空", "CN": "大新华航空", "8L": "祥鹏航空",
    "DZ": "东海航空", "G5": "华夏航空", "BK": "奥凯航空", "EU": "成都航空",
    "UQ": "乌鲁木齐航空", "OQ": "重庆航空", "KY": "昆明航空", "AQ": "江西航空",
    "GT": "北部湾航空", "QW": "青岛航空", "FU": "福州航空", "DZ2": "",
    "2Z": "金鹏航空", "Y8": "金鹿航空", "CGO2": "",
}


def _dl(to_file, redownload=False):
    """下载或复用本地缓存(可离线导入)。"""
    path = os.path.join(DATA_DIR, to_file)
    if os.path.exists(path) and os.path.getsize(path) > 10000 and not redownload:
        return path
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # Watt 代理 TLS 环境
    url = f"{BASE_URL}/{to_file}"
    print(f"[flights] 下载 {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 TrainApp/1.0"})
    last_err = None
    for attempt in range(3):  # 代理环境易截断, 流式读取+重试
        try:
            resp = urllib.request.urlopen(req, timeout=180, context=ctx)
            chunks = []
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            open(path, "wb").write(b"".join(chunks))
            return path
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[flights] 第 {attempt + 1} 次下载失败: {e}, 重试…")
            time.sleep(2)
    raise last_err


def _rows(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for row in csv.reader(fh):
            yield row


def _haversine(lng1, lat1, lng2, lat2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _flight_est(km):
    """估算飞行时长(分钟)与经济舱价格(元)。"""
    duration = 35 + km / 780 * 60  # 起降爬升 + 巡航
    price = max(280, int(km * 0.58 + 120))
    return int(duration), price


def import_flights(redownload=False):
    for f in FILES:
        _dl(f, redownload)
    ap_path = os.path.join(DATA_DIR, "airports.dat")
    al_path = os.path.join(DATA_DIR, "airlines.dat")
    rt_path = os.path.join(DATA_DIR, "routes.dat")

    # 1) 国内机场
    airports = {}  # iata -> dict
    for r in _rows(ap_path):
        if len(r) < 8 or r[3] != "China":
            continue
        iata = r[4] if r[4] != r[4].replace("\\N", "") else r[4]
        if iata in ("", "\\N"):
            continue
        try:
            lat, lon, alt = float(r[6]), float(r[7]), int(float(r[8] or 0))
        except ValueError:
            continue
        airports[iata] = {
            "iata": iata, "name": r[1], "city": r[2], "cn_city": IATA_CN_CITY.get(iata, ""),
            "lat": lat, "lon": lon, "alt": alt,
        }
    # 中文名映射的城市数
    n_cn = sum(1 for a in airports.values() if a["cn_city"])

    # 2) 航司名
    airlines = {}
    for r in _rows(al_path):
        if len(r) < 5:
            continue
        iata = r[3]
        if iata and iata != "\\N":
            airlines[iata] = r[1]

    # 3) 国内航线(起终点均为国内机场)
    con = connect()
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS airports_full (
        iata TEXT PRIMARY KEY, name TEXT NOT NULL, city TEXT, cn_city TEXT,
        lat REAL NOT NULL, lon REAL NOT NULL, alt INTEGER DEFAULT 0)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS flights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        airline TEXT, airline_iata TEXT, flight_no TEXT,
        src_iata TEXT NOT NULL, dst_iata TEXT NOT NULL,
        src_city TEXT, dst_city TEXT,
        km INTEGER NOT NULL, duration_min INTEGER NOT NULL, price_est INTEGER NOT NULL)""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_flights_src ON flights(src_iata)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_flights_dst ON flights(dst_iata)")
    cur.execute("DELETE FROM airports_full")
    cur.execute("DELETE FROM flights")

    n_ap = 0
    for a in airports.values():
        cur.execute(
            "INSERT OR REPLACE INTO airports_full(iata,name,city,cn_city,lat,lon,alt) "
            "VALUES(?,?,?,?,?,?,?)",
            (a["iata"], a["name"], a["city"], a["cn_city"], a["lat"], a["lon"], a["alt"]))
        n_ap += 1

    seen, n_ft, n_skip = set(), 0, 0
    for r in _rows(rt_path):
        if len(r) < 9:
            continue
        al_iata, _al_id, src, _sid, dst, _did, codeshare, stops, _eq = r[:9]
        if codeshare == "Y":  # 共享航班去重
            continue
        sa, da = airports.get(src), airports.get(dst)
        if not sa or not da:
            n_skip += 1
            continue
        key = (al_iata, src, dst)
        if key in seen:
            continue
        seen.add(key)
        km = int(_haversine(sa["lon"], sa["lat"], da["lon"], da["lat"]))
        dur, price = _flight_est(km)
        al_name = AIRLINE_CN.get(al_iata) or airlines.get(al_iata) or al_iata
        flight_no = f"{al_iata}{1000 + n_ft % 9000}"  # 航线号(OpenFlights 无实际班次号)
        cur.execute(
            "INSERT INTO flights(airline,airline_iata,flight_no,src_iata,dst_iata,"
            "src_city,dst_city,km,duration_min,price_est) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (al_name, al_iata, flight_no, src, dst,
             sa["cn_city"] or sa["city"], da["cn_city"] or da["city"], km, dur, price))
        n_ft += 1
    con.commit()
    n_city = cur.execute(
        "SELECT COUNT(DISTINCT cn_city) FROM airports_full WHERE cn_city != ''").fetchone()[0]
    con.close()
    print(f"[flights] 机场 {n_ap}(含中文名映射 {n_cn}) / 国内航线 {n_ft} / 覆盖城市 {n_city}")
    print(f"[flights] 未映射中文城市样例:",
          " ".join(sorted({a["city"] for a in airports.values() if not a["cn_city"]})[:15]))
    return n_ap, n_ft


def update_flights():
    """启动时调用: 重新下载并导入(OpenFlights 不定期更新)。失败返回 False。"""
    try:
        import_flights(redownload=True)
        return True
    except Exception as e:  # noqa: BLE001
        print("[flights] 更新失败:", e)
        return False


if __name__ == "__main__":
    import_flights(redownload="--redownload" in sys.argv)
