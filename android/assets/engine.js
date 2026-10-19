/* engine.js — 出行方案引擎(Android 移植版)。
 * 由 train-app/journey.py + api_journey_v2.py + main.py 移植:
 *   车站/城市模糊解析 → 直达/中转 BFS(时间依赖网络) → 票价估算 → 航班/空铁联运。
 * 静态路网在构建期由 export_data.py 预计算(window.__DATA__), 启动即用, 不再重建。
 * 所有 /api/* 响应形状与桌面版(Python HTTP 服务)一致, 由 apihost.js 路由进来。
 */
(function () {
  "use strict";
  var D = window.__DATA__;

  /* ---------------- 基础索引 ---------------- */
  var stationById = {};
  D.stations.forEach(function (s) {
    stationById[s[0]] = { id: s[0], name: s[1], telecode: s[2], pinyin_full: s[3],
      pinyin_abbr: s[4], city: s[5], is_major: s[6], lng: s[7], lat: s[8] };
  });
  var trainById = {};
  D.trains.forEach(function (t) {
    trainById[t[0]] = { id: t[0], code: t[1], type: t[2], line_id: t[3],
      depart_time: t[4], arrive_time: t[5], mileage: t[6], emu_model: t[7],
      start_name: t[8], end_name: t[9] };
  });
  var airportsByIata = {};
  D.airports_full.forEach(function (a) {
    airportsByIata[a[0]] = { iata: a[0], name: a[1], city: a[2], cn_city: a[3], lat: a[4], lon: a[5] };
  });
  var lineById = {};
  D.lines.forEach(function (l) {
    lineById[l[0]] = { id: l[0], name: l[1], category: l[2], mileage: l[3], speed_limit: l[4] };
  });

  var SEAT_CN = { "9": "商务座", P: "特等座", M: "一等座", O: "二等座", D: "优选一等座",
    W: "无座", A: "高级软卧", F: "动卧", "4": "软卧/一等卧", "3": "硬卧/二等卧",
    "1": "硬座", "2": "软座", "6": "高级软卧", E: "特等座" };
  var SEAT_PRIORITY = ["O", "1", "M", "3", "9", "4", "P", "D", "W", "2", "F", "A", "6", "E"];
  var AIRLINE_CN = { CA: "中国国际航空", MU: "中国东方航空", CZ: "中国南方航空",
    HU: "海南航空", MF: "厦门航空", FM: "上海航空", ZH: "深圳航空",
    "3U": "四川航空", SC: "山东航空", "9C": "春秋航空", KN: "中国联航",
    GJ: "长龙航空", HO: "吉祥航空", GS: "天津航空", JD: "首都航空",
    TV: "西藏航空", PN: "西部航空", CN: "大新华航空", "8L": "祥鹏航空",
    DZ: "东海航空", G5: "华夏航空", BK: "奥凯航空", EU: "成都航空",
    UQ: "乌鲁木齐航空", OQ: "重庆航空", KY: "昆明航空", AQ: "江西航空",
    GT: "北部湾航空", QW: "青岛航空", FU: "福州航空",
    "2Z": "金鹏航空", Y8: "金鹿航空" };

  var PRICE_RATE = { G: 0.45, C: 0.40, D: 0.31, K: 0.16, T: 0.16, Z: 0.18 };
  var DIST_FACTOR = { G: 1.25, C: 1.25, D: 1.22, K: 1.20, T: 1.20, Z: 1.20 };
  var FLIGHT_BUFFER = 150, FLIGHT_RATE = 0.58;
  var MAX_FRONTIER = 12000, ARRIVAL_GAP = 30;

  function hhmm(m) {
    if (m === null || m === undefined) return "--";
    m = ((m % 1440) + 1440) % 1440;
    var h = Math.floor(m / 60), mm = m % 60;
    return (h < 10 ? "0" : "") + h + ":" + (mm < 10 ? "0" : "") + mm;
  }
  function fdur(m) {
    m = Math.max(0, Math.floor(m || 0));
    if (!m) return "--";
    return Math.floor(m / 60) + "小时" + (m % 60 < 10 ? "0" : "") + (m % 60) + "分";
  }
  function haversine(lng1, lat1, lng2, lat2) {
    var r = 6371.0;
    var p1 = lat1 * Math.PI / 180, p2 = lat2 * Math.PI / 180;
    var dp = (lat2 - lat1) * Math.PI / 180, dl = (lng2 - lng1) * Math.PI / 180;
    var a = Math.pow(Math.sin(dp / 2), 2) + Math.cos(p1) * Math.cos(p2) * Math.pow(Math.sin(dl / 2), 2);
    return 2 * r * Math.asin(Math.sqrt(a));
  }
  function localToday() {
    var n = new Date();
    return new Date(n.getFullYear(), n.getMonth(), n.getDate());
  }
  function isoOf(d) {
    var p = function (x) { return (x < 10 ? "0" : "") + x; };
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
  }

  /* ---------------- 地点解析 ---------------- */
  function resolvePlace(text) {
    text = (text || "").trim();
    if (!text) return null;
    // 1) 精确城市名(该城 >=2 站)
    var cityStations = (D.city_sids[text] || []).map(function (id) { return stationById[id]; })
      .sort(function (a, b) { return b.is_major - a.is_major || (a.pinyin_full < b.pinyin_full ? -1 : 1); });
    if (cityStations.length >= 2) {
      return { kind: "city", label: text, sids: cityStations.map(function (s) { return s.id; }),
        stations: cityStations.map(function (s) { return { id: s.id, name: s.name, city: s.city }; }) };
    }
    // 2) 精确车站名
    var exact = null;
    D.stations.forEach(function (s) { if (s[1] === text && !exact) exact = s; });
    if (exact) {
      return { kind: "station", label: exact[1], sids: [exact[0]],
        stations: [{ id: exact[0], name: exact[1], city: exact[5] }] };
    }
    // 3) 模糊(城市或站名包含)
    var rows = [];
    for (var i = 0; i < D.stations.length && rows.length < 200; i++) {
      var s = stationById[D.stations[i][0]];
      if (s.city.indexOf(text) >= 0 || s.name.indexOf(text) >= 0) rows.push(s);
    }
    if (!rows.length) return null;
    rows.sort(function (a, b) { return b.is_major - a.is_major || (a.pinyin_full < b.pinyin_full ? -1 : 1); });
    var top = rows.slice(0, 60);
    var cities = {};
    top.forEach(function (s) { cities[s.city] = 1; });
    var cityList = Object.keys(cities);
    if (cityList.length === 1) {
      var c = cityList[0];
      return { kind: "city", label: c, sids: top.map(function (s) { return s.id; }),
        stations: top.map(function (s) { return { id: s.id, name: s.name, city: s.city }; }) };
    }
    var picked = top.slice(0, 20);
    return { kind: "custom", label: text, sids: picked.map(function (s) { return s.id; }),
      stations: picked.map(function (s) { return { id: s.id, name: s.name, city: s.city }; }) };
  }

  /* ---------------- 路网(静态预计算 + 里程累计惰性) ---------------- */
  function trainStops(tid) { return D.stops[tid] || []; }
  var cumCache = {};
  function trainCum(tr) {
    if (cumCache[tr.id]) return cumCache[tr.id];
    var sl = trainStops(tr.id), cum = [0.0], ok = true;
    for (var i = 1; i < sl.length; i++) {
      var a = D.coords[sl[i - 1][0]], b = D.coords[sl[i][0]];
      if (a && b && ok) {
        cum.push(cum[i - 1] + haversine(a[0], a[1], b[0], b[1]) * (DIST_FACTOR[tr.type] || 1.2));
      } else { ok = false; cum.push(null); }
    }
    cumCache[tr.id] = cum;
    return cum;
  }
  function posOfSeq(sl, seq) {
    for (var i = 0; i < sl.length; i++) if (sl[i][1] === seq) return i;
    return -1;
  }
  function segInfo(tr, p1, p2) {
    var sl = trainStops(tr.id);
    var dep = sl[p1][3] !== null ? sl[p1][3] : sl[p1][2];
    var arr = sl[p2][2] !== null ? sl[p2][2] : sl[p2][3];
    if (dep === null || arr === null) return { ride: null, km: null, price: null, pts: [] };
    var stopSum = 0;
    for (var j = p1 + 1; j < p2; j++) stopSum += sl[j][4];
    var ride = (arr - dep) - stopSum;
    var cum = trainCum(tr);
    var km = (cum[p1] !== null && cum[p2] !== null) ? cum[p2] - cum[p1] : null;
    var price = km ? Math.max(5, Math.round(km * (PRICE_RATE[tr.type] || 0.3))) : null;
    var pts = [];
    for (var k = p1; k <= p2; k++) {
      var c = D.coords[sl[k][0]];
      if (c) pts.push([c[0], c[1], D.names[sl[k][0]] || ""]);
    }
    if (pts.length > 80) {
      var step = pts.length / 80.0, sampled = [];
      for (var m = 0; m < 80; m++) sampled.push(pts[Math.floor(m * step)]);
      pts = sampled;
    }
    return { ride: ride, km: km, price: price, pts: pts };
  }

  /* ---------------- BFS 搜索 ---------------- */
  function searchTrains(fromSids, toSids, after, minTr, minTrCity, maxWait, maxLegs) {
    var toSet = {};
    toSids.forEach(function (s) { toSet[s] = 1; });
    var arrivals = {};   // sid -> [{t, p}] 按时间升序

    function relax(sid, t, parent) {
      var lst = arrivals[sid];
      if (!lst) { lst = arrivals[sid] = []; }
      for (var i = 0; i < lst.length; i++) {
        if (Math.abs(lst[i].t - t) < ARRIVAL_GAP) return false;
      }
      lst.push({ t: t, p: parent });
      lst.sort(function (a, b) { return a.t - b.t; });
      return true;
    }
    fromSids.forEach(function (sid) { relax(sid, after, ["origin"]); });

    var plans = [], seen = {};
    function chain(sid, t, parent) {
      var events = [], curSid = sid, curT = t, p = parent;
      while (p && p[0] !== "origin") {
        events.push([curSid, curT, p]);
        var ref = p[0] === "train" ? p[4] : p[1];
        var refT = p[0] === "train" ? p[5] : p[2];
        var lst = arrivals[ref] || [], found = null;
        for (var i = 0; i < lst.length; i++) {
          if (Math.abs(lst[i].t - refT) < ARRIVAL_GAP) { found = lst[i]; break; }
        }
        if (!found) return null;
        curSid = ref; curT = found.t; p = found.p;
      }
      events.reverse();
      return events;
    }
    function makePlan(sid, t, parent, transfers) {
      var ev = chain(sid, t, parent);
      if (!ev) return;
      var legs = [];
      for (var i = 0; i < ev.length; i++) {
        var eSid = ev[i][0], eP = ev[i][2];
        if (eP[0] === "train") {
          var tid = eP[1], seq1 = eP[2], seq2 = eP[3];
          var tr = trainById[tid];
          var sl = trainStops(tid);
          var p1 = posOfSeq(sl, seq1), p2 = posOfSeq(sl, seq2);
          if (p1 < 0 || p2 < 0) return;
          var si = segInfo(tr, p1, p2);
          var dep = sl[p1][3] !== null ? sl[p1][3] : sl[p1][2];
          var arr = sl[p2][2] !== null ? sl[p2][2] : sl[p2][3];
          legs.push({ kind: "train", train_id: tid, code: tr.code, type: tr.type,
            start: tr.start_name, end: tr.end_name,
            board: D.names[sl[p1][0]] || "", board_sid: sl[p1][0],
            alight: D.names[sl[p2][0]] || "", alight_sid: sl[p2][0],
            board_city: D.city_of[sl[p1][0]] || "", alight_city: D.city_of[sl[p2][0]] || "",
            dep: dep, arr: arr, ride: si.ride, km: si.km, price: si.price, path: si.pts });
        } else {
          legs.push({ kind: "walk", walk_from: D.names[eP[1]] || "",
            walk_to: D.names[eSid] || "", walk_min: minTrCity });
        }
      }
      if (!legs.length || legs[0].kind !== "train") return;
      var key = legs.filter(function (l) { return l.kind === "train"; })
        .map(function (l) { return l.train_id; }).join(",");
      if (seen[key]) return;
      seen[key] = 1;
      var dep0 = legs[0].dep, arrN = legs[legs.length - 1].arr;
      var ride = 0, price = 0, nTrain = 0, nPriced = 0;
      legs.forEach(function (l) {
        if (l.kind === "train") {
          nTrain++;
          if (l.ride) ride += l.ride;
          if (l.price) { price += l.price; nPriced++; }
        }
      });
      if (nPriced !== nTrain) price = null;
      plans.push({ kind: "train", transfers: transfers, legs: legs,
        dep: dep0, arr: arrN, total: arrN - dep0, ride: ride, price: price });
    }

    var frontier = [];
    var fromSet = {};                 // 修复: fromSids 是数组, 不能用 sid 当下标查
    fromSids.forEach(function (s) { fromSet[s] = 1; });
    Object.keys(arrivals).forEach(function (sid) {
      if (fromSet[sid]) arrivals[sid].forEach(function (a) {
        frontier.push([+sid, a.t, a.p]);
      });
    });
    for (var rnd = 0; rnd <= maxLegs; rnd++) {
      var nxt = [], processed = 0;
      frontier.sort(function (a, b) { return a[1] - b[1]; });
      for (var fi = 0; fi < frontier.length; fi++) {
        if (processed >= MAX_FRONTIER) break;
        processed++;
        var sid = frontier[fi][0], t = frontier[fi][1], parent = frontier[fi][2];
        var depFloor = rnd === 0 ? t : t + minTr;
        var depCeil = rnd === 0 ? null : t + maxWait;
        var legsArr = D.legs[sid] || [];
        for (var li = 0; li < legsArr.length; li++) {
          var tid = legsArr[li][0], seq = legsArr[li][1], dep = legsArr[li][3];
          if (dep === null || dep < depFloor) continue;
          if (depCeil !== null && dep > depCeil) continue;
          var tr = trainById[tid];
          var sl = trainStops(tid);
          var p1 = posOfSeq(sl, seq);
          if (p1 < 0) continue;
          for (var j = p1 + 1; j < sl.length; j++) {
            var sid2 = sl[j][0], arrT = sl[j][2] !== null ? sl[j][2] : sl[j][3];
            if (arrT === null) continue;
            var np = ["train", tid, seq, sl[j][1], sid, t];
            if (relax(sid2, arrT, np)) {
              nxt.push([sid2, arrT, np]);
              if (toSet[sid2]) makePlan(sid2, arrT, np, rnd);
            }
          }
        }
      }
      if (rnd < maxLegs) {
        var walks = [];
        nxt.forEach(function (e) {
          var city = D.city_of[e[0]];
          if (!city || (D.city_sids[city] || []).length < 2) return;
          D.city_sids[city].forEach(function (s) {
            if (s === e[0] || toSet[s]) return;
            var wp = ["walk", e[0], e[1]];
            if (relax(s, e[1] + minTrCity, wp)) walks.push([s, e[1] + minTrCity, wp]);
          });
        });
        nxt = nxt.concat(walks);
      }
      frontier = nxt;
      if (!frontier.length) break;
    }
    return plans;
  }

  function search(fromPlace, toPlace, after, minTr, minTrCity, maxWait, maxLegs) {
    var t0 = Date.now();
    var plans = searchTrains(fromPlace.sids, toPlace.sids, after, minTr, minTrCity, maxWait, maxLegs);
    plans.sort(function (a, b) { return a.total - b.total || a.dep - b.dep; });
    plans.forEach(function (p) {
      p.category = p.transfers === 0 ? "直达" : "中转×" + p.transfers;
    });
    return { G: null, plans: plans, elapsed: Math.round((Date.now() - t0) / 100) / 10 };
  }

  /* ---------------- 飞行部分 ---------------- */
  function cityAirports(city) {
    return D.airports_full.filter(function (a) { return a[3] === city; }).map(function (a) { return a[0]; });
  }
  function cjk(s) {
    if (!s) return false;
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      if (c >= 0x4e00 && c <= 0x9fff) return true;
    }
    return false;
  }
  function schedPlans(sa, da, km, priceEst, fromCity, toCity, limit) {
    limit = limit || 8;
    var rows = D.sched.filter(function (s) { return s[2] === fromCity && s[3] === toCity; }).slice(0, limit);
    var out = [];
    rows.forEach(function (s) {
      var dur = Math.max(45, s[7] - s[6]);
      var depAp = cjk(s[4]) ? s[4] : ((sa && sa.cn_city) ? sa.cn_city + "机场" : "");
      var arrAp = cjk(s[5]) ? s[5] : ((da && da.cn_city) ? da.cn_city + "机场" : "");
      out.push({ kind: "flight", category: "直飞", flight_no: s[0],
        airline: AIRLINE_CN[s[1]] || s[1],
        src_iata: sa.iata, src_airport_cn: depAp || sa.name,
        dst_iata: da.iata, dst_airport_cn: arrAp || da.name,
        dep: hhmm(s[6]), arr: hhmm(s[7]), model: s[8],
        ride: dur, km: km, price: priceEst, total: dur + FLIGHT_BUFFER,
        path: [[sa.lon, sa.lat, sa.cn_city], [da.lon, da.lat, da.cn_city]] });
    });
    return out;
  }
  function flightPlans(fromCity, toCity) {
    var src = cityAirports(fromCity), dst = cityAirports(toCity);
    if (!src.length || !dst.length) return [];
    var inSet = function (iata, set) { return set.indexOf(iata) >= 0; };
    var rows = D.flights.filter(function (f) {
      return inSet(f[4], src) && inSet(f[5], dst);
    }).slice(0, 12);
    if (!rows.length) return [];
    var hasSched = D.sched.some(function (s) { return s[2] === fromCity && s[3] === toCity; });
    if (hasSched) {
      var r0 = rows[0];
      var sa = airportsByIata[r0[4]], da = airportsByIata[r0[5]];
      if (!sa || !da) return [];
      return schedPlans(sa, da, r0[8], r0[10], fromCity, toCity);
    }
    var out = [];
    rows.forEach(function (r) {
      var sa = airportsByIata[r[4]], da = airportsByIata[r[5]];
      if (!sa || !da) return;
      out.push({ kind: "flight", category: "直飞", flight_no: r[3],
        airline: r[1] || AIRLINE_CN[r[2]] || r[2],
        src_iata: r[4], src_airport: sa.name,
        dst_iata: r[5], dst_airport: da.name,
        ride: r[9], km: r[8], price: r[10], total: r[9] + FLIGHT_BUFFER,
        path: [[sa.lon, sa.lat, sa.cn_city], [da.lon, da.lat, da.cn_city]] });
    });
    return out;
  }
  function railLegBetween(fromCity, toCity) {
    var fs = {}, ts = {};
    (D.city_sids[fromCity] || []).forEach(function (s) { fs[s] = 1; });
    (D.city_sids[toCity] || []).forEach(function (s) { ts[s] = 1; });
    if (!Object.keys(fs).length || !Object.keys(ts).length) return null;
    var best = null;
    D.trains.forEach(function (tMeta) {
      var tr = trainById[tMeta[0]];
      var sl = trainStops(tr.id);
      var p1 = null, p2 = null;
      for (var i = 0; i < sl.length; i++) {
        var sid = sl[i][0];
        if (fs[sid] && p1 === null && sl[i][3] !== null) p1 = i;
        else if (ts[sid] && p1 !== null && p2 === null && sl[i][2] !== null) { p2 = i; break; }
      }
      if (p1 === null || p2 === null) return;
      var si = segInfo(tr, p1, p2);
      if (si.ride === null) return;
      if (!best || si.ride < best[3]) {
        var dep = sl[p1][3] !== null ? sl[p1][3] : sl[p1][2];
        var arr = sl[p2][2] !== null ? sl[p2][2] : sl[p2][3];
        best = [tr.id, tr.code, tr.type, si.ride, dep, arr, si.price, sl[p1][0], sl[p2][0]];
      }
    });
    return best;
  }
  function trainPath(tid, sidA, sidB) {
    var sl = trainStops(tid), i1 = null, i2 = null;
    for (var i = 0; i < sl.length; i++) {
      if (sl[i][0] === sidA && i1 === null) i1 = i;
      else if (sl[i][0] === sidB && i1 !== null && i2 === null) { i2 = i; break; }
    }
    if (i1 === null || i2 === null) return [];
    var pts = [];
    for (var j = i1; j <= i2; j++) {
      var c = D.coords[sl[j][0]];
      if (c) pts.push([c[0], c[1], D.names[sl[j][0]] || ""]);
    }
    return pts;
  }
  function multimodalPlans(fromCity, toCity, flightList) {
    var HUBS = ["北京", "上海", "广州", "成都", "西安", "昆明", "乌鲁木齐", "长沙", "武汉", "厦门"];
    var out = [];
    function bestFlight(srcIatas, dstIatas) {
      if (!srcIatas.length || !dstIatas.length) return null;
      var d = null, p = null;
      D.flights.forEach(function (g) {
        if (srcIatas.indexOf(g[4]) < 0 || dstIatas.indexOf(g[5]) < 0) return;
        if (d === null || g[9] < d) d = g[9];
        if (p === null || g[10] < p) p = g[10];
      });
      return d === null ? null : { d: d, p: p };
    }
    function emit(hub, rail, fl, flyFrom, flyTo, railFrom, railTo) {
      if (!fl || !fl.d || !rail) return false;
      var rpath = trainPath(rail[0], rail[7], rail[8]);
      var total = fl.d + 90 + rail[3] + 45;
      var price = (fl.p || 0) + (rail[6] || 0);
      out.push({ kind: "multimodal", category: "空铁联运", hub: hub,
        from_city: fromCity, to_city: toCity,
        flight: { airline: null, from_city: flyFrom, to_city: flyTo,
          duration: fl.d, price: fl.p },
        rail: { train_id: rail[0], code: rail[1], type: rail[2],
          from_city: railFrom, to_city: railTo,
          board: rpath.length ? rpath[0][2] : "",
          alight: rpath.length ? rpath[rpath.length - 1][2] : "",
          ride: rail[3], price: rail[6], path: rpath },
        total: total, price: price || null });
      return true;
    }
    // 方向A: 飞行在前 —— 出发机场 → 枢纽机场, 枢纽 → 火车 → 目的地
    var src = cityAirports(fromCity);
    if (src.length) {
      var hubSeenA = {}, nA = 0;
      D.flights.forEach(function (f) {
        if (nA >= 2) return;
        if (src.indexOf(f[4]) < 0) return;
        var ap = airportsByIata[f[5]];
        if (!ap) return;
        var hub = ap.cn_city || ap.city;
        if (HUBS.indexOf(hub) < 0 || hubSeenA[hub] || hub === fromCity || hub === toCity) return;
        hubSeenA[hub] = 1;
        if (emit(hub, railLegBetween(hub, toCity), bestFlight(src, [f[5]]),
            fromCity, hub, hub, toCity)) nA++;
      });
    }
    // 方向B: 铁路在前 —— 出发 → 火车 → 枢纽, 枢纽机场 → 目的地机场
    var dst = cityAirports(toCity);
    if (dst.length) {
      var hubSeenB = {}, nB = 0;
      D.flights.forEach(function (f) {
        if (nB >= 2) return;
        if (dst.indexOf(f[5]) < 0) return;
        var ap = airportsByIata[f[4]];
        if (!ap) return;
        var hub = ap.cn_city || ap.city;
        if (HUBS.indexOf(hub) < 0 || hubSeenB[hub] || hub === fromCity || hub === toCity) return;
        hubSeenB[hub] = 1;
        if (emit(hub, railLegBetween(fromCity, hub), bestFlight(cityAirports(hub), dst),
            hub, toCity, fromCity, hub)) nB++;
      });
    }
    return out;
  }

  /* ---------------- 方案格式化(与桌面版同形) ---------------- */
  function formatTrainPlan(p) {
    var legs = p.legs.map(function (l) {
      if (l.kind === "train") {
        return { kind: "train", train_id: l.train_id, code: l.code, type: l.type,
          start: l.start, end: l.end, board: l.board, board_sid: l.board_sid,
          alight: l.alight, alight_sid: l.alight_sid,
          board_city: l.board_city, alight_city: l.alight_city,
          dep: hhmm(l.dep), arr: hhmm(l.arr), dep_min: l.dep, arr_min: l.arr,
          ride: l.ride, km: l.km ? Math.round(l.km) : null, price: l.price, path: l.path };
      }
      return { kind: "walk", walk_from: l.walk_from, walk_to: l.walk_to, walk_min: l.walk_min };
    });
    return { kind: "train", category: p.category, transfers: p.transfers,
      dep: hhmm(p.dep), arr: hhmm(p.arr), dep_min: p.dep, arr_min: p.arr,
      total: p.total, ride: p.ride, price: p.price,
      total_fmt: fdur(p.total), ride_fmt: fdur(p.ride),
      price_fmt: p.price ? "约 ¥" + p.price : "—", legs: legs };
  }
  function formatFlightPlan(f) {
    var o = {}; for (var k in f) o[k] = f[k];
    o.total_fmt = fdur(f.total); o.ride_fmt = fdur(f.ride);
    o.price_fmt = f.price ? "约 ¥" + f.price : "—";
    o.note = "航班无固定时刻, 时长与票价为按距离估算, 已含往返机场约2.5小时";
    return o;
  }
  function formatMultimodal(m) {
    var o = {}; for (var k in m) o[k] = m[k];
    o.total_fmt = fdur(m.total);
    o.ride_fmt = fdur(m.flight.duration + m.rail.ride);
    o.price_fmt = m.price ? "约 ¥" + m.price : "—";
    var order = m.flight.from_city === m.from_city ? "先飞后铁" : "先铁后飞";
    o.note = "经" + m.hub + "中转(" + order + "), 已含中转缓冲约2.25小时(估算)";
    return o;
  }
  function expandDestSiblings(place) {
    if (place.kind !== "station") return { sids: place.sids.slice(0), more: false };
    var sids = place.sids.slice(0);
    var city = place.stations[0].city;
    var sibs = city ? (D.city_sids[city] || []).filter(function (id) { return id !== sids[0]; }) : [];
    if (sibs.length) { sids = sids.concat(sibs); return { sids: sids, more: true }; }
    return { sids: sids, more: false };
  }
  function placeCity(place) {
    if (place.kind === "city") return place.label;
    var cities = {};
    place.stations.forEach(function (s) { cities[s.city] = 1; });
    var ks = Object.keys(cities);
    return ks.length === 1 ? ks[0] : null;
  }
  function validateDate(raw) {
    if (!raw) return null;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return null;
    var today = localToday();
    var parts = raw.split("-");
    var d = new Date(+parts[0], +parts[1] - 1, +parts[2]);
    if (isNaN(d.getTime()) || isoOf(d) !== raw) return null;
    var max = new Date(today.getTime() + 14 * 864e5);
    if (d < today || d > max) return null;
    return raw;
  }

  /* ---------------- API 处理器 ---------------- */
  var RP = window.__RealPrice || null;   // realprice.js (可选, 无网络时优雅降级)
  var FP = window.__FlightPrice || null; // flightprice.js

  function attachRealPrices(out, dateS, cap) {
    if (!RP || !RP.available()) return 0;
    cap = cap || 8;
    var tele = {};
    D.stations.forEach(function (s) { if (s[2]) tele[s[0]] = s[2]; });
    var pairs = [];
    out.forEach(function (p) {
      if (p.kind !== "train") return;
      p.legs.forEach(function (l) {
        if (l.kind !== "train") return;
        var k = l.board_sid + ">" + l.alight_sid;
        if (pairs.indexOf(k) < 0) pairs.push(k);
      });
    });
    pairs = pairs.slice(0, cap);
    var got = {};
    var t0 = Date.now(), BUDGET = 12000;   // 总预算 12s, 12306 不可达时尽快放弃
    pairs.forEach(function (k) {
      if (Date.now() - t0 > BUDGET) return;
      var ab = k.split(">");
      var d = RP.getPrices(dateS, tele[ab[0]], tele[ab[1]]);
      if (d) got[k] = d;
    });
    out.forEach(function (p) {
      if (p.kind !== "train") return;
      var anyReal = false;
      p.legs.forEach(function (l) {
        if (l.kind !== "train") return;
        var d = got[l.board_sid + ">" + l.alight_sid];
        if (!d) return;
        var info = d[l.code];
        if (info) {
          var b = RP.bestTrainPrice(info);
          if (b) { l.real_price = b; anyReal = true; }
        }
      });
      if (anyReal && p.transfers === 0) {
        var rp = p.legs[0].real_price;
        if (rp) {
          p.real_price = rp;
          var disc = rp.discount && rp.discount < 1 ? " " + trimZeros(rp.discount * 10) + "折" : "";
          p.price_fmt = "¥" + trimZeros(rp.price) + disc + " " + rp.seat;
        }
      }
    });
    return Object.keys(got).length;
  }
  function trimZeros(x) {
    var s = String(Math.round(x * 100) / 100);
    return s;
  }

  function apiJourney(q) {
    var ftext = (q.from || "").trim(), ttext = (q.to || "").trim();
    var dateS = validateDate((q.date || "").trim());
    var after = parseInt(q.after || "360", 10), maxLegs = Math.min(2, Math.max(0, parseInt(q.max_legs || "2", 10)));
    var maxWait = parseInt(q.max_wait || "180", 10);
    var minTr = parseInt(q.min_transfer || "15", 10);
    var minTrCity = parseInt(q.min_transfer_city || "45", 10);
    if (!(ftext || q.from_id) || !(ttext || q.to_id)) return { ok: false, error: "需要 from/to(车站或城市名)" };
    var fp = resolvePlace(ftext), tp = resolvePlace(ttext);
    if (!fp) return { ok: false, error: "未找到匹配的车站或城市: " + ftext };
    if (!tp) return { ok: false, error: "未找到匹配的车站或城市: " + ttext };
    var exp = expandDestSiblings(tp);
    var r = search(fp, { sids: exp.sids }, after, minTr, minTrCity, maxWait, maxLegs);
    if (exp.more) {
      r.plans.forEach(function (p) {
        var last = p.legs[p.legs.length - 1];
        if (last.alight_sid !== tp.sids[0]) p.same_city_arrive = true;
      });
    }
    var out = r.plans.map(formatTrainPlan);
    var realPairs = 0;
    if (dateS) { try { realPairs = attachRealPrices(out, dateS); } catch (e) { /* 降级 */ } }
    var counts = { "直达": 0, "中转×1": 0, "中转×2": 0 };
    out.forEach(function (p) { counts[p.transfers === 0 ? "直达" : "中转×" + p.transfers]++; });
    return { ok: true, elapsed: r.elapsed, date: dateS, real_pairs: realPairs,
      from: { kind: fp.kind, label: fp.label, stations: fp.stations },
      to: { kind: tp.kind, label: tp.label, stations: tp.stations },
      plans: out, counts: counts };
  }

  function apiPlan(q) {
    var ftext = (q.from || "").trim(), ttext = (q.to || "").trim();
    var dateS = validateDate((q.date || "").trim());
    var after = parseInt(q.after || "360", 10);
    var maxLegs = Math.min(2, Math.max(0, parseInt(q.max_legs || "2", 10)));
    var maxWait = parseInt(q.max_wait || "180", 10);
    if (!(ftext || q.from_id) || !(ttext || q.to_id)) return { ok: false, error: "需要 from/to(车站或城市名)" };
    var fp = resolvePlace(ftext), tp = resolvePlace(ttext);
    if (!fp) return { ok: false, error: "未找到匹配的车站或城市: " + ftext };
    if (!tp) return { ok: false, error: "未找到匹配的车站或城市: " + ttext };
    var exp = expandDestSiblings(tp);
    var r = search(fp, { sids: exp.sids }, after, 15, 45, maxWait, maxLegs);
    if (exp.more) {
      r.plans.forEach(function (p) {
        var last = p.legs[p.legs.length - 1];
        if (last.alight_sid !== tp.sids[0]) p.same_city_arrive = true;
      });
    }
    var out = r.plans.map(formatTrainPlan);
    var fromCity = placeCity(fp), toCity = placeCity(tp);
    var flights = [], multimodal = [];
    if (fromCity && toCity && fromCity !== toCity) {
      try {
        flights = flightPlans(fromCity, toCity);
        multimodal = multimodalPlans(fromCity, toCity, flights);
      } catch (e) { /* 航班部分失败不阻断 */ }
    }
    out = out.concat(flights.map(formatFlightPlan)).concat(multimodal.map(formatMultimodal));
    var flightReal = false;
    if (dateS && flights.length && fromCity && toCity && FP && FP.available()) {
      try {
        var mp = FP.monthPrices(fromCity, toCity);
        var v = mp ? mp[dateS] : null;
        if (v) {
          flightReal = true;
          out.forEach(function (p) {
            if (p.kind === "flight") {
              p.real_price = { price: v, seat: "经济舱" };
              p.price_fmt = "¥" + v + " 起";
            }
          });
        }
      } catch (e) { /* 降级 */ }
    }
    var realPairs = 0;
    if (dateS) { try { realPairs = attachRealPrices(out, dateS); } catch (e) { /* 降级 */ } }
    var counts = { "直达": 0, "中转×1": 0, "中转×2": 0, "直飞": flights.length, "空铁联运": multimodal.length };
    out.forEach(function (p) {
      if (p.kind === "train") counts[p.transfers === 0 ? "直达" : "中转×" + p.transfers]++;
    });
    return { ok: true, elapsed: r.elapsed, date: dateS, real_pairs: realPairs, flight_real: flightReal,
      from: { kind: fp.kind, label: fp.label, stations: fp.stations, city: fromCity },
      to: { kind: tp.kind, label: tp.label, stations: tp.stations, city: toCity },
      plans: out, counts: counts };
  }

  function apiFlights(q) {
    var ftext = (q.from || "").trim(), ttext = (q.to || "").trim();
    if (!ftext || !ttext) return { ok: false, error: "需要 from/to(城市或车站)" };
    var fp = resolvePlace(ftext), tp = resolvePlace(ttext);
    if (!fp) return { ok: false, error: "未找到匹配的车站或城市: " + ftext };
    if (!tp) return { ok: false, error: "未找到匹配的车站或城市: " + ttext };
    var fromCity = placeCity(fp), toCity = placeCity(tp);
    if (!fromCity || !toCity) return { ok: true, plans: [], note: "该城市无机场数据" };
    var out = flightPlans(fromCity, toCity).map(formatFlightPlan);
    return { ok: true, from_city: fromCity, to_city: toCity, plans: out };
  }

  function apiCoords(q) {
    var names = (q.names || "").split(",").map(function (s) { return s.trim(); })
      .filter(function (s) { return s; }).slice(0, 80);
    var out = [], seen = {};
    names.forEach(function (nm) {
      var rows = D.stations.filter(function (s) {
        return s[1] === nm && s[7] !== null && s[7] !== undefined;
      });
      if (!rows.length) {
        rows = D.stations.filter(function (s) { return s[5] === nm && s[7] !== null && s[7] !== undefined; });
      }
      rows.forEach(function (s) {
        if (seen[s[1]]) return;
        seen[s[1]] = 1;
        out.push({ name: s[1], city: s[5], lng: s[7], lat: s[8] });
      });
    });
    return { ok: true, count: out.length, data: out };
  }

  function teleOfPlace(place) {
    if (place.kind === "station") {
      var s = stationById[place.sids[0]];
      return s ? s.telecode : null;
    }
    var city = place.stations[0].city, best = null, bestN = -1;
    (D.city_sids[city] || []).forEach(function (sid) {
      var n = (D.legs[sid] || []).length;
      var st = stationById[sid];
      if (n > bestN && st.telecode) { bestN = n; best = st.telecode; }
    });
    return best;
  }
  function adjPrice(base, d, today) {
    var k = 1.0;
    var wd = (d.getDay() + 6) % 7;   // 0=周一
    if (wd === 4 || wd === 6) k = 1.15;
    else if (wd === 5) k = 1.08;
    else if (wd >= 1 && wd <= 3) k = 0.92;
    var lead = Math.round((d - today) / 864e5);
    if (lead >= 21) k *= 0.85;
    else if (lead >= 14) k *= 0.92;
    else if (lead <= 2) k *= 1.12;
    return Math.round(base * k);
  }
  function apiPriceCalendar(q) {
    var ftext = (q.from || "").trim(), ttext = (q.to || "").trim();
    var days = Math.min(15, Math.max(7, parseInt(q.days || "15", 10)));
    if (!ftext || !ttext) return { ok: false, error: "需要 from/to" };
    var fp = resolvePlace(ftext), tp = resolvePlace(ttext);
    if (!fp) return { ok: false, error: "未找到匹配的车站或城市: " + ftext };
    if (!tp) return { ok: false, error: "未找到匹配的车站或城市: " + ttext };
    var fromCity = placeCity(fp), toCity = placeCity(tp);
    var exp = expandDestSiblings(tp);
    var r = search(fp, { sids: exp.sids }, 360, 15, 45, 180, 0);
    var trainBase = null;
    r.plans.forEach(function (p) { if (p.price && (trainBase === null || p.price < trainBase)) trainBase = p.price; });
    var flightBase = null, mmBase = null;
    if (fromCity && toCity && fromCity !== toCity) {
      try {
        var flights = flightPlans(fromCity, toCity);
        flights.forEach(function (f) { if (f.price && (flightBase === null || f.price < flightBase)) flightBase = f.price; });
        var mm = multimodalPlans(fromCity, toCity, flights);
        mm.forEach(function (m) { if (m.price && (mmBase === null || m.price < mmBase)) mmBase = m.price; });
      } catch (e) { /* 忽略 */ }
    }
    var today = localToday();
    var ftc = null, ttc = null;
    if (trainBase !== null) { ftc = teleOfPlace(fp); ttc = teleOfPlace(tp); }
    var trainReal = !!(ftc && ttc);
    var flightMonth = null;
    if (flightBase !== null && fromCity && toCity && FP && FP.available()) {
      try { flightMonth = FP.monthPrices(fromCity, toCity) || null; } catch (e) { flightMonth = null; }
    }
    var flightReal = !!flightMonth;
    var realByDate = {};
    if (trainReal && RP && RP.available()) {
      try { realByDate = RP.getPricesMulti(days, ftc, ttc); } catch (e) { realByDate = {}; }
    }
    var WD = "一二三四五六日";
    var out = [];
    for (var i = 0; i < days; i++) {
      var d = new Date(today.getTime() + i * 864e5);
      var dIso = isoOf(d);
      var rec = { date: dIso, weekday: WD[(d.getDay() + 6) % 7] };
      if (trainReal) {
        var data = realByDate[dIso], best = null;
        if (data) {
          Object.keys(data).forEach(function (code) {
            var b = RP.bestTrainPrice(data[code]);
            if (b && (best === null || b.price < best)) best = b.price;
          });
        }
        if (best !== null) rec.train = Math.round(best);
        else if (trainBase) rec.train = adjPrice(trainBase, d, today);
      } else if (trainBase) {
        rec.train = adjPrice(trainBase, d, today);
      }
      if (flightReal) {
        var fv = flightMonth[dIso];
        if (fv) rec.flight = fv;
        else if (flightBase) rec.flight = adjPrice(flightBase, d, today);
      } else if (flightBase) {
        rec.flight = adjPrice(flightBase, d, today);
      }
      if (mmBase) rec.mm = adjPrice(mmBase, d, today);
      var vals = [];
      ["train", "flight", "mm"].forEach(function (k) { if (rec[k]) vals.push(rec[k]); });
      if (vals.length) rec.min = Math.min.apply(null, vals);
      out.push(rec);
    }
    return { ok: true, from_city: fromCity || fp.label, to_city: toCity || tp.label,
      train_real: trainReal, flight_real: flightReal,
      train_base: trainBase, flight_base: flightBase, mm_base: mmBase, days: out };
  }

  function apiAirportsFull(q) {
    var kw = (q.q || "").trim();
    var rows = D.airports_full.filter(function (a) {
      if (!kw) return true;
      return (a[1] || "").indexOf(kw) >= 0 || (a[3] || "").indexOf(kw) >= 0 ||
             (a[2] || "").indexOf(kw) >= 0 || a[0].indexOf(kw) >= 0;
    });
    rows.sort(function (a, b) {
      var ea = a[3] ? 0 : 1, eb = b[3] ? 0 : 1;
      return ea - eb || (a[3] < b[3] ? -1 : a[3] > b[3] ? 1 : 0) || (a[1] < b[1] ? -1 : 1);
    });
    rows = rows.slice(0, 400);
    return { ok: true, total: rows.length,
      data: rows.map(function (a) {
        return { iata: a[0], name: a[1], city: a[2], cn_city: a[3], lat: a[4], lon: a[5] };
      }) };
  }

  /* --- 数据浏览类 API --- */
  function apiSummary() {
    var byType = {};
    D.trains.forEach(function (t) { byType[t[2]] = (byType[t[2]] || 0) + 1; });
    var major = 0;
    D.stations.forEach(function (s) { if (s[6]) major++; });
    var nStops = 0;
    for (var tid in D.stops) nStops += D.stops[tid].length;
    var typeOrder = ["G", "D", "C", "K", "T", "Z"];
    var dist = {};
    typeOrder.forEach(function (t) { if (byType[t]) dist[t] = byType[t]; });
    return { ok: true, data: {
      "车站": D.stations.length, "线路": D.lines.length, "车次": D.trains.length,
      "经停记录": nStops,
      "机场": D.airports.length, "动车组型号": D.emu.length, "景点": D.scenic.length,      "车次分布": dist, "主要车站": major,
      "数据来源": D.meta.data_source || "本地生成示例数据" } };
  }
  function apiStations(q) {
    var kw = (q.q || "").trim();
    var page = Math.max(1, parseInt(q.page || "1", 10));
    var size = Math.min(100, Math.max(5, parseInt(q.size || "20", 10)));
    var rows = D.stations.filter(function (s) {
      if (!kw) return true;
      return s[1].indexOf(kw) >= 0 || s[3].indexOf(kw) >= 0 ||
             s[4].indexOf(kw) >= 0 || s[5].indexOf(kw) >= 0;
    });
    rows.sort(function (a, b) { return b[6] - a[6] || (a[3] < b[3] ? -1 : a[3] > b[3] ? 1 : 0); });
    var total = rows.length;
    var data = rows.slice((page - 1) * size, page * size).map(function (s) {
      return { id: s[0], name: s[1], telecode: s[2], pinyin_full: s[3],
        pinyin_abbr: s[4], city: s[5], is_major: s[6] };
    });
    return { ok: true, total: total, page: page, size: size, data: data };
  }
  function apiStationDetail(sid) {
    var s = stationById[sid];
    if (!s) return { ok: false, error: "车站不存在" };
    var stopCount = (D.legs[sid] || []).length;
    var lines = [];
    Object.keys(D.line_stations).forEach(function (lid) {
      D.line_stations[lid].forEach(function (e) {
        if (e[0] === sid) {
          var l = lineById[lid];
          lines.push({ id: l.id, name: l.name, category: l.category, seq: e[1], mileage: e[2] });
        }
      });
    });
    lines.sort(function (a, b) { return a.seq - b.seq; });
    var scenic = D.scenic.filter(function (x) { return x[4] === sid; })
      .map(function (x) { return { id: x[0], name: x[1], level: x[3], note: x[5] }; });
    return { ok: true, data: { station: s, stop_count: stopCount, lines: lines, scenic: scenic } };
  }
  function apiStationTrains(sid) {
    var data = (D.legs[sid] || []).map(function (leg) {
      var tid = leg[0], seq = leg[1], arr = leg[2], dep = leg[3];
      var tr = trainById[tid];
      var sl = trainStops(tid);
      var next = null, nextDep = null;
      for (var i = 0; i < sl.length; i++) {
        if (sl[i][1] === seq) {
          if (i + 1 < sl.length) { next = D.names[sl[i + 1][0]]; nextDep = sl[i + 1][3]; }
          break;
        }
      }
      var d = { id: tid, code: tr.code, type: tr.type, emu_model: tr.emu_model,
        arrive_min: arr, depart_min: dep, stop_minutes: sl.filter(function (x) { return x[1] === seq; })[0][4],
        seq: seq, start_name: tr.start_name, end_name: tr.end_name,
        next_station: next, next_depart: nextDep,
        arrive: hhmm(arr), depart: hhmm(dep) };
      if (arr !== null && nextDep !== null) d.section_time = ((nextDep - arr) % 1440 + 1440) % 1440;
      return d;
    }).sort(function (a, b) { return (a.arrive_min || 0) - (b.arrive_min || 0); });
    return { ok: true, station_id: sid, count: data.length, data: data };
  }
  function apiTrains(q) {
    var kw = (q.q || "").trim().toUpperCase();
    var ttype = (q.type || "").trim().toUpperCase();
    var page = Math.max(1, parseInt(q.page || "1", 10));
    var size = Math.min(100, Math.max(5, parseInt(q.size || "20", 10)));
    var rows = D.trains.filter(function (t) {
      if (kw && t[1].indexOf(kw) < 0) return false;
      if (ttype && t[2] !== ttype) return false;
      return true;
    }).sort(function (a, b) { return a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0; });
    var total = rows.length;
    var data = rows.slice((page - 1) * size, page * size).map(function (t) {
      var tr = trainById[t[0]];
      var l = tr.line_id ? lineById[tr.line_id] : null;
      return { id: tr.id, code: tr.code, type: tr.type,
        depart_time: tr.depart_time, arrive_time: tr.arrive_time,
        depart: hhmm(tr.depart_time),
        arrive: hhmm(tr.arrive_time), duration: tr.arrive_time - tr.depart_time,
        mileage: tr.mileage, emu_model: tr.emu_model,
        start_name: tr.start_name, end_name: tr.end_name, line_name: l ? l.name : null };
    });
    return { ok: true, total: total, page: page, size: size, data: data };
  }
  function apiTrainDetail(tid) {
    var tr = trainById[tid];
    if (!tr) return { ok: false, error: "车次不存在" };
    var emuInfo = null;
    D.emu.forEach(function (e) { if (e[0] === tr.emu_model && !emuInfo) emuInfo = e; });
    var l = tr.line_id ? lineById[tr.line_id] : null;
    var sl = trainStops(tid);
    var stops = sl.map(function (x) {
      var s = stationById[x[0]];
      return { seq: x[1], station: s.name, station_id: s.id, city: s.city,
        arrive: hhmm(x[2]), depart: hhmm(x[3]), stop: x[4], mileage: x[5] };
    });
    var slAll = trainStops(tr.id);
    return { ok: true, data: {
      id: tr.id, code: tr.code, type: tr.type, line_id: tr.line_id,
      line_name: l ? l.name : null,
      start_station_id: slAll[0][0], end_station_id: slAll[slAll.length - 1][0],
      depart_time: tr.depart_time, arrive_time: tr.arrive_time,
      start_name: tr.start_name, end_name: tr.end_name,
      depart: hhmm(tr.depart_time), arrive: hhmm(tr.arrive_time),
      duration: tr.arrive_time - tr.depart_time, mileage: tr.mileage,
      emu_model: tr.emu_model,
      emu_nickname: emuInfo ? emuInfo[1] : null,
      emu_max_speed: emuInfo ? emuInfo[3] : null,
      stops: stops } };
  }
  function apiLines() {
    var data = D.lines.map(function (l) {
      var st = D.line_stations[l[0]] || [];
      var route = st.map(function (e) { return D.names[e[0]]; }).join(" — ");
      return { id: l[0], name: l[1], category: l[2], mileage: l[3], speed_limit: l[4],
        station_count: st.length, route: route };
    }).sort(function (a, b) { return b.mileage - a.mileage; });
    return { ok: true, data: data };
  }
  function apiLineDetail(lid) {
    var l = lineById[lid];
    if (!l) return { ok: false, error: "线路不存在" };
    var stations = (D.line_stations[lid] || []).map(function (e) {
      var s = stationById[e[0]];
      return { seq: e[1], id: s.id, name: s.name, city: s.city, mileage: e[2] };
    });
    var trains = D.trains.filter(function (t) { return t[3] === lid; })
      .map(function (t) { return { id: t[0], code: t[1], type: t[2] }; })
      .sort(function (a, b) { return a.code < b.code ? -1 : 1; });
    return { ok: true, data: { line: l, stations: stations, trains: trains } };
  }
  function apiSchedule(q) {
    var sid = q.station_id ? parseInt(q.station_id, 10) : null;
    var after = parseInt(q.after || "0", 10);
    if (sid === null) return { ok: false, error: "缺少 station_id" };
    var s = stationById[sid];
    if (!s) return { ok: false, error: "车站不存在" };
    var rows = (D.legs[sid] || []).map(function (leg) {
      var tr = trainById[leg[0]];
      return { train: tr, depart_min: leg[3] !== null ? leg[3] : leg[2],
        arrive_min: leg[2], id: tr.id, code: tr.code, type: tr.type,
        start_name: tr.start_name, end_name: tr.end_name };
    }).filter(function (r) { return r.depart_min !== null && r.depart_min >= after; })
      .sort(function (a, b) { return a.depart_min - b.depart_min; })
      .slice(0, 50)
      .map(function (r) {
      return { id: r.id, code: r.code, type: r.type,
        arrive_min: r.arrive_min, depart_min: r.depart_min,
        arrive: hhmm(r.arrive_min), depart: hhmm(r.depart_min),
        start_name: r.start_name, end_name: r.end_name };
      });
    return { ok: true, station: s.name, after: hhmm(after), data: rows };
  }
  function apiEmu() {
    return { ok: true, data: D.emu.map(function (e) {
      return { id: e[0], model: e[1], nickname: e[2], manufacturer: e[3],
        max_speed: e[4], formation: e[5] };
    }) };
  }
  function apiScenic() {
    return { ok: true, data: D.scenic.map(function (x) {
      var s = x[4] ? stationById[x[4]] : null;
      return { id: x[0], name: x[1], city: x[2], level: x[3], station_id: x[4],
        station_name: s ? s.name : null, note: x[5] };
    }) };
  }
  function apiUpdateStatus() {
    return { ok: true, data: {
      train_data_date: D.meta.data_date, train_source: D.meta.data_source,
      trains: D.meta.trains, stops: D.meta.stops,
      flights_updated: D.meta.flights_updated,
      update_status: "bundled", update_time: D.meta.data_date, update_error: "" } };
  }

  /* ---------------- 路由 ---------------- */
  function parseQuery(url) {
    var i = url.indexOf("?");
    var q = {};
    if (i < 0) return q;
    url.slice(i + 1).split("&").forEach(function (kv) {
      if (!kv) return;
      var eq = kv.indexOf("=");
      var k = decodeURIComponent(eq < 0 ? kv : kv.slice(0, eq));
      var v = eq < 0 ? "" : decodeURIComponent(kv.slice(eq + 1).replace(/\+/g, " "));
      q[k] = v;
    });
    return q;
  }

  function handle(path, method) {
    var route = path.split("?")[0];
    var q = parseQuery(path);
    var m;
    try {
      if (route === "/api/summary") return apiSummary();
      if (route === "/api/stations") return apiStations(q);
      if ((m = route.match(/^\/api\/stations\/(\d+)\/trains$/))) return apiStationTrains(+m[1]);
      if ((m = route.match(/^\/api\/stations\/(\d+)$/))) return apiStationDetail(+m[1]);
      if (route === "/api/trains") return apiTrains(q);
      if ((m = route.match(/^\/api\/trains\/(\d+)$/))) return apiTrainDetail(+m[1]);
      if (route === "/api/lines") return apiLines();
      if ((m = route.match(/^\/api\/lines\/(\d+)$/))) return apiLineDetail(+m[1]);
      if (route === "/api/schedule") return apiSchedule(q);
      if (route === "/api/journey") return apiJourney(q);
      if (route === "/api/plan") return apiPlan(q);
      if (route === "/api/flights") return apiFlights(q);
      if (route === "/api/coords") return apiCoords(q);
      if (route === "/api/price_calendar") return apiPriceCalendar(q);
      if (route === "/api/airports_full") return apiAirportsFull(q);
      if (route === "/api/emu") return apiEmu();
      if (route === "/api/scenic") return apiScenic();
      if (route === "/api/update_status") return apiUpdateStatus();
      if (route === "/api/update_check") return { ok: true, started: true };
      return { ok: false, error: "unknown route" };
    } catch (e) {
      return { ok: false, error: (e && e.name ? e.name : "Error") + ": " + (e && e.message ? e.message : e) };
    }
  }

  window.__API = { handle: handle, resolvePlace: resolvePlace, search: search };
})();
