# -*- coding: utf-8 -*-
"""export_data.py — 把 train.db 导出为安卓端 assets/data.js。

预计算内容(与 journey.build_graph 同源逻辑, 保证两端一致):
  - trains_by_id: 每车次 stops_list [sid, seq, arr, dep, stop] (seq 升序)
  - legs_by_station: 站 -> [[tid, seq, arr, dep], ...]
  - coords / city_of / city_sids / names
输出 window.__DATA__ = {...}, 供安卓 WebView 内的 JS 引擎使用。
"""
import json
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "train.db")
OUT = os.path.join(BASE, "android", "assets", "data.js")

DIST_FACTOR = {"G": 1.25, "C": 1.25, "D": 1.22, "K": 1.20, "T": 1.20, "Z": 1.20}


def haversine(lng1, lat1, lng2, lat2):
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    stations = []
    names, city_of, coords, city_sids = {}, {}, {}, {}
    for r in cur.execute(
            "SELECT id, name, telecode, pinyin_full, pinyin_abbr, city, is_major, lng, lat "
            "FROM stations ORDER BY id"):
        stations.append([r["id"], r["name"], r["telecode"], r["pinyin_full"],
                         r["pinyin_abbr"], r["city"], r["is_major"], r["lng"], r["lat"]])
        names[r["id"]] = r["name"]
        city_of[r["id"]] = r["city"]
        city_sids.setdefault(r["city"], []).append(r["id"])
        if r["lng"] is not None:
            coords[r["id"]] = [round(r["lng"], 5), round(r["lat"], 5)]

    train_rows = {r["id"]: r for r in cur.execute(
        "SELECT id, code, type, line_id, start_station_id, end_station_id, "
        "depart_time, arrive_time, mileage, emu_model FROM trains")}

    trains_meta = []          # [id, code, type, line_id, depart, arrive, mileage, emu, start_name, end_name]
    stops_by_train = {}       # tid -> [[sid, seq, arr, dep, stop, mileage], ...]
    for tid, r in train_rows.items():
        s1 = names.get(r["start_station_id"], "")
        s2 = names.get(r["end_station_id"], "")
        trains_meta.append([tid, r["code"], r["type"], r["line_id"], r["depart_time"],
                            r["arrive_time"], r["mileage"], r["emu_model"], s1, s2])
        stops_by_train[tid] = []

    for r in cur.execute(
            "SELECT train_id, station_id, seq, arrive_min, depart_min, stop_minutes, mileage "
            "FROM train_stops ORDER BY train_id, seq"):
        stops_by_train[r["train_id"]].append(
            [r["station_id"], r["seq"], r["arrive_min"], r["depart_min"],
             r["stop_minutes"], r["mileage"]])

    legs_by_station = {}
    for tid, stops in stops_by_train.items():
        for sid, seq, arr, dep, _sm, _ml in stops:
            legs_by_station.setdefault(sid, []).append([tid, seq, arr, dep])

    lines = [[r["id"], r["name"], r["category"], r["mileage"], r["speed_limit"]]
             for r in cur.execute("SELECT * FROM lines ORDER BY id")]
    line_stations = {}
    for r in cur.execute(
            "SELECT line_id, station_id, seq, mileage FROM line_stations ORDER BY line_id, seq"):
        line_stations.setdefault(r["line_id"], []).append(
            [r["station_id"], r["seq"], r["mileage"]])

    airports_full = [[r["iata"], r["name"], r["city"], r["cn_city"],
                      round(r["lat"], 5), round(r["lon"], 5)]
                     for r in cur.execute("SELECT * FROM airports_full ORDER BY iata")]

    airports_seed = [[r["iata"], r["name"], r["city"]]
                     for r in cur.execute("SELECT * FROM airports ORDER BY city")]

    flights = [[r["id"], r["airline"], r["airline_iata"], r["flight_no"], r["src_iata"],
                r["dst_iata"], r["src_city"], r["dst_city"], r["km"], r["duration_min"],
                r["price_est"]]
               for r in cur.execute("SELECT * FROM flights ORDER BY duration_min")]

    flight_schedules = [[r["flight_no"], r["airline_iata"], r["dep_city"], r["arr_city"],
                         r["dep_airport"], r["arr_airport"], r["dep_min"], r["arr_min"], r["model"]]
                        for r in cur.execute(
                            "SELECT * FROM flight_schedules ORDER BY dep_city, dep_min")]

    emu = [[r["id"], r["model"], r["nickname"], r["manufacturer"], r["max_speed"], r["formation"]]
           for r in cur.execute("SELECT * FROM emu_models ORDER BY max_speed DESC")]

    scenic = [[r["id"], r["name"], r["city"], r["level"], r["station_id"], r["note"]]
              for r in cur.execute("SELECT * FROM scenic_spots ORDER BY level DESC, city")]

    meta = {r["k"]: r["v"] for r in cur.execute("SELECT k, v FROM meta")}

    data = {
        "stations": stations,
        "trains": trains_meta,
        "stops": stops_by_train,
        "legs": legs_by_station,
        "coords": coords,
        "names": names,
        "city_of": city_of,
        "city_sids": city_sids,
        "lines": lines,
        "line_stations": line_stations,
        "airports": airports_seed,
        "airports_full": airports_full,
        "flights": flights,
        "sched": flight_schedules,
        "emu": emu,
        "scenic": scenic,
        "meta": meta,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("window.__DATA__=")
        f.write(body)
        f.write(";\n")
    n_stops = sum(len(v) for v in stops_by_train.values())
    n_legs = sum(len(v) for v in legs_by_station.values())
    print("OK stations=%d trains=%d stops=%d legs=%d flights=%d sched=%d size=%.1fMB"
          % (len(stations), len(trains_meta), n_stops, n_legs,
             len(flights), len(flight_schedules), os.path.getsize(OUT) / 1e6))


if __name__ == "__main__":
    sys.exit(main())
