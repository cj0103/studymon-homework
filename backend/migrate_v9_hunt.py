# -*- coding: utf-8 -*-
"""v9 迁移：student_user 增加 hunt_region_id（野外捕捉选区）。

- 0 = 未选择，跟随剧情进度（current_region_id），与旧行为完全一致
- >0 = 孩子手动选定的捕捉区（服务端按 region_base.unlock_badge_count 硬校验解锁）
- current_region_id 语义不变（=剧情推进位），通关/周常等既有逻辑零改动
幂等：列已存在则跳过。用法：PKM_DB_ENGINE=sqlite python migrate_v9_hunt.py
"""
import os
from app import db
from app.db import ENGINE


def main():
    cols = [r["name"] if "name" in r else r[0] for r in
            db.q("PRAGMA table_info(student_user)")] if ENGINE == "sqlite" else \
           [r["COLUMN_NAME"] for r in db.q(
               "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
               "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='student_user'")]
    if "hunt_region_id" in cols:
        print("SKIP — hunt_region_id 已存在")
        return
    db.x("ALTER TABLE student_user ADD COLUMN hunt_region_id INT NOT NULL DEFAULT 0")
    n = db.q("SELECT COUNT(*) c FROM student_user WHERE hunt_region_id=0")[0]["c"]
    print(f"ADD COLUMN hunt_region_id (DEFAULT 0=跟随进度)  现有 {n} 个账号全部=0")
    print("MIGRATE_V9 OK")


if __name__ == "__main__":
    main()
