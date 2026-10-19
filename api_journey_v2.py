# -*- coding: utf-8 -*-
"""api_journey_v2.py — 出行方案 v2 API。

统一方案列表: 火车(直达/中转×1/中转×2) + 直飞航班 + 空铁联运,
支持城市/车站模糊输入、多维排序字段(总耗时/车上耗时/价格)。
"""
import threading

import journey
from updater import update_all


def _hhmm(m):
    if m is None:
        return "--"
    m = m % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _fdur(m):
    m = max(0, int(m or 0))
    return f"{m // 60}小时{m % 60:02d}分" if m else "--"


def _resolve(con, text, sid=None):
    """优先按 id, 否则模糊文本解析。返回 (place, error)"""
    cur = con.cursor()
    if sid is not None:
        r = cur.execute("SELECT id, name, city FROM stations WHERE id=?", (sid,)).fetchone()
        if not r:
            return None, f"车站 id={sid} 不存在"
        return {"kind": "station", "label": r["name"], "sids": [r["id"]],
                "stations": [{"id": r["id"], "name": r["name"], "city": r["city"]}]}, None
    place = journey.resolve_place(cur, text)
    if not place:
        return None, f"未找到匹配的车站或城市: {text}"
    return place, None


def _place_city(con, place):
    """该地点对应的主要城市名(航班查询用)。"""
    if place["kind"] == "city":
        return place["label"]
    cities = {s["city"] for s in place["stations"]}
    return next(iter(cities)) if len(cities) == 1 else None


def _format_train_plan(p):
    legs = []
    for l in p["legs"]:
        if l["kind"] == "train":
            legs.append({
                "kind": "train", "train_id": l["train_id"], "code": l["code"],
                "type": l["type"], "start": l["start"], "end": l["end"],
                "board": l["board"], "board_sid": l["board_sid"],
                "alight": l["alight"], "alight_sid": l["alight_sid"],
                "board_city": l["board_city"], "alight_city": l["alight_city"],
                "dep": _hhmm(l["dep"]), "arr": _hhmm(l["arr"]),
                "dep_min": l["dep"], "arr_min": l["arr"],
                "ride": l["ride"], "km": round(l["km"]) if l["km"] else None,
                "price": l["price"], "path": l["path"]})
        else:
            legs.append({"kind": "walk", "walk_from": l["walk_from"],
                         "walk_to": l["walk_to"], "walk_min": l["walk_min"]})
    return {"kind": "train", "category": p["category"], "transfers": p["transfers"],
            "dep": _hhmm(p["dep"]), "arr": _hhmm(p["arr"]),
            "dep_min": p["dep"], "arr_min": p["arr"],
            "total": p["total"], "ride": p["ride"], "price": p["price"],
            "total_fmt": _fdur(p["total"]), "ride_fmt": _fdur(p["ride"]),
            "price_fmt": f"约 ¥{p['price']}" if p["price"] else "—",
            "legs": legs}


def _format_flight_plan(f):
    return {**f, "total_fmt": _fdur(f["total"]), "ride_fmt": _fdur(f["ride"]),
            "price_fmt": f"约 ¥{f['price']}" if f["price"] else "—",
            "note": "航班无固定时刻, 时长与票价为按距离估算, 已含往返机场约2.5小时"}


def _format_multimodal(m):
    return {**m, "total_fmt": _fdur(m["total"]),
            "ride_fmt": _fdur(m["flight"]["duration"] + m["rail"]["ride"]),
            "price_fmt": f"约 ¥{m['price']}" if m.get("price") else "—",
            "note": f"经{m['hub']}中转: 飞行+铁路, 已含中转缓冲约2.25小时(估算)"}


def _expand_dest_siblings(cur, place):
    """目标为单一车站时, 把同城其他站也纳入到达范围(显示"终到同城站")。"""
    if place["kind"] != "station":
        return list(place["sids"]), False
    sids = list(place["sids"])
    city = place["stations"][0]["city"]
    sibs = cur.execute("SELECT id FROM stations WHERE city=? AND id NOT IN (?)",
                       (city, sids[0])).fetchall() if city else []
    if sibs:
        sids += [r["id"] for r in sibs]
        return sids, True
    return sids, False


def api_journey(con, q):
    """出行方案(火车): 模糊城市/车站输入, 直达+中转×1+中转×2。date 可查真实票价。"""
    ftext = (q.get("from", [""])[0] or "").strip()
    ttext = (q.get("to", [""])[0] or "").strip()
    fid = q.get("from_id", [None])[0]
    tid = q.get("to_id", [None])[0]
    date_s = _validate_date((q.get("date", [""])[0] or "").strip())
    try:
        fid = int(fid) if fid is not None else None
        tid = int(tid) if tid is not None else None
        after = int(q.get("after", ["360"])[0])
        max_legs = min(2, max(0, int(q.get("max_legs", ["2"])[0])))
        max_wait = int(q.get("max_wait", ["180"])[0])
        min_tr = int(q.get("min_transfer", ["15"])[0])
        min_tr_city = int(q.get("min_transfer_city", ["45"])[0])
    except ValueError:
        return {"ok": False, "error": "参数错误"}
    if not ((ftext or fid is not None) and (ttext or tid is not None)):
        return {"ok": False, "error": "需要 from/to(车站或城市名)"}
    fp, err = _resolve(con, ftext, fid)
    if err:
        return {"ok": False, "error": err}
    tp, err = _resolve(con, ttext, tid)
    if err:
        return {"ok": False, "error": err}

    cur = con.cursor()
    to_sids, same_city_arrive = _expand_dest_siblings(cur, tp)
    tp2 = {**tp, "sids": to_sids}
    import time as _t
    t0 = _t.time()
    G, plans = journey.search(con, fp, tp2, after=after, min_tr=min_tr,
                              min_tr_city=min_tr_city, max_wait=max_wait, max_legs=max_legs)
    elapsed = round(_t.time() - t0, 2)
    if same_city_arrive:
        for p in plans:
            if p["legs"][-1]["alight_sid"] != tp["sids"][0]:
                p["same_city_arrive"] = True
    out = [_format_train_plan(p) for p in plans]
    real_pairs = 0
    if date_s:
        try:
            real_pairs = _attach_real_prices(con, out, date_s)
        except Exception as e:  # noqa: BLE001
            print("[journey] 真实票价获取失败:", e)
    return {"ok": True, "elapsed": elapsed, "date": date_s, "real_pairs": real_pairs,
            "from": {k: fp[k] for k in ("kind", "label", "stations")},
            "to": {k: tp[k] for k in ("kind", "label", "stations")},
            "plans": out,
            "counts": {
                "直达": sum(1 for p in out if p["transfers"] == 0),
                "中转×1": sum(1 for p in out if p["transfers"] == 1),
                "中转×2": sum(1 for p in out if p["transfers"] == 2)}}


def _validate_date(raw):
    """date 参数: YYYY-MM-DD, 须在今天~预售期内。非法返回 None。"""
    import datetime as _dt
    import realprice
    if not raw:
        return None
    try:
        d = _dt.date.fromisoformat(raw)
    except ValueError:
        return None
    today = _dt.date.today()
    if not (today <= d <= today + _dt.timedelta(days=realprice.presale_limit() - 1)):
        return None
    return d.isoformat()


def _attach_real_prices(con, out, date_s, cap=8):
    """给火车方案挂 12306 真实票价。返回获取到的站对数。"""
    import realprice
    tele = {r[0]: r[1] for r in con.execute(
        "SELECT id, telecode FROM stations WHERE telecode IS NOT NULL")}
    pairs = []
    for p in out:
        if p["kind"] != "train":
            continue
        for l in p["legs"]:
            if l["kind"] == "train":
                k = (l["board_sid"], l["alight_sid"])
                if k not in pairs:
                    pairs.append(k)
    pairs = pairs[:cap]
    got = {}
    for fs, ts in pairs:
        d = realprice.get_prices(con, date_s, tele.get(fs), tele.get(ts))
        if d:
            got[(fs, ts)] = d
    for p in out:
        if p["kind"] != "train":
            continue
        any_real = False
        for l in p["legs"]:
            if l["kind"] != "train":
                continue
            d = got.get((l["board_sid"], l["alight_sid"]))
            if not d:
                continue
            info = d.get(l["code"])
            if info:
                b = realprice.best_train_price(info)
                if b:
                    l["real_price"] = b
                    any_real = True
        if any_real and p["transfers"] == 0:
            l0 = p["legs"][0]
            rp = l0.get("real_price")
            if rp:
                p["real_price"] = rp
                disc = f" {rp['discount'] * 10:g}折" if rp.get("discount") and rp["discount"] < 1 else ""
                p["price_fmt"] = f"¥{rp['price']:g}{disc} {rp['seat']}"
    return len(got)


def api_plan(con, q):
    """综合出行方案: 火车 + 直飞 + 空铁联运。date 参数可查真实票价。"""
    ftext = (q.get("from", [""])[0] or "").strip()
    ttext = (q.get("to", [""])[0] or "").strip()
    fid = q.get("from_id", [None])[0]
    tid = q.get("to_id", [None])[0]
    date_s = _validate_date((q.get("date", [""])[0] or "").strip())
    try:
        fid = int(fid) if fid is not None else None
        tid = int(tid) if tid is not None else None
        after = int(q.get("after", ["360"])[0])
        max_legs = min(2, max(0, int(q.get("max_legs", ["2"])[0])))
        max_wait = int(q.get("max_wait", ["180"])[0])
    except ValueError:
        return {"ok": False, "error": "参数错误"}
    fp, err = _resolve(con, ftext, fid)
    if err:
        return {"ok": False, "error": err}
    tp, err = _resolve(con, ttext, tid)
    if err:
        return {"ok": False, "error": err}

    cur = con.cursor()
    to_sids, same_city_arrive = _expand_dest_siblings(cur, tp)
    tp2 = {**tp, "sids": to_sids}
    import time as _t
    t0 = _t.time()
    G, plans = journey.search(con, fp, tp2, after=after, max_wait=max_wait, max_legs=max_legs)
    if same_city_arrive:
        for p in plans:
            if p["legs"][-1]["alight_sid"] != tp["sids"][0]:
                p["same_city_arrive"] = True
    out = [_format_train_plan(p) for p in plans]

    from_city, to_city = _place_city(con, fp), _place_city(con, tp)
    flights, multimodal = [], []
    if from_city and to_city and from_city != to_city:
        try:
            flights = journey.flight_plans(cur, from_city, to_city)
            multimodal = journey.multimodal_plans(cur, G, from_city, to_city, flights)
        except Exception as e:  # noqa: BLE001
            print("[plan] 航班部分失败:", e)
    out += [_format_flight_plan(f) for f in flights]
    out += [_format_multimodal(m) for m in multimodal]
    # 航班真实价: 携程单程最低价(按需查一次, 覆盖整月), 不可得回退估算
    flight_real = False
    if date_s and flights and from_city and to_city:
        try:
            import flightprice
            mp = flightprice.month_prices(cur, con, from_city, to_city)
            v = (mp or {}).get(date_s)
            if v:
                flight_real = True
                for p in out:
                    if p["kind"] == "flight":
                        p["real_price"] = {"price": v, "seat": "经济舱"}
                        p["price_fmt"] = f"¥{v} 起"
        except Exception as e:  # noqa: BLE001
            print("[plan] 航班真实价获取失败:", e)
    real_pairs = 0
    if date_s:
        try:
            real_pairs = _attach_real_prices(con, out, date_s)
        except Exception as e:  # noqa: BLE001
            print("[plan] 真实票价获取失败:", e)
    return {"ok": True, "elapsed": round(_t.time() - t0, 2), "date": date_s,
            "real_pairs": real_pairs, "flight_real": flight_real,
            "from": {**{k: fp[k] for k in ("kind", "label", "stations")}, "city": from_city},
            "to": {**{k: tp[k] for k in ("kind", "label", "stations")}, "city": to_city},
            "plans": out,
            "counts": {
                "直达": sum(1 for p in out if p["kind"] == "train" and p["transfers"] == 0),
                "中转×1": sum(1 for p in out if p["kind"] == "train" and p["transfers"] == 1),
                "中转×2": sum(1 for p in out if p["kind"] == "train" and p["transfers"] == 2),
                "直飞": len(flights), "空铁联运": len(multimodal)}}


def api_flights(con, q):
    """城市对航班查询。"""
    ftext = (q.get("from", [""])[0] or "").strip()
    ttext = (q.get("to", [""])[0] or "").strip()
    if not ftext or not ttext:
        return {"ok": False, "error": "需要 from/to(城市或车站)"}
    fp, err = _resolve(con, ftext, None)
    if err:
        return {"ok": False, "error": err}
    tp, err = _resolve(con, ttext, None)
    if err:
        return {"ok": False, "error": err}
    from_city, to_city = _place_city(con, fp), _place_city(con, tp)
    if not from_city or not to_city:
        return {"ok": True, "plans": [], "note": "该城市无机场数据"}
    cur = con.cursor()
    out = [_format_flight_plan(f) for f in journey.flight_plans(cur, from_city, to_city)]
    return {"ok": True, "from_city": from_city, "to_city": to_city, "plans": out}


def api_airports_full(con, q):
    """全部国内机场(OpenFlights + 中文城市映射)。"""
    kw = (q.get("q", [""])[0] or "").strip()
    where, params = "1=1", []
    if kw:
        where = "(name LIKE ? OR cn_city LIKE ? OR city LIKE ? OR iata LIKE ?)"
        params = [f"%{kw}%"] * 4
    rows = con.execute(
        f"SELECT iata, name, city, cn_city, lat, lon FROM airports_full "
        f"WHERE {where} ORDER BY CASE WHEN cn_city='' THEN 1 ELSE 0 END, cn_city, name "
        f"LIMIT 400", params).fetchall()
    return {"ok": True, "total": len(rows),
            "data": [{k: r[k] for k in r.keys()} for r in rows]}


def api_price_calendar(con, q):
    """未来 N 天各出行方式最低价日历。
    火车: 12306 真实票价(按日实时查询+缓存, 预售期内); 直飞/联运: 估算模型。"""
    ftext = (q.get("from", [""])[0] or "").strip()
    ttext = (q.get("to", [""])[0] or "").strip()
    try:
        days = min(15, max(7, int(q.get("days", ["15"])[0])))
    except ValueError:
        return {"ok": False, "error": "参数错误"}
    if not (ftext and ttext):
        return {"ok": False, "error": "需要 from/to"}
    fp, err = _resolve(con, ftext, None)
    if err:
        return {"ok": False, "error": err}
    tp, err = _resolve(con, ttext, None)
    if err:
        return {"ok": False, "error": err}
    from_city, to_city = _place_city(con, fp), _place_city(con, tp)
    cur = con.cursor()
    to_sids, _ = _expand_dest_siblings(cur, tp)
    tp2 = {**tp, "sids": to_sids}
    _G, plans = journey.search(con, fp, tp2, max_legs=0)
    train_base = min((p["price"] for p in plans if p.get("price")), default=None)
    flight_base = mm_base = None
    flights = []
    if from_city and to_city and from_city != to_city:
        try:
            flights = journey.flight_plans(cur, from_city, to_city)
            flight_base = min((f["price"] for f in flights if f.get("price")), default=None)
            mm = journey.multimodal_plans(cur, _G, from_city, to_city, flights)
            mm_base = min((m["price"] for m in mm if m.get("price")), default=None)
        except Exception:  # noqa: BLE001
            pass

    def _tele_of_place(place):
        """城市 -> 经停车次最多的主要站 telecode; 车站 -> 本站 telecode。"""
        if place["kind"] == "station":
            r = cur.execute("SELECT telecode FROM stations WHERE id=?",
                            (place["sids"][0],)).fetchone()
            return r["telecode"] if r else None
        r = cur.execute(
            "SELECT s.telecode FROM stations s "
            "LEFT JOIN train_stops ts ON ts.station_id=s.id "
            "WHERE s.city=? GROUP BY s.id ORDER BY COUNT(ts.train_id) DESC LIMIT 1",
            (place["stations"][0]["city"],)).fetchone()
        return r["telecode"] if r else None

    import datetime as _dt
    import realprice
    import flightprice
    today = _dt.date.today()
    # 真实票价: 需要确定查询站对
    ftc = ttc = None
    if train_base is not None:
        ftc, ttc = _tele_of_place(fp), _tele_of_place(tp)
    train_real = bool(ftc and ttc)
    # 航班真实价: 携程整月最低价(按需一次)
    flight_month = None
    if flight_base is not None and from_city and to_city:
        try:
            flight_month = flightprice.month_prices(cur, con, from_city, to_city) or None
        except Exception:  # noqa: BLE001
            flight_month = None
    flight_real = bool(flight_month)

    def _adj(base, d):
        k = 1.0
        wd = d.weekday()  # 0=周一
        if wd in (4, 6):
            k = 1.15          # 周五/周日出行高峰
        elif wd == 5:
            k = 1.08
        elif wd in (1, 2, 3):
            k = 0.92          # 周二至周四低谷
        lead = (d - today).days
        if lead >= 21:
            k *= 0.85         # 提前3周以上
        elif lead >= 14:
            k *= 0.92
        elif lead <= 2:
            k *= 1.12         # 临期票
        return int(round(base * k))

    out = []
    # 真实票价: 一次性并行拉取整个日期范围(结果缓存 3h)
    real_by_date = {}
    if train_real:
        date_list = [(today + _dt.timedelta(days=i)).isoformat() for i in range(days)]
        try:
            real_by_date = realprice.get_prices_multi(date_list, ftc, ttc)
        except Exception as e:  # noqa: BLE001
            print("[calendar] 真实票价批量查询失败:", e)
    for i in range(days):
        d = today + _dt.timedelta(days=i)
        rec = {"date": d.isoformat(), "weekday": "一二三四五六日"[d.weekday()]}
        if train_real:
            # 真实票价: 当日该车次池中最低基础席别价
            data = real_by_date.get(d.isoformat())
            best = None
            if data:
                for info in data.values():
                    b = realprice.best_train_price(info)
                    if b and (best is None or b["price"] < best):
                        best = b["price"]
            if best is not None:
                rec["train"] = int(best)
            elif train_base:
                rec["train"] = _adj(train_base, d)
        elif train_base:
            rec["train"] = _adj(train_base, d)
        if flight_real:
            fv = flight_month.get(d.isoformat())
            rec["flight"] = fv if fv else (_adj(flight_base, d) if flight_base else None)
            if not rec["flight"]:
                rec.pop("flight", None)
        elif flight_base:
            rec["flight"] = _adj(flight_base, d)
        if mm_base:
            rec["mm"] = _adj(mm_base, d)
        vals = [v for kk, v in rec.items() if kk in ("train", "flight", "mm") and v]
        if vals:
            rec["min"] = min(vals)
        out.append(rec)
    return {"ok": True, "from_city": from_city or fp["label"],
            "to_city": to_city or tp["label"],
            "train_real": train_real, "flight_real": flight_real,
            "train_base": train_base, "flight_base": flight_base,
            "mm_base": mm_base, "days": out}


def api_coords(con, q):
    """站名/城市名 -> 坐标(方案地图用)。
    names=逗号分隔; 名字先按站名精确匹配, 无命中再按城市匹配(返回该城所有站)。"""
    raw = (q.get("names", [""])[0] or "").strip()
    names = [n.strip() for n in raw.split(",") if n.strip()][:80]
    out, seen = [], set()
    for nm in names:
        rows = con.execute(
            "SELECT name, city, lng, lat FROM stations WHERE name=? AND lng IS NOT NULL",
            (nm,)).fetchall()
        if not rows:
            rows = con.execute(
                "SELECT name, city, lng, lat FROM stations WHERE city=? AND lng IS NOT NULL",
                (nm,)).fetchall()
        for r in rows:
            if r["name"] in seen:
                continue
            seen.add(r["name"])
            out.append({"name": r["name"], "city": r["city"],
                        "lng": r["lng"], "lat": r["lat"]})
    return {"ok": True, "count": len(out), "data": out}


def api_update_status(con, q):
    meta = {r["k"]: r["v"] for r in con.execute("SELECT k, v FROM meta").fetchall()}
    return {"ok": True, "data": {
        "train_data_date": meta.get("data_date"),
        "train_source": meta.get("data_source"),
        "trains": meta.get("trains"), "stops": meta.get("stops"),
        "flights_updated": meta.get("flights_updated"),
        "update_status": meta.get("update_status", "idle"),
        "update_time": meta.get("update_time"),
        "update_error": meta.get("update_error", "")}}


def api_update_check(con, q, body=None):
    """触发一次后台更新检查。"""
    def _run():
        try:
            update_all()
        except Exception as e:  # noqa: BLE001
            print("[update-check]", e)
    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "started": True}
