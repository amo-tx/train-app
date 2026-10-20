/* app.js — 前端单页应用 (原生 JS, 无依赖) */
const $app = document.getElementById("app");
const $nav = document.getElementById("nav");

async function api(path) {
  const r = await fetch(path);
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || "请求失败");
  return j;
}
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const badge = t => `<span class="badge b-${esc(t)}">${esc(t)}</span>`;
const dur = m => `${Math.floor(m / 60)}小时${m % 60 ? (m % 60) + "分" : ""}`;
const fmtDur = m => !m ? "--" : dur(m);

/* ---------------- 概览 ---------------- */
async function viewOverview() {
  const { data } = await api("/api/summary");
  const cards = Object.entries(data).filter(([k]) => k !== "车次分布")
    .map(([k, v]) => `<div class="card"><div class="num">${v}</div><div class="label">${esc(k)}</div></div>`).join("");
  const dist = Object.entries(data["车次分布"] || {})
    .map(([t, c]) => `<div class="card"><div class="num">${badge(t)} ${c}</div><div class="label">车次分布</div></div>`).join("");
  $app.innerHTML = `<h2>数据概览</h2><div class="cards">${cards}${dist}</div>
    <div class="detail-panel"><h3>关于</h3>
    <p class="muted">复刻自微信小程序"坐着火车去旅行"(wx59621264198bea6e) 的核心数据模型：
    车站 / 车次 / 经停时刻 / 线路 / 机场 / 动车组 / 景点，全部存储在本地 SQLite 单文件数据库中，
    查询、时刻表、直达检索均不依赖任何外部服务。</p></div>`;
}

/* ---------------- 车站 ---------------- */
async function viewStations() {
  $app.innerHTML = `<h2>车站检索</h2>
    <div class="toolbar"><input id="q" placeholder="站名 / 拼音 / 城市，如 青岛 qingdao qd" size="34">
    <button class="primary" id="go">搜索</button></div>
    <div id="list"><div class="loading">加载中…</div></div>
    <div class="pager" id="pager"></div>`;
  const load = async (page = 1) => {
    const q = document.getElementById("q").value.trim();
    const j = await api(`/api/stations?q=${encodeURIComponent(q)}&page=${page}&size=20`);
    const rows = j.data.map(s => `<tr>
      <td><a class="link" href="#/station/${s.id}">${esc(s.name)}</a></td>
      <td>${esc(s.pinyin_full)}</td><td>${esc(s.pinyin_abbr)}</td><td>${esc(s.city)}</td>
      <td class="muted">${esc(s.telecode)}</td>
      <td>${s.is_major ? '<span class="badge tag-major">主要站</span>' : ""}</td></tr>`).join("");
    document.getElementById("list").innerHTML = `<table>
      <thead><tr><th>站名</th><th>全拼</th><th>简拼</th><th>城市</th><th>电报码</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table>`;
    const pages = Math.ceil(j.total / j.size);
    document.getElementById("pager").innerHTML =
      `<button ${page <= 1 ? "disabled" : ""} onclick="window._stPage(${page - 1})">上一页</button>
       第 ${j.page} / ${pages} 页 · 共 ${j.total} 站
       <button ${page >= pages ? "disabled" : ""} onclick="window._stPage(${page + 1})">下一页</button>`;
  };
  window._stPage = load;
  document.getElementById("go").onclick = () => load(1);
  document.getElementById("q").onkeydown = e => { if (e.key === "Enter") load(1); };
  load(1);
}

async function viewStation(sid) {
  const { data } = await api(`/api/stations/${sid}`);
  const s = data.station;
  $app.innerHTML = `<h2>🚉 ${esc(s.name)} ${s.is_major ? '<span class="badge tag-major">主要站</span>' : ""}</h2>
    <div class="grid2">
      <div class="detail-panel"><div class="kv">
        <b>全拼</b><span>${esc(s.pinyin_full)}</span>
        <b>电报码</b><span>${esc(s.telecode)}</span>
        <b>城市</b><span>${esc(s.city)}</span>
        <b>经停车次</b><span class="tt-now">${data.stop_count} 趟</span>
      </div></div>
      <div class="detail-panel"><h3>途经线路</h3>${
        data.lines.length ? data.lines.map(l =>
          `<div><a class="link" href="#/line/${l.id}">${esc(l.name)}</a>
           <span class="muted">· ${esc(l.category)} · K${l.seq + 1} 站 · ${l.mileage} km</span></div>`).join("")
        : '<span class="muted">无</span>'}
        <h3>周边景点</h3>${
        data.scenic.length ? data.scenic.map(x =>
          `<div><span class="badge b-Z">${esc(x.level)}</span><b>${esc(x.name)}</b>
           <span class="muted">— ${esc(x.note || "")}</span></div>`).join("")
        : '<span class="muted">暂无</span>'}</div>
    </div>
    <h3>经停车次时刻</h3><div id="tt"><div class="loading">加载中…</div></div>`;
  const j = await api(`/api/stations/${sid}/trains`);
  document.getElementById("tt").innerHTML = j.count ? `<table>
    <thead><tr><th>车次</th><th>区间</th><th>到点</th><th>开点</th><th>下一站</th><th>担当车型</th></tr></thead>
    <tbody>${j.data.map(r => `<tr>
      <td><a class="link" href="#/train/${r.train_id ?? r.id}">${badge(r.type)}${esc(r.code)}</a></td>
      <td class="muted">${esc(r.start_name)} → ${esc(r.end_name)}</td>
      <td>${r.arrive}</td><td>${r.depart}</td>
      <td>${r.next_station ? `${esc(r.next_station)} ${r.next_depart ?? ""}` : '<span class="muted">终到</span>'}</td>
      <td class="muted">${esc(r.emu_model || "-")}</td></tr>`).join("")}</tbody></table>`
    : '<p class="muted">暂无经停车次</p>';
}

/* ---------------- 车次 ---------------- */
async function viewTrains() {
  $app.innerHTML = `<h2>车次检索</h2>
    <div class="toolbar"><input id="q" placeholder="车次号，如 G 或 G101" size="24">
    <select id="type"><option value="">全部类型</option>${["G", "D", "C", "K", "T", "Z"].map(t => `<option>${t}</option>`).join("")}</select>
    <button class="primary" id="go">查询</button></div><div id="list"></div><div class="pager" id="pager"></div>`;
  const load = async (page = 1) => {
    const q = document.getElementById("q").value.trim();
    const type = document.getElementById("type").value;
    const j = await api(`/api/trains?q=${encodeURIComponent(q)}&type=${type}&page=${page}`);
    document.getElementById("list").innerHTML = `<table>
      <thead><tr><th>车次</th><th>区间</th><th>始发</th><th>终到</th><th>历时</th><th>里程</th><th>车型</th><th>线路</th></tr></thead>
      <tbody>${j.data.map(t => `<tr>
        <td><a class="link" href="#/train/${t.id}">${badge(t.type)}${esc(t.code)}</a></td>
        <td>${esc(t.start_name)} → ${esc(t.end_name)}</td>
        <td class="tt-now">${t.depart}</td><td>${t.arrive}</td><td>${fmtDur(t.duration)}</td>
        <td>${t.mileage} km</td><td class="muted">${esc(t.emu_model || "-")}</td>
        <td class="muted">${esc(t.line_name || "-")}</td></tr>`).join("")}</tbody></table>`;
    const pages = Math.ceil(j.total / j.size);
    document.getElementById("pager").innerHTML =
      `<button ${page <= 1 ? "disabled" : ""} onclick="window._trPage(${page - 1})">上一页</button>
       第 ${j.page} / ${pages} 页 · 共 ${j.total} 趟
       <button ${page >= pages ? "disabled" : ""} onclick="window._trPage(${page + 1})">下一页</button>`;
  };
  window._trPage = load;
  document.getElementById("go").onclick = () => load(1);
  load(1);
}

async function viewTrain(tid) {
  const { data } = await api(`/api/trains/${tid}`);
  $app.innerHTML = `<h2>${badge(data.type)} ${esc(data.code)} 次</h2>
    <div class="detail-panel"><div class="kv">
      <b>区间</b><span>${esc(data.start_name)} → ${esc(data.end_name)}</span>
      <b>时刻</b><span class="tt-now">${data.depart} 开 — ${data.arrive} 到（历时 ${fmtDur(data.duration)}）</span>
      <b>线路</b><span>${esc(data.line_name || "-")}</span>
      <b>担当车型</b><span>${esc(data.emu_model || "-")}${data.emu_nickname ? `（${esc(data.emu_nickname)}，最高 ${data.emu_max_speed} km/h）` : ""}</span>
      <b>总里程</b><span>${data.mileage} km</span>
    </div></div>
    <h3>经停时刻表（${data.stops.length} 站）</h3>
    <table><thead><tr><th>#</th><th>车站</th><th>城市</th><th>到点</th><th>开点</th><th>停时</th><th>累计里程</th></tr></thead>
    <tbody>${data.stops.map(s => `<tr>
      <td class="muted">${s.seq + 1}</td>
      <td><a class="link" href="#/station/${s.station_id ?? ""}">${esc(s.station)}</a></td>
      <td class="muted">${esc(s.city)}</td>
      <td>${s.arrive}</td><td>${s.depart}</td>
      <td>${s.stop ? s.stop + " 分" : '<span class="muted">—</span>'}</td>
      <td>${s.mileage} km</td></tr>`).join("")}</tbody></table>`;
}

/* ---------------- 线路 ---------------- */
async function viewLines() {
  const { data } = await api("/api/lines");
  $app.innerHTML = `<h2>线路</h2><table>
    <thead><tr><th>线路</th><th>类别</th><th>车站数</th><th>里程</th><th>走向</th></tr></thead>
    <tbody>${data.map(l => `<tr>
      <td><a class="link" href="#/line/${l.id}">${esc(l.name)}</a></td>
      <td>${esc(l.category)}</td><td>${l.station_count}</td><td>${l.mileage} km（限速 ${l.speed_limit}）</td>
      <td class="muted">${esc(l.route || "")}</td></tr>`).join("")}</tbody></table>`;
}

async function viewLine(lid) {
  const { data } = await api(`/api/lines/${lid}`);
  const l = data.line;
  $app.innerHTML = `<h2>🛤 ${esc(l.name)}</h2>
    <div class="detail-panel"><div class="kv">
      <b>类别</b><span>${esc(l.category)} · 限速 ${l.speed_limit} km/h</span>
      <b>里程</b><span>${l.mileage} km</span></div></div>
    <div class="grid2">
      <div><h3>车站序列（${data.stations.length} 站）</h3><table>
        <thead><tr><th>#</th><th>车站</th><th>城市</th><th>里程</th></tr></thead>
        <tbody>${data.stations.map(s => `<tr><td class="muted">${s.seq + 1}</td>
          <td><a class="link" href="#/station/${s.id}">${esc(s.name)}</a></td>
          <td class="muted">${esc(s.city)}</td><td>${s.mileage} km</td></tr>`).join("")}</tbody></table></div>
      <div><h3>本线车次（${data.trains.length} 趟）</h3><table>
        <thead><tr><th>车次</th><th></th></tr></thead>
        <tbody>${data.trains.map(t => `<tr>
          <td><a class="link" href="#/train/${t.id}">${badge(t.type)}${esc(t.code)}</a></td>
          <td class="muted">查看时刻</td></tr>`).join("")}</tbody></table></div>
    </div>`;
}

/* ---------------- 时刻表 ---------------- */
async function viewSchedule() {
  $app.innerHTML = `<h2>时刻表查询</h2>
    <div class="toolbar"><input id="q" placeholder="车站名，如 青岛北" size="24">
    <select id="hh">${Array.from({ length: 24 }, (_, h) => `<option value="${h}">${String(h).padStart(2, "0")} 点之后</option>`).join("")}</select>
    <button class="primary" id="go">查询</button></div><div id="out"><p class="muted">输入车站名开始查询</p></div>`;
  document.getElementById("go").onclick = async () => {
    const kw = document.getElementById("q").value.trim();
    const hh = +document.getElementById("hh").value;
    if (!kw) return;
    const st = await api(`/api/stations?q=${encodeURIComponent(kw)}&size=1`);
    if (!st.data.length) { document.getElementById("out").innerHTML = '<p class="muted">未找到车站</p>'; return; }
    const s = st.data[0];
    const j = await api(`/api/schedule?station_id=${s.id}&after=${hh * 60}`);
    document.getElementById("out").innerHTML = `<p class="muted" style="margin-bottom:10px">
      ${esc(j.station)} · ${esc(j.after)} 之后 · 共 ${j.total ?? j.data.length} 趟</p><table>
      <thead><tr><th>车次</th><th>区间</th><th>到点</th><th>开点</th></tr></thead>
      <tbody>${j.data.map(r => `<tr><td><a class="link" href="#/train/${r.id}">${badge(r.type)}${esc(r.code)}</a></td>
        <td class="muted">${esc(r.start_name)} → ${esc(r.end_name)}</td>
        <td>${r.arrive}</td><td class="tt-now">${r.depart}</td></tr>`).join("")}</tbody></table>`;
  };
}

/* ---------------- 出行方案 v2(城市模糊 + 两次中转 + 航班/联运 + 排序) ---------------- */
let _lastPlans = null, _planSort = "total", _pendingPlan = null, _transferState = null, _calState = null, _pendingAutoQuery = false;

const PLAN_COLOR = { G: "#fe295f", D: "#ff8a3d", C: "#ffb020", K: "#38bdf8", T: "#818cf8", Z: "#34d399" };

function planSummary(p) {
  if (p.kind === "train") {
    return p.legs.filter(l => l.kind === "train").map(l =>
      `<a class="link" href="#/train/${l.train_id}">${badge(l.type)}${esc(l.code)}</a>
       <span class="muted" style="font-size:12px">${esc(l.board)}→${esc(l.alight)}</span>`
    ).join('<span style="color:var(--muted)"> → </span>');
  }
  if (p.kind === "flight") {
    const ap = n => esc(n || "");
    return `${esc(p.airline)} <b>${esc(p.flight_no)}</b>
      ${p.dep ? `<span class="tt-now">${p.dep}→${p.arr}</span> ` : ""}
      <span class="muted">${ap(p.src_airport_cn || p.src_airport)}(${p.src_iata}) → ${ap(p.dst_airport_cn || p.dst_airport)}(${p.dst_iata})${p.model ? " · " + esc(p.model) : ""}</span>`;
  }
  const flyPart = `✈ ${esc(p.flight.from_city)} → ${esc(p.flight.to_city)} <span class="muted">飞行${fmtDur(p.flight.duration)}</span>`;
  const railPart = `🚄 ${badge(p.rail.type)}${esc(p.rail.code)} <span class="muted">${esc(p.rail.from_city)} → ${esc(p.rail.to_city)} ${fmtDur(p.rail.ride)}</span>`;
  return p.flight.from_city === p.from_city ? `${flyPart}\n    → ${railPart}` : `${railPart}\n    → ${flyPart}`;
}

function planCatBadge(p) {
  if (p.kind === "train") {
    const col = { 0: "b-G", 1: "b-D", 2: "b-K" }[p.transfers] || "b-K";
    let s = `<span class="badge ${col}">${p.category}</span>`;
    if (p.legs.some(l => l.kind === "walk")) s += `<span class="badge b-Z" title="同城异站换乘, 已含通行时间">同城换站</span>`;
    if (p.same_city_arrive) s += `<span class="badge b-C" title="终到站与请求站同城">同城终到</span>`;
    return s;
  }
  if (p.kind === "flight") return `<span class="badge b-D">✈ 直飞</span>`;
  return `<span class="badge b-C">✈+🚄 空铁联运</span>`;
}

function renderPlans() {
  const box = document.getElementById("plan-list");
  if (!_lastPlans || !_lastPlans.length) { box.innerHTML = '<p class="muted">无方案</p>'; return; }
  const key = _planSort;
  const sorted = [..._lastPlans].sort((a, b) => {
    const pv = x => (x.real_price ? x.real_price.price : x.price) ?? Infinity;
    const va = key === "price" || key === "pricedesc" ? pv(a) : (a[key] ?? Infinity);
    const vb = key === "price" || key === "pricedesc" ? pv(b) : (b[key] ?? Infinity);
    return key === "pricedesc" ? vb - va : va - vb;
  });
  const rpCell = p => {
    if (p.real_price) {
      const r = p.real_price;
      const disc = r.discount && r.discount < 1 ? ` · ${r.discount * 10}折` : "";
      return `<span class="badge" style="background:#1d7a46;color:#fff">真实</span> ¥${r.price}${disc} <span class="muted" style="font-size:12px">${r.seat}</span>`;
    }
    return p.price_fmt;
  };
  box.innerHTML = `<table><thead><tr><th style="width:90px">类型</th><th>方案</th>
    <th>出发→到达</th><th>总耗时</th><th>乘车/飞行</th><th>票价</th></tr></thead><tbody>` +
    sorted.map((p, i) => `<tr class="plan-row" data-i="${_lastPlans.indexOf(p)}" style="cursor:pointer">
      <td>${planCatBadge(p)}</td>
      <td>${planSummary(p)}</td>
      <td class="tt-now">${p.dep ?? "--"} → ${p.arr ?? "--"}</td>
      <td>${p.total_fmt}</td><td class="muted">${p.ride_fmt}</td>
      <td>${rpCell(p)}</td></tr>`).join("") +
    `</tbody></table>
     <p class="muted">点击任意方案在地图上查看线路走向${_lastPlans.some(p => p.real_price) ? " · <b style='color:#4ade80'>真实</b> = 12306/携程 当日实际票价(含浮动折扣)" : " · 火车票价为按里程估算, 选择日期后自动查询 12306 真实票价"}</p>`;
  box.querySelectorAll(".plan-row").forEach(tr => {
    tr.onclick = () => {
      _pendingPlan = _lastPlans[+tr.dataset.i];
      location.hash = "#/routemap";
    };
  });
}

async function viewTransfer() {
  $app.innerHTML = `<h2>出行方案</h2>
    <div class="toolbar" style="flex-wrap:wrap;gap:8px">
      <input id="from" placeholder="出发城市/车站，如 北京" size="14">
      <span style="color:var(--muted)">→</span>
      <input id="to" placeholder="到达城市/车站，如 上海" size="14">
      <select id="mode" style="width:auto">
        <option value="all">全部方式</option>
        <option value="flight">✈ 仅直飞</option>
        <option value="rail">🚄 仅火车</option></select>
      <input type="date" id="pdate" title="选择日期后查询 12306 真实票价" style="width:auto">
      <button class="primary" id="go">查询</button>
      <button id="calgo" title="未来15天各方案最低价对比(火车为12306真实票价)">📅 价格日历</button>
      <details style="color:var(--text)"><summary style="cursor:pointer;color:var(--muted)">更多筛选</summary>
        <span style="display:inline-flex;gap:8px;align-items:center;margin-left:8px">
        <select id="hh">${Array.from({ length: 24 }, (_, h) => `<option value="${h}">${String(h).padStart(2, "0")} 点后出发</option>`).join("")}</select>
        <select id="legs"><option value="2">含两次中转</option><option value="1">最多一次中转</option><option value="0">仅直达</option></select>
        <select id="wait"><option value="180">换乘等待≤3h</option><option value="720">≤12h(含跨夜)</option><option value="60">≤1h</option></select></span></details></div>
    <div class="toolbar" id="plan-meta"></div>
    <div id="plan-list"><p class="muted">输入出发与到达(城市或车站, 支持模糊)开始查询</p></div>`;
  document.getElementById("go").onclick = queryPlans;
  // 日期选择器: 今天~预售期内
  {
    const pd = document.getElementById("pdate");
    const now = new Date();
    const iso = d => d.toISOString().slice(0, 10);
    pd.value = iso(now);
    pd.min = iso(now);
    pd.max = iso(new Date(now.getTime() + 14 * 864e5));
  }
  document.getElementById("calgo").onclick = () => {
    const f = document.getElementById("from").value.trim();
    const t = document.getElementById("to").value.trim();
    if (!f || !t) { document.getElementById("plan-list").innerHTML = '<p class="muted">请先填写出发与到达</p>'; return; }
    _calState = { f, t };
    location.hash = "#/calendar";
  };
  // 从价格日历选完日期返回: 填好起止地+日期并自动查询
  if (_pendingAutoQuery && _calState) {
    document.getElementById("from").value = _calState.f;
    document.getElementById("to").value = _calState.t;
    if (_calState.date) document.getElementById("pdate").value = _calState.date;
    _pendingAutoQuery = false;
    queryPlans();
  } else if (_transferState && _lastPlans && _lastPlans.length) {
    document.getElementById("from").value = _transferState.f;
    document.getElementById("to").value = _transferState.t;
    if (_transferState.mode) document.getElementById("mode").value = _transferState.mode;
    if (_transferState.pdate) document.getElementById("pdate").value = _transferState.pdate;
    document.getElementById("plan-meta").innerHTML = _transferState.meta;
    const sortSel = document.getElementById("sort");
    if (sortSel) {
      sortSel.value = _planSort;
      sortSel.onchange = () => { _planSort = sortSel.value; renderPlans(); };
    }
    renderPlans();
  }
  async function queryPlans() {
    const f = document.getElementById("from").value.trim();
    const t = document.getElementById("to").value.trim();
    if (!f || !t) return;
    const after = +document.getElementById("hh").value * 60;
    const legs = document.getElementById("legs").value;
    const wait = document.getElementById("wait").value;
    const mode = document.getElementById("mode").value;
    const pdate = document.getElementById("pdate").value || "";
    const api_path = mode === "rail" ? "/api/journey" : "/api/plan";
    document.getElementById("plan-list").innerHTML =
      `<div class="loading">搜索中…(两次中转约需几秒${pdate ? ", 正在查询 12306 真实票价" : ""})</div>`;
    const j = await api(`${api_path}?from=${encodeURIComponent(f)}&to=${encodeURIComponent(t)}&after=${after}&max_legs=${legs}&max_wait=${wait}&date=${encodeURIComponent(pdate)}`);
    if (!j.ok) { document.getElementById("plan-list").innerHTML = `<p class="muted">${esc(j.error)}</p>`; return; }
    if (mode === "flight") j.plans = j.plans.filter(p => p.kind !== "multimodal");
    _lastPlans = j.plans;
    if (mode === "flight") j.counts = Object.fromEntries(Object.entries(j.counts).filter(([k]) => k !== "空铁联运"));
    document.getElementById("plan-meta").innerHTML =
      `<b>${esc(j.from.label)}</b> <span class="muted">(${esc(j.from.kind === "city" ? "城市·" + j.from.stations.length + "站" : "车站")})</span>
       → <b>${esc(j.to.label)}</b> <span class="muted">(${esc(j.to.kind === "city" ? "城市·" + j.to.stations.length + "站" : "车站")})</span>
       <span class="muted">· ${j.elapsed}s · </span>` +
      Object.entries(j.counts).filter(([, c]) => c > 0)
        .map(([k, c]) => `<span class="badge b-G">${k} ${c}</span>`).join(" ") +
      `&nbsp;&nbsp;排序：<select id="sort" style="width:auto">
        <option value="total">总耗时 ↑</option><option value="ride">乘车/飞行时间 ↑</option>
        <option value="price">价格 低→高</option><option value="pricedesc">价格 高→低</option></select>`;
    const sortSel = document.getElementById("sort");
    sortSel.value = _planSort;
    sortSel.onchange = () => {
      _planSort = sortSel.value;
      renderPlans();
    };
    _transferState = { f, t, mode, pdate, meta: document.getElementById("plan-meta").innerHTML };
    renderPlans();
  }
}

/* ---------------- 中国地图(Leaflet + 高德瓦片, 全信息量) ---------------- */
let _lmap = null, _routeLayer = null;

function wgs2gcj(lng, lat) {
  // 标准 WGS84 -> GCJ02 纠偏(中国境内)
  const a = 6378245.0, ee = 0.00669342162296594323;
  const tLat = lat => {
    let r = -100 + 2 * lng + 3 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * Math.sqrt(Math.abs(lng));
    r += (20 * Math.sin(6 * lng * Math.PI) + 20 * Math.sin(2 * lng * Math.PI)) * 2 / 3;
    r += (20 * Math.sin(lat * Math.PI) + 40 * Math.sin(lat / 3 * Math.PI)) * 2 / 3;
    r += (160 * Math.sin(lat / 12 * Math.PI) + 320 * Math.sin(lat * Math.PI / 30)) * 2 / 3;
    return r;
  };
  const tLng = lng => {
    let r = 300 + lng + 2 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * Math.sqrt(Math.abs(lng));
    r += (20 * Math.sin(6 * lng * Math.PI) + 20 * Math.sin(2 * lng * Math.PI)) * 2 / 3;
    r += (20 * Math.sin(lng * Math.PI) + 40 * Math.sin(lng / 3 * Math.PI)) * 2 / 3;
    r += (150 * Math.sin(lng / 12 * Math.PI) + 300 * Math.sin(lng / 30 * Math.PI)) * 2 / 3;
    return r;
  };
  let dLat = tLat(lng - 105), dLng = tLng(lng - 35);
  const radlat = lat / 180 * Math.PI;
  let magic = Math.sin(radlat);
  magic = 1 - ee * magic * magic;
  const sqrtmagic = Math.sqrt(magic);
  dLat = (dLat * 180) / ((a * (1 - ee)) / (magic * sqrtmagic) * Math.PI);
  dLng = (dLng * 180) / (a / sqrtmagic * Math.cos(radlat) * Math.PI);
  return [lng + dLng, lat + dLat];
}

// Leaflet 要求 [lat, lng] 顺序, 而数据源是 [lng, lat], 在此统一翻转
const gcj = ll => {
  const r = wgs2gcj(ll[0], ll[1]);        // r = [lng, lat]
  const lat = r[1], lng = r[0];
  if (!isFinite(lat) || !isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) return null;
  return [lat, lng];                       // -> Leaflet [lat, lng]
};

async function viewRouteMap() {
  if (!_pendingPlan) {
    $app.innerHTML = `<div class="detail-panel"><p>尚未选择出行方案。</p>
      <a class="link" href="#/transfer">去「出行方案」查询 →</a></div>`;
    return;
  }
  const plan = _pendingPlan; _pendingPlan = null;
  $app.innerHTML = `
    <div class="toolbar" style="justify-content:flex-end;flex-wrap:wrap;gap:10px">
      <span style="display:flex;gap:10px;align-items:center">
        <select id="base" style="width:auto"><option value="std">标准地图</option><option value="sat">卫星影像</option></select>
        <span class="muted">高德底图 · 需联网</span></span></div>
    <div id="map" style="height:540px;border:1px solid var(--border);border-radius:8px;overflow:hidden"></div>
    <div id="plan-detail"></div>`;
  renderPlanDetail(plan);

  // 修复"用过一次地图后再进全黑": 路由切换时容器已被移除,
  // 旧 Leaflet 实例必须销毁, 每次进入都重新绑定新容器
  if (_lmap) { try { _lmap.remove(); } catch (e) { /* 容器已脱离文档 */ } _lmap = null; }
  _routeLayer = null;
  const map = _lmap = L.map("map", { preferCanvas: true, zoomControl: true });
  window._lmap = map;  // 调试/E2E 用
  const std = L.tileLayer("https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
    { subdomains: ["1", "2", "3", "4"], maxZoom: 18, attribution: "© 高德地图" });
  const sat = L.tileLayer("https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}",
    { subdomains: ["1", "2", "3", "4"], maxZoom: 18, attribution: "© 高德地图" });
  const satLabel = L.tileLayer("https://webst0{s}.is.autonavi.com/appmaptile?style=8&x={x}&y={y}&z={z}",
    { subdomains: ["1", "2", "3", "4"], maxZoom: 18, opacity: 0.9 });
  std.addTo(map);
  map._bases = { std, sat: L.layerGroup([sat, satLabel]) };
  document.getElementById("base").onchange = e => {
    Object.values(map._bases).forEach(l => map.removeLayer(l));
    map._bases[e.target.value].addTo(map);
  };
  setTimeout(() => map.invalidateSize(), 50);

  // 仅拉取本方案涉及站点的坐标(不加载全量路网)
  const names = new Set();
  (plan.legs || []).forEach(l => {
    if (l.kind === "train") { names.add(l.board); names.add(l.alight); }
    if (l.kind === "walk") { names.add(l.walk_from); names.add(l.walk_to); }
  });
  if (plan.kind === "multimodal") [plan.from_city, plan.hub, plan.to_city].forEach(c => c && names.add(c));
  const byName = {};
  if (names.size) {
    try {
      const j = await api("/api/coords?names=" + encodeURIComponent([...names].join(",")));
      (j.data || []).forEach(s => { if (!byName[s.name]) byName[s.name] = s; });
    } catch (e) { console.warn("方案坐标加载失败", e); }
  }
  drawPlanRoute(plan, byName);
}

function renderPlanDetail(plan) {
  const box = document.getElementById("plan-detail");
  const rpHead = plan.real_price
    ? ` · 实际票价 <b style="color:#4ade80">¥${plan.real_price.price}</b><span class="muted"> (${plan.real_price.seat}${plan.real_price.discount && plan.real_price.discount < 1 ? " · " + plan.real_price.discount * 10 + "折" : ""})</span>`
    : ` · 参考价 <b>${plan.price_fmt}</b>`;
  const head = `<div class="detail-panel" style="margin-top:12px">
    <h3>方案详情 ${planCatBadge(plan)}</h3>
    <p>出发 <b class="tt-now">${plan.dep ?? "--"}</b> · 到达 <b class="tt-now">${plan.arr ?? "--"}</b>
     · 总耗时 <b>${plan.total_fmt}</b> · 乘车/飞行 <b>${plan.ride_fmt}</b> ·${rpHead}</p>
    ${plan.note ? `<p class="muted">${esc(plan.note)}</p>` : ""}%T</div>`;
  if (plan.kind === "train") {
    const rpCell = l => l.real_price
      ? `<span style="color:#4ade80">¥${l.real_price.price}</span><span class="muted" style="font-size:12px"> ${l.real_price.seat}${l.real_price.discount && l.real_price.discount < 1 ? " " + l.real_price.discount * 10 + "折" : ""}${l.real_price.left ? " · 余" + l.real_price.left : ""}</span>`
      : (l.price ? "¥" + l.price : "—");
    const rows = plan.legs.map(l => l.kind === "train" ? `
      <tr><td>${badge(l.type)}<a class="link" href="#/train/${l.train_id}">${esc(l.code)}</a></td>
      <td>${esc(l.board)}<span class="muted">(${esc(l.board_city || "")})</span> → ${esc(l.alight)}<span class="muted">(${esc(l.alight_city || "")})</span></td>
      <td class="tt-now">${l.dep} → ${l.arr}</td>
      <td class="muted">${fmtDur(l.ride)}${l.km ? " · " + l.km + " km" : ""}</td>
      <td>${rpCell(l)}</td></tr>` : `
      <tr><td><span class="badge b-Z">同城换乘</span></td>
      <td>${esc(l.walk_from)} → ${esc(l.walk_to)}</td><td>—</td>
      <td class="muted">${l.walk_min} 分钟通行</td><td>—</td></tr>`).join("");
    box.innerHTML = head.replace("%T", `
      <table><thead><tr><th>车次/环节</th><th>区间</th><th>时间</th><th>历时</th><th>票价</th></tr></thead>
      <tbody>${rows}</tbody></table>
      <p class="muted">${plan.real_price || plan.legs.some(l => l.real_price) ? "<b style='color:#4ade80'>绿色 = 12306 当日真实票价</b> · " : ""}地图中: 实线=列车区间(按车型着色) · 灰虚线=同城换站 · 点=上下车站</p>`);
  } else if (plan.kind === "flight") {
    box.innerHTML = head.replace("%T", `<table><tbody><tr>
      <td>✈ <b>${esc(plan.flight_no)}</b><span class="muted"> ${esc(plan.airline || "")}${plan.model ? " · " + esc(plan.model) : ""}</span></td>
      <td>${plan.dep ? `<span class="tt-now">${plan.dep} → ${plan.arr}</span><br>` : ""}${esc(plan.src_airport_cn || plan.src_airport)}(${esc(plan.src_iata)}) → ${esc(plan.dst_airport_cn || plan.dst_airport)}(${esc(plan.dst_iata)})</td>
      <td class="muted">飞行 ${plan.ride_fmt}</td><td class="muted">${plan.km} km</td><td>${plan.price_fmt}</td></tr></tbody></table>
      <p class="muted">${plan.dep ? "航班号为真实班次(FP-Dataset 时刻库)" : "时刻为估算"} · 票价为估价 · 地图中: 蓝虚线=直飞航线(大圆示意) · 点=起降机场</p>`);
  } else {
    box.innerHTML = head.replace("%T", `<table><tbody>
      <tr><td>✈ 航班</td><td>${esc(plan.flight.from_city)} → ${esc(plan.flight.to_city)}${plan.flight.from_city === plan.from_city ? "(出发段)" : "(到达段)"}</td>
      <td class="muted">飞行 ${fmtDur(plan.flight.duration)}</td><td>—</td>
      <td>${plan.flight.price ? "¥" + plan.flight.price : "—"}</td></tr>
      <tr><td>🚄 铁路</td><td>${badge(plan.rail.type)}<a class="link" href="#/train/${plan.rail.train_id}">${esc(plan.rail.code)}</a> ${esc(plan.rail.from_city)} → ${esc(plan.rail.to_city)}</td>
      <td class="muted">车上 ${fmtDur(plan.rail.ride)}</td><td>—</td>
      <td>${plan.rail.price ? "¥" + plan.rail.price : "—"}</td></tr></tbody></table>
      <p class="muted">地图中: 蓝虚线=飞行段 · 橙虚线=铁路段(示意) · 点=城市代表站</p>`);
  }
}

function drawPlanRoute(plan, byName) {
  if (_routeLayer) { _lmap.removeLayer(_routeLayer); }
  _routeLayer = L.layerGroup();
  const bounds = [];
  const segs = [];
  const addLL = ll => { bounds.push(ll); return ll; };
  if (plan.kind === "train") {
    plan.legs.forEach((l, i) => {
      if (l.kind === "train") {
        const latlngs = (l.path || []).map(p => gcj([p[0], p[1]])).filter(Boolean).map(addLL);
        if (latlngs.length >= 2) {
          L.polyline(latlngs, { color: PLAN_COLOR[l.type] || "#fe295f", weight: 5, opacity: 0.9 })
            .bindTooltip(`${l.code} ${l.board} → ${l.alight}`)
            .addTo(_routeLayer);
          segs.push(`<span style="color:${PLAN_COLOR[l.type]}">━</span> ${badge(l.type)}${esc(l.code)} ${esc(l.board)} → ${esc(l.alight)} <span class="muted">${l.dep}–${l.arr}</span>`);
          [l.board, l.alight].forEach(nm => {
            const s = byName[nm];
            const pt = s && gcj([s.lng, s.lat]);
            if (pt) L.circleMarker(pt, { radius: 6, color: "#fff", weight: 2, fillColor: "#fe295f", fillOpacity: 1 })
              .bindTooltip(nm).addTo(_routeLayer);
          });
        }
      } else {
        const a = byName[l.walk_from], b = byName[l.walk_to];
        const pa = a && gcj([a.lng, a.lat]), pb = b && gcj([b.lng, b.lat]);
        if (pa && pb) {
          L.polyline([addLL(pa), addLL(pb)],
            { color: "#9aa7b8", weight: 3, dashArray: "6 6" })
            .bindTooltip(`同城换乘 ${l.walk_from} → ${l.walk_to}（${l.walk_min} 分钟）`).addTo(_routeLayer);
          segs.push(`<span style="color:#9aa7b8">╌</span> 同城换乘 ${esc(l.walk_from)} → ${esc(l.walk_to)} <span class="muted">${l.walk_min} 分钟</span>`);
        }
      }
    });
  } else if (plan.kind === "flight") {
    const a = gcj(plan.path[0]), b = gcj(plan.path[1]);
    if (a && b) {
      L.polyline([addLL(a), addLL(b)], { color: "#4da3ff", weight: 4, dashArray: "10 6" })
        .bindTooltip(`${plan.flight_no} ${plan.src_airport} → ${plan.dst_airport}`).addTo(_routeLayer);
      [a, b].forEach(p => L.circleMarker(p, { radius: 6, color: "#fff", weight: 2, fillColor: "#4da3ff", fillOpacity: 1 }).addTo(_routeLayer));
    }
    segs.push(`<span style="color:#4da3ff">╌</span> ✈ ${esc(plan.flight_no)} ${esc(plan.src_airport)} → ${esc(plan.dst_airport)} <span class="muted">${plan.ride_fmt}</span>`);
  } else if (plan.kind === "multimodal") {
    const cityPt = c => {
      const s = Object.values(byName).find(x => x.name.includes(c) || (x.stops && false));
      return s ? gcj([s.lng, s.lat]) : null;
    };
    const markName = nm => {
      const s = byName[nm]; const pt = s && gcj([s.lng, s.lat]);
      if (pt) L.circleMarker(pt, { radius: 6, color: "#fff", weight: 2, fillColor: "#ff8a3d", fillOpacity: 1 })
        .bindTooltip(nm).addTo(_routeLayer);
    };
    // 飞行段: 航班两端城市(示意), 两个方向均由字段决定
    const p1 = cityPt(plan.flight.from_city), p2 = cityPt(plan.flight.to_city);
    if (p1 && p2) L.polyline([addLL(p1), addLL(p2)], { color: "#4da3ff", weight: 4, dashArray: "10 6" })
      .bindTooltip(`✈ ${plan.flight.from_city} → ${plan.flight.to_city}（示意）`).addTo(_routeLayer);
    // 铁路段: 有真实路径坐标则实线绘制, 否则城市示意虚线
    const rp = (plan.rail && plan.rail.path) || [];
    const rlat = rp.map(p => gcj([p[0], p[1]])).filter(Boolean).map(addLL);
    const flySeg = `<span style="color:#4da3ff">╌</span> ✈ ${esc(plan.flight.from_city)} → ${esc(plan.flight.to_city)} <span class="muted">示意</span>`;
    const railSeg = `<span style="color:${PLAN_COLOR[plan.rail.type] || "#ff8a3d"}">━</span> ${badge(plan.rail.type)}${esc(plan.rail.code)} ${esc(plan.rail.board || plan.rail.from_city)} → ${esc(plan.rail.alight || plan.rail.to_city || "")}`;
    if (rlat.length >= 2) {
      L.polyline(rlat, { color: PLAN_COLOR[plan.rail.type] || "#ff8a3d", weight: 5, opacity: 0.9 })
        .bindTooltip(`🚄 ${plan.rail.code} ${plan.rail.board || ""} → ${plan.rail.alight || ""}`).addTo(_routeLayer);
      markName(plan.rail.board); markName(plan.rail.alight);
      segs.push(plan.flight.from_city === plan.from_city ? `${flySeg} · ${railSeg}` : `${railSeg} · ${flySeg}`);
    } else {
      const p3 = cityPt(plan.rail.from_city), p4 = cityPt(plan.rail.to_city);
      if (p3 && p4) L.polyline([addLL(p3), addLL(p4)], { color: "#ff8a3d", weight: 4, dashArray: "4 6" })
        .bindTooltip(`🚄 ${plan.rail.code} ${plan.rail.from_city} → ${plan.rail.to_city}（示意）`).addTo(_routeLayer);
      const railSeg2 = `🚄 ${esc(plan.rail.code)} ${esc(plan.rail.from_city)} → ${esc(plan.rail.to_city || "")} <span class="muted">示意</span>`;
      segs.push(plan.flight.from_city === plan.from_city ? `${flySeg} · ${railSeg2}` : `${railSeg2} · ${flySeg}`);
    }
  }
  _routeLayer.addTo(_lmap);
  window._routeLayer = _routeLayer;  // 调试/E2E 用
  if (bounds.length) {
    try { _lmap.fitBounds(L.latLngBounds(bounds).pad(0.15)); }
    catch (e) { console.warn("fitBounds 失败", e); }
  }
}

/* ---------------- 价格日历(跨日期跨方案比价) ---------------- */
async function viewPriceCalendar() {
  if (!_calState) {
    $app.innerHTML = `<div class="detail-panel"><p>请先在「出行方案」填写出发与到达。</p>
      <a class="link" href="#/transfer">去填写 →</a></div>`;
    return;
  }
  $app.innerHTML = `<h2>📅 价格日历 <span class="muted" style="font-size:14px" id="cal-sub"></span></h2>
    <p class="muted" id="cal-note">正在查询 12306 真实票价(首次约需 5-10 秒) · 点选日期查看对比, 再点下方按钮直接查询该日方案</p>
    <div id="cal-grid" class="cal-grid"><div class="loading">查询中…</div></div>
    <div id="cal-detail"></div>`;
  const j = await api(`/api/price_calendar?from=${encodeURIComponent(_calState.f)}&to=${encodeURIComponent(_calState.t)}&days=15`);
  if (!j.ok) { document.getElementById("cal-grid").innerHTML = `<p class="muted">${esc(j.error)}</p>`; return; }
  document.getElementById("cal-sub").textContent = `${j.from_city} → ${j.to_city}`;
  document.getElementById("cal-note").innerHTML =
    (j.train_real ? "🚄 火车为 <b style='color:#4ade80'>12306 真实票价</b>(当日最低基础席别)" : "🚄 火车为估算") +
    " · " +
    (j.flight_real ? "✈ 直飞为 <b style='color:#4ade80'>携程真实最低价</b>" : "✈ 直飞为估算(数据源不可达时回退)") +
    " · 点击日期查看对比";
  const mins = j.days.map(d => d.min);
  const lo = Math.min(...mins), hi = Math.max(...mins);
  const color = v => {
    const t = hi === lo ? 0.5 : (v - lo) / (hi - lo);
    const r = Math.round(40 + 200 * t), g = Math.round(180 - 130 * t), b = 90;
    return `rgba(${r},${g},${b},.30)`;
  };
  document.getElementById("cal-grid").innerHTML = j.days.map(d => `
    <div class="cal-cell" data-d="${d.date}" style="background:${color(d.min)}">
      <div class="cal-date">${d.date.slice(5)} <span class="muted">周${d.weekday}</span></div>
      ${d.train ? `<div class="cal-line">🚄 ¥${d.train}</div>` : ""}
      ${d.flight ? `<div class="cal-line">✈ ¥${d.flight}</div>` : ""}
      ${d.mm ? `<div class="cal-line">✈🚄 ¥${d.mm}</div>` : ""}
    </div>`).join("");
  document.querySelectorAll(".cal-cell").forEach(c => c.onclick = () => {
    const d = j.days.find(x => x.date === c.dataset.d);
    document.getElementById("cal-detail").innerHTML = `<div class="detail-panel" style="margin-top:12px">
      <h3>${d.date} 周${d.weekday} · ${esc(j.from_city)} → ${esc(j.to_city)}</h3>
      <table><tbody>
        ${d.train ? `<tr><td>🚄 火车直达</td><td><b>¥${d.train}</b> 起</td><td class="muted">${j.train_real ? "12306 真实票价" : "二等座估价"}</td></tr>` : ""}
        ${d.flight ? `<tr><td>✈ 直飞</td><td><b>¥${d.flight}</b> 起</td><td class="muted">${j.flight_real ? "携程真实最低价" : "经济舱估价"}</td></tr>` : ""}
        ${d.mm ? `<tr><td>✈🚄 空铁联运</td><td><b>¥${d.mm}</b> 起</td><td class="muted">飞行+铁路合计</td></tr>` : ""}
      </tbody></table>
      <button class="primary" id="cal-go" style="margin-top:10px">按 ${d.date} 查询出行方案 →</button></div>`;
    document.getElementById("cal-go").onclick = () => {
      _calState.date = d.date;          // 带所选日期回方案页
      _pendingAutoQuery = true;         // 回去后自动执行查询
      location.hash = "#/transfer";
    };
  });
}

/* ---------------- 周边数据 ---------------- */
async function viewExplore() {
  const [ap, em, sc] = await Promise.all([api("/api/airports_full?q="), api("/api/emu"), api("/api/scenic")]);
  $app.innerHTML = `
    <h2>✈️ 国内机场（${ap.total}）</h2>
    <div class="toolbar"><input id="apq" placeholder="机场/城市/三字码" size="24">
    <button class="primary" id="apgo">筛选</button>
    <span style="color:var(--muted)">│</span>
    <input id="ff" placeholder="出发城市" size="12"> → <input id="ft" placeholder="到达城市" size="12">
    <button class="primary" id="fgo">查航班</button></div>
    <div id="flights"></div>
    <div id="aplist"></div>
    <h2>🚄 动车组型号（${em.data.length}）</h2><table>
      <thead><tr><th>型号</th><th>别名</th><th>厂商</th><th>最高速度</th><th>编组</th></tr></thead>
      <tbody>${em.data.map(e => `<tr><td><b>${esc(e.model)}</b></td><td>${esc(e.nickname || "-")}</td>
        <td class="muted">${esc(e.manufacturer)}</td><td>${e.max_speed} km/h</td><td class="muted">${esc(e.formation)}</td></tr>`).join("")}</tbody></table>
    <h2>🏔 景点（${sc.data.length}）</h2><table>
      <thead><tr><th>景点</th><th>等级</th><th>城市</th><th>关联车站</th><th>简介</th></tr></thead>
      <tbody>${sc.data.map(s => `<tr><td><b>${esc(s.name)}</b></td><td>${badge(s.level === "5A" ? "Z" : "K")}${esc(s.level)}</td>
        <td class="muted">${esc(s.city)}</td><td>${s.station_name ? `<a class="link" href="#/station/${s.station_id}">${esc(s.station_name)}</a>` : "-"}</td>
        <td class="muted">${esc(s.note || "")}</td></tr>`).join("")}</tbody></table>`;
  const loadAp = async q => {
    const j = await api(`/api/airports_full?q=${encodeURIComponent(q)}`);
    document.getElementById("aplist").innerHTML = `<table>
      <thead><tr><th>IATA</th><th>机场</th><th>城市</th><th>坐标</th></tr></thead>
      <tbody>${j.data.map(a => `<tr><td class="tt-now">${esc(a.iata)}</td><td>${esc(a.name)}</td>
        <td>${esc(a.cn_city || a.city)}</td><td class="muted">${a.lat?.toFixed(2)}, ${a.lon?.toFixed(2)}</td></tr>`).join("")}</tbody></table>`;
  };
  document.getElementById("apgo").onclick = () => loadAp(document.getElementById("apq").value.trim());
  loadAp("");
  document.getElementById("fgo").onclick = async () => {
    const f = document.getElementById("ff").value.trim(), t = document.getElementById("ft").value.trim();
    if (!f || !t) return;
    document.getElementById("flights").innerHTML = '<div class="loading">查询中…</div>';
    const j = await api(`/api/flights?from=${encodeURIComponent(f)}&to=${encodeURIComponent(t)}`);
    document.getElementById("flights").innerHTML = j.plans.length ? `<h3>✈ ${esc(j.from_city)} → ${esc(j.to_city)} 直飞航线</h3><table>
      <thead><tr><th>航线</th><th>航司</th><th>出发机场</th><th>到达机场</th><th>飞行时长</th><th>距离</th><th>参考价</th></tr></thead>
      <tbody>${j.plans.map(p => `<tr><td><b>${esc(p.flight_no)}</b></td><td class="muted">${esc(p.airline)}</td>
        <td>${esc(p.src_airport)}(${p.src_iata})</td><td>${esc(p.dst_airport)}(${p.dst_iata})</td>
        <td>${p.ride_fmt}</td><td class="muted">${p.km} km</td><td>${p.price_fmt}</td></tr>`).join("")}</tbody></table>
      <p class="muted">时刻与票价为估算(OpenFlights 航线库), 启动时自动联网更新</p>`
      : `<p class="muted">无直飞航线(${esc(j.note || "")}), 可在"出行方案"查看空铁联运</p>`;
  };
}

/* ---------------- 路由 ---------------- */
const routes = [
  [/^#\/overview$/, () => viewOverview()],
  [/^#\/stations$/, () => viewStations()],
  [/^#\/station\/(\d+)$/, m => viewStation(+m[1])],
  [/^#\/trains$/, () => viewTrains()],
  [/^#\/train\/(\d+)$/, m => viewTrain(+m[1])],
  [/^#\/lines$/, () => viewLines()],
  [/^#\/line\/(\d+)$/, m => viewLine(+m[1])],
  [/^#\/routemap$/, () => viewRouteMap()],
  [/^#\/calendar$/, () => viewPriceCalendar()],
  [/^#\/schedule$/, () => viewSchedule()],
  [/^#\/transfer$/, () => viewTransfer()],
  [/^#\/explore$/, () => viewExplore()],
];

let _navPrev = null;
async function router() {
  const hash = location.hash || "#/transfer";
  const prev = _navPrev;
  _navPrev = hash;
  for (const [re, fn] of routes) {
    const m = hash.match(re);
    if (m) {
      document.querySelectorAll("nav a").forEach(a =>
        a.classList.toggle("active", hash.startsWith(a.getAttribute("href"))));
      $app.innerHTML = '<div class="loading">加载中…</div>';
      try { await fn(m); } catch (e) {
        $app.innerHTML = `<div class="detail-panel">出错了：${esc(e.message)}</div>`;
      }
      // 全局返回键(主页"出行方案"除外)
      if (hash !== "#/transfer" && prev && prev !== hash) {
        $app.insertAdjacentHTML("afterbegin",
          `<div class="toolbar" style="margin-bottom:10px"><button id="nav-back" class="primary" style="padding:4px 16px">← 返回</button></div>`);
        document.getElementById("nav-back").onclick = () => history.back();
      }
      return;
    }
  }
  location.hash = "#/transfer";
}
window.addEventListener("hashchange", router);
router();

/* ---------------- 数据版本徽章(启动自动更新状态) ---------------- */
(async function badge() {
  const el = document.getElementById("data-badge");
  if (!el) return;
  const load = async () => {
    try {
      const { data } = await api("/api/update_status");
      const st = data.update_status;
      el.innerHTML = `车次 ${esc(data.train_data_date || "?")} · 航班 ${esc(data.flights_updated || "?")}
        ${st === "checking" ? " · <span class='badge b-C'>更新中…</span>" : " · <a class='link' href='#' id='ck-upd'>检查更新</a>"}`;
      const btn = document.getElementById("ck-upd");
      if (btn) btn.onclick = async e => {
        e.preventDefault();
        await fetch("/api/update_check", { method: "POST" });
        el.innerHTML = "<span class='badge b-C'>更新中…</span>";
        setTimeout(() => load(), 3000);
      };
    } catch { el.textContent = ""; }
  };
  load();
})();
