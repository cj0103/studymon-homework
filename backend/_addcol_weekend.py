# -*- coding: utf-8 -*-
"""v21 轻量迁移：task_template 补 weekend_only 列（本地开发库 + 线上共用口径）。幂等。"""
import os, sys
os.environ.setdefault("PKM_DB_ENGINE", "sqlite")
from app import db

def ensure():
    if db.ENGINE == "sqlite":
        c = db._sqlite_conn()
        cols = [r[1] for r in c.execute("PRAGMA table_info(task_template)")]
        if "weekend_only" not in cols:
            c.execute("ALTER TABLE task_template ADD COLUMN weekend_only TINYINT NOT NULL DEFAULT 0")
            c.commit()
            print("ADDED sqlite weekend_only")
        else:
            print("EXISTS sqlite weekend_only")
    else:
        c = db._conn()
        cur = c.cursor()
        cur.execute("SHOW COLUMNS FROM task_template LIKE 'weekend_only'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE task_template ADD COLUMN weekend_only TINYINT NOT NULL DEFAULT 0")
            c.commit()
            print("ADDED mysql weekend_only")
        else:
            print("EXISTS mysql weekend_only")

if __name__ == "__main__":
    ensure()
