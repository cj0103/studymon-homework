# -*- coding: utf-8 -*-
"""部署#31 线上只读验证：队形 3/3/3/4x5 + 三处挪动落位 + 区2-8答案怪≥2。"""
import sys, json
sys.path.insert(0, '/opt/pkmn-homework/backend')
from app import db

fails = []

sizes = []
gb = {r['id']: r['sort'] for r in db.q('SELECT id, sort FROM gym_base')}
for t in db.q('SELECT * FROM gym_trainer_team'):
    team = json.loads(t['pokemon_json'] or '[]')
    sizes.append((gb[t['gym_id']], len(team)))
sizes.sort()
got = [n for _, n in sizes]
if got != [3, 3, 3, 4, 4, 4, 4, 4]:
    fails.append(f'队形不符: {got}')

pool = {}
for r in db.q('SELECT region_id, pokedex_no FROM region_wild_pokemon'):
    pool.setdefault(r['pokedex_no'], set()).add(r['region_id'])
moves = {37: {4}, 92: {5}, 127: {6}, 54: {7}, 58: {8}, 140: {8}}
for pid, want in moves.items():
    if pool.get(pid) != want:
        fails.append(f'pid{pid} 落位 {pool.get(pid)} != {want}')

eff = {(r['attack_type'], r['defend_type']): float(r['rate'])
       for r in db.q('SELECT attack_type, defend_type, rate FROM type_effect')}
GYM_TYPE = {2: "水", 3: "电", 4: "草", 5: "毒", 6: "超能力", 7: "火", 8: "地面"}
ptypes = {r['pokedex_no']: ({r['type1'] or ''} | {r['type2'] or ''}) - {''}
          for r in db.q('SELECT pokedex_no, type1, type2 FROM pokemon_base')}
reg_rows = db.q('SELECT region_id, pokedex_no FROM region_wild_pokemon')
for reg in range(2, 9):
    gt = GYM_TYPE[reg]
    ans = [r['pokedex_no'] for r in reg_rows if r['region_id'] == reg
           and any(t == gt or eff.get((t, gt), 1.0) > 1
                   for t in ptypes.get(r['pokedex_no'], set()))]
    print(f'REG{reg}({gt}) 答案怪 {len(ans)}: {sorted(ans)}')
    if len(ans) < 2:
        fails.append(f'区{reg}({gt}) 答案怪 {len(ans)} < 2')

total = len(reg_rows)
if total != 82:
    fails.append(f'野生总数 {total} != 82')

if fails:
    print('V20_VERIFY_FAIL', fails)
else:
    print('V20_VERIFY_OK total=82 sizes=', got)
