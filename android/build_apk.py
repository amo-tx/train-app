# -*- coding: utf-8 -*-
"""build_apk.py — 离线打包安卓 APK(不依赖 Gradle/Android Studio)。

流水线: 暂存 → aapt2 compile/link → javac → d8 → jar uf →
        zip 条目名反斜杠修复(aapt2 已知问题 120436372) →
        zipalign → keytool/debug.keystore → apksigner → 校验。
每步打印耗时与产物规模; 全部通过后才把产物拷回项目 dist 目录。
"""
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))           # train-app/android
PROJ = os.path.dirname(HERE)                                 # train-app
SDK = os.path.join(os.path.dirname(PROJ), "android-sdk")     # ../android-sdk
STAGE = os.path.join(os.environ.get("TEMP", os.path.join(PROJ, "build")),
                     "trainapp_build")
OUT_DIST = os.path.join(PROJ, "dist")

JAVA = "java"
JAVAC = "javac"
JAR = "jar"
KEYTOOL = "keytool"


def find_sdk():
    bt = plat = None
    for root, dirs, files in os.walk(SDK):
        for f in files:
            if f == "aapt2.exe" and bt is None:
                bt = root
        for f in files:
            if f == "android.jar" and plat is None:
                plat = root
    if not bt or not plat:
        sys.exit("未找到 SDK: 需要 aapt2.exe 与 android.jar 在 %s 下" % SDK)
    return bt, plat


def run(cmd, **kw):
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                       encoding="utf-8", **kw)
    dt = time.time() - t0
    if r.returncode != 0:
        print("FAIL (%.2fs): %s" % (dt, " ".join(map(str, cmd[:6]))))
        print(r.stdout[-3000:])
        print(r.stderr[-3000:])
        sys.exit(1)
    return dt, r


def fix_zip_separators(apk):
    """aapt2 在 Windows 上把 assets 子目录打包成反斜杠条目; 用 zipfile 原地重写,
    保留每条 compress_type(resources.arsc 必须保持 STORED)。"""
    tmp = apk + ".fix"
    n = 0
    with zipfile.ZipFile(apk) as zin, \
            zipfile.ZipFile(tmp, "w") as zout:
        for i in zin.infolist():
            name = i.filename
            if "\\" in name:
                name = name.replace("\\", "/")
                n += 1
            zi = zipfile.ZipInfo(name, date_time=i.date_time)
            zi.compress_type = i.compress_type
            zi.external_attr = i.external_attr
            zout.writestr(zi, zin.read(i.filename))
    shutil.move(tmp, apk)
    return n


def main():
    t_start = time.time()
    bt, plat = find_sdk()
    android_jar = os.path.join(plat, "android.jar")
    lambda_stubs = os.path.join(bt, "core-lambda-stubs.jar")
    d8_jar = os.path.join(bt, "lib", "d8.jar")
    apksigner_jar = os.path.join(bt, "lib", "apksigner.jar")
    aapt2 = os.path.join(bt, "aapt2.exe")
    zipalign = os.path.join(bt, "zipalign.exe")
    print("SDK build-tools:", bt)
    print("platform:", plat)

    # 0) 暂存目录(纯 ASCII)
    if os.path.exists(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(os.path.join(STAGE, "src"), exist_ok=True)
    shutil.copytree(os.path.join(HERE, "src"), os.path.join(STAGE, "src"),
                    dirs_exist_ok=True)
    shutil.copytree(os.path.join(HERE, "res"), os.path.join(STAGE, "res"),
                    dirs_exist_ok=True)
    shutil.copy2(os.path.join(HERE, "AndroidManifest.xml"),
                 os.path.join(STAGE, "AndroidManifest.xml"))
    shutil.copytree(os.path.join(HERE, "assets"), os.path.join(STAGE, "assets"),
                    dirs_exist_ok=True)
    # 清掉测试探针残留
    for junk in ("__probe.html",):
        p = os.path.join(STAGE, "assets", junk)
        if os.path.exists(p):
            os.remove(p)
    n_assets = sum(len(fs) for _, _, fs in os.walk(os.path.join(STAGE, "assets")))
    print("OK stage: src+res+manifest+assets(%d 文件) -> %s" % (n_assets, STAGE))

    os.chdir(STAGE)

    # 3) aapt2 compile
    dt, _ = run([aapt2, "compile", "--dir", "res", "-o", "res.zip"])
    print("OK aapt2 compile (%.2fs)" % dt)

    # 4) aapt2 link
    dt, _ = run([aapt2, "link", "-o", "base.apk", "-I", android_jar,
                 "--manifest", "AndroidManifest.xml",
                 "-A", "assets", "--java", "gen",
                 "--min-sdk-version", "26", "--target-sdk-version", "34",
                 "--auto-add-overlay", "res.zip"])
    print("OK aapt2 link (%.2fs)" % dt)

    # 5) javac
    srcs = []
    for root, _, files in os.walk("src"):
        srcs += [os.path.join(root, f) for f in files if f.endswith(".java")]
    for root, _, files in os.walk("gen"):
        srcs += [os.path.join(root, f) for f in files if f.endswith(".java")]
    dt, _ = run([JAVAC, "-source", "8", "-target", "8", "-encoding", "UTF-8",
                 "-J-Duser.language=en", "-J-Duser.country=US",
                 "-bootclasspath", android_jar + os.pathsep + lambda_stubs,
                 "-d", "classes"] + srcs)
    n_cls = sum(len(fs) for _, _, fs in os.walk("classes"))
    print("OK javac (%.2fs, %d class)" % (dt, n_cls))

    # 6) d8 + jar uf
    cls = []
    os.makedirs("dex", exist_ok=True)
    for root, _, files in os.walk("classes"):
        cls += [os.path.join(root, f) for f in files if f.endswith(".class")]
    dt, _ = run([JAVA, "-cp", d8_jar, "com.android.tools.r8.D8",
                 "--release", "--min-api", "26",
                 "--lib", android_jar, "--lib", lambda_stubs,
                 "--output", "dex"] + cls)
    shutil.move(os.path.join("dex", "classes.dex"), "classes.dex")
    dt2, _ = run([JAR, "uf", "base.apk", "classes.dex"], cwd=STAGE)
    print("OK d8 + jar uf (%.2fs + %.2fs -> classes.dex)" % (dt, dt2))

    # 7) zip 条目名修复 + zipalign + 签名
    n_fix = fix_zip_separators("base.apk")
    print("OK zip 分隔符修复: 重写 %d 条目" % n_fix)
    dt, _ = run([zipalign, "-f", "-p", "4", "base.apk", "aligned.apk"])
    ks = os.path.join(STAGE, "debug.keystore")
    if not os.path.exists(ks):
        dt, _ = run([KEYTOOL, "-J-Dfile.encoding=UTF-8", "-genkeypair",
                     "-keystore", "debug.keystore", "-storepass", "android",
                     "-keypass", "android", "-alias", "trainapp",
                     "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
                     "-dname", "CN=TrainApp,O=Personal,C=CN"])
    dt, _ = run([JAVA, "-jar", apksigner_jar, "sign",
                 "--ks", "debug.keystore", "--ks-pass", "pass:android",
                 "--ks-key-alias", "trainapp",
                 "--v1-signing-enabled", "true", "--v2-signing-enabled", "true",
                 "--out", "app.apk", "aligned.apk"])
    print("OK zipalign + apksigner (%.2fs + %.2fs)" % (dt, dt))

    # 8) 校验(必须还在暂存目录里做)
    dt, r = run([JAVA, "-jar", apksigner_jar, "verify", "--print-certs", "app.apk"])
    print("OK apksigner verify (%.2fs)\n%s" % (dt, r.stdout.strip()[:400]))
    dt, r = run([aapt2, "dump", "badging", "app.apk"])
    badging = r.stdout
    pkg = next((l for l in badging.splitlines() if l.startswith("package:")), "")
    launch = next((l for l in badging.splitlines() if "launchable-activity" in l), "")
    perms = [l for l in badging.splitlines() if l.startswith("uses-permission")]
    print("OK badging:\n  %s\n  %s\n  %s" % (pkg.strip()[:120], launch.strip()[:120],
                                             "; ".join(p.split(":")[1].split("'")[1] for p in perms)))
    with zipfile.ZipFile("app.apk") as z:
        names = z.namelist()
        bad = [n for n in names if "\\" in n]
        assert not bad, "仍有反斜杠条目: %s" % bad[:5]
        for need in ("AndroidManifest.xml", "classes.dex", "resources.arsc",
                     "assets/index.html", "assets/data.js", "assets/app.js",
                     "assets/engine.js", "mipmap-xhdpi-v4/ic_launcher.png"):
            hit = [n for n in names if n == need or n.endswith(need.split("/")[-1])
                   and need.split("/")[0] in n]
            assert hit, "缺少关键条目: %s" % need
        sz = sum(i.compress_size for i in z.infolist())
    print("OK zip 校验: %d 条目, 无反斜杠, 压缩总体积 %.1fMB"
          % (len(names), sz / 1e6))

    # 拷回项目 dist
    os.makedirs(OUT_DIST, exist_ok=True)
    dst = os.path.join(OUT_DIST, "TrainApp.apk")
    shutil.copy2("app.apk", dst)
    print("\nDONE (%.1fs): %s (%.1fMB)"
          % (time.time() - t_start, dst, os.path.getsize(dst) / 1e6))


if __name__ == "__main__":
    main()
