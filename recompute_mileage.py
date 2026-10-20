# -*- coding: utf-8 -*-
"""recompute_mileage.py — 重建 train.db 里的里程数据。

背景: train_stops.mileage / trains.mileage 全库为 0, 车次详情与直达查询的
累计里程显示 0 km。本脚本用球面距离×绕行系数重建(与出行方案引擎同口径):
  - train_stops.mileage: 沿车次停站累计(km, 1 位小数), 首站 0
  - trains.mileage:      末站累计(取整)
  - line_stations.mileage: 线内累计并归一到 lines.mileage(官方线长标定)
同时更新 meta.data_build, 触发 exe 端 seed() 重新释放数据库。
"""
import math
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "train.db")
BUILD = "20261020-mileage1"

DIST_FACTOR = {"G": 1.25, "C": 1.25, "D": 1.22, "K": 1.20, "T": 1.20, "Z": 1.20}


def haversine(lng1, lat1, lng2, lat2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    coords = {r["id"]: (r["lng"], r["lat"]) for r in cur.execute(
        "SELECT id, lng, lat FROM stations WHERE lng IS NOT NULL AND lat IS NOT NULL")}

    # ---- 1) 车次停站累计里程 ----
    n_tr = n_stop = n_nocoord = 0
    trains = cur.execute(
        "SELECT id, type FROM trains ORDER BY id").fetchall()
    for t in trains:
        stops = cur.execute(
            "SELECT id, station_id FROM train_stops WHERE train_id=? ORDER BY seq",
            (t["id"],)).fetchall()
        factor = DIST_FACTOR.get(t["type"], 1.20)
        cum, ok = 0.0, True
        vals = []
        for i, st in enumerate(stops):
            if i > 0:
                a = coords.get(stops[i - 1]["station_id"])
                b = coords.get(st["station_id"])
                if a and b:
                    cum += haversine(a[0], a[1], b[0], b[1]) * factor
                else:
                    ok = False
            vals.append(cum)
        cur.executemany(
            "UPDATE train_stops SET mileage=? WHERE id=?",
            [(round(v, 1), st["id"]) for v, st in zip(vals, stops)])
        cur.execute("UPDATE trains SET mileage=? WHERE id=?",
                    (round(vals[-1]) if vals else 0, t["id"]))
        n_tr += 1
        n_stop += len(stops)
        if not ok:
            n_nocoord += 1
    print(f"车次 {n_tr} 趟 / 停站 {n_stop} 条已重建; 途中遇缺坐标的车次 {n_nocoord} 趟")

    # ---- 2) 线路站点里程(归一到官方线长) ----
    n_line = 0
    lines = cur.execute("SELECT id, mileage FROM lines").fetchall()
    for l in lines:
        stations = cur.execute(
            "SELECT id, station_id FROM line_stations WHERE line_id=? ORDER BY seq",
            (l["id"],)).fetchall()
        if not stations:
            continue
        raw, cum = [], 0.0
        for i, st in enumerate(stations):
            if i > 0:
                a = coords.get(stations[i - 1]["station_id"])
                b = coords.get(st["station_id"])
                if a and b:
                    cum += haversine(a[0], a[1], b[0], b[1]) * 1.22
            raw.append(cum)
        scale = (l["mileage"] / raw[-1]) if raw[-1] else 1.0
        cur.executemany(
            "UPDATE line_stations SET mileage=? WHERE id=?",
            [(round(v * scale, 1), st["id"]) for v, st in zip(raw, stations)])
        n_line += 1
    print(f"线路 {n_line} 条站点里程已重建(按官方线长归一)")

    cur.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('data_build',?)", (BUILD,))
    con.commit()
    cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    # 抽查
    r = cur.execute(
        "SELECT t.code, t.mileage, (SELECT mileage FROM train_stops WHERE train_id=t.id "
        "ORDER BY seq DESC LIMIT 1) AS last_m FROM trains t WHERE t.code IN ('G1','T269','Z164')")
    for x in r:
        print("抽查:", dict(x))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
