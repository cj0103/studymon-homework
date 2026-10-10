# -*- coding: utf-8 -*-
"""v7 迁移：trainer_pokemon 加 gift_gym_sort 列（幂等）。

道馆赠礼封印怪记录来源道馆 sort（1..8），激活等级改为该馆 recommend_level
（取代"跟随出战队伍最高级"）。历史数据回填：按 GYM_GIFTS 反查 pokedex_no。
"""
import os
import sqlite3

DBFILE = os.environ.get("PKM_SQLITE_FILE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "pkm.sqlite3")))

GYM_GIFTS = {1: 143, 2: 144, 3: 145, 4: 146, 5: 150, 6: 142, 7: 151, 8: 137}

c = sqlite3.connect(DBFILE)
cols = [r[1] for r in c.execute("PRAGMA table_info(trainer_pokemon)")]
if "gift_gym_sort" not in cols:
    c.execute("ALTER TABLE trainer_pokemon ADD COLUMN gift_gym_sort INT")
    print("ADD COLUMN gift_gym_sort")
else:
    print("COLUMN EXISTS")
n = 0
# 只回填"仍封印中或等级还停在入库级"的赠礼怪——已按旧口径激活（队伍最高级）的
# 历史行不硬改（避免经验/等级不一致），新口径只对新发放与待激活的生效。
for sort, no in GYM_GIFTS.items():
    n += c.execute("UPDATE trainer_pokemon SET gift_gym_sort=? WHERE pokedex_no=? "
                   "AND gift_gym_sort IS NULL AND (sealed=1 OR level=10)",
                   (sort, no)).rowcount
c.commit()
left = c.execute("SELECT COUNT(*) FROM trainer_pokemon WHERE gift_gym_sort IS NOT NULL").fetchone()[0]
c.close()
print(f"MIGRATE OK — 回填 {n} 行，现存标记 {left} 行")
