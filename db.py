# -*- coding: utf-8 -*-
"""db.py — 本地数据库层：建库、建表、种子数据导入。

复刻"坐着火车去旅行"的数据模型（车站/车次/经停/线路/机场/动车组/景点），
数据落 SQLite 单文件 data/train.db。
"""
import json
import os
import random
import re
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "train.db")
STATION_JS = os.path.join(BASE_DIR, "data", "station_name.js")

# 打包(frozen)模式: 可写数据放 exe 旁, 只读资源在 _MEIPASS
if getattr(sys, "frozen", False):
    RESOURCE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    DB_PATH = os.path.join(BASE_DIR, "data", "train.db")
    STATION_JS = os.path.join(RESOURCE_DIR, "data", "station_name.js")

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS stations (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    telecode    TEXT NOT NULL,
    pinyin_full TEXT NOT NULL,
    pinyin_abbr TEXT NOT NULL,
    city        TEXT NOT NULL,
    is_major    INTEGER NOT NULL DEFAULT 0,
    lng         REAL,                   -- WGS84 经度(地图用, 可空)
    lat         REAL                    -- WGS84 纬度
);

CREATE TABLE IF NOT EXISTS lines (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,
    category  TEXT NOT NULL,            -- 高铁/普速/城际
    mileage   INTEGER NOT NULL,
    speed_limit INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS line_stations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    line_id    INTEGER NOT NULL REFERENCES lines(id),
    station_id INTEGER NOT NULL REFERENCES stations(id),
    seq        INTEGER NOT NULL,
    mileage    INTEGER NOT NULL,
    UNIQUE(line_id, seq),
    UNIQUE(line_id, station_id)
);

CREATE TABLE IF NOT EXISTS trains (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,   -- 车次号, 如 G101
    type        TEXT NOT NULL,          -- G/D/C/K/T/Z
    line_id     INTEGER REFERENCES lines(id),
    start_station_id INTEGER NOT NULL REFERENCES stations(id),
    end_station_id   INTEGER NOT NULL REFERENCES stations(id),
    depart_time INTEGER NOT NULL,       -- 始发 分钟数(0-1439)
    arrive_time INTEGER NOT NULL,       -- 终到 分钟数, 可>1439 表示跨天
    mileage     INTEGER NOT NULL,
    emu_model   TEXT                    -- 担当车型
);

CREATE TABLE IF NOT EXISTS train_stops (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    train_id     INTEGER NOT NULL REFERENCES trains(id),
    station_id   INTEGER NOT NULL REFERENCES stations(id),
    seq          INTEGER NOT NULL,
    arrive_min   INTEGER,               -- 距始发累计分钟; 始发站为 NULL
    depart_min   INTEGER,               -- 终到站为 NULL
    stop_minutes INTEGER NOT NULL DEFAULT 2,
    mileage      INTEGER NOT NULL,
    UNIQUE(train_id, seq)
);

CREATE TABLE IF NOT EXISTS airports (
    id    INTEGER PRIMARY KEY,
    iata  TEXT NOT NULL UNIQUE,
    name  TEXT NOT NULL,
    city  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS emu_models (
    id            INTEGER PRIMARY KEY,
    model         TEXT NOT NULL UNIQUE, -- 型号, 如 CR400AF
    nickname      TEXT,                 -- 别名, 如 复兴号
    manufacturer  TEXT NOT NULL,
    max_speed     INTEGER NOT NULL,
    formation     TEXT NOT NULL         -- 编组
);

CREATE TABLE IF NOT EXISTS scenic_spots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    city       TEXT NOT NULL,
    level      TEXT NOT NULL,           -- 5A/4A/...
    station_id INTEGER REFERENCES stations(id),
    note       TEXT
);

CREATE INDEX IF NOT EXISTS idx_ts_station ON train_stops(station_id);
CREATE INDEX IF NOT EXISTS idx_ts_train   ON train_stops(train_id);
CREATE INDEX IF NOT EXISTS idx_train_code ON trains(code);
CREATE INDEX IF NOT EXISTS idx_st_city    ON stations(city);
CREATE INDEX IF NOT EXISTS idx_st_name    ON stations(name);
"""

# ---------------------------------------------------------------- 种子数据
# 主要城市(直辖市/省会/计划单列市) => 该城市主要站名候选
MAJOR_CITIES = {
    "北京": ["北京", "北京南", "北京西", "北京北", "北京朝阳", "北京丰台"],
    "上海": ["上海", "上海虹桥", "上海南", "上海西"],
    "广州": ["广州", "广州南", "广州东", "广州北"],
    "深圳": ["深圳", "深圳北", "深圳东", "福田", "深圳坪山"],
    "天津": ["天津", "天津西", "天津南", "天津北"],
    "重庆": ["重庆北", "重庆西", "沙坪坝"],
    "成都": ["成都", "成都东", "成都南", "成都西"],
    "武汉": ["武汉", "汉口", "武昌", "武汉站"],
    "杭州": ["杭州", "杭州东", "杭州南", "杭州西"],
    "南京": ["南京", "南京南", "南京西"],
    "西安": ["西安", "西安北", "西安南"],
    "郑州": ["郑州", "郑州东", "郑州南"],
    "长沙": ["长沙", "长沙南"],
    "沈阳": ["沈阳", "沈阳北", "沈阳南"],
    "哈尔滨": ["哈尔滨", "哈尔滨西", "哈尔滨北"],
    "青岛": ["青岛", "青岛北", "青岛西"],
    "济南": ["济南", "济南西", "济南东"],
    "厦门": ["厦门", "厦门北"],
    "福州": ["福州", "福州南"],
    "昆明": ["昆明", "昆明南"],
    "贵阳": ["贵阳", "贵阳北", "贵阳东"],
    "南宁": ["南宁", "南宁东"],
    "兰州": ["兰州", "兰州西"],
    "乌鲁木齐": ["乌鲁木齐", "乌鲁木齐南"],
    "太原": ["太原", "太原南"],
    "石家庄": ["石家庄", "石家庄北"],
    "合肥": ["合肥", "合肥南"],
    "南昌": ["南昌", "南昌西"],
    "长春": ["长春", "长春西"],
    "大连": ["大连", "大连北", "大连南"],
    "宁波": ["宁波", "宁波东"],
    "苏州": ["苏州", "苏州北", "苏州园区"],
    "无锡": ["无锡", "无锡东"],
    "常州": ["常州", "常州北"],
    "徐州": ["徐州", "徐州东"],
    "温州": ["温州南", "温州"],
    "珠海": ["珠海", "珠海北"],
    "汕头": ["汕头", "汕头南"],
    "洛阳": ["洛阳", "洛阳龙门"],
    "襄阳": ["襄阳", "襄阳东"],
    "宜昌": ["宜昌东", "宜昌"],
    "桂林": ["桂林", "桂林北", "桂林西"],
    "柳州": ["柳州"],
    "济南2": [], "呼和浩特": ["呼和浩特", "呼和浩特东"],
    "银川": ["银川"],
    "西宁": ["西宁"],
    "拉萨": ["拉萨"],
    "香港": ["香港西九龙"],
    "高雄": [],
}

# 真实感线路: (名称, 类别, 里程, 限速, 途径城市序列)
LINES = [
    ("京沪高速铁路", "高铁", 1318, 350, ["北京南", "天津南", "沧州西", "济南西", "徐州东", "南京南", "苏州北", "上海虹桥"]),
    ("京广高速铁路", "高铁", 2298, 350, ["北京西", "石家庄", "郑州东", "武汉", "长沙南", "广州南"]),
    ("沪昆高速铁路", "高铁", 2252, 350, ["上海虹桥", "杭州东", "南昌西", "长沙南", "贵阳北", "昆明南"]),
    ("京哈高速铁路", "高铁", 1198, 350, ["北京朝阳", "沈阳北", "长春西", "哈尔滨西"]),
    ("贵广高速铁路", "高铁", 857, 250, ["贵阳北", "桂林西", "肇庆东", "广州南"]),
    ("兰新高速铁路", "高铁", 1776, 250, ["兰州西", "西宁", "乌鲁木齐"]),
    ("成渝高速铁路", "高铁", 308, 350, ["成都东", "资阳北", "沙坪坝"]),
    ("京津城际铁路", "城际", 120, 350, ["北京南", "天津"]),
    ("沪宁城际铁路", "城际", 301, 350, ["上海", "苏州", "无锡", "常州", "南京"]),
    ("胶济客运专线", "普速", 363, 250, ["济南", "淄博", "潍坊", "青岛"]),
    ("西成高速铁路", "高铁", 658, 250, ["西安北", "汉中", "广元", "成都东"]),
    ("杭深铁路", "高铁", 1450, 250, ["杭州东", "宁波", "温州南", "福州", "厦门北", "深圳北"]),
]

# 真实动车组型号
EMU_LIST = [
    ("CR400AF", "复兴号", "中车青岛四方", 350, "8编(4M4T)"),
    ("CR400BF", "复兴号", "中车长客", 350, "8编(4M4T)"),
    ("CR400AF-B", "复兴号", "中车青岛四方", 350, "16编长编组"),
    ("CR300AF", "复兴号", "中车青岛四方", 250, "8编"),
    ("CR300BF", "复兴号", "中车长客", 250, "8编"),
    ("CRH380A", "和谐号", "中车青岛四方", 380, "8编(6M2T)"),
    ("CRH380B", "和谐号", "中车长客", 380, "8编"),
    ("CRH2A", "和谐号", "中车青岛四方", 250, "8编(4M4T)"),
    ("CRH6A", "城际之星", "中车青岛四方", 200, "4编/8编"),
    ("CRH5A", "和谐号", "长客庞巴迪", 250, "8编"),
]

AIRPORTS = [
    ("PEK", "北京首都国际机场", "北京"), ("PKX", "北京大兴国际机场", "北京"),
    ("SHA", "上海虹桥国际机场", "上海"), ("PVG", "上海浦东国际机场", "上海"),
    ("CAN", "广州白云国际机场", "广州"), ("SZX", "深圳宝安国际机场", "深圳"),
    ("CTU", "成都天府国际机场", "成都"), ("TFU", "成都双流国际机场", "成都"),
    ("HGH", "杭州萧山国际机场", "杭州"), ("NKG", "南京禄口国际机场", "南京"),
    ("XIY", "西安咸阳国际机场", "西安"), ("CGO", "郑州新郑国际机场", "郑州"),
    ("CSX", "长沙黄花国际机场", "长沙"), ("WUH", "武汉天河国际机场", "武汉"),
    ("TAO", "青岛胶东国际机场", "青岛"), ("TNA", "济南遥墙国际机场", "济南"),
    ("SYX", "三亚凤凰国际机场", "三亚"), ("HAK", "海口美兰国际机场", "海口"),
    ("KMG", "昆明长水国际机场", "昆明"), ("HRB", "哈尔滨太平国际机场", "哈尔滨"),
]

# 跨线直通车(真实存在): (车次, 类型, [(站名, 累计里程)...])
THROUGH_TRAINS = [
    ("G205", "G", [("北京南", 0), ("沧州西", 219), ("济南", 405), ("淄博", 498),
                   ("潍坊", 578), ("青岛北", 790), ("青岛", 819)]),
    ("G206", "G", [("青岛", 0), ("青岛北", 29), ("潍坊", 241), ("淄博", 321),
                   ("济南", 414), ("沧州西", 600), ("北京南", 819)]),
    ("G207", "G", [("上海虹桥", 0), ("苏州北", 85), ("南京南", 295), ("徐州东", 626),
                   ("济南", 873), ("青岛北", 1258), ("青岛", 1287)]),
]

# 景点(挂到对应车站): (名称, 城市, 等级, 车站名, 简介)
SCENIC = [
    ("故宫博物院", "北京", "5A", "北京", "明清两代皇宫, 世界文化遗产"),
    ("八达岭长城", "北京", "5A", "北京北", "明长城保存最好的一段"),
    ("外滩", "上海", "4A", "上海", "万国建筑博览群"),
    ("豫园", "上海", "4A", "上海", "明代江南古典园林"),
    ("广州塔", "广州", "4A", "广州", "昵称小蛮腰, 城市地标"),
    ("西湖", "杭州", "5A", "杭州东", "世界文化遗产, 人间天堂"),
    ("夫子庙", "南京", "5A", "南京南", "秦淮河畔历史文化街区"),
    ("兵马俑", "西安", "5A", "西安北", "秦始皇陵陪葬坑"),
    ("少林寺", "郑州", "5A", "郑州", "禅宗祖庭, 天下第一名刹"),
    ("橘子洲", "长沙", "5A", "长沙南", "湘江中沙洲, 青年毛泽东艺术雕塑"),
    ("黄鹤楼", "武汉", "5A", "武昌", "江南三大名楼之一"),
    ("栈桥", "青岛", "4A", "青岛", "青岛百年地标"),
    ("崂山", "青岛", "5A", "青岛北", "海上第一名山"),
    ("趵突泉", "济南", "5A", "济南", "天下第一泉"),
    ("鼓浪屿", "厦门", "5A", "厦门", "世界文化遗产, 音乐之岛"),
    ("滇池", "昆明", "4A", "昆明南", "高原明珠"),
    ("黄果树瀑布", "贵阳", "5A", "贵阳北", "亚洲第一大瀑布"),
    ("漓江", "桂林", "5A", "桂林北", "山水甲天下"),
    ("青城山", "成都", "5A", "成都", "道教名山"),
    ("三峡大坝", "宜昌", "5A", "宜昌东", "世界最大水利枢纽"),
]


def _parse_station_js():
    """解析 12306 station_name.js。
    每段格式: @简拼|站名|电报码|全拼|首字母|序号|局码|城市|...
    """
    if not os.path.exists(STATION_JS):
        return []
    text = open(STATION_JS, encoding="utf-8").read()
    m = re.search(r"'([^']*)'", text)
    if not m:
        return []
    out = []
    for seg in m.group(1).split("@"):
        parts = seg.split("|")
        if len(parts) >= 8 and parts[1]:
            out.append({
                "name": parts[1],
                "telecode": parts[2],
                "pinyin_full": parts[3],
                "pinyin_abbr": parts[0],
                "city": parts[7] if parts[7] else parts[1],
            })
    return out


def _station_id_by_name(cur, name):
    row = cur.execute("SELECT id FROM stations WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def _hhmm_to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _gen_times(mileages, depart0, avg_speed):
    """按里程序列生成 (arrive_min, depart_min) 时刻列表。"""
    times = [(None, depart0)]
    t = depart0
    for j in range(len(mileages) - 1):
        run = round((mileages[j + 1] - mileages[j]) / avg_speed * 60) + 2
        t += run
        arrive = t
        stop = 2 if j < len(mileages) - 2 else 0
        t += stop
        times.append((arrive, t if stop else None))
    return times


def _write_train(cur, code, ttype, lid, sids, mileages, depart0, avg_speed, emu, total):
    times = _gen_times(mileages, depart0, avg_speed)
    cur.execute(
        "INSERT INTO trains(code, type, line_id, start_station_id, end_station_id, "
        "depart_time, arrive_time, mileage, emu_model) VALUES(?,?,?,?,?,?,?,?,?)",
        (code, ttype, lid, sids[0], sids[-1], depart0, times[-1][0], total, emu))
    tid = cur.lastrowid
    for seq, (sid, (am, dm)) in enumerate(zip(sids, times)):
        cur.execute(
            "INSERT INTO train_stops(train_id, station_id, seq, arrive_min, depart_min, "
            "stop_minutes, mileage) VALUES(?,?,?,?,?,?,?)",
            (tid, sid, seq, am, dm, 2 if seq not in (0, len(sids) - 1) else 0, mileages[seq]))
    return tid


def seed(force=False):
    if os.path.exists(DB_PATH) and not force:
        print("[skip] 数据库已存在:", DB_PATH)
        return
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    cur = con.cursor()

    # 1) 车站(真实 12306 数据)
    stations = _parse_station_js()
    if not stations:
        sys.exit("[fatal] 未找到车站数据, 请先获取 data/station_name.js")
    major_names = {n for cands in MAJOR_CITIES.values() for n in cands}
    for st in stations:
        cur.execute(
            "INSERT INTO stations(name, telecode, pinyin_full, pinyin_abbr, city, is_major) "
            "VALUES(?,?,?,?,?,?)",
            (st["name"], st["telecode"], st["pinyin_full"], st["pinyin_abbr"],
             st["city"], 1 if st["name"] in major_names else 0))
    print(f"[seed] 车站 {len(stations)} 站(真实12306数据)")

    # 2) 线路 + 线路车站
    rng = random.Random(2026)
    line_ids = {}
    for lname, cat, mileage, speed, city_names in LINES:
        cur.execute("INSERT INTO lines(name, category, mileage, speed_limit) VALUES(?,?,?,?)",
                    (lname, cat, mileage, speed))
        lid = cur.lastrowid
        line_ids[lname] = lid
        ids, used = [], []
        for cn in city_names:
            sid = _station_id_by_name(cur, cn)
            if sid and sid not in used:
                used.append(sid)
                ids.append(sid)
            elif sid is None:
                print(f"[warn] 线路 {lname} 缺站: {cn}")
        n = len(ids)
        for seq, sid in enumerate(ids):
            seg = round(mileage / max(n - 1, 1) * seq)
            cur.execute("INSERT INTO line_stations(line_id, station_id, seq, mileage) VALUES(?,?,?,?)",
                        (lid, sid, seq, seg))
    print(f"[seed] 线路 {len(LINES)} 条")

    # 3) 动车组 / 机场 / 景点
    cur.executemany("INSERT INTO emu_models(model, nickname, manufacturer, max_speed, formation) VALUES(?,?,?,?,?)",
                    EMU_LIST)
    cur.executemany("INSERT INTO airports(iata, name, city) VALUES(?,?,?)", AIRPORTS)
    for name, city, level, sname, note in SCENIC:
        sid = _station_id_by_name(cur, sname)
        cur.execute("INSERT INTO scenic_spots(name, city, level, station_id, note) VALUES(?,?,?,?,?)",
                    (name, city, level, sid, note))
    print(f"[seed] 机场 {len(AIRPORTS)} / 动车组 {len(EMU_LIST)} / 景点 {len(SCENIC)}")

    # 4) 车次 + 经停时刻(按线路生成, 时刻为模拟数据)
    type_by_cat = {"高铁": "G", "城际": "C", "普速": "D"}
    n_trains = 0
    for lname, cat, mileage, speed, city_names in LINES:
        lid = line_ids[lname]
        rows = cur.execute(
            "SELECT ls.seq, s.id, s.name FROM line_stations ls JOIN stations s ON s.id=ls.station_id "
            "WHERE ls.line_id=? ORDER BY ls.seq", (lid,)).fetchall()
        if len(rows) < 2:
            continue
        n_stop_trains = 6 if cat == "高铁" else 4
        # 车型按线路限速筛选(真实性: 350 专线不会配 200km/h 车型)
        emu_pool = [e[0] for e in EMU_LIST if e[3] >= speed]
        for i in range(n_stop_trains):
            ttype = type_by_cat[cat] if cat != "普速" else rng.choice(["D", "K"])
            code = f"{ttype}{100 + i * 2 + rng.randint(0, 8)}"
            if cur.execute("SELECT 1 FROM trains WHERE code=?", (code,)).fetchone():
                continue  # 车次号冲突则跳过
            sids = [r[1] for r in rows]
            mileages = [round(mileage / (len(rows) - 1) * r[0]) for r in rows]
            depart0 = rng.randint(6 * 60, 21 * 60)
            avg_speed = speed * (0.72 if cat != "城际" else 0.8)  # 含停站折算
            emu = rng.choice(emu_pool) if ttype in "GDC" else None
            _write_train(cur, code, ttype, lid, sids, mileages,
                         depart0, avg_speed, emu, mileage)
            n_trains += 1

    # 4b) 跨线直通车
    for code, ttype, route in THROUGH_TRAINS:
        if cur.execute("SELECT 1 FROM trains WHERE code=?", (code,)).fetchone():
            continue
        sids = [_station_id_by_name(cur, n) for n, _ in route]
        if None in sids:
            print(f"[warn] 直通车 {code} 缺站, 跳过")
            continue
        mileages = [m for _, m in route]
        _write_train(cur, code, ttype, None, sids, mileages,
                     rng.randint(7 * 60, 19 * 60), 350 * 0.78,
                     "CR400AF", mileages[-1])
        n_trains += 1
    print(f"[seed] 车次 {n_trains} 趟 + 经停记录")
    con.commit()
    counts = {t: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("stations", "lines", "line_stations", "trains", "train_stops",
                        "airports", "emu_models", "scenic_spots")}
    con.close()
    print("[seed] 完成:", json.dumps(counts, ensure_ascii=False))


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


if __name__ == "__main__":
    seed(force="--force" in sys.argv)
