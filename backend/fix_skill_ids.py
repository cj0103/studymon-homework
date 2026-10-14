# -*- coding: utf-8 -*-
"""修复 skill_base.id 为 NULL 的存量行（sqlite INT PRIMARY KEY 非 rowid 别名缺陷）。

根因：建表 DDL 用 `id INT PRIMARY KEY`（非 INTEGER），sqlite 不把它当 rowid 别名，
显式插 NULL 不报错也不填充 → 历史插入产生 NULL id 行。
本脚本：BEGIN IMMEDIATE（占住写锁，服务侧 COMMIT 忙时会自动等待）→
按 (skill_name, rowid) 顺序分配「全表 max(id)+1 起」的新 id →
将 pokemon_skill_learn / trainer_pokemon 两个 JSON 列中引用旧 NULL 的行重新对齐
（JSON 内无法按旧 id 映射，统一按学习表重排：learned 取 learnable 兜底、known 取学习池）。
用法: PKM_DB_ENGINE=sqlite python fix_skill_ids.py
"""
import json
import os
import sqlite3
import sys

DBFILE = os.environ.get("PKM_SQLITE_FILE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "pkm.sqlite3")))

def main():
    if os.environ.get("PKM_DB_ENGINE", "mysql") != "sqlite":
        raise SystemExit("本脚本仅用于 sqlite 本地库；须 PKM_DB_ENGINE=sqlite")
    conn = sqlite3.connect(DBFILE, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    nulls = conn.execute("SELECT rowid, skill_name FROM skill_base WHERE id IS NULL ORDER BY rowid").fetchall()
    if not nulls:
        print("无 NULL id 行，跳过")
        return
    max_id = conn.execute("SELECT MAX(id) FROM skill_base").fetchone()[0] or 0
    print(f"NULL id 行数: {len(nulls)}, 当前 max(id)={max_id}")

    # 学习表 NULL skill_id 行（FK 关闭时插入产生的悬空引用）→ 删除后由 build_skills_v3 重建
    n_null_learn = conn.execute("SELECT COUNT(*) FROM pokemon_skill_learn WHERE skill_id IS NULL").fetchone()[0]

    conn.execute("BEGIN IMMEDIATE")
    try:
        mapping = {}
        for i, r in enumerate(nulls, start=1):
            new_id = max_id + i
            conn.execute("UPDATE skill_base SET id=? WHERE rowid=?", (new_id, r["rowid"]))
            mapping[r["rowid"]] = new_id
        deleted = conn.execute("DELETE FROM pokemon_skill_learn WHERE skill_id IS NULL").rowcount
        print(f"学习表删除悬空 NULL 引用 {deleted} 条（原有 {n_null_learn} 条），稍后由 build_skills_v3 重建")
        # trainer 身上 JSON 列表里含 null 的行 → 用学习表重排兜底
        bad_tp = conn.execute(
            "SELECT id, pokedex_no, level, learned_skill_json, known_skill_json "
            "FROM trainer_pokemon WHERE learned_skill_json LIKE '%null%' "
            "OR known_skill_json LIKE '%null%'").fetchall()
        fixed_tp = 0
        for tp in bad_tp:
            pool = [x["skill_id"] for x in conn.execute(
                "SELECT skill_id FROM pokemon_skill_learn "
                "WHERE pokedex_no=? AND learn_level<=? AND skill_id IS NOT NULL "
                "ORDER BY learn_level, skill_id", (tp["pokedex_no"], tp["level"]))]
            def sanitize(raw):
                try:
                    arr = json.loads(raw or "[]")
                except Exception:
                    arr = []
                return [s for s in arr if isinstance(s, int)]
            learned = sanitize(tp["learned_skill_json"])
            known = sanitize(tp["known_skill_json"])
            if not known:
                known = pool[-4:][::-1] or pool[:]
            if not learned:
                learned = known[:4]
            conn.execute("UPDATE trainer_pokemon SET learned_skill_json=?, known_skill_json=? WHERE id=?",
                         (json.dumps(learned), json.dumps(known), tp["id"]))
            fixed_tp += 1
        conn.execute("COMMIT")
        print(f"重编号 {len(mapping)} 行，清理学习表 NULL 引用 {deleted} 条，重排宝可梦 {fixed_tp} 只")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    # 验证
    conn = sqlite3.connect(DBFILE)
    try:
        n_null = conn.execute("SELECT COUNT(*) FROM skill_base WHERE id IS NULL").fetchone()[0]
        n = conn.execute("SELECT COUNT(*) FROM skill_base").fetchone()[0]
        n_orphan = conn.execute(
            "SELECT COUNT(*) FROM skill_base WHERE id NOT IN "
            "(SELECT DISTINCT skill_id FROM pokemon_skill_learn)").fetchone()[0]
        bad_json = conn.execute(
            "SELECT COUNT(*) FROM trainer_pokemon WHERE learned_skill_json LIKE '%null%' "
            "OR known_skill_json LIKE '%null%'").fetchone()[0]
        dup = conn.execute(
            "SELECT COUNT(*) FROM (SELECT id FROM skill_base GROUP BY id HAVING COUNT(*)>1)").fetchone()[0]
        print(f"验证: 总数={n} NULL={n_null} 重复id={dup} 孤儿={n_orphan} 含nullJSON={bad_json}")
        assert n_null == 0 and dup == 0 and bad_json == 0, "修复不完整！"
        print("FIX OK")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
