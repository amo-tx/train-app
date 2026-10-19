# -*- coding: utf-8 -*-
"""更新 GitHub release v1.0.1: 删旧附件、改说明、上传新 APK + exe。"""
import json, subprocess, urllib.request, urllib.error, urllib.parse, os

cred = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n",
                      capture_output=True, text=True).stdout
token = [l.split("=", 1)[1] for l in cred.splitlines() if l.startswith("password=")][0]
REL = "https://api.github.com/repos/amo-tx/train-app/releases/417325320"
UP = "https://uploads.github.com/repos/amo-tx/train-app/releases/417325320/assets"

BODY = (
    "## 坐着火车去旅行 v1.0.1\n\n"
    "### 下载\n"
    "| 文件 | 说明 |\n"
    "|---|---|\n"
    "| `TrainApp.apk` | 安卓版（Android 8.0+，约 2MB），安装即用 |\n"
    "| `TrainApp.exe` | Windows 桌面版（约 42MB，免安装，双击运行，浏览器自动打开） |\n\n"
    "### v1.0.1 安卓修复\n"
    "- 修复实时价模块（12306 真实票价 / 携程机票价）加载顺序错误，此前安卓端真实票价从未生效\n"
    "- 12306 查价增加 12 秒总预算，网络不佳时不再长时间阻塞界面\n"
    "- 查询出错时页面直接显示错误信息（页面底部另有红色错误横幅，便于反馈问题）\n\n"
    "### 功能\n"
    "- 全国火车出行方案：直达 / 一次中转 / 两次中转（BFS），9969 车次离线数据\n"
    "- 空铁联运 + 直飞筛选，Leaflet 地图展示方案路线\n"
    "- 12306 真实票价（席别 / 折扣 / 余票）、携程月度最低价、15 天价格日历对比\n\n"
    "若安卓端仍查询不到火车方案，请把页面底部红色横幅里的错误文字反馈给我们，即可精确定位。"
)


def req(url, method="GET", data=None, ctype=None):
    headers = {
        "Authorization": "token " + token,
        "Accept": "application/vnd.github+json",
    }
    if ctype:
        headers["Content-Type"] = ctype
    if data is not None and not isinstance(data, bytes):
        data = json.dumps(data).encode()
        headers.setdefault("Content-Type", "application/json")
    r = urllib.request.Request(url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=600) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")
    except OSError as e:
        # 系统代理 502/连接失败时回退直连
        print("  (代理失败, 直连重试:", e, ")")
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with direct.open(r, timeout=600) as resp:
            return resp.status, json.load(resp)


s, assets = req(REL + "/assets")
print("现有附件:", [(a["name"], a["id"]) for a in assets] if isinstance(assets, list) else assets)
for a in (assets if isinstance(assets, list) else []):
    if a["name"] in ("TrainApp.apk", "TrainApp.exe"):
        s2, d2 = req(REL + "/assets/" + str(a["id"]), "DELETE")
        print("删除旧附件:", a["name"], s2, d2 if s2 != 204 else "")

s, rel = req(REL, "PATCH", {"name": "v1.0.1 修复安卓真实票价与错误提示", "body": BODY})
print("release 说明更新:", s, rel.get("name", ""))

for path, name, label, ctype in [
    ("dist/TrainApp.apk", "TrainApp.apk", "安卓版APK", "application/vnd.android.package-archive"),
    ("dist/TrainApp.exe", "TrainApp.exe", "Windows桌面版", "application/octet-stream"),
]:
    size = os.path.getsize(path)
    q = UP + "?name=" + name + "&label=" + urllib.parse.quote(label)
    with open(path, "rb") as f:
        data = f.read()
    s, d = req(q, "POST", data, ctype)
    tag = "上传成功" if s == 201 else "上传失败(%d)" % s
    print(tag + ":", name, "%.1fMB" % (size / 1048576),
          d.get("browser_download_url") or str(d.get("message", ""))[:200])
