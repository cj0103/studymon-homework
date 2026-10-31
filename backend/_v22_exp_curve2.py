# -*- coding: utf-8 -*-
"""v22 第二轮：缩放写法修正——乘法缩放 vs 指数自带的'曲线收缩'，公平对比"""
import sqlite3

conn = sqlite3.connect("pkm.sqlite3")
conn.row_factory = sqlite3.Row
TBL = {r["level"]: {"fast": r["exp_fast"], "medium": r["exp_medium"], "slow": r["exp_slow"]}
       for r in conn.execute("SELECT level, exp_fast, exp_medium, exp_slow FROM level_exp_table")}

def need(group, lv): return TBL[lv+1][group] - TBL[lv][group]
SHARE = 230 // 3  # 76

def n_lin(gap, base_lv, step=0.5, cap=8.0):
    """线性+乘法缩放（对照组）"""
    if gap <= 0: return 1.0
    return min(cap, 1 + step * gap * (base_lv / 19.0))

def n_exp(gap, base_lv, a=1.30, cap=8.0):
    """指数：底数不随基准级变——曲线自身收缩，无需额外缩放开关"""
    if gap <= 0: return 1.0
    return min(cap, a ** gap)

def days_to2(target_lv, start_lv, group, base_lv, nfn):
    lv, exp_in, days = start_lv, 0.0, 0
    rem = need(group, lv)
    while lv < target_lv and days < 4000:
        exp_in += SHARE * nfn(max(0, base_lv - lv), base_lv)
        while lv < target_lv and exp_in >= rem:
            exp_in -= rem; lv += 1
            if lv < target_lv: rem = need(group, lv)
        days += 1
    return days

curves = [
    ("线性 0.5/×8+缩放",  lambda g,b: n_lin(g,b,0.5,8.0)),
    ("指数 1.25/×8",     lambda g,b: n_exp(g,b,1.25,8.0)),
    ("指数 1.30/×8",     lambda g,b: n_exp(g,b,1.30,8.0)),
    ("指数 1.30/×6",     lambda g,b: n_exp(g,b,1.30,6.0)),
    ("指数 1.35/×6",     lambda g,b: n_exp(g,b,1.35,6.0)),
    ("指数 1.35/×8",     lambda g,b: n_exp(g,b,1.35,8.0)),
    ("指数 1.35/×10",    lambda g,b: n_exp(g,b,1.35,10.0)),
    ("指数 1.40/×8",     lambda g,b: n_exp(g,b,1.40,8.0)),
]

print("【倍率值】基准19（差距→n）")
print(f"{'差距':>4}", *[f"{n:>13}" for n,_, in [(c[0],0) for c in curves]])
for gap in [1,2,3,4,5,6,7,8,9,10]:
    row = f"{gap:>4}"
    for name, fn in curves: row += f"{fn(gap,19):>13.2f}"
    print(row)

print("\n【倍率值】基准46（馆8，指数无需缩放自动收缩）")
for gap in [1,2,3,5,7,9]:
    row = f"{gap:>4}"
    for name, fn in curves: row += f"{fn(gap,46):>13.2f}"
    print(row)

print("\n【关键场景天数】(medium 组, 每只日份额=76×n)")
scen = [("梯队 Lv12→19", 19,12,"medium",19), ("尾段 Lv16→19", 19,16,"medium",19),
        ("馆5新怪 Lv24→28", 28,24,"medium",28), ("馆8新怪 Lv37→46", 46,37,"medium",46)]
print(f"{'场景':<18}", *[f"{n:>13}" for n,_ in curves])
for sname, tgt, st, grp, bl in scen:
    row = f"{sname:<18}"
    for name, fn in curves: row += f"{days_to2(tgt,st,grp,bl,fn):>13}"
    print(row)

print("\n【差距感】基准19：n(10)/n(5)，越大越'惩罚落后'")
for name, fn in curves:
    print(f"  {name:<14} n(5)={fn(5,19):.2f}  n(10)={fn(10,19):.2f}  比值={fn(10,19)/fn(5,19):.2f}")

print("\n【边际体感】相邻级经验比 n(g+1)/n(g)（基准19，恒定=指数底数）")
for name, fn in curves:
    ratios = [fn(g+1,19)/fn(g,19) for g in range(1,6)]
    print(f"  {name:<14} " + " ".join(f"{r:.2f}" for r in ratios))

print("\n【封顶触达】基准19时达到封顶的差距级（越早触顶→后期差距感越平）")
for name, fn in curves:
    top = next((g for g in range(1,20) if fn(g,19) >= fn(19,19)-1e-9), None)
    # 找到第一个等于最大值的 gap
    mx = fn(19,19)
    top = next((g for g in range(1,20) if abs(fn(g,19)-mx)<1e-9), None)
    print(f"  {name:<14} gap={top}")
