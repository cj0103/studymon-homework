# -*- coding: utf-8 -*-
"""v11 迁移：捕获额度从"周池"改为"当日池"（懒重置）。

- student_user 新增 caught_today INT DEFAULT 0 + catch_date DATE NULL
- 额度=当日捕获数 vs sys_config.daily_catch_limit(默认3)；catch_date≠今天即视为新的一天（读时归零）
- 旧字段 week_catch_times 保留但不再作为闸门（历史周语义作废，孩子只会得到更多额度，只多不少）
幂等：列已存在则跳过。用法：PKM_DB_ENGINE=sqlite python migrate_v11_catch.py
"""
from app import db
from app.db import ENGINE


def main():
    cols = [r["name"] if "name" in r else r[0] for r in
            db.q("PRAGMA table_info(student_user)")] if ENGINE == "sqlite" else \
           [r["COLUMN_NAME"] for r in db.q(
               "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
               "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='student_user'")]
    added = []
    if "caught_today" not in cols:
        db.x("ALTER TABLE student_user ADD COLUMN caught_today INT NOT NULL DEFAULT 0")
        added.append("caught_today")
    if "catch_date" not in cols:
        db.x("ALTER TABLE student_user ADD COLUMN catch_date DATE NULL")
        added.append("catch_date")
    print("ADD COLUMN:", added or "（已存在，跳过）")
    n = db.q("SELECT COUNT(*) c FROM student_user")[0]["c"]
    print(f"现有 {n} 个账号；旧 week_catch_times 停用，额度改当日 3 次")
    print("MIGRATE_V11 OK")


if __name__ == "__main__":
    main()
