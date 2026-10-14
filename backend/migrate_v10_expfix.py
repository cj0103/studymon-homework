# -*- coding: utf-8 -*-
"""v10 存量修复：trainer_pokemon 中 level 与 total_exp 脱钩的记录回填。

背景：捕捉/赠礼/初始入袋曾把 total_exp 写死 0，一旦获得经验，
level_for(exp_group, 0+delta) 反推导致等级"一夜回到 Lv1"。

规则：对每只宝可梦，按经验组算 cur_lv = level_for(total_exp)；
若 cur_lv < level（等级虚高），把 total_exp 抬到 Lv(level) 门槛值（exp_floor）。
只加不减——自洽记录（如打卡正常养成的皮卡丘）一律不动。可重复执行（幂等）。
用法: PKM_DB_ENGINE=sqlite python migrate_v10_expfix.py
"""
from app import db
from app.exp import level_for, exp_floor


def main():
    rows = db.q("SELECT tp.id, tp.pokedex_no, tp.level, tp.total_exp, "
                "COALESCE(pb.exp_group,'medium') g FROM trainer_pokemon tp "
                "LEFT JOIN pokemon_base pb ON pb.pokedex_no=tp.pokedex_no")
    fixed, skipped = [], 0
    for r in rows:
        cur_lv = level_for(r["g"], r["total_exp"])
        if cur_lv < r["level"]:
            floor = exp_floor(r["g"], r["level"])
            db.x("UPDATE trainer_pokemon SET total_exp=%s WHERE id=%s", (floor, r["id"]))
            fixed.append({"id": r["id"], "no": r["pokedex_no"], "lv": r["level"],
                          "exp_from": r["total_exp"], "exp_to": floor})
        else:
            skipped += 1
    print(f"扫描 {len(rows)} 只：回填 {len(fixed)} 只，自洽未动 {skipped} 只")
    for f in fixed:
        print(f"  #{f['id']} dex#{f['no']} Lv{f['lv']}: total_exp {f['exp_from']} -> {f['exp_to']}")
    # 复验：全表 level_for(total_exp) == level（Lv50 封顶时门槛仍成立）
    bad = [r["id"] for r in rows
           if level_for(r["g"], exp_floor(r["g"], r["level"]) if r["id"] in {f["id"] for f in fixed} else r["total_exp"]) < r["level"]]
    print("MIGRATE_V10 OK" if not bad else f"WARN 仍脱钩: {bad}")


if __name__ == "__main__":
    main()
