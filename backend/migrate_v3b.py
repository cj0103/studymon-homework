# -*- coding: utf-8 -*-
"""v3b：重建 skill_base 表，把 id 列改为 INTEGER PRIMARY KEY（rowid 别名）。

根因：建表 DDL 用 `id INT PRIMARY KEY`——sqlite 仅 `INTEGER PRIMARY KEY` 才是 rowid 别名，
`INT PRIMARY KEY` 列无自动填充，且 NOT NULL 约束缺失时插 NULL 不报错，
导致所有"不显式给 id 的插入"（init 种子数据、build_skills_v3 新增招）都产生 NULL id 行。

本迁移（仅本地 sqlite 开发库；ECS sqlite 同样适用）：
1) 检查现表 id 类型，已是 INTEGER 则跳过；
2) PRAGMA foreign_keys=OFF；
3) 按名合并去重重建新表（同名单行，保留内容最新的非 NULL id 行），id 重新 1..N 连续分配；
4) 学习表按 (pokedex_no, 新技能名) 重映射；
5) trainer 两个 JSON 列表按 旧id→名→新id 重映射（剔除 null/失效项；空则学习池兜底前4）；
6) DROP 旧表、改名、重建索引、开启 foreign_keys、COMMIT；
7) 验证：NULL=0、重名=0、悬空=0。
用法: PKM_DB_ENGINE=sqlite python migrate_v3b.py
"""
import json
import os
import sqlite3

DBFILE = os.environ.get("PKM_SQLITE_FILE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "pkm.sqlite3")))

NEW_DDL = """CREATE TABLE skill_base_new (
    id INTEGER PRIMARY KEY,
    skill_name VARCHAR(50) NOT NULL UNIQUE,
    skill_type VARCHAR(20) NOT NULL,
    power INT NOT NULL,
    accuracy INT NOT NULL,
    effect_type VARCHAR(30) NULL,
    effect_value DECIMAL(2,1) NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    ailment VARCHAR(10),
    ailment_chance INT DEFAULT 0
)"""

def main():
    if os.environ.get("PKM_DB_ENGINE", "mysql") != "sqlite":
        raise SystemExit("须 PKM_DB_ENGINE=sqlite")
    conn = sqlite3.connect(DBFILE, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row

    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='skill_base'").fetchone()[0]
    if "id INTEGER PRIMARY KEY" in ddl:
        print("skill_base.id 已是 INTEGER PRIMARY KEY，跳过")
        return

    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN IMMEDIATE")
    try:
        # 1. 取全部行（按 rowid 序），同名单行保留最后一条非 NULL id 的、否则最后一条
        rows = conn.execute(
            "SELECT rowid AS rid, id, skill_name, skill_type, power, accuracy, "
            "effect_type, effect_value, create_time, ailment, ailment_chance "
            "FROM skill_base ORDER BY rowid").fetchall()
        by_name = {}
        for r in rows:
            prev = by_name.get(r["skill_name"])
            if prev is None:
                by_name[r["skill_name"]] = r
            elif r["id"] is not None and prev["id"] is None:
                by_name[r["skill_name"]] = r
            elif (r["id"] is None) == (prev["id"] is None):
                by_name[r["skill_name"]] = r       # 同级取后见
        keep = list(by_name.values())
        # 稳定顺序：有 id 的按 id 升序在前，NULL id 按 rowid 序在后（分配连续新 id）
        keep.sort(key=lambda r: (r["id"] is None, r["id"] if r["id"] is not None else r["rid"]))
        old2new = {}
        conn.execute(NEW_DDL)
        for i, r in enumerate(keep, start=1):
            old2new[r["rid"]] = i
            conn.execute(
                "INSERT INTO skill_base_new(id,skill_name,skill_type,power,accuracy,"
                "effect_type,effect_value,create_time,ailment,ailment_chance) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (i, r["skill_name"], r["skill_type"], r["power"], r["accuracy"],
                 r["effect_type"], r["effect_value"], r["create_time"],
                 r["ailment"], r["ailment_chance"]))
        print(f"重建 skill_base_new: 源 {len(rows)} 行 → 去重后 {len(keep)} 行")

        # 2. 学习表重映射（skill_id 旧行 rowid → 新 id；NULL/悬空丢弃）
        conn.execute(
            "CREATE TABLE pokemon_skill_learn_new ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "pokedex_no INT NOT NULL, skill_id INT NOT NULL, learn_level INT NOT NULL, "
            "UNIQUE (pokedex_no, skill_id))")
        remap_ok = remap_drop = 0
        for r in conn.execute(
                "SELECT psl.rowid AS rid, psl.pokedex_no, psl.skill_id, psl.learn_level "
                "FROM pokemon_skill_learn psl ORDER BY psl.rowid").fetchall():
            new_id = old2new.get(r["skill_id"]) if r["skill_id"] is not None else None
            if new_id is None:
                remap_drop += 1
                continue
            conn.execute(
                "INSERT OR IGNORE INTO pokemon_skill_learn_new(pokedex_no,skill_id,learn_level) "
                "VALUES(?,?,?)", (r["pokedex_no"], new_id, r["learn_level"]))
            remap_ok += 1
        print(f"学习表重映射: 保留 {remap_ok}，丢弃 {remap_drop}")

        # 3. trainer JSON 列表重映射（旧 id → 名 → 新 id）
        id2name = {r["rid"]: r["skill_name"] for r in rows}
        name2new = {r["skill_name"]: old2new[r["rid"]] for r in rows}
        fixed = 0
        for tp in conn.execute(
                "SELECT id, pokedex_no, level, learned_skill_json, known_skill_json "
                "FROM trainer_pokemon").fetchall():
            def map_arr(raw):
                try:
                    arr = json.loads(raw or "[]")
                except Exception:
                    return None
                out = []
                for sid in arr:
                    nm = id2name.get(sid) if isinstance(sid, int) else None
                    nid = name2new.get(nm) if nm else None
                    if nid is not None and nid not in out:
                        out.append(nid)
                return out
            learned = map_arr(tp["learned_skill_json"])
            known = map_arr(tp["known_skill_json"])
            if learned is None and known is None:
                continue
            if known is None:
                known = []
            if learned is None:
                learned = known[:4]
            pool = [x["skill_id"] for x in conn.execute(
                "SELECT skill_id FROM pokemon_skill_learn_new "
                "WHERE pokedex_no=? AND learn_level<=? ORDER BY learn_level, skill_id",
                (tp["pokedex_no"], tp["level"]))]
            if not known and pool:
                known = pool[-4:][::-1]
            if not learned:
                learned = (known or pool)[:4]
            conn.execute("UPDATE trainer_pokemon SET learned_skill_json=?, known_skill_json=? WHERE id=?",
                         (json.dumps(learned), json.dumps(known), tp["id"]))
            fixed += 1
        print(f"trainer 技能 JSON 重映射: {fixed} 只")

        # 4. 替换
        conn.execute("DROP TABLE pokemon_skill_learn")
        conn.execute("ALTER TABLE pokemon_skill_learn_new RENAME TO pokemon_skill_learn")
        conn.execute("DROP TABLE skill_base")
        conn.execute("ALTER TABLE skill_base_new RENAME TO skill_base")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_psl_pokedex ON pokemon_skill_learn(pokedex_no)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_psl_skill ON pokemon_skill_learn(skill_id)")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    # 5. 验证
    conn.execute("PRAGMA foreign_keys=ON")
    n = conn.execute("SELECT COUNT(*) n FROM skill_base").fetchone()["n"]
    dup_name = conn.execute(
        "SELECT COUNT(*) n FROM (SELECT skill_name FROM skill_base GROUP BY skill_name HAVING COUNT(*)>1)").fetchone()["n"]
    n_learn = conn.execute("SELECT COUNT(*) n FROM pokemon_skill_learn").fetchone()["n"]
    dangling = conn.execute(
        "SELECT COUNT(*) n FROM pokemon_skill_learn psl LEFT JOIN skill_base sb ON sb.id=psl.skill_id "
        "WHERE sb.id IS NULL").fetchone()["n"]
    nulls = conn.execute("SELECT COUNT(*) n FROM skill_base WHERE id IS NULL").fetchone()["n"]
    print(f"验证: 技能={n} NULL={nulls} 重名={dup_name} 学习表={n_learn} 悬空={dangling}")
    assert nulls == 0 and dup_name == 0 and dangling == 0, "迁移验证失败！"
    conn.close()
    print("MIGRATE_V3B OK")

if __name__ == "__main__":
    main()
