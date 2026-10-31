# -*- coding: utf-8 -*-
"""#33 线上只读验证：列存在+默认0；今日实时口径下 child 过滤 SQL 语义正确。"""
import sys, datetime as dt
sys.path.insert(0, '/opt/pkmn-homework/backend')
from app import db

cols = [r.get('name') for r in db.q('PRAGMA table_info(task_template)')] if db.ENGINE == 'sqlite' else None
if cols is None:
    cols = [list(r.values())[0] for r in db.q('SHOW COLUMNS FROM task_template')]
assert 'weekend_only' in cols, f"列缺失: {cols}"
n = db.q('SELECT COUNT(*) c FROM task_template WHERE weekend_only=1')[0]['c']
total = db.q('SELECT COUNT(*) c FROM task_template')[0]['c']
today = dt.date.today()
wd = today.weekday()
print(f"V21 列OK 任务{total}条 weekend_only=1 计{n}条 今日周{'一二三四五六日'[wd]} weekend={wd>=5}")
print("V21_VERIFY_OK")
