# -*- coding: utf-8 -*-
"""updater.py — 启动时后台自动更新数据库。

1) 车次数据: 检查 HerbertHe/cr-12306-train-info 最新 release (data-YYYYMMDD),
   比本地 meta.data_date 新则下载 6 个车次 JSON 并重新导入。
2) 航班数据: OpenFlights (airports/airlines/routes) 重新下载导入。
全程在守护线程执行, 不阻塞界面; 状态写入 meta 表供 /api/update_status 查询。
"""
import json
import os
import re
import ssl
import threading
import time
import urllib.request

from db import BASE_DIR, DB_PATH, connect

DATA_DIR = os.path.join(BASE_DIR, "data")
TRAIN_RELEASES = "https://github.com/HerbertHe/cr-12306-train-info/releases.atom"
TRAIN_DL = ("https://github.com/HerbertHe/cr-12306-train-info/releases/"
            "download/data-{d}/train_detail_{t}_{d}.json")
TRAIN_TYPES = ["G", "D", "C", "K", "Z", "T"]

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE  # Watt 代理 TLS 环境


def _meta_set(cur, k, v):
    cur.execute("INSERT OR REPLACE INTO meta(k, v) VALUES(?,?)", (k, str(v)))


def _fetch(url, timeout=120, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 TrainApp/1.0"})
    resp = urllib.request.urlopen(req, timeout=timeout, context=_ctx)
    body = resp.read()
    return body if binary else body.decode("utf-8", "replace")


def _latest_train_date():
    """从 releases.atom 解析最新 data-YYYYMMDD。网络不可用返回 None。"""
    text = _fetch(TRAIN_RELEASES, timeout=45)
    dates = [int(d) for d in re.findall(r"data-(\d{8})", text)]
    return max(dates) if dates else None


def _download_trains(date_str):
    """下载某日期的全部车次 JSON, 带重试。返回成功下载的类型列表。"""
    ok = []
    for t in TRAIN_TYPES:
        url = TRAIN_DL.format(d=date_str, t=t)
        path = os.path.join(DATA_DIR, f"train_detail_{t}_{date_str}.json")
        for attempt in range(3):
            try:
                body = _fetch(url, timeout=600, binary=True)
                if len(body) < 1000:
                    raise IOError(f"文件过小({len(body)}B), 可能404页")
                # 验证 JSON 完整性
                json.loads(body)
                open(path, "wb").write(body)
                ok.append(t)
                print(f"[update] {t} {date_str}: {len(body) // 1024} KB")
                break
            except Exception as e:  # noqa: BLE001
                print(f"[update] {t} 第{attempt + 1}次失败: {e}")
                time.sleep(3)
    return ok


def update_all():
    """执行一次完整更新检查。任何失败都不抛出, 状态落 meta。"""
    con = connect()
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    _meta_set(cur, "update_status", "checking")
    _meta_set(cur, "update_time", time.strftime("%Y-%m-%d %H:%M:%S"))
    _meta_set(cur, "update_error", "")
    con.commit()
    cur.close()
    con.close()

    # ---- 1) 车次
    try:
        current = 0
        con = connect()
        r = con.execute("SELECT v FROM meta WHERE k='data_date'").fetchone()
        current = int(r["v"]) if r else 0
        con.close()
        latest = _latest_train_date()
        if latest and latest > current:
            print(f"[update] 车次数据有新版本: {current} -> {latest}, 开始下载")
            got = _download_trains(str(latest))
            if got:
                import import_real
                import_real.import_real(data_date=str(latest))
                # 新补插车站可能缺坐标: 尝试用已有 OSM 数据补齐
                try:
                    import merge_osm
                    if os.path.exists(merge_osm.RAW):
                        merge_osm.main()
                except Exception as e:  # noqa: BLE001
                    print("[update] 坐标补齐跳过:", e)
                _meta_set_ok("train_updated", str(latest))
            else:
                _meta_set_ok("update_error", f"车次 {latest} 下载全部失败, 保留 {current}")
        else:
            print(f"[update] 车次数据已是最新({current}), 无需更新")
            _meta_set_ok("train_checked", str(current))
    except Exception as e:  # noqa: BLE001
        _meta_set_ok("update_error", f"车次更新: {type(e).__name__}: {e}")

    # ---- 2) 航班
    try:
        import import_flights
        if import_flights.update_flights():
            _meta_set_ok("flights_updated", time.strftime("%Y-%m-%d %H:%M"))
    except Exception as e:  # noqa: BLE001
        _meta_set_ok("update_error", f"航班更新: {type(e).__name__}: {e}")

    # ---- 2b) 航班班期库(航线更新后重算, FP-Dataset 走本地缓存)
    try:
        import import_flightnumbers
        import_flightnumbers.build_schedules(redownload=False, use_fp=True)
    except Exception as e:  # noqa: BLE001
        print("[update] 班期重算失败:", e)

    _meta_set_ok("update_status", "idle")
    print("[update] 更新检查完成")


def _meta_set_ok(k, v):
    try:
        con = connect()
        con.execute("INSERT OR REPLACE INTO meta(k, v) VALUES(?,?)", (k, str(v)))
        con.commit()
        con.close()
    except Exception as e:  # noqa: BLE001
        print("[update] meta 写入失败:", e)


def start_background():
    """启动守护线程执行 update_all(进程启动后 3 秒)。"""
    def _run():
        time.sleep(3)
        try:
            update_all()
        except Exception as e:  # noqa: BLE001
            print("[update] 线程异常:", e)
    threading.Thread(target=_run, daemon=True, name="db-updater").start()


if __name__ == "__main__":
    update_all()
