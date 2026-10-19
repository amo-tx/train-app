/* flightprice.js — 携程整月机票最低价按需查询(由 flightprice.py 移植)。
 * 一次请求返回整月每日最低价; WAF 拦截/失败时返回 null, 上层回退估算价。
 */
(function () {
  "use strict";
  var UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36";
  var CACHE_TTL = 6 * 3600 * 1000;
  var NEG_TTL = 10 * 60 * 1000;

  var CITY_CODE_OVERRIDE = {
    "北京": "BJS", "上海": "SHA", "南京": "NKG", "杭州": "HGH",
    "广州": "CAN", "深圳": "SZX", "成都": "CTU", "重庆": "CKG",
    "武汉": "WUH", "西安": "SIA", "长沙": "CSX", "厦门": "XMN",
    "青岛": "TAO", "大连": "DLC", "昆明": "KMG", "三亚": "SYX",
    "海口": "HAK", "哈尔滨": "HRB", "沈阳": "SHE", "郑州": "CGO",
    "天津": "TSN", "贵阳": "KWE", "南宁": "NNG", "福州": "FOC",
    "兰州": "LHW", "乌鲁木齐": "URC", "拉萨": "LXA", "呼和浩特": "HET",
    "银川": "INC", "西宁": "XNN", "济南": "TNA", "太原": "TYN",
    "合肥": "HFE", "南昌": "KHN"
  };

  function available() {
    return typeof window !== "undefined" && window.AndroidHost &&
      typeof window.AndroidHost.httpGet === "function";
  }
  function cityCodes(city) {
    var D = window.__DATA__;
    var codes = [];
    var ov = CITY_CODE_OVERRIDE[city];
    if (ov) codes.push(ov);
    D.airports_full.forEach(function (a) {
      if ((a[3] === city || a[2] === city) && a[0] && codes.indexOf(a[0]) < 0) codes.push(a[0]);
    });
    return codes.slice(0, 3);
  }
  function fetchMonthPrices(dcode, acode) {
    var url = "https://flights.ctrip.com/itinerary/api/12808/lowestPrice" +
      "?flightWay=Oneway&dcity=" + encodeURIComponent(dcode) +
      "&acity=" + encodeURIComponent(acode) + "&direct=true&army=false";
    var raw = window.AndroidHost.httpGet(url, JSON.stringify({
      "User-Agent": UA,
      "Referer": "https://flights.ctrip.com/itinerary/oneway/",
      "Accept": "application/json, text/plain, */*"
    }));
    var r = JSON.parse(raw);
    if (r.error) return null;
    var d = JSON.parse(r.body);
    var arr = (d && d.data && d.data.oneWayPrice) || [];
    if (!arr.length || typeof arr[0] !== "object") return null;
    var out = {};
    Object.keys(arr[0]).forEach(function (k) {
      var v = parseInt(arr[0][k], 10);
      if (v > 0) out[k] = v;
    });
    return Object.keys(out).length ? out : null;
  }
  var memCache = {};
  function key(fc, tc) { return "fp:" + fc + ":" + tc; }
  function cacheGet(k) {
    var e = memCache[k];
    if (!e) {
      try {
        var raw = window.localStorage.getItem(k);
        if (raw) { e = JSON.parse(raw); memCache[k] = e; }
      } catch (x) { /* 忽略 */ }
    }
    if (!e) return undefined;
    var age = Date.now() - e.at;
    var empty = Object.keys(e.data).length === 0;
    if (empty) return age < NEG_TTL ? {} : undefined;
    return age < CACHE_TTL ? e.data : undefined;
  }
  function cachePut(k, data) {
    var e = { at: Date.now(), data: data };
    memCache[k] = e;
    try { window.localStorage.setItem(k, JSON.stringify(e)); } catch (x) { /* 超限忽略 */ }
  }
  function monthPrices(fromCity, toCity) {
    if (!fromCity || !toCity || fromCity === toCity) return null;
    var k = key(fromCity, toCity);
    var hit = cacheGet(k);
    if (hit !== undefined) return hit;
    var dc = cityCodes(fromCity), ac = cityCodes(toCity);
    for (var i = 0; i < dc.length; i++) {
      for (var j = 0; j < ac.length; j++) {
        if (dc[i] === ac[j]) continue;
        try {
          var data = fetchMonthPrices(dc[i], ac[j]);
          if (data) { cachePut(k, data); return data; }
        } catch (e) { /* 试下一组代码 */ }
      }
    }
    cachePut(k, {});   // 负缓存, 10 分钟后再试
    return null;
  }
  function priceOn(fromCity, toCity, dateS) {
    var m = monthPrices(fromCity, toCity);
    return m ? m[dateS] : null;
  }
  window.__FlightPrice = { available: available, monthPrices: monthPrices, priceOn: priceOn };
})();
