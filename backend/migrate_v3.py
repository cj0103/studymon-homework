# -*- coding: utf-8 -*-
"""v3 招式系统迁移：skill_base 加 ailment / ailment_chance 列（幂等）。
用法（本地）: PKM_DB_ENGINE=sqlite PKM_SQLITE_FILE=backend/pkm.sqlite3 python migrate_v3.py
用法（ECS） : 在 backend/ 目录下用 venv python 直接运行（sqlite 引擎）。
"""
import os
import sqlite3
import sys

DBFILE = os.environ.get("PKM_SQLITE_FILE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "pkm.sqlite3")))

def main():
    if os.environ.get("PKM_DB_ENGINE", "mysql") != "sqlite" and "--force" not in sys.argv:
        raise SystemExit("本迁移脚本仅用于 sqlite 本地库；ECS 上请显式 PKM_DB_ENGINE=sqlite")
    conn = sqlite3.connect(DBFILE)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(skill_base)")}
    for col, ddl in [("ailment", "VARCHAR(10)"), ("ailment_chance", "INT DEFAULT 0")]:
        if col not in cols:
            conn.execute(f"ALTER TABLE skill_base ADD COLUMN {col} {ddl}")
            print(f"ADDED skill_base.{col}")
        else:
            print(f"SKIP  skill_base.{col} 已存在")
    conn.commit()
    conn.close()
    print("MIGRATE OK", DBFILE)

if __name__ == "__main__":
    main()
