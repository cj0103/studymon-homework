# -*- coding: utf-8 -*-
"""v22 追赶加成：sys_config 补种三参数（幂等，INSERT IGNORE 同义）。
本地与线上共用：PKM_DB_ENGINE=sqlite <venv> _addcol_catchup.py
"""
from app import db

SEED = [("catchup_base", "1.30", "v22追赶倍率指数底数：每差1级上场经验×1.30（≤1=关闭加成）"),
        ("catchup_max_mult", "8", "v22追赶倍率封顶（家长可调2~15）"),
        ("catchup_dead", "0", "v22追赶死区：差距≤N级不吃加成（0=关，到基准级自动取消恒有）")]

done = []
for k, v, memo in SEED:
    exist = db.q("SELECT cfg_value FROM sys_config WHERE cfg_key=%s", (k,))
    if exist:
        done.append(f"EXISTS {k}={exist[0]['cfg_value']}")
    else:
        db.x("INSERT INTO sys_config(cfg_key,cfg_value,memo) VALUES(%s,%s,%s)", (k, v, memo))
        done.append(f"ADDED {k}={v}")
print("SEED_OK:", "; ".join(done))
