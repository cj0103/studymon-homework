# -*- coding: utf-8 -*-
"""v4：trainer_pokemon 增加 sealed 列（道馆赠礼"封印宝可梦"标记）。

- sealed=1：道馆赠礼入库态——不出现在出战/经验/进化链路，图鉴可见；
  连续打卡获批满 seal_streak_days(7) 天后自动激活（sealed=0）。
- 幂等：PRAGMA/SHOW COLUMNS 判列后再 ALTER，本地 sqlite 与 ECS 均可重复执行。
用法:
  本地: PKM_DB_ENGINE=sqlite python migrate_v4_seal.py
  ECS : cd /opt/pkmn-homework/backend && PKM_DB_ENGINE=sqlite venv/bin/python migrate_v4_seal.py
"""
import os
import sqlite3

DBFILE = os.environ.get("PKM_SQLITE_FILE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "pkm.sqlite3")))

def main():
    if os.environ.get("PKM_DB_ENGINE", "mysql") != "sqlite":
        raise SystemExit("须 PKM_DB_ENGINE=sqlite（ECS 同样用 sqlite 引擎）")
    conn = sqlite3.connect(DBFILE, timeout=10)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(trainer_pokemon)")]
    if "sealed" in cols:
        print("trainer_pokemon.sealed 已存在，跳过")
    else:
        conn.execute("ALTER TABLE trainer_pokemon ADD COLUMN sealed TINYINT NOT NULL DEFAULT 0")
        conn.commit()
        print("已添加 trainer_pokemon.sealed")
    n = conn.execute("SELECT COUNT(*) FROM trainer_pokemon WHERE sealed=1").fetchone()[0]
    print(f"验证: sealed 列可用，当前封印中 {n} 只")
    conn.close()
    print("MIGRATE_V4_SEAL OK")

if __name__ == "__main__":
    main()
