# -*- coding: utf-8 -*-
"""v22 追赶倍率测算：线性 vs 指数（只读本地库 level_exp_table，不改任何程序）"""
import sqlite3, math

conn = sqlite3.connect("pkm.sqlite3")
conn.row_factory = sqlite3.Row
cur = conn.execute("SELECT level, exp_fast, exp_medium, exp_slow FROM level_exp_table ORDER BY level")
TBL = {r["level"]: {"fast": r["exp_fast"], "medium": r["exp_medium"], "slow": r["exp_slow"]} for r in cur}

def need(group, lv):
    """从 lv 级升到 lv+1 级还需多少经验"""
    return TBL[lv+1][group] - TBL[lv][group]

DAILY = 230          # 每日定额（不含快手/连击，测算是保守口径）
TEAM = 3             # 出战 3 只，even 平分
SHARE = DAILY // TEAM  # 先分后乘：每只份额 76

# ---------- 倍率曲线 ----------
def n_lin(gap, base_lv, step=0.5, cap=8.0, scale=1):
    """线性（前期推荐档）：n = min(cap, 1 + step*gap*(base_lv/19 缩放))"""
    if gap <= 0: return 1.0
    k = 1 + step * gap * ((base_lv/19.0) if scale else 1.0)
    return min(cap, k)

def n_exp(gap, base_lv, base=1.25, cap=8.0, scale=1):
    """指数：n = min(cap, base^gap)，缩放=指数收缩 a^(gap*19/base_lv)"""
    if gap <= 0: return 1.0
    e = gap * ((19.0/base_lv) if scale else 1.0)
    return min(cap, base ** e)

def n_exp2(gap, base_lv, base=1.25, cap=8.0, scale=1):
    """指数变体：底数收缩 n = (1+(a-1)*19/base_lv)^gap —— 等价于对指数底数做后期缩放"""
    if gap <= 0: return 1.0
    a = 1 + (base - 1) * ((19.0/base_lv) if scale else 1.0)
    return min(cap, a ** gap)

def days_to(target_lv, start_lv, group, base_lv, nfn, **kw):
    """模拟：从 start_lv 升到 target_lv 需要多少天（每天每只拿 SHARE*n(gap)）"""
    lv, days = start_lv, 0.0
    while lv < target_lv and days < 4000:
        gap = max(0, base_lv - lv)
        n = nfn(gap, base_lv, **kw)
        gain = SHARE * n
        # 一天内可能升多级：按天粗粒度足够
        rem = need(group, lv)
        used = 0.0
        while lv < target_lv:
            left = rem - used
            if left <= 0:
                lv += 1
                if lv >= target_lv: break
                rem = need(group, lv); used = 0.0
                continue
            if used + gain < rem:  # 一天不够升下一级
                used += gain
                days += 1
                gain = SHARE * nfn(max(0, base_lv - lv), base_lv, **kw)
                if used >= rem: break
            else:
                used = rem
                lv += 1
                if lv >= target_lv: break
                rem = need(group, lv)
                leftover = gain - (rem - used)  # 近似：剩余经验滚入下一级
                if leftover > 0:
                    used = 0.0
                    # 把 leftover 记入下一级消耗
                    gain = leftover
                    continue
                gain = 0
                days += 1
                gain = SHARE * nfn(max(0, base_lv - lv), base_lv, **kw)
                used = 0.0
    return days

# 简化重算：按“经验池累积”逐日推进（上面模拟有粗糙处，重做一个干净的）
def days_to2(target_lv, start_lv, group, base_lv, nfn, **kw):
    lv = start_lv
    exp_in = 0.0
    rem_need = need(group, lv)
    days = 0
    while lv < target_lv and days < 4000:
        gap = max(0, base_lv - lv)
        n = nfn(gap, base_lv, **kw)
        exp_in += SHARE * n
        while lv < target_lv and exp_in >= rem_need:
            exp_in -= rem_need
            lv += 1
            if lv < target_lv:
                rem_need = need(group, lv)
        days += 1
    return days

print("="*80)
print("经验表片段（medium 组升级所需）：")
for lv in [5,8,10,12,15,18,19,25,30,36,40,45]:
    print(f"  Lv{lv}->Lv{lv+1}: {need('medium',lv)}", end="")
    if lv % 3 == 0: print()
print()
print(f"每日定额 {DAILY}，3 只平分 → 每只份额 {SHARE}")
print("="*80)

curves = [
    ("线性 0.5/×8 (前期推荐)", lambda g,b: n_lin(g,b,0.5,8.0,scale=1), dict()),
    ("指数 1.25^gap/×8 缩放", lambda g,b: n_exp(g,b,1.25,8.0,scale=1), dict()),
    ("指数 1.30^gap/×8 缩放", lambda g,b: n_exp(g,b,1.30,8.0,scale=1), dict()),
    ("指数 1.35^gap/×8 缩放", lambda g,b: n_exp(g,b,1.35,8.0,scale=1), dict()),
    ("指数 1.40^gap/×8 缩放", lambda g,b: n_exp(g,b,1.40,8.0,scale=1), dict()),
]

print("\n【倍率曲线对比】基准级19（未缩放=前期口径）")
print(f"{'差距':>4}", *[f"{name.split()[0]+name.split()[1][:6]:>16}" for name,_,_ in curves])
for gap in [1,2,3,4,5,6,7,8,9,10,12]:
    row = f"{gap:>4}"
    for name, fn, kw in curves:
        row += f"{fn(gap,19):>16.2f}"
    print(row)

print("\n【梯队天数】当前主力约 Lv12 → 馆2 基准 Lv19（medium 组）")
for name, fn, kw in curves:
    d = days_to2(19, 12, "medium", 19, fn)
    d2 = days_to2(19, 16, "medium", 19, fn)
    print(f"  {name:<24} Lv12→19: {d:>4} 天   Lv16→19(尾段): {d2:>3} 天")

print("\n【馆8 新怪追赶】野捕 Lv37 → 基准 Lv46（medium 组，缩放生效 base_lv=46）")
for name, fn, kw in curves:
    d = days_to2(46, 37, "medium", 46, fn)
    print(f"  {name:<24} Lv37→46: {d:>4} 天")

print("\n【差距感】差10级 vs 差5级 最终经验比（基准19，缩放开）")
for name, fn, kw in curves:
    n5, n10 = fn(5,19), fn(10,19)
    print(f"  {name:<24} n(5)={n5:.2f} n(10)={n10:.2f}  比值={n10/n5:.2f}")

print("\n【日发峰值】基准46 缩放后 n(最大差距9~10) × 份额（先分后乘，队3只）")
for name, fn, kw in curves:
    nmax = fn(9, 46)
    print(f"  {name:<24} 46馆差距9: n={nmax:.2f}  该只日得={int(SHARE*nmax)}  队伍日实发上限≈{int(SHARE*nmax + SHARE*n_lin(4,46,0.5,8,scale=1)*0 + 76*2)}(粗)")
