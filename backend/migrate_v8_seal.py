# -*- coding: utf-8 -*-
"""v8 迁移：trainer_pokemon 加 seal_start_date 列（幂等）。

封印宝可梦独立 7 天计时：起算日=获得当日（发放时写入），激活要求
"从起算日起每一天都打卡获批，连续满 seal_streak_days(7) 天"。
NULL（v8 前的存量封印怪）视为"迁移日重新起算"，代码里兜底，无需洗数据。
"""
import os
import sqlite3

DBFILE = os.environ.get("PKM_SQLITE_FILE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "pkm.sqlite3")))

c = sqlite3.connect(DBFILE)
cols = [r[1] for r in c.execute("PRAGMA table_info(trainer_pokemon)")]
if "seal_start_date" not in cols:
    c.execute("ALTER TABLE trainer_pokemon ADD COLUMN seal_start_date DATE")
    print("ADD COLUMN seal_start_date")
else:
    print("COLUMN EXISTS")
n = c.execute("SELECT COUNT(*) FROM trainer_pokemon WHERE sealed=1").fetchone()[0]
c.close()
print(f"MIGRATE OK — 现存封印怪 {n} 只（seal_start_date 为 NULL 的按迁移日重新起算）")
