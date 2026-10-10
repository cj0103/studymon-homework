# -*- coding: utf-8 -*-
"""v5 战斗迁移：skill_base 加 priority（先制等级）与 max_pp（每场上手次数）列（幂等）。

【priority】红/蓝口径先制招：本库 128 招仅 电光一闪=1，其余 0。
【max_pp】按威力归档（家长定档，2026-10-07）：
    变化招(<1威力)=8 | 小招 <65 =8 | 中招 65~99 =6 | 大招 100~149 =4
    终极招 ≥150 =2（破坏光线/自爆/大爆炸）| 吸血类(drain)=3（反"永不动盾"）
用法（本地）: PKM_DB_ENGINE=sqlite python migrate_v5_battle.py
用法（ECS） : backend/ 下 venv python 直接运行（sqlite 引擎）。
"""
import os
import sqlite3
import sys

DBFILE = os.environ.get("PKM_SQLITE_FILE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "pkm.sqlite3")))


def pp_for(power, effect_type):
    if (effect_type or "") == "drain":
        return 3
    if power >= 150:
        return 2
    if power >= 100:
        return 4
    if power >= 65:
        return 6
    return 8  # 含变化招（power=0）


def main():
    if os.environ.get("PKM_DB_ENGINE", "mysql") != "sqlite" and "--force" not in sys.argv:
        raise SystemExit("本迁移脚本仅用于 sqlite 本地库；ECS 上请显式 PKM_DB_ENGINE=sqlite")
    conn = sqlite3.connect(DBFILE)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(skill_base)")}
    if "priority" not in cols:
        conn.execute("ALTER TABLE skill_base ADD COLUMN priority INT DEFAULT 0")
        print("ADDED skill_base.priority")
    else:
        print("SKIP  skill_base.priority 已存在")
    if "max_pp" not in cols:
        conn.execute("ALTER TABLE skill_base ADD COLUMN max_pp INT DEFAULT 8")
        print("ADDED skill_base.max_pp")
    else:
        print("SKIP  skill_base.max_pp 已存在")
    # 数据灌入（幂等重跑无害）
    conn.execute("UPDATE skill_base SET priority=0")
    conn.execute("UPDATE skill_base SET priority=1 WHERE skill_name='电光一闪'")
    rows = conn.execute("SELECT id, power, effect_type FROM skill_base").fetchall()
    n = 0
    for sid, power, et in rows:
        conn.execute("UPDATE skill_base SET max_pp=? WHERE id=?",
                     (pp_for(int(power or 0), et), sid))
        n += 1
    conn.commit()
    # 校验
    p1 = conn.execute("SELECT skill_name FROM skill_base WHERE priority>0").fetchall()
    dist = dict(conn.execute("SELECT max_pp, COUNT(*) FROM skill_base GROUP BY max_pp").fetchall())
    conn.close()
    print(f"priority>0: {[r[0] for r in p1]}  | max_pp 分布: {dist} | 共灌 {n} 招")
    print("MIGRATE OK", DBFILE)


if __name__ == "__main__":
    main()
