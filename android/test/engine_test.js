/* engine_test.js — 在 Node(vm) 中加载安卓 assets 的 data.js + engine.js,
 * 按用例清单执行 __API.handle, 输出 JSON 供 Python 对照脚本比对。
 * 用法: node engine_test.js cases.json results.json
 */
"use strict";
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const ASSETS = path.join(__dirname, "..", "assets");

const sandbox = { console, JSON, Math, Date, isFinite, parseInt, parseFloat,
  isNaN, RegExp, Error, Object, Array, String, Number, Boolean };
sandbox.window = sandbox;
sandbox.setTimeout = setTimeout;
vm.createContext(sandbox);

for (const f of ["data.js", "engine.js", "realprice.js", "flightprice.js", "apihost.js"]) {
  const code = fs.readFileSync(path.join(ASSETS, f), "utf8");
  vm.runInContext(code, sandbox, { filename: f });
  console.error("loaded", f);
}

const cases = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const t0 = Date.now();
const results = cases.map(c => {
  const t = Date.now();
  let r;
  try { r = sandbox.__API.handle(c.path, c.method || "GET"); }
  catch (e) { r = { ok: false, error: "EXC:" + e.message }; }
  return { name: c.name, ms: Date.now() - t, result: r };
});
fs.writeFileSync(process.argv[3], JSON.stringify(results));
console.error("done", results.length, "cases in", Date.now() - t0, "ms");
