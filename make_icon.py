# -*- coding: utf-8 -*-
"""make_icon.py — 生成托盘图标 assets/icon.ico (多尺寸)。"""
import os

from PIL import Image, ImageDraw

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "assets", "icon.ico")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

THEME = "#fe295f"      # 主题红(沿用原小程序)
DARK = "#20262f"
WHITE = "#ffffff"


def draw(size):
    s = size / 64  # 以 64 为基准的缩放系数
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 圆角方形底
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(14 * s), fill=THEME)
    # 车头: 白色圆角矩形
    bx0, by0, bx1, by1 = int(16 * s), int(12 * s), int(48 * s), int(44 * s)
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=int(10 * s), fill=WHITE)
    # 挡风窗
    d.rounded_rectangle([int(22 * s), int(17 * s), int(42 * s), int(28 * s)],
                        radius=int(4 * s), fill=DARK)
    # 车灯
    d.ellipse([int(22 * s), int(33 * s), int(28 * s), int(39 * s)], fill=THEME)
    d.ellipse([int(36 * s), int(33 * s), int(42 * s), int(39 * s)], fill=THEME)
    # 车轮
    d.ellipse([int(18 * s), int(42 * s), int(28 * s), int(52 * s)], fill=DARK)
    d.ellipse([int(36 * s), int(42 * s), int(46 * s), int(52 * s)], fill=DARK)
    # 轨道
    d.rounded_rectangle([int(12 * s), int(55 * s), int(52 * s), int(58 * s)],
                        radius=int(1.5 * s), fill=WHITE)
    return img


imgs = [draw(n) for n in (16, 24, 32, 48, 64, 128, 256)]
imgs[-1].save(OUT, format="ICO", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)],
              append_images=imgs[:-1])
print("icon ->", OUT, os.path.getsize(OUT), "bytes")
