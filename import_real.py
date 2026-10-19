# -*- coding: utf-8 -*-
"""import_real.py — 将 12306 真实车次时刻数据集导入 SQLite。

数据源: HerbertHe/cr-12306-train-info GitHub Release (12306 官方接口口径)
  data/train_detail_{G,D,C}_20260617.json
结构: [{"train_no", "station_train_codes": "G1", "data": [
        {"station_name", "arrive_time"|"----", "start_time"|"----",
         "arrive_day_diff": "0/1/..", "station_no"}...]}]

用法: python import_real.py [--keep-generated]
"""
import glob
import json
import os
import re
import sqlite3
import sys

from db import BASE_DIR, DB_PATH, connect, seed, _parse_station_js

DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_DATE = "20260617"
SOURCE = f"12306 官方接口口径 · cr-12306-train-info release data-{DATA_DATE}"


def hhmm(s):
    """'06:30' -> 分钟; '----' -> None"""
    if not s or s == "----":
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})$", s.strip())
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def import_real(keep_generated=False, data_date=None):
    """导入车次数据。data_date 可指定 release 日期(自动更新时传入新日期)。"""
    if not os.path.exists(DB_PATH):
        seed(force=True)
    if data_date is None:
        data_date = DATA_DATE
    files = sorted(glob.glob(os.path.join(DATA_DIR, f"train_detail_*_{data_date}.json")))
    files = [f for f in files if re.search(r"train_detail_[A-Z]+_", f)]
    if not files:
        sys.exit(f"[fatal] 未找到数据文件, 请先下载 train_detail_*_{data_date}.json 到 {DATA_DIR}")

    con = connect()
    cur = con.cursor()

    # 站名 -> id (12306 车站表为准)
    name2id = {r["name"]: r["id"] for r in cur.execute("SELECT id, name FROM stations")}
    st_meta = {s["name"]: s for s in _parse_station_js()}

    if not keep_generated:
        cur.execute("DELETE FROM train_stops")
        cur.execute("DELETE FROM trains")
        print("[import] 已清空生成的车次/经停数据")

    cur.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    n_trains = n_stops = n_skip = 0
    missing_stations = {}

    for path in files:
        label = os.path.basename(path)
        print(f"[import] 处理 {label} ...")
        with open(path, encoding="utf-8") as fh:
            trains = json.load(fh)
        for t in trains:
            code = (t.get("station_train_codes") or "").strip()
            stops = t.get("data") or []
            if not code or len(stops) < 2:
                n_skip += 1
                continue
            stops = sorted(stops, key=lambda s: int(s.get("station_no") or 0))
            # 解析每站的 绝对分钟(相对始发日 0 点)
            parsed = []
            base = None
            ok = True
            for s in stops:
                sname = (s.get("station_name") or "").strip()
                if not sname:
                    ok = False
                    break
                day = int(s.get("arrive_day_diff") or 0)
                arr = hhmm(s.get("arrive_time"))
                dep = hhmm(s.get("start_time"))
                arr_abs = arr + day * 1440 if arr is not None else None
                dep_abs = dep + day * 1440 if dep is not None else None
                if base is None:
                    base = dep_abs if dep_abs is not None else arr_abs
                parsed.append((sname, arr_abs, dep_abs))
            if not ok or base is None or len(parsed) < 2:
                n_skip += 1
                continue

            # 车站 id, 缺失则补插
            sids = []
            for sname, _, _ in parsed:
                sid = name2id.get(sname)
                if sid is None:
                    meta = st_meta.get(sname, {})
                    cur.execute(
                        "INSERT INTO stations(name, telecode, pinyin_full, pinyin_abbr, city, is_major) "
                        "VALUES(?,?,?,?,?,0)",
                        (sname, meta.get("telecode", ""), meta.get("pinyin_full", ""),
                         meta.get("pinyin_abbr", ""), sname))
                    sid = cur.lastrowid
                    name2id[sname] = sid
                    missing_stations[sname] = True
                sids.append(sid)

            ttype = code[0]
            start_sid, end_sid = sids[0], sids[-1]
            depart0 = parsed[0][2] if parsed[0][2] is not None else parsed[0][1]
            last_arr = parsed[-1][1] if parsed[-1][1] is not None else parsed[-1][2]
            # 里程未知 -> 用 0 占位(真实里程不在此数据集中)
            cur.execute(
                "INSERT INTO trains(code, type, line_id, start_station_id, end_station_id, "
                "depart_time, arrive_time, mileage, emu_model) VALUES(?,?,?,?,?,?,?,?,NULL)",
                (code, ttype, None, start_sid, end_sid, depart0, last_arr, 0))
            tid = cur.lastrowid
            rows = []
            for seq, ((sname, arr_abs, dep_abs), sid) in enumerate(zip(parsed, sids)):
                stop_min = (dep_abs - arr_abs) if (arr_abs is not None and dep_abs is not None) else 0
                rows.append((tid, sid, seq, arr_abs, dep_abs, stop_min))
            cur.executemany(
                "INSERT INTO train_stops(train_id, station_id, seq, arrive_min, depart_min, "
                "stop_minutes, mileage) VALUES(?,?,?,?,?,?,0)", rows)
            n_trains += 1
            n_stops += len(rows)
        con.commit()
        print(f"[import] 累计: 车次 {n_trains}, 经停 {n_stops}, 跳过 {n_skip}")

    cur.executemany("INSERT OR REPLACE INTO meta(k, v) VALUES(?,?)",
                    [("data_source", f"12306 官方接口口径 · cr-12306-train-info release data-{data_date}"),
                     ("data_date", data_date),
                     ("trains", str(n_trains)), ("stops", str(n_stops))])
    con.commit()
    con.close()
    print(f"[import] 完成! 车次 {n_trains} / 经停 {n_stops} / 跳过 {n_skip} / 补插车站 {len(missing_stations)}")
    if missing_stations:
        print("[import] 补插的车站:", " ".join(list(missing_stations)[:20]),
              "..." if len(missing_stations) > 20 else "")


if __name__ == "__main__":
    import_real(keep_generated="--keep-generated" in sys.argv)
