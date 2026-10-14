# -*- coding: utf-8 -*-
"""v6 一次性脚本：把 rebuild_wild.py 的 PLOT_HOME 等级带重写为「道馆锚定版」。

口径（用户定稿）：
- 每区新上限 = 本区道馆推荐级 - 4；锚定区间 = [上限-5, 上限]（带宽 6 级）
  区1 7~12 / 区2 10~15 / 区3 15~20 / 区4 19~24 / 区5 23~28 / 区6 27~32 / 区7 31~36 / 区8 37~42
- 区内错开：旧带在区内相对位置低的怪贴下限，位置高的贴上限（每怪带宽 3 级）
- 只改 lo/hi；catch_weight、归属区、产地注释一律不动；动态跟随(dynamic_level)下线

做法：正则逐行重写 PLOT_HOME 数字段，先 dry-run 打印新旧对照+断言校验，
带 PKM_APPLY=1 才真正写回源文件（先备份 .bak_v6）。
"""
import os
import re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "rebuild_wild.py")

# 道馆推荐级（区 i ↔ gym sort i，与 guide 一致）：16/19/24/28/32/36/40/46
GYM_REC = {1: 16, 2: 19, 3: 24, 4: 28, 5: 32, 6: 36, 7: 40, 8: 46}
# 中间进化形态名单（与 rebuild_wild 文档口径一致）→ 贴区间上限
INTERMEDIATE = {17, 30, 33, 44, 61, 64, 67, 70, 75, 93, 148}
BAND = 3  # 每怪带宽

LINE = re.compile(r"^(\s*)(\d+):\s*\((\d+),\s*(\d+),\s*(\d+),\s*(\d+),(\s*)")

def main():
    src = open(SRC, encoding="utf-8").read()
    # 1) 收集 PLOT_HOME 段内的行
    lines = src.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith("PLOT_HOME"))
        end = next(i for i, l in enumerate(lines[start:], start) if l.strip() == "}")
    except StopIteration:
        raise SystemExit("未找到 PLOT_HOME 段")
    entries = []  # (line_idx, pid, reg, lo, hi, w)
    for i in range(start, end):
        m = LINE.match(lines[i])
        if m:
            entries.append((i, int(m.group(2)), int(m.group(3)),
                            int(m.group(4)), int(m.group(5)), int(m.group(6))))
    assert len(entries) == 82, f"应匹配 82 只，实际 {len(entries)}"

    # 2) 区内按旧带中值排序 → 相对位置 r∈[0,1]
    per = defaultdict(list)
    for e in entries:
        per[e[2]].append(e)
    new_band = {}  # line_idx -> (lo, hi)
    for reg, es in per.items():
        cap = GYM_REC[reg] - 4
        lo_a, hi_a = cap - 5, cap
        es_sorted = sorted(es, key=lambda e: (e[3] + e[4]) / 2)
        n = len(es_sorted)
        for k, e in enumerate(es_sorted):
            r = k / (n - 1) if n > 1 else 0.0
            lo = lo_a + round(r * ((hi_a - BAND) - lo_a))
            hi = lo + BAND
            # 链头/未进化贴下限，中间进化形态贴上限
            if e[1] in INTERMEDIATE:
                lo, hi = hi_a - BAND, hi_a
            assert lo_a <= lo < hi <= hi_a, f"区{reg} pid{e[1]} 带 {lo}-{hi} 越界"
            new_band[e[0]] = (lo, hi)

    # 3) 校验阶梯：各区均值单调不降
    means = []
    for reg in sorted(per):
        ms = [sum(new_band[e[0]]) / 2 for e in per[reg]]
        means.append(sum(ms) / len(ms))
    assert all(b >= a for a, b in zip(means, means[1:])), f"阶梯倒挂: {means}"
    # 旧表对照（阶梯基线）
    old_means = []
    for reg in sorted(per):
        ms = [(e[3] + e[4]) / 2 for e in per[reg]]
        old_means.append(sum(ms) / len(ms))

    # 4) 打印新旧对照
    print(f"{'pid':>4} {'区':>2} {'旧带':>8} -> {'新带':>8}")
    for i, pid, reg, lo, hi, w in entries:
        nlo, nhi = new_band[i]
        mark = " *" if pid in INTERMEDIATE else ""
        print(f"{pid:>4} {reg:>2} Lv{lo:>2}~{hi:<2} -> Lv{nlo:>2}~{nhi:<2}{mark}")
    print(f"\n新区均值阶梯: {' → '.join(f'{a:.1f}' for a in means)}"
          f"（旧: {' → '.join(f'{a:.1f}' for a in old_means)}）")
    print(f"各区上限: {[GYM_REC[r]-4 for r in sorted(GYM_REC)]}"
          f" = 道馆推荐级{[GYM_REC[r] for r in sorted(GYM_REC)]} - 4")

    # 5) 写回
    if os.environ.get("PKM_APPLY") != "1":
        print("\n[dry-run] 未写回；PKM_APPLY=1 时写回源文件")
        return
    for i, (nlo, nhi) in new_band.items():
        m = LINE.match(lines[i])
        indent, pid_s, reg_s, _lo, _hi, w_s, gap = m.groups()
        lines[i] = f"{indent}{pid_s}: ({reg_s}, {nlo}, {nhi}, {w_s},{gap}" + \
                   lines[i][m.end():]
    open(SRC + ".bak_v6", "w", encoding="utf-8").write(src)
    open(SRC, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"\n[APPLIED] 已写回 {SRC}（备份 {SRC}.bak_v6）")

if __name__ == "__main__":
    main()
