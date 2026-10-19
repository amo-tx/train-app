# -*- coding: utf-8 -*-
"""merge_osm.py — 用 OSM (Overpass) 数据补齐 stations 表缺失的坐标。

数据源: data/osm_stations_raw.json (Overpass, railway=station/halt, 中国 bbox)
排除 subway/light_rail/monorail/tram, 避免城市轨道交通同名站干扰。
只更新 lng IS NULL 的站, 不覆盖已有坐标。
"""
import json
import os
import sqlite3
import sys

from db import BASE_DIR, DB_PATH

RAW = os.path.join(BASE_DIR, "data", "osm_stations_raw.json")


def load_osm():
    d = json.load(open(RAW, encoding="utf-8"))
    out = {}
    for e in d.get("elements", []):
        tags = e.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        if tags.get("station") in ("subway", "light_rail", "monorail", "tram") \
                or tags.get("subway") == "yes" or tags.get("light_rail") == "yes" \
                or tags.get("monorail") == "yes" or tags.get("tram") == "yes":
            continue
        # 同名多节点: 保留带 railway_ref/网络标签更全的那个(取标签数最多)
        rec = {"lng": e["lon"], "lat": e["lat"], "ntags": len(tags)}
        old = out.get(name)
        if old is None or rec["ntags"] > old["ntags"]:
            out[name] = rec
    return out


def main():
    if not os.path.exists(RAW):
        sys.exit(f"[fatal] 未找到 {RAW}")
    osm = load_osm()
    print(f"[osm] 载入 {len(osm)} 个具名车站节点(已排除城市轨道交通)")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    rows = cur.execute(
        "SELECT name, city FROM stations WHERE lng IS NULL").fetchall()
    print(f"[osm] 库内待补 {len(rows)} 站")
    matched = 0
    still = []
    for name, city in rows:
        cands = [name, name + "站", name[:-1] if name.endswith("站") else None]
        rec = None
        for c in cands:
            if c and c in osm:
                rec = osm[c]
                break
        # 再试 "城市+站名"(OSM 里部分小站名带城市前缀)
        if rec is None and city and (city + name) in osm:
            rec = osm[city + name]
        if rec:
            cur.execute("UPDATE stations SET lng=?, lat=? WHERE name=?",
                        (rec["lng"], rec["lat"], name))
            matched += 1
        else:
            still.append(name)
    con.commit()
    total = cur.execute("SELECT COUNT(*) FROM stations WHERE lng IS NOT NULL").fetchone()[0]
    grand = cur.execute("SELECT COUNT(*) FROM stations").fetchone()[0]
    con.close()
    print(f"[osm] 补齐 {matched} 站; 仍缺 {len(still)} 站")
    print(f"[osm] 有坐标总站数: {total}/{grand} ({total * 100 // grand}%)")
    if still:
        print("[osm] 仍缺样例:", " ".join(still[:25]), "..." if len(still) > 25 else "")


if __name__ == "__main__":
    main()
