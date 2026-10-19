# -*- coding: utf-8 -*-
"""宝可梦技能（方案v2·孩子自主选招）：
- known_skill_json = 已学技能袋：升级到达级新招自动入袋（永不被遗忘），捕获入库一次性入袋
- learned_skill_json = 当前出战的4个技能：孩子在宝可梦页自主勾选，≤4 且必须来自已学袋
- 兼容旧数据：known 为空时回退用 learned/学习池 作为已学
- v18 家族技能池（修进化丢招 bug）：学习池按<b>整条进化链</b>（dexline.family_nos
  连通分量）取并集。旧口径按"当前形态"学习表裁剪 known——三段链学习表互不重叠
  （绿毛虫:撞击/吐丝/变硬；蛹:变硬；蝶:起风…），进化一次整袋清零一次，且交集为空
  时 added=[] 静默跳过，known 被覆写成仅新形态一两个招（现场：巴大蝶 known=[起风]
  而装备=[变硬,吐丝,撞击] 不合法）。新口径下旧招在家族池内、裁剪不丢；
  历史已丢的招通过"携带∪known 并集入池"保护性找回（不再静默删）。
"""
import json
from . import db

MAX_CARRY = 4

def _pool_rows(nos, level: int):
    """一族编号在 ≤level 的学习行（learn_level 升序）。空集合安全。"""
    nos = sorted(set(nos))
    if not nos:
        return []
    ph = ",".join(["%s"] * len(nos))
    return db.q(f"SELECT skill_id, learn_level FROM pokemon_skill_learn "
                f"WHERE pokedex_no IN ({ph}) AND learn_level<=%s "
                f"ORDER BY learn_level, skill_id", tuple(nos) + (level,))

def learn_pool(pokedex_no: int, level: int):
    """当前形态学习池：家族并集，按 learn_level 降序（调用方 pool[:4] 即最强前4，
    与原"最后习得的4项"口径一致）。"""
    from . import dexline
    return sorted(_pool_rows(dexline.family_nos(pokedex_no), level),
                  key=lambda r: (-r["learn_level"], -r["skill_id"]))

def ensure_known(tp_id: int, pokedex_no: int, level: int, known_json: str, carry_json: str):
    """升级/进化/初始化后把家族到级新招并入已学袋；返回落库后的 known JSON。
    v18 合并规则：
      1) 家族到级池为基底（含旧形态已学招——进化不丢）；
      2) known/carry 中"不在池内"的历史招<b>保护性保留</b>（追加尾部）——
         修历史丢招（绿毛虫时期的招已在携带里，重新入袋即合法），不再静默删；
      3) 首次（known、carry 均空）→ 池为空则不动；池非空自动带最强前4。"""
    known = json.loads(known_json or "[]")
    carry = json.loads(carry_json or "[]")
    if not known:                                # 旧数据迁移：已学=当前携带
        known = carry
    from . import dexline
    pool = [r["skill_id"] for r in _pool_rows(dexline.family_nos(pokedex_no), level)]
    merged = list(dict.fromkeys(pool + known + carry))   # 池优先排序，历史招保底
    if merged != known:
        db.x("UPDATE trainer_pokemon SET known_skill_json=%s WHERE id=%s",
             (json.dumps(merged), tp_id))
        if not known and not carry and pool:     # 真·首次入库才自动配招
            db.x("UPDATE trainer_pokemon SET learned_skill_json=%s WHERE id=%s",
                 (json.dumps(pool[:MAX_CARRY]), tp_id))
    return json.dumps(merged)
