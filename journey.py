# -*- coding: utf-8 -*-
"""journey.py — 出行方案搜索引擎。

功能:
  - 车站/城市模糊解析(输入"北京"得到该城全部站点之间的连接方案)
  - 直达 / 一次中转 / 两次中转 BFS(时间依赖网络, 含同城异站换乘)
  - 票价与车上时长估算(站点坐标球面距离 × 车型费率; 真实票价以 12306 为准)
  - 方案路径坐标(供地图绘制线路走向)
"""
import math

from db import connect

# 票价估算参数: 车型 -> (费率 元/km, 距离放大系数 铁路绕行)
PRICE_RATE = {"G": 0.45, "C": 0.40, "D": 0.31, "K": 0.16, "T": 0.16, "Z": 0.18}
DIST_FACTOR = {"G": 1.25, "C": 1.25, "D": 1.22, "K": 1.20, "T": 1.20, "Z": 1.20}
FLIGHT_BUFFER = 150   # 直飞往返机场/安检缓冲(分钟)
FLIGHT_RATE = 0.58    # 经济舱估算 元/km

MAX_FRONTIER = 12000  # 每轮 relaxation 处理的到达事件上限(按时间取最早)
ARRIVAL_GAP = 30      # 同一车站两次到达间隔小于此值视为重复(分钟)


def haversine(lng1, lat1, lng2, lat2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ------------------------------------------------------------ 地点解析
def resolve_place(cur, text):
    """车站/城市模糊解析。城市名精确匹配优先(输入"北京"得到全城站点), 其次同名车站。"""
    text = (text or "").strip()
    if not text:
        return None
    # 1) 精确城市名(该城 ≥2 站才视为城市查询)
    rows = cur.execute(
        "SELECT id, name, city, is_major FROM stations WHERE city=? "
        "ORDER BY is_major DESC, pinyin_full", (text,)).fetchall()
    if len(rows) >= 2:
        return {"kind": "city", "label": text,
                "sids": [r["id"] for r in rows],
                "stations": [{"id": r["id"], "name": r["name"], "city": r["city"]} for r in rows]}
    # 2) 精确车站名
    exact = cur.execute(
        "SELECT id, name, city FROM stations WHERE name=?", (text,)).fetchall()
    if exact and len(exact) == 1:
        r = exact[0]
        return {"kind": "station", "label": r["name"], "sids": [r["id"]],
                "stations": [{"id": r["id"], "name": r["name"], "city": r["city"]}]}
    # 3) 模糊匹配(城市或站名包含)
    rows = cur.execute(
        "SELECT id, name, city, is_major FROM stations "
        "WHERE city LIKE ? OR name LIKE ? ORDER BY is_major DESC, pinyin_full LIMIT 60",
        (f"%{text}%", f"%{text}%")).fetchall()
    if not rows:
        return None
    cities = {r["city"] for r in rows}
    if len(cities) == 1:
        c = next(iter(cities))
        return {"kind": "city", "label": c,
                "sids": [r["id"] for r in rows],
                "stations": [{"id": r["id"], "name": r["name"], "city": r["city"]} for r in rows]}
    return {"kind": "custom", "label": text,
            "sids": [r["id"] for r in rows[:20]],
            "stations": [{"id": r["id"], "name": r["name"], "city": r["city"]} for r in rows[:20]]}


# ------------------------------------------------------------ 网络构建
def build_graph(cur):
    trains, station_legs = {}, {}
    for r in cur.execute(
            "SELECT ts.train_id, t.code, t.type, ts.station_id, ts.seq, ts.arrive_min, "
            "ts.depart_min, ts.stop_minutes, s1.name AS start_name, s2.name AS end_name "
            "FROM train_stops ts JOIN trains t ON t.id = ts.train_id "
            "JOIN stations s1 ON s1.id = t.start_station_id "
            "JOIN stations s2 ON s2.id = t.end_station_id "
            "ORDER BY ts.train_id, ts.seq"):
        tr = trains.get(r["train_id"])
        if tr is None:
            tr = trains[r["train_id"]] = {
                "code": r["code"], "type": r["type"], "start": r["start_name"],
                "end": r["end_name"], "stops_list": [], "cum": None}
        tr["stops_list"].append(
            (r["station_id"], r["seq"], r["arrive_min"], r["depart_min"], r["stop_minutes"]))
        station_legs.setdefault(r["station_id"], []).append(
            (r["train_id"], r["seq"], r["arrive_min"], r["depart_min"]))
    coords, names, city_of, city_sids = {}, {}, {}, {}
    for r in cur.execute("SELECT id, name, city, lng, lat FROM stations"):
        names[r["id"]] = r["name"]
        city_of[r["id"]] = r["city"]
        city_sids.setdefault(r["city"], []).append(r["id"])
        if r["lng"] is not None:
            coords[r["id"]] = (r["lng"], r["lat"])
    return {"trains": trains, "legs": station_legs, "coords": coords,
            "names": names, "city_of": city_of, "city_sids": city_sids}


def _train_cum(G, tr):
    """累计里程(公里, 球面距离×绕行系数); 任一站缺坐标则该位置之后为 None。"""
    if tr["cum"] is not None:
        return tr["cum"]
    cum, ok = [0.0], True
    sl = tr["stops_list"]
    for i in range(1, len(sl)):
        a, b = G["coords"].get(sl[i - 1][0]), G["coords"].get(sl[i][0])
        if a and b and ok:
            cum.append(cum[i - 1] + haversine(a[0], a[1], b[0], b[1])
                       * DIST_FACTOR.get(tr["type"], 1.2))
        else:
            ok = False
            cum.append(None)
    tr["cum"] = cum
    return cum


def _seg_info(G, tr, p1, p2):
    """(车行驶分钟, 估算里程km|None, 估算票价|None, 路径坐标)"""
    sl = tr["stops_list"]
    dep = sl[p1][3] if sl[p1][3] is not None else sl[p1][2]
    arr = sl[p2][2] if sl[p2][2] is not None else sl[p2][3]
    if dep is None or arr is None:
        return None, None, None, []
    ride = (arr - dep) - sum(sl[j][4] for j in range(p1 + 1, p2))
    cum = _train_cum(G, tr)
    km = (cum[p2] - cum[p1]) if (cum[p1] is not None and cum[p2] is not None) else None
    price = max(5, round(km * PRICE_RATE.get(tr["type"], 0.3))) if km else None
    # 路径坐标(最多 80 点, 均匀采样)
    pts = [(G["coords"][sl[j][0]][0], G["coords"][sl[j][0]][1], G["names"].get(sl[j][0], ""))
           for j in range(p1, p2 + 1) if sl[j][0] in G["coords"]]
    if len(pts) > 80:
        step = len(pts) / 80.0
        pts = [pts[int(i * step)] for i in range(80)]
    return ride, km, price, pts


def _pos_of_seq(sl, seq):
    for i, s in enumerate(sl):
        if s[1] == seq:
            return i
    return -1


# ------------------------------------------------------------ BFS 搜索
def _search(G, from_sids, to_sids, after, min_tr, min_tr_city, max_wait, max_legs):
    trains, legs, names = G["trains"], G["legs"], G["names"]
    to_set = set(to_sids)
    arrivals = {}   # sid -> [(t, parent), ...] 按时间升序

    def relax(sid, t, parent):
        lst = arrivals.setdefault(sid, [])
        for tt, _ in lst:
            if abs(tt - t) < ARRIVAL_GAP:
                return False
        lst.append((t, parent))
        lst.sort(key=lambda x: x[0])
        return True

    for sid in from_sids:
        relax(sid, after, ("origin",))

    plans, seen = [], set()

    def chain(sid, t, parent):
        """回溯到出发站, 返回到达事件链(倒序->正序)。"""
        events = []
        cur_sid, cur_t, p = sid, t, parent
        while p and p[0] != "origin":
            events.append((cur_sid, cur_t, p))
            if p[0] == "train":
                _, tid, seq1, seq2, bsid, bt = p
                # 上车站的到达事件
                found = None
                for tt, pp in arrivals.get(bsid, []):
                    if abs(tt - bt) < ARRIVAL_GAP:
                        found = (tt, pp)
                        break
                if found is None:
                    return None
                cur_sid, cur_t, p = bsid, found[0], found[1]
            else:  # walk: (_, from_sid, from_t)
                _, fsid, ft = p
                found = None
                for tt, pp in arrivals.get(fsid, []):
                    if abs(tt - ft) < ARRIVAL_GAP:
                        found = (tt, pp)
                        break
                if found is None:
                    return None
                cur_sid, cur_t, p = fsid, found[0], found[1]
        events.reverse()
        return events

    def make_plan(sid, t, parent, transfers):
        ev = chain(sid, t, parent)
        if not ev:
            return
        legs = []
        for e_sid, e_t, e_p in ev:
            if e_p[0] == "train":
                _, tid, seq1, seq2, bsid, bt = e_p
                tr = trains[tid]
                p1, p2 = _pos_of_seq(tr["stops_list"], seq1), _pos_of_seq(tr["stops_list"], seq2)
                if p1 < 0 or p2 < 0:
                    return
                ride, km, price, pts = _seg_info(G, tr, p1, p2)
                sl = tr["stops_list"]
                dep = sl[p1][3] if sl[p1][3] is not None else sl[p1][2]
                arr = sl[p2][2] if sl[p2][2] is not None else sl[p2][3]
                legs.append({"kind": "train", "train_id": tid, "code": tr["code"],
                             "type": tr["type"], "start": tr["start"], "end": tr["end"],
                             "board": names.get(sl[p1][0], ""), "board_sid": sl[p1][0],
                             "alight": names.get(sl[p2][0], ""), "alight_sid": sl[p2][0],
                             "board_city": G["city_of"].get(sl[p1][0], ""),
                             "alight_city": G["city_of"].get(sl[p2][0], ""),
                             "dep": dep, "arr": arr, "ride": ride, "km": km, "price": price,
                             "path": pts})
            else:
                _, fsid, _ft = e_p
                legs.append({"kind": "walk", "walk_from": names.get(fsid, ""),
                             "walk_to": names.get(e_sid, ""), "walk_min": min_tr_city})
        if not legs or legs[0].get("kind") != "train":
            return
        key = tuple(l["train_id"] for l in legs if l["kind"] == "train")
        if key in seen:
            return
        seen.add(key)
        dep0, arrN = legs[0]["dep"], legs[-1]["arr"]
        ride = sum(l["ride"] for l in legs if l["kind"] == "train" and l["ride"])
        price = sum(l["price"] for l in legs if l["kind"] == "train" and l["price"])
        n_legs = len([l for l in legs if l["kind"] == "train"])
        price = price if len([l for l in legs if l["kind"] == "train" and l["price"]]) == n_legs else None
        plans.append({"kind": "train", "transfers": transfers,
                      "legs": legs, "dep": dep0, "arr": arrN,
                      "total": arrN - dep0, "ride": ride, "price": price})

    frontier = []
    for sid, lst in arrivals.items():
        if sid in from_sids:
            for t, p in lst:
                frontier.append((sid, t, p))

    for rnd in range(max_legs + 1):
        nxt = []
        processed = 0
        for sid, t, parent in sorted(frontier, key=lambda x: x[1]):
            if processed >= MAX_FRONTIER:
                break
            processed += 1
            dep_floor = t if rnd == 0 else t + min_tr
            dep_ceil = None if rnd == 0 else t + max_wait
            for tid, seq, _arr0, dep in legs.get(sid, ()):
                if dep is None or dep < dep_floor:
                    continue
                if dep_ceil is not None and dep > dep_ceil:
                    continue
                tr = trains[tid]
                p1 = _pos_of_seq(tr["stops_list"], seq)
                if p1 < 0:
                    continue
                for j in range(p1 + 1, len(tr["stops_list"])):
                    sid2, seq2, arr2, dep2, _sm = tr["stops_list"][j]
                    arr_t = arr2 if arr2 is not None else dep2
                    if arr_t is None:
                        continue
                    np = ("train", tid, seq, seq2, sid, t)
                    if relax(sid2, arr_t, np):
                        nxt.append((sid2, arr_t, np))
                        if sid2 in to_set:
                            make_plan(sid2, arr_t, np, rnd)
        # 同城步行边(不计入换乘次数)
        if rnd < max_legs:
            walks = []
            for sid, t, parent in nxt:
                city = G["city_of"].get(sid)
                if not city or len(G["city_sids"].get(city, ())) < 2:
                    continue
                for s in G["city_sids"][city]:
                    if s == sid or s in to_set:
                        continue
                    wp = ("walk", sid, t)
                    if relax(s, t + min_tr_city, wp):
                        walks.append((s, t + min_tr_city, wp))
            nxt.extend(walks)
        frontier = nxt
        if not frontier:
            break
    return plans


# ------------------------------------------------------------ 飞行部分
def _city_airports(cur, city):
    return [r["iata"] for r in cur.execute(
        "SELECT iata FROM airports_full WHERE cn_city=?", (city,))]


def _hhmm_min(m):
    m %= 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _sched_plans(cur, sa, da, km, price_est, from_city, to_city, limit=8):
    """flight_schedules 中该机场对的真实班次 → 方案列表(无则 [])。"""
    rows = cur.execute(
        "SELECT flight_no, airline_iata, dep_airport, arr_airport, dep_min, arr_min, model "
        "FROM flight_schedules WHERE dep_city=? AND arr_city=? ORDER BY dep_min LIMIT ?",
        (from_city, to_city, limit)).fetchall()
    out = []
    cjk = lambda s: bool(s and any('\u4e00' <= ch <= '\u9fff' for ch in s))
    for s in rows:
        from import_flights import AIRLINE_CN
        dur = max(45, s["arr_min"] - s["dep_min"])
        dep_ap = s["dep_airport"] if cjk(s["dep_airport"]) else f'{sa["cn_city"]}机场'
        arr_ap = s["arr_airport"] if cjk(s["arr_airport"]) else f'{da["cn_city"]}机场'
        out.append({
            "kind": "flight", "category": "直飞",
            "flight_no": s["flight_no"], "airline": AIRLINE_CN.get(s["airline_iata"], s["airline_iata"]),
            "src_iata": sa["iata"], "src_airport_cn": dep_ap or sa["name"],
            "dst_iata": da["iata"], "dst_airport_cn": arr_ap or da["name"],
            "dep": _hhmm_min(s["dep_min"]), "arr": _hhmm_min(s["arr_min"]),
            "model": s["model"],
            "ride": dur, "km": km, "price": price_est,
            "total": dur + FLIGHT_BUFFER,
            "path": [[sa["lon"], sa["lat"], sa["cn_city"]], [da["lon"], da["lat"], da["cn_city"]]],
        })
    return out


def flight_plans(cur, from_city, to_city):
    """城市对直飞方案: 优先返回真实航班时刻(flight_schedules), 否则按航线估算。"""
    src = _city_airports(cur, from_city)
    dst = _city_airports(cur, to_city)
    if not src or not dst:
        return []
    qmarks = ",".join("?" * len(src))
    qmarks2 = ",".join("?" * len(dst))
    rows = cur.execute(
        f"SELECT * FROM flights WHERE src_iata IN ({qmarks}) AND dst_iata IN ({qmarks2}) "
        f"ORDER BY duration_min LIMIT 12", src + dst).fetchall()
    has_sched = cur.execute(
        "SELECT 1 FROM flight_schedules WHERE dep_city=? AND arr_city=? LIMIT 1",
        (from_city, to_city)).fetchone()
    if has_sched and rows:
        # 班期库按"城市对"排班: 只用第一条航线行取里程/估价, 避免多机场组合重复展开
        r = rows[0]
        sa = cur.execute("SELECT iata, name, cn_city, lat, lon FROM airports_full WHERE iata=?",
                         (r["src_iata"],)).fetchone()
        da = cur.execute("SELECT iata, name, cn_city, lat, lon FROM airports_full WHERE iata=?",
                         (r["dst_iata"],)).fetchone()
        return _sched_plans(cur, sa, da, r["km"], r["price_est"], from_city, to_city)
    out = []
    for r in rows:
        sa = cur.execute("SELECT iata, name, cn_city, lat, lon FROM airports_full WHERE iata=?",
                         (r["src_iata"],)).fetchone()
        da = cur.execute("SELECT iata, name, cn_city, lat, lon FROM airports_full WHERE iata=?",
                         (r["dst_iata"],)).fetchone()
        if not sa or not da:
            continue
        out.append({
            "kind": "flight", "category": "直飞",
            "flight_no": r["flight_no"], "airline": r["airline"],
            "src_iata": r["src_iata"], "src_airport": sa["name"],
            "dst_iata": r["dst_iata"], "dst_airport": da["name"],
            "ride": r["duration_min"], "km": r["km"], "price": r["price_est"],
            "total": r["duration_min"] + FLIGHT_BUFFER,
            "path": [[sa["lon"], sa["lat"], sa["cn_city"]], [da["lon"], da["lat"], da["cn_city"]]],
        })
    return out


def rail_leg_between(cur, G, from_city, to_city):
    """两城市间最快直达火车
    (train_id, code, type, ride_min, dep, arr, price, board_sid, alight_sid) | None"""
    fs = {r["id"] for r in cur.execute("SELECT id FROM stations WHERE city=?", (from_city,))}
    ts = {r["id"] for r in cur.execute("SELECT id FROM stations WHERE city=?", (to_city,))}
    if not fs or not ts:
        return None
    best = None
    for tid, in cur.execute("SELECT id FROM trains"):
        tr = G["trains"].get(tid)
        if not tr:
            continue
        p1 = p2 = None
        for i, (sid, seq, arr, dep, _sm) in enumerate(tr["stops_list"]):
            if sid in fs and p1 is None and dep is not None:
                p1 = i
            elif sid in ts and p1 is not None and p2 is None and arr is not None:
                p2 = i
                break
        if p1 is None or p2 is None:
            continue
        ride, _km, price, _pts = _seg_info(G, tr, p1, p2)
        if ride is None:
            continue
        if best is None or ride < best[3]:
            dep = tr["stops_list"][p1][3] or tr["stops_list"][p1][2]
            arr = tr["stops_list"][p2][2] or tr["stops_list"][p2][3]
            best = (tid, tr["code"], tr["type"], ride, dep, arr, price,
                    tr["stops_list"][p1][0], tr["stops_list"][p2][0])
    return best


def multimodal_plans(cur, G, from_city, to_city, flight_list):
    """空铁联运: 经枢纽组合飞行+铁路, 与直飞并列展示供对比。
    方向A 飞行在前: 出发→✈→枢纽→🚄→目的地
    方向B 铁路在前: 出发→🚄→枢纽→✈→目的地
    每方向最多2条。"""
    HUBS = ["北京", "上海", "广州", "成都", "西安", "昆明", "乌鲁木齐", "长沙", "武汉", "厦门"]
    out = []

    def _best_flight(src_iatas, dst_iatas):
        if not src_iatas or not dst_iatas:
            return None
        q1 = ",".join("?" * len(src_iatas))
        q2 = ",".join("?" * len(dst_iatas))
        return cur.execute(
            f"SELECT MIN(duration_min) d, MIN(price_est) p FROM flights "
            f"WHERE src_iata IN ({q1}) AND dst_iata IN ({q2})",
            list(src_iatas) + list(dst_iatas)).fetchone()

    def _hub_city(iata):
        ap = cur.execute("SELECT cn_city, city FROM airports_full WHERE iata=?",
                         (iata,)).fetchone()
        return (ap["cn_city"] or ap["city"]) if ap else None

    def _emit(hub, rail, fl, fly_from, fly_to, rail_from, rail_to):
        if not fl or not fl["d"] or not rail:
            return False
        tid, code, ttype, ride, dep, arr, rprice, sid1, sid2 = rail
        total = fl["d"] + 90 + ride + 45
        price = (fl["p"] or 0) + (rprice or 0)
        rpath = train_path(cur, tid, sid1, sid2)
        out.append({"kind": "multimodal", "category": "空铁联运", "hub": hub,
                    "from_city": from_city, "to_city": to_city,
                    "flight": {"airline": None, "from_city": fly_from, "to_city": fly_to,
                               "duration": fl["d"], "price": fl["p"]},
                    "rail": {"train_id": tid, "code": code, "type": ttype,
                             "from_city": rail_from, "to_city": rail_to,
                             "board": rpath[0][2] if rpath else "",
                             "alight": rpath[-1][2] if rpath else "",
                             "ride": ride, "price": rprice, "path": rpath},
                    "total": total, "price": price if price else None})
        return True

    # 方向A: 飞行在前 —— 出发城市机场 → 枢纽机场, 枢纽 → 火车 → 目的地
    src = _city_airports(cur, from_city)
    if src:
        hub_seen, n_a = set(), 0
        for (dst_iata,) in cur.execute(
                "SELECT DISTINCT dst_iata FROM flights WHERE src_iata IN (%s)"
                % ",".join("?" * len(src)), src).fetchall():
            hub = _hub_city(dst_iata)
            if (hub not in HUBS or hub in hub_seen
                    or hub in (from_city, to_city)):
                continue
            hub_seen.add(hub)
            fl = _best_flight(src, [dst_iata])
            rail = rail_leg_between(cur, G, hub, to_city)
            if _emit(hub, rail, fl, from_city, hub, hub, to_city):
                n_a += 1
                if n_a >= 2:
                    break
    # 方向B: 铁路在前 —— 出发 → 火车 → 枢纽, 枢纽机场 → 目的地机场
    dst = _city_airports(cur, to_city)
    if dst:
        hub_seen, n_b = set(), 0
        for (src_iata,) in cur.execute(
                "SELECT DISTINCT src_iata FROM flights WHERE dst_iata IN (%s)"
                % ",".join("?" * len(dst)), dst).fetchall():
            hub = _hub_city(src_iata)
            if (hub not in HUBS or hub in hub_seen
                    or hub in (from_city, to_city)):
                continue
            hub_seen.add(hub)
            fl = _best_flight(_city_airports(cur, hub), dst)
            rail = rail_leg_between(cur, G, from_city, hub)
            if _emit(hub, rail, fl, hub, to_city, from_city, hub):
                n_b += 1
                if n_b >= 2:
                    break
    return out


# ------------------------------------------------------------ 对外入口
def search(con, from_place, to_place, after=360, min_tr=15, min_tr_city=45,
           max_wait=180, max_legs=2):
    cur = con.cursor()
    G = build_graph(cur)
    plans = _search(G, set(from_place["sids"]), set(to_place["sids"]),
                    after, min_tr, min_tr_city, max_wait, max_legs)
    plans.sort(key=lambda p: (p["total"], p["dep"]))
    for p in plans:
        p["category"] = ("直达" if p["transfers"] == 0
                         else f"中转×{p['transfers']}")
    return G, plans


def train_path(cur, tid, sid_a, sid_b):
    """某车次 a→b 区间的路径坐标(地图绘制)。"""
    rows = cur.execute(
        "SELECT ts.station_id, s.name, s.lng, s.lat, ts.seq FROM train_stops ts "
        "JOIN stations s ON s.id=ts.station_id WHERE ts.train_id=? ORDER BY ts.seq", (tid,)).fetchall()
    i1 = i2 = None
    pts = []
    for i, r in enumerate(rows):
        if r["station_id"] == sid_a and i1 is None:
            i1 = i
        elif r["station_id"] == sid_b and i1 is not None and i2 is None:
            i2 = i
    if i1 is None or i2 is None:
        return pts
    for r in rows[i1:i2 + 1]:
        if r["lng"] is not None:
            pts.append([r["lng"], r["lat"], r["name"]])
    return pts
