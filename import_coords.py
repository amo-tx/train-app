# -*- coding: utf-8 -*-
"""import_coords.py — 为 stations 表补充经纬度坐标。

数据源: listenzcc/China-rail-way-stations-data (src/station.csv, 整理自 heywhale 数据集)
  列: ,站名,车站地址,铁路局,类别,性质,省,市,lng火星,lat火星,WGS84_Lng,WGS84_Lat,BD_Lng,BD_Lat
采用 WGS84 坐标(ECharts geo 使用经纬度直出即可)。
"""
import csv
import os
import sqlite3
import sys

from db import BASE_DIR, DB_PATH

CSV_PATH = os.path.join(BASE_DIR, "data", "station_listenzcc.csv")


def ensure_cols(cur):
    cols = {r[1] for r in cur.execute("PRAGMA table_info(stations)")}
    if "lng" not in cols:
        cur.execute("ALTER TABLE stations ADD COLUMN lng REAL")
    if "lat" not in cols:
        cur.execute("ALTER TABLE stations ADD COLUMN lat REAL")


def load_csv():
    """返回 {站名: (wgs_lng, wgs_lat)}，多坐标系取 WGS84。"""
    out = {}
    with open(CSV_PATH, encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        i_name = header.index("站名")
        i_lng = header.index("WGS84_Lng")
        i_lat = header.index("WGS84_Lat")
        for row in reader:
            if len(row) <= max(i_name, i_lng, i_lat):
                continue
            name = row[i_name].strip()
            try:
                lng, lat = float(row[i_lng]), float(row[i_lat])
            except ValueError:
                continue
            if name and 70 < lng < 140 and 15 < lat < 55:
                out[name] = (lng, lat)
    return out


def main():
    if not os.path.exists(CSV_PATH):
        sys.exit(f"[fatal] 未找到 {CSV_PATH}")
    coords = load_csv()
    print(f"[coords] CSV 载入 {len(coords)} 站")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    ensure_cols(cur)
    matched = unmatched = 0
    missing = []
    for name, telecode, py, city in cur.execute(
            "SELECT name, telecode, pinyin_full, city FROM stations").fetchall():
        c = coords.get(name)
        if c is None and name.endswith("站"):
            c = coords.get(name[:-1])
        if c is None:
            # CSV 站名可能带"站"后缀
            c = coords.get(name + "站")
        if c:
            cur.execute("UPDATE stations SET lng=?, lat=? WHERE name=?", (c[0], c[1], name))
            matched += 1
        else:
            unmatched += 1
            missing.append(name)
    con.commit()
    total = cur.execute("SELECT COUNT(*) FROM stations WHERE lng IS NOT NULL").fetchone()[0]
    con.close()
    print(f"[coords] 匹配 {matched} 站 / 未匹配 {unmatched} 站 / 库内有坐标 {total} 站")
    if missing:
        print("[coords] 未匹配样例:", " ".join(missing[:25]),
              "..." if len(missing) > 25 else "")


if __name__ == "__main__":
    main()
