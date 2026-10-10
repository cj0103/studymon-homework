# -*- coding: utf-8 -*-
"""v3 馆主配招重建：技能表重建后，gym_trainer_team 的显式 moves 可能指向已改名/剔除的旧行。
策略（原作风）：每只从 pokedex_no 的 v3 学习表按原作升级等级段位挑4招——
  ① 原作等级 ≤ 该只等级：段位(等级高)优先，同段主题属性优先、攻击招优先；
  ② 不足4只时放宽（允许超前1档，模拟道馆强训）；
  ③ 再不足从无等级要求招兜底（防零招）。
学习等级是 v3 重排后的节奏值，仅作段位排序参考，不再直接决定招式内容。
用法: PKM_DB_ENGINE=sqlite python rebuild_gyms_v3.py          # 干跑
      PKM_DB_ENGINE=sqlite PKM_APPLY=1 python rebuild_gyms_v3.py
"""
import json
import os
import sqlite3
from collections import Counter

DBFILE = os.environ.get("PKM_SQLITE_FILE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "pkm.sqlite3")))


def pick4(cur, pid, cap, theme_types):
    rows = cur.execute(
        """SELECT l.skill_id, l.learn_level, s.skill_type, s.power, s.effect_type
           FROM pokemon_skill_learn l JOIN skill_base s ON s.id=l.skill_id
           WHERE l.pokedex_no=? ORDER BY l.learn_level DESC, s.power DESC""", (pid,)).fetchall()
    def key(r):                                   # 主题属性优先 → 攻击招优先 → 等级高、威力大
        return (0 if r["skill_type"] in theme_types else 1,
                0 if r["power"] > 0 else 1, -r["learn_level"], -r["power"])
    chosen, seen = [], set()
    for slack in (0, 6, 99):                      # 等级达标 → 超前1档 → 全放开
        for r in sorted(rows, key=key):
            if r["skill_id"] in seen:
                continue
            if r["learn_level"] <= cap + slack:
                chosen.append(r["skill_id"]); seen.add(r["skill_id"])
            if len(chosen) == 4:
                return chosen
        if len(chosen) == 4:
            break
    return chosen


def main():
    apply = os.environ.get("PKM_APPLY", "0") == "1"
    conn = sqlite3.connect(DBFILE)
    conn.row_factory = sqlite3.Row
    changed = 0
    for g in conn.execute("SELECT gym_id, pokemon_json FROM gym_trainer_team ORDER BY gym_id").fetchall():
        team = json.loads(g["pokemon_json"])
        # 主题属性：全队出现最多的属性
        from collections import Counter
        cnt = Counter()
        pb = {r["pokedex_no"]: (r["type1"], r["type2"]) for r in
              conn.execute("SELECT pokedex_no, type1, type2 FROM pokemon_base")}
        for t in team:
            for x in pb.get(t["pokedex_no"], ()):
                if x:
                    cnt[x] += 1
        theme = {t for t, n in cnt.most_common(1)}
        moved = False
        for t in team:
            new = pick4(conn, t["pokedex_no"], t["level"], theme)
            if new and new != (t.get("moves") or []):
                t["moves"] = new; moved = True
        if moved:
            changed += 1
            names = {r["id"]: r["skill_name"] for r in conn.execute("SELECT id, skill_name FROM skill_base")}
            print("gym", g["gym_id"], "theme=", theme,
                  [(t["pokedex_no"], [names.get(m, "?") for m in (t.get("moves") or [])]) for t in team])
            if apply:
                conn.execute("UPDATE gym_trainer_team SET pokemon_json=? WHERE gym_id=?",
                             (json.dumps(team, ensure_ascii=False), g["gym_id"]))
    if apply:
        conn.commit()
    conn.close()
    print(("APPLIED" if apply else "DRY"), "重配馆主数:", changed)


if __name__ == "__main__":
    main()
