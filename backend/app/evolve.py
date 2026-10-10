# -*- coding: utf-8 -*-
"""进化引擎：到级自动进化（等级进化统一规则）。

- 升级后调用 maybe_evolve：查 pkm_evolution，等级达标则把这只 trainer_pokemon
  的 pokedex_no 换成进化形态；可能连锁进化（一次跨多级）。
- 进化后技能：保留原已学技能(known) + 并入新形态到级的学习池，重新 ensure_known；
  孩子原配的 4 个上场技能(learned)保持不变。
- 进化是"惊喜"：返回进化链供前端弹提示。
"""
import json
from . import db, skills


def maybe_evolve(tp_id: int):
    """若该宝可梦达到进化等级则进化（可连锁）。返回进化到的名字列表（空=没进化）。"""
    evolved_names = []
    for _ in range(5):                       # 防意外死循环，最多连锁5次
        row = db.q("SELECT tp.id, tp.pokedex_no, tp.level, tp.known_skill_json, "
                   "tp.learned_skill_json, tp.sealed, pb.name FROM trainer_pokemon tp "
                   "JOIN pokemon_base pb ON pb.pokedex_no=tp.pokedex_no WHERE tp.id=%s",
                   (tp_id,))[0]
        if row.get("sealed"):                # 封印中的宝可梦不检查进化
            break
        evo = db.q("SELECT to_no, min_level FROM pkm_evolution WHERE from_no=%s",
                   (row["pokedex_no"],))
        if not evo or row["level"] < evo[0]["min_level"]:
            break
        to_no = evo[0]["to_no"]
        to_name = db.q("SELECT name FROM pokemon_base WHERE pokedex_no=%s", (to_no,))
        to_name = to_name[0]["name"] if to_name else f"#{to_no}"
        # 进化：换 dex 号（等级/经验/上场配置保留）
        db.x("UPDATE trainer_pokemon SET pokedex_no=%s WHERE id=%s", (to_no, tp_id))
        # 技能：并入新形态到级技能，保留已学与上场配置
        skills.ensure_known(tp_id, to_no, row["level"],
                            row["known_skill_json"], row["learned_skill_json"])
        evolved_names.append(to_name)
    return evolved_names
