/* apihost.js — /api/* 垫片: 让桌面版前端(app.js 原样复用)在 file:// 环境下
 * 无改动地工作。拦截 window.fetch 中相对路径的 /api/* 请求, 路由到 engine.js;
 * 其余请求(瓦片/真实网络)透传给原生 fetch。
 */
(function () {
  "use strict";
  var origFetch = window.fetch ? window.fetch.bind(window) : null;

  function jsonResp(obj, status) {
    var body = JSON.stringify(obj);
    try {
      return new Response(body, { status: status || 200,
        headers: { "Content-Type": "application/json; charset=utf-8" } });
    } catch (e) {
      // 极老 WebView 无 Response 构造器: 退化为伪对象(app.js 只用 .json()/.ok)
      return Promise.resolve({
        ok: true, status: 200,
        json: function () { return Promise.resolve(obj); }
      });
    }
  }

  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    if (/^\/api\//.test(url)) {
      var result = window.__API.handle(url, (init && init.method) || "GET");
      return jsonResp(result, result && result.ok === false && result.error &&
        /unknown route/.test(result.error) ? 404 : 200);
    }
    if (origFetch) return origFetch(input, init);
    return Promise.reject(new Error("fetch unavailable"));
  };
})();
