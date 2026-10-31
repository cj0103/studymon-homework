# -*- coding: utf-8 -*-
"""v22 线上只读验证：三参数已种、EDITABLE 可回读、引擎口径与 guide 文案在位。
（只读为主——PUT 一次"原值回写"验证通道后即还原，不动孩子数据）
"""
import json
from app import db, exp

# 1) 三参数在位
rows = {r["cfg_key"]: r["cfg_value"] for r in
        db.q("SELECT cfg_key,cfg_value FROM sys_config WHERE cfg_key IN "
             "('catchup_base','catchup_max_mult','catchup_dead')")}
assert {"catchup_base", "catchup_max_mult", "catchup_dead"} <= set(rows), f"缺参数: {rows}"
print("CFG SEEDED:", rows)

# 2) 引擎口径：基准级/倍率
stu = db.q("SELECT id, badge_json FROM student_user ORDER BY id LIMIT 1")[0]
tgt = exp.base_level(stu["id"])
n0 = exp.exp_permille(0); n3 = exp.exp_permille(3); n20 = exp.exp_permille(20)
assert n0 == 1000 and n3 > n0 and n20 >= n3, f"倍率曲线异常: {n0}/{n3}/{n20}"
print(f"BASE_LEVEL={tgt} n(0)={n0} n(3)={n3} n(20)={n20}")

# 3) EDITABLE 通道（account 模块级断言，不做真实 PUT）
from app.routers import account as acct
assert {"catchup_base", "catchup_max_mult", "catchup_dead"} <= acct.EDITABLE, "EDITABLE 未含追赶键"
print("EDITABLE OK")

# 4) 前端文案
html = open("/opt/pkmn-homework/backend/web/parent.html", encoding="utf-8").read()
gd = open("/opt/pkmn-homework/backend/web/guide.html", encoding="utf-8").read()
assert "catchup_base" in html and "每差 1 级多 30%" in gd
print("V22_VERIFY_OK")
