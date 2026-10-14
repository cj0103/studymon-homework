# -*- coding: utf-8 -*-
"""重算 pokemon_skill_learn 的解锁等级（技能成长·每级解锁节奏）

背景：原始静态数据把 TM/教学招式都写成 learn_level=0，导致低等级宝可梦"已学袋"
混入大量高级招式（如 Lv5 小火龙有火箭头锤）。本脚本为每只宝可梦重建解锁节奏：
  - 取该宝可梦全部可学技能（去重）
  - 排序键：先按原作 learn_level（lv0 视为"无等级"排后），无等级者按威力升序
  - 重新分配 learn_level：前 4 个 = Lv1 初始；之后每 STEP 级解锁 1 个，封顶 CAP
  - 落库：UPDATE 现有行的 learn_level（技能集合不变，只改解锁等级）
幂等：每次从"去重后的技能集合"重算，不叠加。
"""
import os
import sqlite3
from app.db import DBFILE

STEP = int(os.environ.get("PKM_SKILL_STEP", "3"))   # 每几级解锁一个新招
INIT = int(os.environ.get("PKM_SKILL_INIT", "2"))   # 初始携带数量（Lv1就有）
CAP = 50


def rebuild(dbfile=DBFILE, apply=True):
    c = sqlite3.connect(dbfile)
    c.row_factory = sqlite3.Row
    rows = c.execute("""
        SELECT l.pokedex_no, l.skill_id, l.learn_level AS raw_lv, s.power
        FROM pokemon_skill_learn l
        JOIN skill_base s ON s.id = l.skill_id
    """).fetchall()

    # 每只宝可梦：技能集合(去重) + 取该技能最大威力、最小原始等级
    by_pkm = {}
    for r in rows:
        d = by_pkm.setdefault(r["pokedex_no"], {})
        sid = r["skill_id"]
        prev = d.get(sid)
        if prev is None:
            d[sid] = {"raw": r["raw_lv"], "power": r["power"] or 0}
        else:
            prev["raw"] = min(prev["raw"], r["raw_lv"])
            prev["power"] = max(prev["power"], r["power"] or 0)

    changes = 0
    total_new = []
    for no, skills in by_pkm.items():
        attacks = [(sid, m) for sid, m in skills.items() if m["power"] > 0]
        status = [(sid, m) for sid, m in skills.items() if m["power"] == 0]
        # 初始：从攻击招里挑 INIT 个，威力适中优先（不要一上来就大招，也别全变化招）
        # 排序攻击招：威力升序，取中段偏前的实用招作初始
        atk_sorted = sorted(attacks, key=lambda x: (x[1]["power"], x[0]))
        if len(atk_sorted) > INIT:
            # 跳过威力最低的（太弱如挣扎），取前 INIT 个较合理威力；不足则从头取
            pool = atk_sorted[:INIT] if len(atk_sorted) <= INIT + 1 else atk_sorted[:INIT]
        else:
            pool = atk_sorted
        init_ids = [sid for sid, _ in pool]
        # 若无攻击招可用（极端），用变化招补
        if len(init_ids) < INIT:
            for sid, _ in sorted(status, key=lambda x: x[0]):
                if sid not in init_ids:
                    init_ids.append(sid)
                if len(init_ids) >= INIT:
                    break
        # 其余技能（未入选初始的）按威力升序排队解锁，变化招穿插其后
        rest = [sid for sid, _ in sorted(
            [(s, m) for s, m in skills.items() if s not in init_ids],
            key=lambda x: (x[1]["power"], 0 if x[1]["raw"] > 0 else 1, x[1]["raw"], x[0]))]
        ordered = init_ids + rest
        for idx, sid in enumerate(ordered):
            if idx < len(init_ids):
                new_lv = 1
            else:
                new_lv = 1 + (idx - len(init_ids) + 1) * STEP
                new_lv = min(new_lv, CAP)
            total_new.append((new_lv, sid, no))
            if skills[sid]["raw"] != new_lv:
                changes += 1
                if apply:
                    c.execute("UPDATE pokemon_skill_learn SET learn_level=? "
                              "WHERE pokedex_no=? AND skill_id=?", (new_lv, no, sid))
    if apply:
        c.commit()
    c.close()
    return len(by_pkm), len(total_new), changes


if __name__ == "__main__":
    npkm, nrow, ch = rebuild(apply=(os.environ.get("PKM_APPLY", "1") == "1"))
    print(f"重建完成：{npkm} 只宝可梦 / {nrow} 条学习记录，其中 {ch} 条改了 learn_level")
