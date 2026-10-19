# 坐着火车去旅行 · 本地数据库版

复刻自微信小程序"坐着火车去旅行"（AppID `wx59621264198bea6e`）的核心数据模型，
完全本地化运行：数据存 SQLite 单文件。

**当前版本**：12306 官方接口口径全量 **G/D/C/K/T/Z** 车次时刻（**9969 车次 / 96395 经停**，
[HerbertHe/cr-12306-train-info](https://github.com/HerbertHe/cr-12306-train-info)）+ 
OpenFlights 国内航班库（**201 机场 / 5696 条国内航线**）+ 车站坐标覆盖 98%（12306 + OSM）。
**启动时后台自动更新**车次与航班数据。

## 安卓版（Android APK）

同一套前端代码（`static/`）原样复用，打包成离线 APK（**2.0 MB**，minSdk 26 / Android 8+）：

```
train-app/
├── android/
│   ├── AndroidManifest.xml      # INTERNET 权限, Material 主题
│   ├── src/.../MainActivity.java  # WebView 宿主 + AndroidHost 原生 HTTP 桥 + 返回键
│   ├── assets/                  # index.html + 前端(app.js 原样) + data.js(预计算路网 6.1MB)
│   │   ├── engine.js            # Python 后端移植: 城市解析/BFS 搜索/航班/联运/价格日历
│   │   ├── realprice.js         # 12306 官方票价查询(经原生桥, 含 Cookie/折扣解析/缓存)
│   │   ├── flightprice.js       # 携程整月最低价(按需查询, WAF 拦截自动回退估算)
│   │   └── apihost.js           # fetch 垫片: /api/* 路由到页内引擎, 前端零改动
│   ├── build_apk.py             # 离线打包流水线(aapt2/javac/d8/zipalign/apksigner, 无 Gradle)
│   └── test/                    # 引擎等价性对照(17 用例 vs Python 后端)
└── dist/TrainApp.apk
```

**架构**：静态路网在构建期由 `export_data.py` 从 `train.db` 预计算为 `data.js`
（9969 车次 / 96395 停站的图结构），页内 JS 引擎毫秒级响应查询；12306/携程实时
查价走 `AndroidHost.httpGet` 原生桥（可设 Cookie/Referer 头，无 CORS 限制）。
构建与等价性验证：

```bash
python export_data.py            # train.db -> android/assets/data.js
python android/test/compare_py.py  # 17 用例对照 Python 后端(键集合/方案序列/计数)
python android/build_apk.py        # 打包 -> dist/TrainApp.apk(需 platform-34 + build-tools r34)
```

## 快速开始

```bash
# A. 单文件 exe（无需 Python, 原生桌面窗口不依赖浏览器）
dist/TrainApp.exe
#   默认: WebView2 桌面窗口(1280x860); 关窗即退出
#   --web      浏览器 + 系统托盘模式
#   --no-tray  浏览器模式(无托盘)
#   首次运行自动释放数据库到 exe 旁 data/; 启动后台线程自动更新车次/航班数据

# B. 源码运行
python main.py            # 桌面窗口(需 venv 中 pywebview), 失败自动回退浏览器
python main.py --web      # 浏览器 + 托盘
python main.py --no-tray  # 浏览器(无托盘)

# C. 重新打包 exe（需 PyInstaller + pywebview + pystray + Pillow）
pyinstaller --onefile --windowed --name TrainApp --icon assets/icon.ico ^
  --add-data "static;static" --add-data "data/train.db;data" --add-data "assets/icon.ico;assets" ^
  --hidden-import pystray._win32 --hidden-import webview.platforms.winforms --collect-submodules webview main.py
```

## 架构

```
train-app/
├── main.py             # 入口: http.server + REST API + 桌面窗口(WebView2) + 托盘
├── db.py               # 建表/种子(12306 车站表 + 生成线路)
├── journey.py          # 出行方案引擎: 城市解析 + 多次中转BFS + 票价/里程估算 + 路径坐标
├── api_journey_v2.py   # /api/plan /api/journey /api/flights /api/update_status 等
├── import_real.py      # 车次数据导入(支持指定 release 日期, 供自动更新调用)
├── import_flights.py   # OpenFlights 机场/航线导入(估算时长/票价)
├── updater.py          # 启动自动更新: 车次新 release 检测下载 + 航班数据刷新
├── import_coords.py / merge_osm.py   # 车站坐标导入/OSM 补齐
├── make_icon.py        # 托盘图标生成
├── data/               # train.db + 车次 JSON + OpenFlights dat + OSM 坐标
├── static/             # 前端 SPA: Leaflet+高德瓦片地图 / ECharts 离线轮廓 / 原生 JS
└── dist/TrainApp.exe   # 单文件可执行程序
```

## 功能（对应原小程序页面）

| 模块 | 原 小程序页面 | 本版实现 |
|---|---|---|
| 数据概览 | main | 统计卡片（含数据来源与更新状态徽章） |
| 车站检索/详情 | station | 站名/全拼/简拼/城市搜索 + 详情 + 经停车次 |
| 车次检索/详情 | train / panorama | 车次列表 + 全程经停时刻表（真实 12306 时刻） |
| 线路 | line / heat_map | 线路走向 + 车站序列 |
| 时刻表查询 | schedule | 某站 N 点之后到发车次 |
| **出行方案** | transfer | **城市/车站模糊输入**（输入"北京"即得全城 65 站间方案）· **直达 + 中转×1 + 中转×2** 时间依赖 BFS · 同城异站换乘（默认 45 分钟通行） · **直飞航班** · **空铁联运**（无直飞时经枢纽 飞行+铁路） · **按总耗时/乘车时间/价格(低→高/高→低)排序** · 点击方案在地图绘制全程走向 |
| **地图** | map / heat_map | **Leaflet + 高德瓦片全信息量地图**（完整路网/地名/省界，标准+卫星切换，WGS→GCJ 纠偏）：铁路线着色、3392 站散点、主要站高亮；方案路径绘制（车次实线按车型着色/同城换乘虚线/航班蓝色虚线/联运示意）；另有 ECharts 离线轮廓模式兜底 |
| 机场/航班/动车组/景点 | airport / emu / scenic_spot | 全量国内机场（中文名映射）+ 城市对直飞航线查询 |
| 数据更新 | downloader | **启动自动更新**（后台线程）：车次检测 cr-12306 最新 release 自动下载导入；航班数据定期重取；头部徽章显示版本并可手动"检查更新" |

## 票价与时长估算口径（诚实声明）

- **火车票价**：数据集不含票价，按"坐标球面距离 × 绕行系数(G/D/C 1.25, K/T/Z 1.2) × 车型费率(G 0.45 / C 0.40 / D 0.31 / K·T 0.16 / Z 0.18 元/km)"估算，界面标注"约 ¥"
- **航班**：OpenFlights 航线无时刻与票价，飞行时长 = 35min 起降 + 距离/780km/h，票价 = 0.58 元/km（下限 280 元）；总耗时已含往返机场约 2.5 小时缓冲
- **空铁联运**：出发城市无直飞航线时自动生成"飞枢纽 + 高铁到目的地"方案（中转缓冲 2.25 小时），铁路段取真实最快直达车

## API 一览

```
GET  /api/summary                        统计(含数据来源)
GET  /api/stations?q=&page=&size=        车站搜索
GET  /api/stations/{id}                  车站详情(线路/景点)
GET  /api/stations/{id}/trains           经停车次
GET  /api/trains?q=&type=                车次搜索
GET  /api/trains/{id}                    车次详情(全程时刻)
GET  /api/lines  /api/lines/{id}         线路
GET  /api/map                            地图数据(有坐标车站+线路走向)
GET  /api/schedule?station_id=&after=    时刻表查询
GET  /api/journey?from=&to=&after=&max_legs=&max_wait=
                                         火车出行方案(模糊城市/车站, 中转×0/1/2)
GET  /api/plan?...                       综合方案(火车+直飞+空铁联运)
GET  /api/flights?from=&to=              城市对直飞航线
GET  /api/airports_full?q=               全量国内机场
GET  /api/update_status                  数据版本与更新状态
POST /api/update_check                   手动触发更新检查
GET  /api/transfer?from=&to=             仅直达(兼容保留)
GET  /api/airports  /api/emu  /api/scenic
POST /api/import  {"table": "...", "rows": [...]}   JSON 导入
```

## 已知边界

- 车次数据覆盖 G/D/C/K/T/Z（数据源口径）；Y/S 市域列车未导入
- 车站坐标覆盖 98%：境外站、香港西九龙等 52 站无坐标，不显示在地图
- 火车票价与航班时刻均为估算（界面已标注）；真实票价以 12306/航司为准
- 地图高德瓦片需联网；断网时可切换"离线轮廓模式"（ECharts）
- 同城换乘按 12306 车站表 `city` 字段分组，跨站通行默认 45 分钟（`min_transfer_city` 可调）
