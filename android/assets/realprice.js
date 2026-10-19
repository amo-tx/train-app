/* realprice.js — 12306 官方余票/票价查询(由 realprice.py 移植)。
 * HTTP 经 AndroidHost.httpGet 原生桥(可设 Cookie 头、无 CORS 限制);
 * 无桥环境(如 Node 测试)自动降级为不可用, 上层回退估算价。
 * 价格串: 每 10 字符一组 <席别字母><5位价格分><4位计数>; 折扣串 <席别字母><4位折扣>。
 */
(function () {
  "use strict";
  var UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36";
  var ENDPOINT = "queryG";
  var cookie = { value: null, ts: 0 };
  var CACHE_TTL = 3 * 3600 * 1000;

  function available() {
    return typeof window !== "undefined" && window.AndroidHost &&
      typeof window.AndroidHost.httpGet === "function";
  }
  function http(url, headers) {
    try {
      var raw = window.AndroidHost.httpGet(url, JSON.stringify(headers || {}));
      return JSON.parse(raw);
    } catch (e) {
      return { error: String(e && e.message || e) };
    }
  }
  function getCookie(force) {
    if (cookie.value && !force && Date.now() - cookie.ts < 3600 * 1000) return cookie.value;
    var r = http("https://kyfw.12306.cn/otn/leftTicket/init", { "User-Agent": UA });
    if (r && r.set_cookie) {
      cookie.value = r.set_cookie;
      cookie.ts = Date.now();
    }
    return cookie.value || "_uab_collina=1";
  }
  function httpQuery(dateS, fromTc, toTc) {
    var q = "leftTicketDTO.train_date=" + encodeURIComponent(dateS) +
      "&leftTicketDTO.from_station=" + encodeURIComponent(fromTc) +
      "&leftTicketDTO.to_station=" + encodeURIComponent(toTc) +
      "&purpose_codes=ADULT";
    var url = "https://kyfw.12306.cn/otn/leftTicket/queryG?" + q;
    var lastErr = null;
    for (var attempt = 0; attempt < 3; attempt++) {
      var r = http(url, {
        "User-Agent": UA,
        "Referer": "https://kyfw.12306.cn/otn/leftTicket/init?linktypeid=dc",
        "Cookie": getCookie(attempt > 0),
        "Accept": "application/json"
      });
      if (r.error) { lastErr = r.error; continue; }
      try {
        var d = JSON.parse(r.body);
        if (d && d.c_url) {
          ENDPOINT = String(d.c_url).split("/").pop();
          url = "https://kyfw.12306.cn/otn/leftTicket/" + ENDPOINT + "?" + q;
          continue;
        }
        return d;
      } catch (e) { lastErr = String(e); }
    }
    throw new Error("12306 查询失败: " + lastErr);
  }
  var PRICE_RE = /([A-Z0-9])(\d{5})(\d{4})/g;
  var DISC_RE = /([A-Z0-9])(\d{4})/g;
  function parseRow(row) {
    var f = row.split("|");
    if (f.length < 40) return null;
    var prices = {};
    var ps = f.length > 39 ? f[39] : "";
    PRICE_RE.lastIndex = 0;
    var m;
    while ((m = PRICE_RE.exec(ps))) {
      var name = SEAT_CN[m[1]];
      if (!name) continue;
      var yuan = parseInt(m[2], 10) / 10;
      if (prices[name] === undefined || yuan < prices[name]) prices[name] = yuan;
    }
    if (!Object.keys(prices).length) return null;
    var disc = {};
    var ds = f.length > 54 ? f[54] : "";
    DISC_RE.lastIndex = 0;
    while ((m = DISC_RE.exec(ds))) {
      var nm = SEAT_CN[m[1]];
      if (nm && prices[nm] !== undefined) disc[nm] = parseInt(m[2], 10) / 100;
    }
    return { code: f[3], dep: f[8], arr: f[9], dur: f[10], can_buy: f[11] === "Y",
      prices: prices, discount: disc,
      left: { "二等座": f[30], "一等座": f[31], "商务座": f[32],
              "硬座": f[28], "硬卧": f[27], "软卧": f[23] } };
  }
  function fetchDay(dateS, fromTc, toTc) {
    var d = httpQuery(dateS, fromTc, toTc);
    var out = {};
    var rows = (d && d.data && d.data.result) || [];
    rows.forEach(function (row) {
      var p = parseRow(row);
      if (p) out[p.code] = p;
    });
    return out;
  }
  /* ---- 缓存(内存 + localStorage 尽力持久化) ---- */
  var memCache = {};
  function cacheKey(d, a, b) { return "pc:" + d + ":" + a + ":" + b; }
  function cacheGet(k) {
    var e = memCache[k];
    if (!e) {
      try {
        var raw = window.localStorage.getItem(k);
        if (raw) { e = JSON.parse(raw); memCache[k] = e; }
      } catch (x) { /* 忽略 */ }
    }
    if (e && Date.now() - e.at < CACHE_TTL) return e.data;
    return null;
  }
  function cachePut(k, data) {
    var e = { at: Date.now(), data: data };
    memCache[k] = e;
    try { window.localStorage.setItem(k, JSON.stringify(e)); } catch (x) { /* 超限忽略 */ }
  }
  function getPrices(dateS, fromTc, toTc) {
    if (!fromTc || !toTc) return null;
    var k = cacheKey(dateS, fromTc, toTc);
    var hit = cacheGet(k);
    if (hit !== null) return hit;
    try {
      var data = fetchDay(dateS, fromTc, toTc);
      cachePut(k, data);
      return data;
    } catch (e) {
      return null;
    }
  }
  function getPricesMulti(days, fromTc, toTc) {
    var out = {};
    var today = new Date();
    var iso = function (d) {
      var p = function (x) { return (x < 10 ? "0" : "") + x; };
      return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
    };
    for (var i = 0; i < days; i++) {
      var d = new Date(today.getFullYear(), today.getMonth(), today.getDate() + i);
      out[iso(d)] = getPrices(iso(d), fromTc, toTc);
    }
    return out;
  }
  function bestTrainPrice(info) {
    if (!info || !info.prices) return null;
    for (var i = 0; i < SEAT_PRIORITY.length; i++) {
      var name = SEAT_CN[SEAT_PRIORITY[i]];
      if (info.prices[name] !== undefined) {
        return { seat: name, price: info.prices[name],
          discount: info.discount ? info.discount[name] : undefined,
          left: info.left ? info.left[name] : undefined };
      }
    }
    return null;
  }
  function presaleLimit() { return 15; }

  var SEAT_CN = { "9": "商务座", P: "特等座", M: "一等座", O: "二等座", D: "优选一等座",
    W: "无座", A: "高级软卧", F: "动卧", "4": "软卧/一等卧", "3": "硬卧/二等卧",
    "1": "硬座", "2": "软座", "6": "高级软卧", E: "特等座" };
  var SEAT_PRIORITY = ["O", "1", "M", "3", "9", "4", "P", "D", "W", "2", "F", "A", "6", "E"];

  window.__RealPrice = { available: available, getPrices: getPrices,
    getPricesMulti: getPricesMulti, bestTrainPrice: bestTrainPrice,
    presaleLimit: presaleLimit, fetchDay: fetchDay };
})();
