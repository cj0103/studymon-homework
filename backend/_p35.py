import sys
sys.path.insert(0, '/opt/pkmn-homework/backend')
from app import db
print('--- 背包 ---')
for r in db.q("SELECT tp.pokedex_no, tp.level, tp.is_in_team, pb.name, pb.exp_group "
              "FROM trainer_pokemon tp JOIN pokemon_base pb ON pb.pokedex_no=tp.pokedex_no "
              "WHERE tp.student_id=1 ORDER BY tp.level"):
    print(r['pokedex_no'], r['name'], r['exp_group'], 'Lv', r['level'], 'team' if r['is_in_team'] else '')
print('--- 学生 ---')
print(db.q('SELECT * FROM student_user WHERE id=1'))
print('--- 经验流水汇总 ---')
print(db.q("SELECT reason, COUNT(*) n, SUM(exp_delta) s FROM exp_log GROUP BY reason"))
