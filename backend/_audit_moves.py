# -*- coding: utf-8 -*-
"""审计：当前库 pokemon_skill_learn vs veekun 原作（升级∪TM）——
1) 逐只列出"原作完全学不了"的招（升级/TM 都没有 → 家族借招/兜底招）
2) 其中标注跨属性招（与自身两属性都不同）——重点问题项
用法: python _audit_moves.py [pokedex_no ...]  # 不带参数=全151审计摘要"""
import csv, sqlite3, sys
from collections import defaultdict

V = '../assets/veekun-csv/'
pkmoves = list(csv.DictReader(open(V + 'pokemon_moves.csv', encoding='utf-8-sig')))
moves = {int(r['id']): r for r in csv.DictReader(open(V + 'moves.csv', encoding='utf-8-sig'))}
zh = {int(r['move_id']): r['name'] for r in csv.DictReader(open(V + 'move_names.csv', encoding='utf-8-sig'))
      if r['local_language_id'] == '12'}
EX = {"transform", "metronome", "mimic", "substitute", "mirror-move", "disable",
      "conversion", "conversion-2", "sleep-talk", "sketch", "reflect-type",
      "counter", "seismic-toss", "night-shade", "flail", "bide", "haze", "mist",
      "bind", "wrap", "fire-spin", "clamp", "whirlpool",
      "dig", "fly", "sky-attack", "fury-attack", "twineedle", "skull-bash",
      "splash", "struggle", "teleport", "focus-energy", "leech-seed", "ingrain",
      "barrage", "twister", "camouflage", "roar", "whirlwind"}
inst = {mid for mid, m in moves.items() if m['generation_id'] == '1' and m['identifier'] not in EX}

learn = defaultdict(dict)
tms = defaultdict(set)
for r in pkmoves:
    vg = r['version_group_id']
    if vg not in ('1', '2', '3'):
        continue
    no = int(r['pokemon_id'])
    if not (1 <= no <= 151):
        continue
    mid = int(r['move_id'])
    if mid not in inst:
        continue
    if r['pokemon_move_method_id'] == '1':
        if int(r['level'] or 0) > 0:
            if vg == '1':
                learn[no][mid] = int(r['level'])
            elif mid not in learn[no]:
                learn[no][mid] = int(r['level'])
    elif r['pokemon_move_method_id'] == '4' and vg in ('1', '2'):
        tms[no].add(mid)

TYPE_ID2CN = {"1": "一般", "2": "格斗", "3": "飞行", "4": "毒", "5": "地面", "6": "岩石",
              "7": "虫", "8": "幽灵", "9": "钢", "10": "火", "11": "水", "12": "草",
              "13": "电", "14": "超能力", "15": "冰", "16": "龙", "17": "恶"}

db = sqlite3.connect('pkm.sqlite3')
db.row_factory = sqlite3.Row
skills = {r['id']: r for r in db.execute("SELECT id, skill_name, skill_type FROM skill_base")}
pname = {r['pokedex_no']: r['name'] for r in db.execute("SELECT pokedex_no, name FROM pokemon_base")}
ptypes = {r['pokedex_no']: {r['type1'], r['type2']} for r in
          db.execute("SELECT pokedex_no, type1, type2 FROM pokemon_base")}

only = [int(x) for x in sys.argv[1:]]
target = only if only else range(1, 152)

foreign_total = cross_total = 0
rows_report = []
for no in target:
    if no == 25:
        continue                    # 皮卡丘冻结规则=雷丘池并入，属设计内
    db_moves = {r['skill_id'] for r in db.execute(
        "SELECT skill_id FROM pokemon_skill_learn WHERE pokedex_no=?", (no,))}
    original = set(learn[no]) | set(tms[no])
    # 库里的 skill_name → veekun mid
    name2mid = {moves[m]['identifier']: m for m in inst}
    orig_names = {zh.get(m, moves[m]['identifier']) for m in original}
    extras = []
    for sid in db_moves:
        s = skills.get(sid)
        if not s:
            continue
        if s['skill_name'] not in orig_names:
            mine = ptypes.get(no, set())
            cross = s['skill_type'] not in mine
            extras.append((s['skill_name'], s['skill_type'], cross))
    # 过滤审计噪音：皮卡丘/雷丘冻结规则（雷丘池并入=设计内）
    if no in (25, 26):
        continue
    if extras:
        foreign_total += len(extras)
        cx = [e for e in extras if e[2]]
        cross_total += len(cx)
        rows_report.append((no, pname.get(no, no),
                            sorted(e[0] + ('⚡跨属性' if e[2] else '') for e in extras)))

if only:
    for no, nm, ex in rows_report:
        print(f"#{no} {nm}: {ex}")
    if not rows_report:
        print("这些编号与原作完全一致（升级∪TM）")
else:
    print(f"存在非原作招的宝可梦数: {len(rows_report)} / 151")
    print(f"非原作招总数: {foreign_total}，其中跨属性: {cross_total}")
    for no, nm, ex in rows_report[:40]:
        print(f"  #{no} {nm}: {ex}")
    if len(rows_report) > 40:
        print(f"  ...（其余 {len(rows_report)-40} 只略）")
