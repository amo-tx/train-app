# -*- coding: utf-8 -*-
"""main.py — 本地服务入口。

纯标准库实现: http.server 提供 REST API + 静态页面。
启动: python main.py  (默认 http://127.0.0.1:8642)
"""
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# 打包为无窗口 exe 时 stdout/stderr 为 None, 任何 print 都会崩
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from db import BASE_DIR, DB_PATH, connect, seed
import api_journey_v2 as planv2

if getattr(sys, "frozen", False):
    RESOURCE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
else:
    RESOURCE_DIR = BASE_DIR
STATIC_DIR = os.path.join(RESOURCE_DIR, "static")
PORT = 8642


def _row(r):
    return {k: r[k] for k in r.keys()}


def _min_to_hhmm(m):
    if m is None:
        return "--"
    m = m % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


# ------------------------------------------------------------------ API
def api_summary(con, q):
    cur = con.cursor()
    tables = {
        "stations": "车站", "lines": "线路", "trains": "车次",
        "train_stops": "经停记录", "airports": "机场",
        "emu_models": "动车组型号", "scenic_spots": "景点",
    }
    data = {label: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t, label in tables.items()}
    by_type = cur.execute("SELECT type, COUNT(*) c FROM trains GROUP BY type ORDER BY type").fetchall()
    data["车次分布"] = {r["type"]: r["c"] for r in by_type}
    major = cur.execute("SELECT COUNT(*) FROM stations WHERE is_major=1").fetchone()[0]
    data["主要车站"] = major
    meta = {r["k"]: r["v"] for r in cur.execute("SELECT k, v FROM meta").fetchall()}
    data["数据来源"] = meta.get("data_source", "本地生成示例数据")
    return {"ok": True, "data": data}


def api_stations(con, q):
    cur = con.cursor()
    kw = (q.get("q", [""])[0] or "").strip()
    page = max(1, int(q.get("page", ["1"])[0]))
    size = min(100, max(5, int(q.get("size", ["20"])[0])))
    where, params = "1=1", []
    if kw:
        where = "(name LIKE ? OR pinyin_full LIKE ? OR pinyin_abbr LIKE ? OR city LIKE ?)"
        params = [f"%{kw}%"] * 4
    total = cur.execute(f"SELECT COUNT(*) FROM stations WHERE {where}", params).fetchone()[0]
    rows = cur.execute(
        f"SELECT id, name, telecode, pinyin_full, pinyin_abbr, city, is_major "
        f"FROM stations WHERE {where} ORDER BY is_major DESC, pinyin_full LIMIT ? OFFSET ?",
        params + [size, (page - 1) * size]).fetchall()
    return {"ok": True, "total": total, "page": page, "size": size,
            "data": [_row(r) for r in rows]}


def api_station_detail(con, q, sid):
    cur = con.cursor()
    r = cur.execute("SELECT * FROM stations WHERE id=?", (sid,)).fetchone()
    if not r:
        return {"ok": False, "error": "车站不存在"}
    stop_count = cur.execute("SELECT COUNT(*) FROM train_stops WHERE station_id=?", (sid,)).fetchone()[0]
    lines = cur.execute(
        "SELECT l.id, l.name, l.category, ls.seq, ls.mileage FROM line_stations ls "
        "JOIN lines l ON l.id = ls.line_id WHERE ls.station_id=? ORDER BY ls.seq", (sid,)).fetchall()
    scenic = cur.execute("SELECT id, name, level, note FROM scenic_spots WHERE station_id=?", (sid,)).fetchall()
    return {"ok": True, "data": {
        "station": _row(r), "stop_count": stop_count,
        "lines": [_row(x) for x in lines],
        "scenic": [_row(x) for x in scenic]}}


def api_station_trains(con, q, sid):
    cur = con.cursor()
    rows = cur.execute(
        "SELECT t.id, t.code, t.type, t.emu_model, ts.arrive_min, ts.depart_min, ts.stop_minutes, "
        "ts.seq, s1.name AS start_name, s2.name AS end_name, "
        "(SELECT s.name FROM train_stops x JOIN stations s ON s.id=x.station_id "
        " WHERE x.train_id=t.id AND x.seq=ts.seq+1) AS next_station, "
        "(SELECT x.depart_min FROM train_stops x WHERE x.train_id=t.id AND x.seq=ts.seq+1) AS next_depart "
        "FROM train_stops ts JOIN trains t ON t.id=ts.train_id "
        "JOIN stations s1 ON s1.id=t.start_station_id JOIN stations s2 ON s2.id=t.end_station_id "
        "WHERE ts.station_id=? ORDER BY ts.arrive_min", (sid,)).fetchall()
    data = []
    for r in rows:
        d = _row(r)
        d["arrive"] = _min_to_hhmm(r["arrive_min"])
        d["depart"] = _min_to_hhmm(r["depart_min"])
        if r["arrive_min"] is not None and r["next_depart"] is not None:
            d["section_time"] = (r["next_depart"] - r["arrive_min"]) % 1440
        data.append(d)
    return {"ok": True, "station_id": sid, "count": len(data), "data": data}


def api_trains(con, q):
    cur = con.cursor()
    kw = (q.get("q", [""])[0] or "").strip().upper()
    ttype = (q.get("type", [""])[0] or "").strip().upper()
    page = max(1, int(q.get("page", ["1"])[0]))
    size = min(100, max(5, int(q.get("size", ["20"])[0])))
    where, params = "1=1", []
    if kw:
        where += " AND t.code LIKE ?"
        params.append(f"%{kw}%")
    if ttype:
        where += " AND t.type = ?"
        params.append(ttype)
    total = cur.execute(f"SELECT COUNT(*) FROM trains t WHERE {where}", params).fetchone()[0]
    rows = cur.execute(
        f"SELECT t.id, t.code, t.type, t.depart_time, t.arrive_time, t.mileage, t.emu_model, "
        f"s1.name AS start_name, s2.name AS end_name, l.name AS line_name "
        f"FROM trains t JOIN stations s1 ON s1.id=t.start_station_id "
        f"JOIN stations s2 ON s2.id=t.end_station_id LEFT JOIN lines l ON l.id=t.line_id "
        f"WHERE {where} ORDER BY t.code LIMIT ? OFFSET ?",
        params + [size, (page - 1) * size]).fetchall()
    data = []
    for r in rows:
        d = _row(r)
        d["depart"] = _min_to_hhmm(r["depart_time"])
        d["arrive"] = _min_to_hhmm(r["arrive_time"])
        d["duration"] = r["arrive_time"] - r["depart_time"]
        data.append(d)
    return {"ok": True, "total": total, "page": page, "size": size, "data": data}


def api_train_detail(con, q, tid):
    cur = con.cursor()
    t = cur.execute(
        "SELECT t.*, s1.name AS start_name, s2.name AS end_name, l.name AS line_name, "
        "e.nickname AS emu_nickname, e.max_speed AS emu_max_speed "
        "FROM trains t JOIN stations s1 ON s1.id=t.start_station_id "
        "JOIN stations s2 ON s2.id=t.end_station_id "
        "LEFT JOIN lines l ON l.id=t.line_id LEFT JOIN emu_models e ON e.model=t.emu_model "
        "WHERE t.id=?", (tid,)).fetchone()
    if not t:
        return {"ok": False, "error": "车次不存在"}
    stops = cur.execute(
        "SELECT ts.seq, s.name, s.city, ts.arrive_min, ts.depart_min, ts.stop_minutes, ts.mileage "
        "FROM train_stops ts JOIN stations s ON s.id=ts.station_id "
        "WHERE ts.train_id=? ORDER BY ts.seq", (tid,)).fetchall()
    data = _row(t)
    data["depart"] = _min_to_hhmm(t["depart_time"])
    data["arrive"] = _min_to_hhmm(t["arrive_time"])
    data["duration"] = t["arrive_time"] - t["depart_time"]
    data["stops"] = [{
        "seq": r["seq"], "station": r["name"], "city": r["city"],
        "arrive": _min_to_hhmm(r["arrive_min"]), "depart": _min_to_hhmm(r["depart_min"]),
        "stop": r["stop_minutes"], "mileage": r["mileage"],
    } for r in stops]
    return {"ok": True, "data": data}


def api_lines(con, q):
    cur = con.cursor()
    rows = cur.execute(
        "SELECT l.*, COUNT(ls.id) AS station_count, "
        "GROUP_CONCAT(s.name, ' — ') AS route "
        "FROM lines l JOIN line_stations ls ON ls.line_id=l.id "
        "JOIN stations s ON s.id=ls.station_id "
        "GROUP BY l.id ORDER BY l.mileage DESC").fetchall()
    return {"ok": True, "data": [_row(r) for r in rows]}


def api_line_detail(con, q, lid):
    cur = con.cursor()
    l = cur.execute("SELECT * FROM lines WHERE id=?", (lid,)).fetchone()
    if not l:
        return {"ok": False, "error": "线路不存在"}
    stops = cur.execute(
        "SELECT ls.seq, s.id, s.name, s.city, ls.mileage FROM line_stations ls "
        "JOIN stations s ON s.id=ls.station_id WHERE ls.line_id=? ORDER BY ls.seq", (lid,)).fetchall()
    trains = cur.execute(
        "SELECT id, code, type FROM trains WHERE line_id=? ORDER BY code", (lid,)).fetchall()
    return {"ok": True, "data": {"line": _row(l),
                                 "stations": [_row(r) for r in stops],
                                 "trains": [_row(r) for r in trains]}}


def api_schedule(con, q):
    """时刻表查询: 某站 N 点之后出发/到达的车次(复刻 schedule 页面)。"""
    cur = con.cursor()
    sid = q.get("station_id", [None])[0]
    after = q.get("after", ["0"])[0]
    try:
        sid = int(sid) if sid is not None else None
        after = int(after)
    except ValueError:
        return {"ok": False, "error": "参数错误"}
    if sid is None:
        return {"ok": False, "error": "缺少 station_id"}
    s = cur.execute("SELECT name FROM stations WHERE id=?", (sid,)).fetchone()
    if not s:
        return {"ok": False, "error": "车站不存在"}
    total = cur.execute(
        "SELECT COUNT(*) FROM train_stops ts JOIN trains t ON t.id=ts.train_id "
        "WHERE ts.station_id=? AND (COALESCE(ts.depart_min, ts.arrive_min) >= ?)",
        (sid, after)).fetchone()[0]
    rows = cur.execute(
        "SELECT t.id, t.code, t.type, ts.arrive_min, ts.depart_min, "
        "s1.name AS start_name, s2.name AS end_name "
        "FROM train_stops ts JOIN trains t ON t.id=ts.train_id "
        "JOIN stations s1 ON s1.id=t.start_station_id JOIN stations s2 ON s2.id=t.end_station_id "
        "WHERE ts.station_id=? AND (COALESCE(ts.depart_min, ts.arrive_min) >= ?) "
        "ORDER BY COALESCE(ts.depart_min, ts.arrive_min) LIMIT 500", (sid, after)).fetchall()
    data = []
    for r in rows:
        d = _row(r)
        d["arrive"] = _min_to_hhmm(r["arrive_min"])
        d["depart"] = _min_to_hhmm(r["depart_min"])
        data.append(d)
    return {"ok": True, "station": s["name"], "after": _min_to_hhmm(after),
            "total": total, "data": data}


def _sid_name(con, sid):
    r = con.execute("SELECT name FROM stations WHERE id=?", (sid,)).fetchone()
    return r["name"] if r else None


def fmt_dur(m):
    m = max(0, int(m))
    return f"{m // 60}小时{m % 60:02d}分"


def api_transfer(con, q):
    """直达查询: 两站之间的所有直达车(复刻 transfer 页面)。"""
    cur = con.cursor()
    try:
        fid, tid = int(q["from"][0]), int(q["to"][0])
    except (KeyError, ValueError):
        return {"ok": False, "error": "需要 from 与 to 两个 station_id"}
    f = cur.execute("SELECT name FROM stations WHERE id=?", (fid,)).fetchone()
    t = cur.execute("SELECT name FROM stations WHERE id=?", (tid,)).fetchone()
    if not f or not t:
        return {"ok": False, "error": "车站不存在"}
    rows = cur.execute(
        "SELECT t1.id, t1.code, t1.type, t1.emu_model, "
        "a1.depart_min AS d1, a1.arrive_min AS a1, a2.arrive_min AS a2, "
        "a1.mileage AS m1, a2.mileage AS m2, t1.mileage AS total "
        "FROM trains t1 "
        "JOIN train_stops a1 ON a1.train_id=t1.id AND a1.station_id=? "
        "JOIN train_stops a2 ON a2.train_id=t1.id AND a2.station_id=? AND a2.seq>a1.seq "
        "ORDER BY a1.depart_min", (fid, tid)).fetchall()
    data = []
    for r in rows:
        data.append({
            "train_id": r["id"], "code": r["code"], "type": r["type"], "emu_model": r["emu_model"],
            "depart": _min_to_hhmm(r["d1"]), "arrive": _min_to_hhmm(r["a2"]),
            "duration": r["a2"] - r["d1"],
            "mileage": r["m2"] - r["m1"],
        })
    return {"ok": True, "from": f["name"], "to": t["name"], "count": len(data), "data": data}


def api_airports(con, q):
    rows = con.execute("SELECT * FROM airports ORDER BY city").fetchall()
    return {"ok": True, "data": [_row(r) for r in rows]}


def api_emu(con, q):
    rows = con.execute("SELECT * FROM emu_models ORDER BY max_speed DESC").fetchall()
    return {"ok": True, "data": [_row(r) for r in rows]}


def api_scenic(con, q):
    rows = con.execute(
        "SELECT sp.*, s.name AS station_name FROM scenic_spots sp "
        "LEFT JOIN stations s ON s.id=sp.station_id ORDER BY sp.level DESC, sp.city").fetchall()
    return {"ok": True, "data": [_row(r) for r in rows]}


def api_import(con, q, body):
    """数据导入(复刻 downloader): POST JSON {"table": "...", "rows": [...]}"""
    table = (body.get("table") or "").strip()
    rows = body.get("rows") or []
    allowed = {
        "scenic_spots": ["name", "city", "level", "note"],
        "airports": ["iata", "name", "city"],
    }
    if table not in allowed:
        return {"ok": False, "error": f"仅支持导入 {list(allowed)}"}
    cols = allowed[table]
    n = 0
    for row in rows:
        vals = [row.get(c) for c in cols]
        if not vals[0]:
            continue
        try:
            con.execute(
                f"INSERT INTO {table}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", vals)
            n += 1
        except sqlite3.IntegrityError:
            continue  # 重复数据跳过
    con.commit()
    return {"ok": True, "imported": n, "table": table}


ROUTES = [
    (r"^/api/summary$", api_summary),
    (r"^/api/stations$", api_stations),
    (r"^/api/stations/(\d+)/trains$", api_station_trains),
    (r"^/api/stations/(\d+)$", api_station_detail),
    (r"^/api/trains$", api_trains),
    (r"^/api/trains/(\d+)$", api_train_detail),
    (r"^/api/lines$", api_lines),
    (r"^/api/lines/(\d+)$", api_line_detail),
    (r"^/api/schedule$", api_schedule),
    (r"^/api/journey$", planv2.api_journey),
    (r"^/api/plan$", planv2.api_plan),
    (r"^/api/flights$", planv2.api_flights),
    (r"^/api/coords$", planv2.api_coords),
    (r"^/api/price_calendar$", planv2.api_price_calendar),
    (r"^/api/airports_full$", planv2.api_airports_full),
    (r"^/api/update_status$", planv2.api_update_status),
    (r"^/api/transfer$", api_transfer),
    (r"^/api/airports$", api_airports),
    (r"^/api/emu$", api_emu),
    (r"^/api/scenic$", api_scenic),
]


class Handler(BaseHTTPRequestHandler):
    server_version = "TrainApp/1.0"

    def log_message(self, fmt, *args):
        print("[http]", self.address_string(), fmt % args)

    # -- 响应工具
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        fp = os.path.normpath(os.path.join(
            STATIC_DIR, path.lstrip("/").removeprefix("static/")))
        if not fp.startswith(STATIC_DIR) or not os.path.isfile(fp):
            self._send_json({"ok": False, "error": "not found"}, 404)
            return
        ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        body = open(fp, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- GET
    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        con = connect()
        try:
            for pattern, fn in ROUTES:
                m = re.match(pattern, parsed.path)
                if m:
                    args = [con, qs] + [int(g) for g in m.groups()]
                    return self._send_json(fn(*args))
            if parsed.path.startswith("/static/") or parsed.path == "/":
                return self._send_static(parsed.path)
            return self._send_json({"ok": False, "error": "unknown route"}, 404)
        except Exception as e:  # noqa: BLE001
            return self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        finally:
            con.close()

    # -- POST /api/import
    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/update_check":
            return self._send_json(planv2.api_update_check(connect(), {}))
        if parsed.path != "/api/import":
            return self._send_json({"ok": False, "error": "unknown route"}, 404)
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            return self._send_json({"ok": False, "error": f"bad json: {e}"}, 400)
        con = connect()
        try:
            return self._send_json(api_import(con, parse_qs(parsed.query), body))
        except Exception as e:  # noqa: BLE001
            return self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        finally:
            con.close()


def main():
    # 打包模式: 首次运行把内置数据库解包到 exe 旁
    if getattr(sys, "frozen", False):
        bundled = os.path.join(RESOURCE_DIR, "data", "train.db")
        if not os.path.exists(DB_PATH) and os.path.exists(bundled):
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            shutil.copy(bundled, DB_PATH)
            print("[init] 已释放内置数据库 ->", DB_PATH)
    seed()  # 已存在则跳过
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{PORT}"
    print("=== 坐着火车去旅行 · 本地数据库版 ===")
    print(f"数据库: {os.path.join(BASE_DIR, 'data', 'train.db')}")
    print(f"服务已启动: {url}")
    try:
        import updater
        updater.start_background()  # 每次进入程序自动更新车次/航班数据
    except Exception as e:  # noqa: BLE001
        print("[warn] 自动更新启动失败:", e)
    if "--web" in sys.argv or "--no-tray" in sys.argv or os.name != "nt":
        # 浏览器模式(显式)
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
        if "--no-tray" in sys.argv or os.name != "nt":
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                print("\nbye")
            return
        _run_tray(url)
        return
    _run_desktop(url)


def _run_desktop(url):
    """原生桌面窗口(WebView2), 不依赖浏览器。失败则退化为浏览器。"""
    try:
        import webview
        print("[ui] 启动桌面窗口(WebView2)...")
        webview.create_window("坐着火车去旅行 · 本地版", url, width=1280, height=860,
                              background_color="#0f1420")
        webview.start()
        print("[ui] 窗口已关闭, 退出")
        os._exit(0)
    except Exception as e:  # noqa: BLE001
        print("[warn] 桌面窗口失败, 回退浏览器:", e)
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass


def _run_tray(url):
    """系统托盘: 左键/双击打开页面, 右键菜单退出。"""
    try:
        import pystray
        from PIL import Image
    except ImportError:
        print("[warn] 未安装 pystray/Pillow, 退化为控制台模式 (--no-tray)")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return
    icon_path = os.path.join(RESOURCE_DIR, "assets", "icon.ico")
    try:
        image = Image.open(icon_path)
    except Exception:  # noqa: BLE001
        image = Image.new("RGB", (64, 64), "#fe295f")

    def on_open(icon, item):
        webbrowser.open(url)

    def on_quit(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("打开页面", on_open, default=True),
        pystray.MenuItem("退出", on_quit),
    )
    icon = pystray.Icon("TrainApp", image, "坐着火车去旅行 · 本地版", menu)
    print("[tray] 托盘图标已启动, 右键退出")
    try:
        icon.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
