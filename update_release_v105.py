# -*- coding: utf-8 -*-
"""update_release_v105.py — 发布 GitHub release v1.0.5（新建 tag + 上传 APK/exe）。"""
import json, subprocess, urllib.request, urllib.error, urllib.parse, os, sys

cred = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n",
                      capture_output=True, text=True).stdout
token = [l.split("=", 1)[1] for l in cred.splitlines() if l.startswith("password=")][0]
API = "https://api.github.com/repos/amo-tx/train-app"

BODY = (
    "## 坐着火车去旅行 v1.0.5\n\n"
    "### 下载\n"
    "| 文件 | 说明 |\n"
    "|---|---|\n"
    "| `TrainApp.apk` | 安卓版（Android 8.0+，约 2MB），安装即用 |\n"
    "| `TrainApp.exe` | Windows 桌面版（约 42MB，免安装，双击运行，浏览器自动打开） |\n\n"
    "### v1.0.5 修复\n"
    "- **时刻表最多显示 50 条** → 放宽到 500 条，并显示全日实际趟数"
    "（如北京南 0 点后全日 468 趟此前只能看到 50 趟）\n"
    "- **车次累计里程全为 0**：库内车次/停站里程字段是空的，"
    "已按「球面距离×绕行系数」重建全部 9969 趟车的逐站累计里程与总里程"
    "（G1 北京南→上海虹桥 1470km，与实际一致）；直达查询区间里程同步修复\n"
    "- 线路详情中 12 条缺失站点里程的线路已按官方线长归一补齐\n\n"
    "### v1.0.4 修复\n"
    "- 修复火车中转方案总价显示 \"—\"（52 站缺坐标致里程断链，波及 523 趟车）\n\n"
    "### 功能\n"
    "- 全国火车出行方案：直达 / 一次中转 / 两次中转（BFS），9969 车次离线数据\n"
    "- 空铁联运（先飞后铁 / 先铁后飞）+ 直飞筛选，Leaflet 地图展示方案路线\n"
    "- 12306 真实票价（席别 / 折扣 / 余票）、携程月度最低价、15 天价格日历对比\n"
)


def req(url, method="GET", data=None, ctype=None):
    headers = {"Authorization": "token " + token,
               "Accept": "application/vnd.github+json"}
    if ctype:
        headers["Content-Type"] = ctype
    if data is not None and not isinstance(data, bytes):
        data = json.dumps(data).encode()
        headers.setdefault("Content-Type", "application/json")
    r = urllib.request.Request(url, method=method, data=data, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(r, timeout=600) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode() or "{}"
            if e.code >= 500 or attempt < 2:
                import time
                time.sleep(2 * (attempt + 1))
                continue
            return e.code, json.loads(body)
        except OSError as e:
            print("  (代理失败, 直连重试:", e, ")")
            direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with direct.open(r, timeout=600) as resp:
                return resp.status, json.load(resp)
    return 0, {}


def main():
    s, rels = req(API + "/releases?per_page=20")
    for rel in (rels if isinstance(rels, list) else []):
        if rel.get("tag_name") == "v1.0.5":
            s2, _ = req(API + "/releases/" + str(rel["id"]), "DELETE")
            print("删除旧 v1.0.5 release:", s2)
    s, refs = req(API + "/git/ref/tags/v1.0.5")
    if s == 200:
        s2, _ = req(API + "/git/refs/tags/v1.0.5", "DELETE")
        print("删除旧 tag:", s2)

    s, rel = req(API + "/releases", "POST", {
        "tag_name": "v1.0.5", "target_commitish": "main",
        "name": "v1.0.5 时刻表放宽 + 车次里程修复",
        "body": BODY, "draft": False, "prerelease": False})
    if s != 201:
        print("创建 release 失败:", s, rel)
        return 1
    rid = rel["id"]
    print("release v1.0.5 已创建, id =", rid)

    base = os.path.dirname(os.path.abspath(__file__))
    ok = True
    for path, name, label, ctype in [
        (os.path.join(base, "dist", "TrainApp.apk"), "TrainApp.apk",
         "安卓版APK", "application/vnd.android.package-archive"),
        (os.path.join(base, "dist", "TrainApp.exe"), "TrainApp.exe",
         "Windows桌面版", "application/octet-stream"),
    ]:
        q = ("https://uploads.github.com/repos/amo-tx/train-app/releases/%d/assets"
             "?name=%s&label=%s" % (rid, name, urllib.parse.quote(label)))
        with open(path, "rb") as f:
            data = f.read()
        s2, d2 = req(q, "POST", data, ctype)
        good = s2 == 201
        ok = ok and good
        print("上传" + ("成功" if good else "失败(%d)" % s2) + ":", name,
              "%.1fMB" % (len(data) / 1048576),
              d2.get("browser_download_url") or str(d2.get("message", ""))[:200])
    print("下载页:", rel.get("html_url", ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
