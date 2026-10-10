# -*- coding: utf-8 -*-
"""从 assets/artwork/official/*.png（475px 官方绘图，单张 ~150KB）批量生成 96px 缩略图标
到 assets/artwork/thumb/（透明底 PNG，单张 ~5KB），供指南页/图鉴批量加载。
96px = 2x 设备像素下的 48px 显示，学习平板上仍清晰。幂等，可重跑。"""
import os
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "artwork"))
SRC = os.path.join(ROOT, "official")
DST = os.path.join(ROOT, "thumb")
SIZE = 96


def make():
    os.makedirs(DST, exist_ok=True)
    n = 0
    for fn in sorted(os.listdir(SRC)):
        if not fn.lower().endswith(".png"):
            continue
        src_path = os.path.join(SRC, fn)
        img = Image.open(src_path).convert("RGBA")
        img.thumbnail((SIZE, SIZE), Image.LANCZOS)
        out = os.path.join(DST, fn)
        img.save(out, optimize=True)                       # 保留透明通道
        n += 1
    total_in = sum(os.path.getsize(os.path.join(SRC, f)) for f in os.listdir(SRC) if f.endswith(".png"))
    total_out = sum(os.path.getsize(os.path.join(DST, f)) for f in os.listdir(DST) if f.endswith(".png"))
    print(f"生成 {n} 张缩略图 → {DST}")
    print(f"体积: {total_in/1024/1024:.1f}MB → {total_out/1024/1024:.1f}MB")


if __name__ == "__main__":
    make()
