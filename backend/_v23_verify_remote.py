# -*- coding: utf-8 -*-
"""线上 v23 行为验证（进程内直调 act 回合引擎，独立会话，不触孩子数据）。
必须放 backend/ 目录内跑（sys.path）。胜利路径会向 battle_record 插一行野生胜场——
该表本就是战斗流水，孩子无感知；除此之外零写入。
"""
import os
os.environ["PKM_DB_ENGINE"] = "sqlite"
from app.routers import battle as bt

PSN = {"ailment": "poison", "turns": 99}
MV = {"id": 1, "skill_name": "撞击", "skill_type": "一般", "power": 40, "accuracy": 100,
      "effect_type": None, "effect_value": None, "ailment": None, "ailment_chance": 0,
      "priority": 0, "max_pp": 8}

def unit(ref, mx, cur, atk=10, dfn=10, spd=10, st=None, foe=False):
    u = {"ref": ref, "pokedex_no": 16, "name": ("波波" if foe else "皮卡丘"), "level": 10,
         "types": ["飞行"] if foe else ["一般"],
         "stats": {"hp": mx, "atk": atk, "def": dfn, "spd": spd}, "hp": cur,
         "status": dict(st) if st else None, "moves": [dict(MV)], "pp": {1: 8}}
    if foe:
        u["move_weights"] = [1.0]
    return u

fails = []
# A) 我方毒死→换人
bt.SESSIONS[991] = {"kind": "wild", "sid": 991, "buffs": {}, "wild": {}, "wild_level": 5,
    "my": [unit("p1", 80, 8, spd=90, st=PSN), unit("p2", 40, 40, spd=10)],
    "foe": [unit("w0", 100, 100, atk=0, spd=5, foe=True)]}
r = bt.act({"action": "attack", "skill_id": 1}, {"uid": 991})
if not (r["result"] == "continue" and r["my_idx"] == 1 and "因中毒倒下" in "\n".join(r["messages"])):
    fails.append(f"A我方毒死换人失败: {r['result']} {r['messages']}")
bt.SESSIONS.pop(991, None)
# B) 我方毒死无备→判负
bt.SESSIONS[992] = {"kind": "wild", "sid": 992, "buffs": {}, "wild": {}, "wild_level": 5,
    "my": [unit("p1", 80, 8, spd=90, st=PSN)],
    "foe": [unit("w0", 100, 100, atk=0, spd=5, foe=True)]}
r = bt.act({"action": "attack", "skill_id": 1}, {"uid": 992})
if r["result"] != "lose":
    fails.append(f"B我方毒死判负失败: {r['result']}")
bt.SESSIONS.pop(992, None)
# C) 对方毒死→判胜（battle_record 插一行野生胜场，可接受）
bt.SESSIONS[993] = {"kind": "wild", "sid": 993, "buffs": {}, "wild": {}, "wild_level": 5,
    "my": [unit("p1", 80, 80, atk=999, spd=90)],
    "foe": [unit("w0", 96, 10, atk=5, dfn=10, spd=5, st=PSN, foe=True)]}
r = bt.act({"action": "attack", "skill_id": 1}, {"uid": 993})
if r["result"] != "win":
    fails.append(f"C对方毒死判胜失败: {r['result']}")
bt.SESSIONS.pop(993, None)
bt._CUR_SESS[0] = None
# D) 防御 buff 生效 + 双通道共存（纯函数级，零副作用）
sess = {"buffs": {}}
bt._CUR_SESS[0] = sess
u1, d1 = unit("a1", 100, 100, atk=80), unit("b1", 100, 100, dfn=50)
bt._attack_step(u1, d1, dict(MV), sess, True, []); base = 100 - d1["hp"]
u2, d2 = unit("a2", 100, 100, atk=80), unit("b2", 100, 100, dfn=50)
sess["buffs"] = {d2["ref"]: {"def": 1.5}}
bt._attack_step(u2, d2, dict(MV), sess, True, []); hard = 100 - d2["hp"]
if not hard < base:
    fails.append(f"D防御增益未减伤: 变硬{hard} 基准{base}")
bt._CUR_SESS[0] = None

if fails:
    print("V23_VERIFY_FAIL:", fails)
else:
    print("V23_VERIFY_OK 毒死换人/判负/判胜 + 防御buff生效 全通过")
