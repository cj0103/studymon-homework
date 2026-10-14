# -*- coding: utf-8 -*-
"""宝可梦技能（方案v2·孩子自主选招）：
- known_skill_json = 已学技能袋：升级到达级新招自动入袋（永不被遗忘），捕获入库一次性入袋
- learned_skill_json = 当前出战的4个技能：孩子在宝可梦页自主勾选，≤4 且必须来自已学袋
- 兼容旧数据：known 为空时回退用 learned/学习池 作为已学
"""
import json
from . import db

MAX_CARRY = 4

def learn_pool(pokedex_no: int, level: int):
    return db.q("SELECT skill_id, learn_level FROM pokemon_skill_learn "
                "WHERE pokedex_no=%s AND learn_level<=%s ORDER BY learn_level DESC, skill_id",
                (pokedex_no, level))

def ensure_known(tp_id: int, pokedex_no: int, level: int, known_json: str, carry_json: str):
    """升级/初始化后把到级新招并入已学袋；返回是否有变化并落库"""
    known = json.loads(known_json or "[]")
    if not known:                                # 旧数据迁移：已学=当前携带∪学习池
        known = json.loads(carry_json or "[]")
    pool = [r["skill_id"] for r in learn_pool(pokedex_no, level)]
    if not pool:
        return json.dumps(known)
    added = [s for s in pool if s not in known]
    if added:
        known = [s for s in known if s in pool] + added      # 去重合并
        db.x("UPDATE trainer_pokemon SET known_skill_json=%s WHERE id=%s",
             (json.dumps(known), tp_id))
        # 首次（还没配置过携带）→ 自动带入池中最强的前4个
        carry = json.loads(carry_json or "[]")
        if not carry:
            db.x("UPDATE trainer_pokemon SET learned_skill_json=%s WHERE id=%s",
                 (json.dumps(pool[:MAX_CARRY]), tp_id))
    return json.dumps(known)
