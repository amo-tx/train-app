# -*- coding: utf-8 -*-
"""import_flightnumbers.py — 航班班期库构建。

数据来源:
  1) FP-Dataset(AlexMufeng/FP-Dataset, 9.8万条国内航班记录, jsDelivr CDN 拉取)
     —— 经体检其时刻字段不可信(95% 班次时长<=30分钟, 系爬虫/合成噪声),
        仅采用其"城市对直飞航线存在性"(2935 对)作为航线网络覆盖;
  2) OpenFlights routes.dat(已在 import_flights.py 入库) —— 机场坐标/里程/估价。

班期与时刻按航距拟真生成(确定性种子, 同航线每次结果一致):
  每天 1~6 班, 06:00-20:00 分布, 时长 = 35 + km/780*60 ± 5%, 航班号 = 真实航司码 + 稳定编号。
UI 需标注: 班期为模拟, 真实购票以航司/12306 为准。

产出表:
  flight_schedules(flight_no, airline_iata, dep_city, arr_city,
                   dep_airport, arr_airport, dep_min, arr_min, model)
用法: python import_flightnumbers.py [--no-download]
"""
import math
import os
import random
import re
import ssl
import sys
import time
import urllib.request

from db import BASE_DIR, connect
from import_flights import AIRLINE_CN, _haversine

DATA_DIR = os.path.join(BASE_DIR, "data", "fpd")
BASE_URL = "https://cdn.jsdelivr.net/gh/AlexMufeng/FP-Dataset@main/data"

# FP-Dataset 仓库实际存在的机型文件(35 个)
MODELS = [
    "190", "300", "319", "320", "321", "323", "325", "32A", "32D", "32F",
    "32G", "32I", "330", "332", "333", "33E", "346", "380", "733", "737",
    "738", "739", "73C", "73D", "73E", "73G", "73H", "73K", "73L", "744",
    "757", "773", "787", "CR9", "EMB",
]

# 常见机型池: 短程窄体 / 中程 / 远程宽体
_MODELS_SHORT = ["738", "320", "321", "739", "73H", "32D"]
_MODELS_MID = ["738", "321", "330", "73K", "787"]
_MODELS_LONG = ["330", "773", "787", "773", "350"]


def _dl(model, redownload=False):
    path = os.path.join(DATA_DIR, f"{model}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100 and not redownload:
        return path
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # Watt 代理 TLS 环境
    url = f"{BASE_URL}/{model}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 TrainApp/1.0"})
    last = None
    for attempt in range(3):
        try:
            resp = urllib.request.urlopen(req, timeout=180, context=ctx)
            chunks = []
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            data = b"".join(chunks)
            if len(data) < 100:
                raise IOError(f"响应过小({len(data)}B)")
            open(path, "wb").write(data)
            return path
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2)
    print(f"[sched] {model} 下载失败: {last}")
    return None


def _city_pairs_from_fp(redownload=False):
    """FP-Dataset -> 城市对集合(只取 CITY_DEPARTURE/CITY_ARRIVAL, 不采信时刻)。"""
    pairs = set()
    n_files = 0
    for model in MODELS:
        path = _dl(model, redownload)
        if not path:
            continue
        n_files += 1
        try:
            import json
            data = json.load(open(path, encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"[sched] {model} 解析失败: {e}")
            continue
        for rec in data.values():
            dc = (rec.get("CITY_DEPARTURE") or "").strip()
            ac = (rec.get("CITY_ARRIVAL") or "").strip()
            if dc and ac and dc != ac:
                pairs.add((dc, ac))
    print(f"[sched] FP-Dataset 机型文件 {n_files} / 城市对 {len(pairs)}")
    return pairs


def _est_dur(km):
    return 35 + km / 780.0 * 60


def _pick_model(km, rng):
    if km < 1500:
        return rng.choice(_MODELS_SHORT)
    if km < 2600:
        return rng.choice(_MODELS_MID)
    return rng.choice(_MODELS_LONG)


def build_schedules(redownload=False, use_fp=True):
    con = connect()
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS flight_schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        flight_no TEXT NOT NULL, airline_iata TEXT NOT NULL,
        dep_city TEXT NOT NULL, arr_city TEXT NOT NULL,
        dep_airport TEXT, arr_airport TEXT,
        dep_min INTEGER NOT NULL, arr_min INTEGER NOT NULL, model TEXT)""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sched_dep ON flight_schedules(dep_city, arr_city)")
    cur.execute("DELETE FROM flight_schedules")

    # 1) 航线网络: OpenFlights 航线(按城市对聚合) + FP-Dataset 城市对
    route_km = {}   # (fc, tc) -> (km, price_est, dep_ap, arr_ap)
    for r in cur.execute(
            "SELECT f.src_city, f.dst_city, MIN(f.km) km, MIN(f.price_est) pe, "
            "sa.name san, da.name dan FROM flights f "
            "JOIN airports_full sa ON sa.iata=f.src_iata "
            "JOIN airports_full da ON da.iata=f.dst_iata "
            "WHERE f.src_city != '' AND f.dst_city != '' "
            "GROUP BY f.src_city, f.dst_city").fetchall():
        route_km[(r["src_city"], r["dst_city"])] = (r["km"], r["pe"], r["san"], r["dan"])

    pairs = set(route_km)
    if use_fp:
        pairs |= _city_pairs_from_fp(redownload)

    # 2) 城市代表机场坐标(无 OpenFlights 航线的城市对用球面距离兜底)
    city_xy = {}
    city_ap = {}
    for r in cur.execute(
            "SELECT cn_city, iata, name, lat, lon FROM airports_full WHERE cn_city != ''"):
        if r["cn_city"] not in city_xy:
            city_xy[r["cn_city"]] = (r["lon"], r["lat"])
            city_ap[r["cn_city"]] = r["name"]

    airlines = [a for a in AIRLINE_CN if re.match(r"^[A-Z0-9]{2}$", a)]
    n_ins, n_skip = 0, 0
    for fc, tc in sorted(pairs):
        info = route_km.get((fc, tc))
        if info:
            km, price, dep_ap, arr_ap = info
        else:
            xy1, xy2 = city_xy.get(fc), city_xy.get(tc)
            if not xy1 or not xy2:
                n_skip += 1
                continue
            km = int(_haversine(xy1[0], xy1[1], xy2[0], xy2[1]))
            price = max(280, int(km * 0.58 + 120))
            dep_ap, arr_ap = city_ap.get(fc, ""), city_ap.get(tc, "")
        if km < 300:  # 过短不排班
            n_skip += 1
            continue
        rng = random.Random(f"{fc}->{tc}")
        n_flights = min(6, 1 + km // 900)
        dur = int(round(_est_dur(km) * (0.95 + 0.1 * rng.random())))
        al = rng.choice(airlines)          # 整条航线同一主航司
        no_base = 1000 + rng.randint(0, 8600)
        for i in range(n_flights):
            dep = 6 * 60 + int((14 * 60 - 60) * (i + rng.random()) / n_flights)
            arr = dep + dur
            flight_no = f"{al}{no_base + i * 2}"
            cur.execute(
                "INSERT INTO flight_schedules(flight_no,airline_iata,dep_city,arr_city,"
                "dep_airport,arr_airport,dep_min,arr_min,model) VALUES(?,?,?,?,?,?,?,?,?)",
                (flight_no, al, fc, tc, dep_ap, arr_ap, dep, arr, _pick_model(km, rng)))
            n_ins += 1
    con.commit()
    total = cur.execute("SELECT COUNT(*) FROM flight_schedules").fetchone()[0]
    npairs = cur.execute(
        "SELECT COUNT(DISTINCT dep_city || '-' || arr_city) FROM flight_schedules").fetchone()[0]
    con.close()
    print(f"[sched] 生成航班 {n_ins} 班 / 城市对 {npairs} / 跳过 {n_skip}")
    return total


if __name__ == "__main__":
    build_schedules(redownload=False, use_fp="--no-download" not in sys.argv)
