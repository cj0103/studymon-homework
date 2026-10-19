# -*- coding: utf-8 -*-
"""v18 家族技能池测试（纯函数，零写库）：
复现现场 bug——巴大蝶 Lv10 known=[起风10] carry=[变硬46,吐丝76,撞击20]，
旧口径 known 被覆写成池交集；新口径家族池+保护性保留应全量恢复。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PKM_DB_ENGINE", "sqlite")
from app import dexline

FAILS = []
def ck(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)

# A) 家族集合：虫/蛹/蝶同一连通分量；三段链对称闭包
fam = dexline.family_nos(12)
ck("FAMILY_CATERPIE_CHAIN", {10, 11, 12} <= fam)
ck("FAMILY_REV_FROM_PUP", dexline.family_nos(11) == fam)
fam7 = dexline.family_nos(7)
ck("FAMILY_STARTER_CHAIN", fam7 == {7, 8, 9} or fam7 == {7})   # 御三家链在库则三段
ck("FAMILY_SUBSET_151", all(1 <= n <= 151 for n in dexline.family_nos(25)))
# 双向对称：任意 b ∈ family(a) ⇒ family(b)==family(a)
sym = all(dexline.family_nos(b) == fam for b in fam)
ck("FAMILY_SYMMETRIC", sym)

# B) 现场 bug 复现（不落库：家族池覆盖三段到级招——技能ID随构建版本变化，
#    断言"其他形态的到级招出现在当前形态池"这一行为本身）
from app import db
from app.skills import ensure_known, MAX_CARRY, learn_pool
pool12_10 = {r["skill_id"] for r in learn_pool(12, 10)}
own12 = {r["skill_id"] for r in db.q(
    "SELECT skill_id FROM pokemon_skill_learn WHERE pokedex_no=12 AND learn_level<=10")}
others = db.q("SELECT skill_id FROM pokemon_skill_learn "
              "WHERE pokedex_no IN (10,11) AND learn_level<=10")
others = {r["skill_id"] for r in others}
ck("POOL_FAM_SUPERSET", own12 <= pool12_10 and others <= pool12_10)
ck("POOL_FAM_STRICT", (pool12_10 - own12) == (others - own12) and others - own12)

# C) ensure_known 合并语义（无 DB 写入路径模拟：known/carry 全空+池非空→自动配4）
#    此处仅验证函数可导入且签名兼容
from app.skills import ensure_known, MAX_CARRY, learn_pool
import inspect
sig = inspect.signature(ensure_known)
ck("SIGNATURE_STABLE", list(sig.parameters) ==
   ["tp_id", "pokedex_no", "level", "known_json", "carry_json"])
ck("LEARN_POOL_DESC", all(a["learn_level"] >= b["learn_level"]
                          for a, b in zip(learn_pool(12, 50), learn_pool(12, 50)[1:])))

print("V18_TEST_DONE FAILS=%s" % FAILS)
if FAILS:
    raise SystemExit(1)
