# -*- coding: utf-8 -*-
"""端到端冒烟测试：登录→组队→打卡→审批→经验→升级→驳回→战斗闸门
用法（先起服务）: python smoke_test.py
"""
import json
import os
import urllib.request
import urllib.parse
import datetime as dt

B = "http://127.0.0.1:8471/api"
FAILS = []
# 本机可能存有系统代理（HTTP_PROXY），localhost 必须直连，否则 502
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def call(method, path, body=None, token=None, expect=200, note=""):
    req = urllib.request.Request(B + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with _opener.open(req, data) as r:
            code, txt = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        code, txt = e.code, e.read().decode()
    ok = code == expect
    if not ok:
        FAILS.append(f"{note or path} {method} {path} -> {code} (期望{expect}) {txt[:150]}")
    print(f"[{'PASS' if ok else 'FAIL'}] {note or path}: {code} {txt[:180]}")
    try:
        return json.loads(txt)
    except Exception:
        return {"_raw": txt}

print("========== 1. 健康与家长登录 ==========")
call("GET", "/health", note="健康检查")
pt = call("POST", "/parent/login", {"phone": "13800000000", "password": "admin123"}, note="家长登录(兜底)")
PTK = pt["token"]
assert PTK and pt.get("students"), "家长 token/学生列表缺失"

print("========== 1b. 设备令牌链路 ==========")
devs = call("GET", "/parent/devices", token=PTK, note="设备列表(种子3条)")
assert len([d for d in devs if d["role"] == "kid"]) == 1 and len([d for d in devs if d["role"] == "parent"]) == 2
kid_k = [d["token"] for d in devs if d["role"] == "kid"][0]
par_k = [d["token"] for d in devs if d["role"] == "parent"][0]
rj = call("GET", f"/resolve/{kid_k}", note="孩子令牌resolve→直发JWT")
STK = rj["token"]
assert rj["role"] == "kid" and STK
pj = call("GET", f"/resolve/{par_k}", note="家长令牌resolve→仅hint")
assert pj["role"] == "parent" and "token" not in pj, "家长链接不应直接发token"
call("POST", "/parent/unlock", {"token": par_k, "pin": "wrong"}, expect=400, note="错误PIN应400")
pu = call("POST", "/parent/unlock", {"token": par_k, "pin": "admin123"}, note="家长PIN解锁")
assert pu.get("token"), "PIN解锁应发JWT"
call("GET", "/resolve/" + urllib.parse.quote("par_不存在的令牌"), expect=404, note="伪造令牌404")
# kid 令牌直接当 Bearer 也可用（kid_auth 双通道）
call("GET", "/child/tasks", token=kid_k, note="kid令牌直接作Bearer")

print("========== 1c. 传统孩子登录（兜底通道） ==========")
st = call("POST", "/student/login", {"student_id": 1, "pin": "1234"}, note="孩子ID+PIN登录")
call("POST", "/student/login", {"student_id": 1, "pin": "0000"}, expect=400, note="错误PIN应400")

print("========== 2. 任务菜单与组队 ==========")
tasks = call("GET", "/child/tasks", token=STK, note="孩子任务菜单")
assert len(tasks) == 8, "任务应为8个"
mons = call("GET", "/child/pokemon", token=STK, note="我的宝可梦")
assert len(mons) == 1 and mons[0]["pokedex_no"] == 25, "开档礼赠应为 1 只皮卡丘"
tids = [m["id"] for m in mons]
call("POST", "/child/team", {"team_ids": tids}, token=STK, note="皮卡丘上阵")
call("POST", "/child/team", {"team_ids": tids + [2, 3, 99]}, token=STK, expect=400, note="越权/超3只应400")
mons2 = call("GET", "/child/pokemon", token=STK, note="组队后")
assert all(m["is_in_team"] for m in mons2), "三只都应在队中"
for m in mons2:
    assert m["known_details"] and m["known"], f"{m['name']} 无已学技能袋"
call("GET", "/child/pokedex", token=STK, note="图鉴(151)")

print("========== 3. 打卡 → 审批 → 经验 ==========")
call("GET", "/child/today", token=STK, note="今日打卡状态")
items = [tasks[0]["id"], tasks[1]["id"], tasks[2]["id"], tasks[5]["id"]]
call("POST", "/child/checkin", {"items": items}, token=STK, note="孩子提交打卡(4项)")
call("POST", "/child/checkin", {"items": items}, token=STK, expect=400, note="重复提交应400")
pend = call("GET", "/parent/pending", token=PTK, note="家长待审")
assert pend, "待审列表不应为空"
today_rec = [r for r in pend if str(r["task_date"]) == str(dt.date.today())][0]
cid, quick = today_rec["id"], today_rec["quick_win"]
apr = call("POST", "/parent/approve", {"checkin_id": cid, "adjusted": items, "penalty": 10},
           token=PTK, note="扣减批准-10(没理书包)")
c1 = apr.get("exp_final", 0)
expect = 230 + (46 if quick else 0) - 10   # 引擎（千分比整数）：230+46-10=266
print(f"    >> 首日实发 exp_final={c1}, 预期={expect} (快手={quick})")
assert c1 == expect, f"经验结算错误: {c1} != {expect}"
mons3 = call("GET", "/child/pokemon", token=STK, note="审批后经验核对")
tot = sum(m["total_exp"] for m in mons3)
print(f"    >> 队伍经验合计={tot} (应≈{c1}, 平分3人)")
assert abs(tot - c1) <= 3, f"经验分配不符: {tot} vs {c1}"
call("POST", "/parent/approve", {"checkin_id": cid}, token=PTK, expect=400, note="重复审批应400")

print("========== 4. 待审直接驳回（未发不扣） ==========")
import sqlite3, os
db = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pkm.sqlite3"))
yd = (dt.date.today() - dt.timedelta(days=1)).isoformat()
cur = db.execute("INSERT INTO checkin_record(student_id,task_date,item_json,status,quick_win) VALUES(1,?,?,1,0)",
                 (yd, json.dumps([items[0]])))
rid2 = cur.lastrowid
db.commit(); db.close()
call("POST", "/parent/reject", {"checkin_id": rid2, "reason": "字迹潦草重做"}, token=PTK, note="驳回昨日待审(带原因)")
mons4 = call("GET", "/child/pokemon", token=STK, note="驳回后经验不变")
assert sum(m["total_exp"] for m in mons4) == tot, "驳回误扣经验！"
h = call("GET", "/parent/history", token=PTK, note="打卡历史(含驳回+扣批)")
assert any(r["status"] == 4 for r in h) and any(r["status"] == 3 for r in h), "历史应含驳回与扣批记录"

print("========== 5. 已批记录反向撤销（驳回已发经验） ==========")
call("POST", "/parent/reject", {"checkin_id": cid, "reason": "撤销测试"}, token=PTK, note="驳回今日已批记录")
mons5 = call("GET", "/child/pokemon", token=STK, note="撤销后经验应扣回")
back = sum(m["total_exp"] for m in mons5)
print(f"    >> 撤销后队伍经验={back} (应≈0)")
assert back <= 3, f"撤销未扣回: {back}"
# 恢复：重新init数据太破坏，改用直接补一笔批准场景留待前端联调

print("========== 6. 道馆/野生（战斗闸门） ==========")
avail = call("GET", "/child/battle/availability", token=STK, note="战斗可用性")
weekend = dt.date.today().weekday() >= 5
assert avail["weekend"] == weekend, "weekend 标志错误"
call("PUT", "/config", {"key": "battle_weekday_open", "value": "0"}, token=PTK, note="切'仅周末'")
exp_gym = 200 if weekend else 400
call("POST", "/child/battle/gym", {}, token=STK, expect=exp_gym,
     note=f"仅周末模式-道馆（{'周末放行' if weekend else '工作日拦截'}）")
call("POST", "/child/battle/wild", {}, token=STK, expect=exp_gym, note="仅周末模式-野生")
call("PUT", "/config", {"key": "battle_weekday_open", "value": "1"}, token=PTK, note="恢复测试期常开")
if weekend:
    for mv_idx in range(1):
        pass
    r1 = call("POST", "/child/battle/act", {"action": "attack", "skill_id": None}, token=STK,
              expect=400, note="无效招式应400")
else:
    print("    今日工作日：闸门400已验证；战斗回合逻辑走代码审查+周末实测")

print("========== 7. 配置与设备签发 ==========")
cfg = call("GET", "/config", token=PTK, note="读配置")
assert cfg.get("daily_base_exp") in ("230", 230), f"定额应为230, 实际{cfg.get('daily_base_exp')}"
call("PUT", "/config", {"key": "daily_base_exp", "value": "240"}, token=PTK, note="改定额240")
cfg2 = call("GET", "/config", token=PTK, note="确认已改")
assert cfg2.get("daily_base_exp") == "240"
call("PUT", "/config", {"key": "jwt_secret", "value": "x"}, token=PTK, expect=400, note="非白名单应400")
call("PUT", "/config", {"key": "daily_base_exp", "value": "230"}, token=PTK, note="改回230")
iss = call("POST", "/parent/device/issue", {"role": "kid", "label": "备用平板", "student_id": 1},
           token=PTK, note="签发新孩子令牌")
new_k = iss["token"]
call("GET", f"/child/today", token=new_k, note="新令牌立即可用")
call("PUT", f"/parent/device/{new_k}", {"enabled": False}, token=PTK, note="吊销新令牌")
call("GET", f"/child/today", token=new_k, expect=401, note="吊销后应401")

print("========== 8. 成员管理 & 战斗开关 ==========")
mem = call("GET", "/parent/members", token=PTK, note="成员列表")
assert mem["kids"][0]["kid_token"], "成员页应带出孩子链接"
call("PUT", "/parent/child/1", {"name": "小训练家"}, token=PTK, note="改昵称")
call("PUT", "/parent/child/1", {"name": "  "}, token=PTK, expect=400, note="空昵称应400")
call("PUT", "/parent/child/1", {"pin": "12"}, token=PTK, expect=400, note="短PIN应400")
call("PUT", "/parent/child/1", {"name": "训练家", "pin": "1234"}, token=PTK, note="改昵称为训练家")
rj2 = call("GET", f"/resolve/{mem['kids'][0]['kid_token']}", note="resolve显示新昵称")
assert rj2["name"] == "训练家", "昵称未生效"
call("PUT", "/parent/child/1", {"name": "小训练家"}, token=PTK, note="改回小训练家")
rt = call("POST", "/parent/child/1/regen-token", {}, token=PTK, note="重新生成孩子链接")
call("GET", "/child/today", token=mem["kids"][0]["kid_token"], expect=401, note="旧孩子链接应即刻失效")
call("GET", "/child/today", token=rt["token"], note="新孩子链接可用")
call("PUT", "/parent/self", {"old_password": "wrong", "password": "newpass123"}, token=PTK, expect=400, note="原密码错误应400")
call("PUT", "/config", {"key": "battle_weekday_open", "value": "1"}, token=PTK, note="开学习日战斗")
av2 = call("GET", "/child/battle/availability", token=rt["token"], note="开放后availability")
assert av2["can_battle"] is True, "开关开启后 can_battle 应为 True"
g2 = call("POST", "/child/battle/gym", {}, token=rt["token"], note="学习日可开道馆战(开关生效)")
call("POST", "/child/battle/act", {"action": "run"}, token=rt["token"], note="逃跑结束会话")
call("PUT", "/config", {"key": "battle_weekday_open", "value": "0"}, token=PTK, note="关回仅周末")
# 周末当天开关关闭仍放行（原作口径），仅工作日才应 400 拦截
call("POST", "/child/battle/gym", {}, token=rt["token"],
     expect=400 if not weekend else 200, note="关闭后学习日应拦截（周末放行）")
if not weekend:
    # 上一步拦截返回 400 未建会话，此处再逃跑必然 400——本就是负断言（会话不存在）
    call("POST", "/child/battle/act", {"action": "run"}, token=rt["token"], expect=400,
         note="拦截未建会话-逃跑应400(8节)")
call("PUT", "/config", {"key": "battle_weekday_open", "value": "1"}, token=PTK, note="测试期默认恢复开放")
mons5 = call("GET", "/child/pokemon", token=rt["token"], note="宝可梦卡含四维+招式详情")
assert mons5[0]["move_details"] and mons5[0]["stats_names"], "缺 move_details/stats_names"
call("POST", "/child/team", {"team_ids": []}, token=rt["token"], note="全部撤下(空队伍)")
mon6 = call("GET", "/child/pokemon", token=rt["token"], note="撤下后 is_in_team 全0")
assert not any(m["is_in_team"] for m in mon6), "撤下未生效"
call("POST", "/child/team", {"team_ids": [1]}, token=rt["token"], note="皮卡丘重新上阵")

print("========== 9. 设备改名/删除 & 技能袋+自主选技(v2) ==========")
devs2 = call("GET", "/parent/devices", token=PTK, note="设备列表")
tgt = [d for d in devs2 if d["role"] == "parent"][0]["token"]
call("PUT", f"/parent/device/{tgt}", {"label": "爸爸手机Pro"}, token=PTK, note="设备改名")
devs3 = call("GET", "/parent/devices", token=PTK, note="确认改名生效")
assert any(d["label"] == "爸爸手机Pro" for d in devs3), "改名未生效"
iss2 = call("POST", "/parent/device/issue", {"role": "kid", "label": "待删除", "student_id": 1},
            token=PTK, note="签发临时链接")
call("DELETE", f"/parent/device/{iss2['token']}", token=PTK, note="删除临时链接")
devs4 = call("GET", "/parent/devices", token=PTK, note="确认已删除(非仅吊销)")
assert not any(d["token"] == iss2["token"] for d in devs4), "删除未生效"

import sqlite3 as _sq, os as _os
_db = _sq.connect(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "pkm.sqlite3"))
moves_l5 = json.loads(_db.execute("SELECT learned_skill_json FROM trainer_pokemon WHERE id=1").fetchone()[0])
_dfs_id = _db.execute("SELECT id FROM skill_base WHERE skill_name='电光一闪'").fetchone()[0]
# 把首发皮卡丘提到 Lv14（电光一闪已入学习池），验证到级新招自动入袋、不遗忘
_db.execute("UPDATE trainer_pokemon SET total_exp=5000, level=14 WHERE id=1"); _db.commit(); _db.close()
mons7 = call("GET", "/child/pokemon", token=rt["token"], note="Lv14 皮卡丘(读时自动回填已学袋)")
seed = [m for m in mons7 if m["id"] == 1][0]
kn = seed["known"]
print(f"    >> Lv5携带={moves_l5} → Lv14已学袋={kn} 携带={seed['moves']} (电光一闪id={_dfs_id})")
assert _dfs_id in kn, "到级新招(电光一闪)未自动入袋"
assert set(moves_l5) <= set(kn), "已学袋必须包含此前已学技能（永不遗忘）"
assert len(seed["moves"]) <= 4, "携带技能不能超过4个"
# 幂等：再读一次已学袋不变
mons7b = call("GET", "/child/pokemon", token=rt["token"], note="重复读取")
assert [m for m in mons7b if m["id"] == 1][0]["known"] == kn, "已学袋回填不幂等"
# v4：/child/pokemon 应带出 sealed 字段（当前全为 0）
assert all("sealed" in m for m in mons7b), "/child/pokemon 缺 sealed 字段（migrate/DDL 未生效？）"
assert all(m["sealed"] == 0 for m in mons7b), "普通宝可梦 sealed 应为 0"
# 孩子自主选技
all_moves = [k["id"] for k in seed["known_details"]]
assert len(all_moves) == len(kn), "known_details 与 known 数量一致"
pick = all_moves[:2] + all_moves[-1:]
call("POST", "/child/pokemon/1/moves", {"moves": pick}, token=rt["token"], note="自主选3个上场")
mons7c = call("GET", "/child/pokemon", token=rt["token"], note="确认携带已更新")
assert sorted([m for m in mons7c if m["id"] == 1][0]["moves"]) == sorted(pick), "携带未更新"
call("POST", "/child/pokemon/1/moves", {"moves": all_moves[:5] if len(all_moves) >= 5 else all_moves + [all_moves[0]]},
     token=rt["token"], expect=400, note="超4个应拒绝")
call("POST", "/child/pokemon/1/moves", {"moves": [9999]}, token=rt["token"], expect=400, note="未学技能应拒绝")
call("POST", "/child/pokemon/1/moves", {"moves": []}, token=rt["token"], expect=400, note="空技能应拒绝")
call("POST", "/child/pokemon/999/moves", {"moves": [33]}, token=rt["token"], expect=404, note="别人的宝可梦应404")
print("    >> 已学袋只增不减 + 自主选技校验 OK")

print("========== 10. 到级自动进化（皮卡丘不进化 + 御三家进化） ==========")
import sqlite3 as _sq2, os as _os2
_db2 = _sq2.connect(_os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), "pkm.sqlite3"))
_today_iso = dt.date.today().isoformat()
# A. 皮卡丘为"不进化伙伴"：满级也不进化，且 pkm_evolution 无 25→26 记录
assert not _db2.execute("SELECT 1 FROM pkm_evolution WHERE from_no=25").fetchone(), "皮卡丘不应有进化链"
_db2.execute("UPDATE trainer_pokemon SET pokedex_no=25, total_exp=1000000, level=50 WHERE id=1")
_today_iso_rows = None
_db2.execute("DELETE FROM checkin_record WHERE task_date=?", (_today_iso,))
_db2.commit(); _db2.close()
items_e = [tasks[0]["id"], tasks[1]["id"]]
call("POST", "/child/checkin", {"items": items_e}, token=rt["token"], note="不进化测试-提交打卡")
pend_e = call("GET", "/parent/pending", token=PTK, note="不进化测试-待审")
rec_e = [r for r in pend_e if str(r["task_date"]) == str(dt.date.today())][0]
apr_e = call("POST", "/parent/approve", {"checkin_id": rec_e["id"], "penalty": 0},
             token=PTK, note="批准→皮卡丘不应进化")
assert not apr_e.get("evolved"), f"皮卡丘被误进化: {apr_e.get('evolved')}"
det_p = call("GET", "/child/pokemon/1", token=rt["token"], note="皮卡丘详情(无进化预告)")
assert det_p["pokedex_no"] == 25 and det_p.get("evolution") is None, "皮卡丘应保持不进化且无预告"
print("    >> 不进化伙伴皮卡丘 OK（Lv50 仍皮卡丘，evolution=null）")
# B. 进化链路整体仍正常：借一只野外妙蛙种子(slow组 Lv16=5120)走完整流程
_db2b = _sq2.connect(_os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), "pkm.sqlite3"))
sid_ = _db2b.execute("SELECT id FROM student_user LIMIT 1").fetchone()[0]
_db2b.execute("INSERT INTO trainer_pokemon(student_id,pokedex_no,level,total_exp,"
              "learned_skill_json,known_skill_json,is_in_team) VALUES(?,1,15,5040,'[]','[]',0)",
              (sid_,))
_seed_id = _db2b.execute("SELECT last_insert_rowid()").fetchone()[0]
# 清掉今日记录后，队伍只留这只妙蛙种子出战（独享经验+276跨5120）
_db2b.execute("DELETE FROM checkin_record WHERE task_date=?", (_today_iso,))
_db2b.execute("UPDATE trainer_pokemon SET is_in_team=0 WHERE id!=?", (_seed_id,))
_db2b.execute("UPDATE trainer_pokemon SET is_in_team=1, slot=0 WHERE id=?", (_seed_id,))
_db2b.commit(); _db2b.close()
det0 = call("GET", f"/child/pokemon/{_seed_id}", token=rt["token"], note="Lv15 妙蛙种子(进化预告)")
assert det0.get("evolution") and det0["evolution"]["min_level"] == 16 and det0["evolution"]["name"] == "妙蛙草", "详情页缺进化预告"
moves_before = det0["moves"]
if not moves_before:
    # ensure_known 兜底回填 learned 发生在响应读取之后（先读后更），二次读取取回填结果
    det0 = call("GET", f"/child/pokemon/{_seed_id}", token=rt["token"], note="Lv15 妙蛙种子(兜底携带二次读取)")
    moves_before = det0["moves"]
assert moves_before, "Lv15 妙蛙种子应有兜底携带技能"
call("POST", "/child/checkin", {"items": items_e}, token=rt["token"], note="进化测试-提交打卡")
pend_e = call("GET", "/parent/pending", token=PTK, note="进化测试-待审")
rec_e = [r for r in pend_e if str(r["task_date"]) == str(dt.date.today())][0]
apr_e = call("POST", "/parent/approve", {"checkin_id": rec_e["id"], "penalty": 0},
             token=PTK, note="批准→触发升级进化")
assert apr_e.get("evolved") and "妙蛙草" in apr_e["evolved"], f"审批未返回进化信息: {apr_e.get('evolved')}"
det1 = call("GET", f"/child/pokemon/{_seed_id}", token=rt["token"], note="进化后详情")
assert det1["pokedex_no"] == 2 and det1["name"] == "妙蛙草", f"未进化: {det1['pokedex_no']} {det1['name']}"
assert det1["moves"] == moves_before, f"进化后上场配置应保持不变: {moves_before} vs {det1['moves']}"
today_e = call("GET", "/child/today", token=rt["token"], note="孩子首页(进化惊喜卡)")
assert today_e["record"].get("evolved_json") and "妙蛙草" in today_e["record"]["evolved_json"], "首页缺进化卡数据"
print("    >> 到级自动进化 + 技能保留 + 前端进化卡 数据链路 OK")

print("========== 11. 冒险指南接口 ==========")
g = call("GET", "/child/guide", token=rt["token"], note="指南数据")
assert g["total"] == 151, "图鉴总数应151"
assert len(g["regions"]) == 8 and len(g["gyms"]) == 8, "应8区域8道馆"
r1 = g["regions"][0]
assert r1["unlocked"] is True and len(r1["pokemon"]) >= 1, "区域1应解锁且野生池非空"
assert all(len(reg["gyms"]) == 1 for reg in g["regions"]), "每区应恰好对应1座道馆"
# 区内去重 + 跨区去重（每只怪只归属一个区）
all_pids = [p["pokedex_no"] for reg in g["regions"] for p in reg["pokemon"]]
assert len(all_pids) == len(set(all_pids)), "野生池不应跨区重复"
assert not any(pid == 25 for pid in all_pids), "皮卡丘不应出现在野生池"
assert 26 in all_pids, "雷丘应可野外捕捉"
# v6：静态带重新上线（道馆锚定），指南 pokemon 条目应带 lo/hi 且 lo<=hi
myteam = call("GET", "/child/pokemon", token=rt["token"], note="指南联动-我的队伍")
ttl = max(x["level"] for x in myteam if x["is_in_team"] == 1)
assert g.get("team_top_level") == ttl, f"指南team_top_level应={ttl}，实际{g.get('team_top_level')}"
assert all("lo" in p and "hi" in p and p["lo"] <= p["hi"]
           for reg in g["regions"] for p in reg["pokemon"]), "v6 指南pokemon应带静态等级带 lo<=hi"
print(f"    >> 指南：区域分布 {[len(x['pokemon']) for x in g['regions']]}，雷丘可抓，"
      f"v6 静态等级带已上线(lo/hi)")

print("========== 12. 野生遭遇：v6 静态等级带 + 末4招 ==========")
call("PUT", "/config", {"key": "battle_weekday_open", "value": "1"}, token=PTK, note="节12-临时放行野生")
# v6：本区道馆推荐级−4 封顶（动态跟随已下线），遭遇等级必落在本怪 [lo,hi] 内
import app.db as _db
GYM_REC12 = {1: 16, 2: 19, 3: 24, 4: 28, 5: 32, 6: 36, 7: 40, 8: 46}
_cur_sid = _db.q("SELECT id FROM student_user ORDER BY id LIMIT 1")[0]["id"]
_cur_reg = _db.q("SELECT current_region_id c FROM student_user WHERE id=%s", (_cur_sid,))[0]["c"]
_db.x("UPDATE student_user SET hunt_region_id=0 WHERE id=%s", (_cur_sid,))  # v9 节12 语义：跟随剧情进度区
_cap12 = GYM_REC12[_cur_reg] - 4
_db.x("UPDATE student_user SET caught_today=0, catch_date=NULL WHERE id=%s", (_cur_sid,))  # v11 当日额度清零
call("PUT", "/config", {"key": "daily_catch_limit", "value": "99"}, token=PTK, note="节12-抽样期额度充足")
# 多次遭遇抽样：等级必在本怪静态带内且不超过区上限
_seen_lv = []
_pool12_all = {}   # 按遭遇实际区缓存野生池（hunt_region 可能被更早节次污染，以响应区为准）
for _i in range(12):
    _hunt12 = _db.q("SELECT hunt_region_id h FROM student_user WHERE id=%s", (_cur_sid,))[0]["h"] or _cur_reg
    w = call("POST", "/child/battle/wild", {}, token=rt["token"], note=f"野生遭遇抽样{_i+1}")
    foe = w["foe"][0]
    # 按「遭遇即扣」新口径：每次遭遇都会消耗额度，须逐次清零保持 12 次抽样额度充足
    _db.x("UPDATE student_user SET caught_today=0, catch_date=NULL WHERE id=%s", (_cur_sid,))
    if _hunt12 not in _pool12_all:
        _pool12_all[_hunt12] = {p["pokedex_no"]: p for p in _db.q(
            "SELECT pokedex_no, min_level lo, max_level hi FROM region_wild_pokemon WHERE region_id=%s", (_hunt12,))}
    band = _pool12_all[_hunt12].get(foe["pokedex_no"])
    assert band, f"遭遇 {foe['name']}(#{foe['pokedex_no']}) 不在区{_hunt12}野生池"
    assert band["lo"] <= foe["level"] <= band["hi"], \
        f"v6 遭遇等级 Lv{foe['level']} 应落在 {foe['name']} 静态带 Lv{band['lo']}~{band['hi']}"
    assert foe["level"] <= _cap12, f"v6 区{_cur_reg} 野生应≤道馆推荐−4(Lv{_cap12})，实际Lv{foe['level']}"
    assert 1 <= len(foe["moves"]) <= 4, f"野怪招式应1~4项，实际{len(foe['moves'])}"
    _seen_lv.append(foe["level"])
    # 末4招规则：这些招的学习等级应是"≤怪级"学习池中最大的4个
    no = foe["pokedex_no"]; lvf = foe["level"]
    pool = _db.q("SELECT skill_id, learn_level FROM pokemon_skill_learn "
                 "WHERE pokedex_no=%s AND learn_level<=%s ORDER BY learn_level, skill_id", (no, lvf))
    expect = [r["skill_id"] for r in pool][-4:]
    got = [m["id"] for m in foe["moves"]]
    assert sorted(got) == sorted(expect), f"应为末4招 {expect}，实际 {got}"
    if len(expect) >= 2:   # 新→旧排列：第一个应是学习等级最高的招
        maxlv = max(r["learn_level"] for r in pool if r["skill_id"] in got)
        first_lv = next(r["learn_level"] for r in pool if r["skill_id"] == got[0])
        assert first_lv == maxlv, f"招式顺序应新→旧，首位learn_level={first_lv}≠{maxlv}"
    # v3：野怪招式详情应带 ailment/ailment_chance 字段
    assert all("ailment" in m and "ailment_chance" in m for m in foe["moves"]), "野怪招式详情缺 ailment 字段"
# 战斗结束释放会话
call("POST", "/child/battle/act", {"action": "run"}, token=rt["token"], note="逃跑收尾")
_db.x("UPDATE student_user SET caught_today=0, catch_date=NULL WHERE id=%s", (_cur_sid,))  # v11 恢复满额度
# v11 回归防护：节12 用 limit=99 抽样，若遗留到节6"仅周末闸门"（今天恰为周末）会被
# v11 新增的当日额度闸门以"用完"拦截（400≠期望200）。恢复默认 3 保证节6 断言语义纯净。
call("PUT", "/config", {"key": "daily_catch_limit", "value": "3"}, token=PTK, note="节12-额度恢复默认3")
call("PUT", "/config", {"key": "battle_weekday_open", "value": "0"}, token=PTK, note="节12-恢复仅周末")
print(f"    >> 野生12次抽样 Lv{min(_seen_lv)}~{max(_seen_lv)}（区{_cur_reg}封顶Lv{_cap12}）"
      f"·静态带内·末4招·新→旧")

print("========== 13. v4 技能库与状态异常引擎 ==========")
import sqlite3 as _sq3
_db3 = _sq3.connect(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "pkm.sqlite3"))
n_moves = _db3.execute("SELECT COUNT(*) FROM skill_base").fetchone()[0]
n_null = _db3.execute("SELECT COUNT(*) FROM skill_base WHERE id IS NULL").fetchone()[0]
n_orphan = _db3.execute("SELECT COUNT(*) FROM skill_base WHERE id NOT IN "
                        "(SELECT DISTINCT skill_id FROM pokemon_skill_learn)").fetchone()[0]
# v4（trim_moves 精简后）：红/蓝 level-up only 口径，冲浪/居合斩作为纯孤儿 TM 已删 → 128 招
assert n_moves == 128, f"v4 技能库应为128招，实际 {n_moves}"
assert n_null == 0, f"skill_base 存在 NULL id {n_null} 行（迁移未完成？）"
assert n_orphan == 0, f"存在 {n_orphan} 个未被学习表引用的孤儿技能行"
n_status_moves = _db3.execute("SELECT COUNT(*) FROM skill_base WHERE effect_type LIKE 'status_%'").fetchone()[0]
n_ail_all = _db3.execute("SELECT COUNT(*) FROM skill_base WHERE ailment IS NOT NULL AND ailment<>''").fetchone()[0]
n_extra_ail = _db3.execute("SELECT COUNT(*) FROM skill_base WHERE power>0 AND ailment IS NOT NULL AND ailment<>''").fetchone()[0]
# 33 = 带异常标注的招总数（13 变化异常招 + 20 附加异常攻击招）
assert n_status_moves == 13 and n_ail_all == 33 and n_extra_ail == 20, \
    f"异常招统计异常: 变化{n_status_moves}/全标注{n_ail_all}/附加{n_extra_ail}"
hb_lv = _db3.execute("SELECT learn_level FROM pokemon_skill_learn WHERE pokedex_no=25 AND "
                     "skill_id=(SELECT id FROM skill_base WHERE skill_name='破坏光线')").fetchone()
assert hb_lv and hb_lv[0] == 28, f"皮卡丘破坏光线应 Lv28，实际 {hb_lv and hb_lv[0]}"
print(f"    >> v4 技能库 OK：128招（变化异常招13·附加异常攻击招20）·皮卡丘破坏光线Lv28")

# —— 状态引擎单元（直接调用 battle 路由内部函数，不起额外服务） ——
import os as _os3
os.environ["PKM_DB_ENGINE"] = "sqlite"
import app.db as _db3m
from app.routers import battle as _bt

def _mk(hp=100, atk=50, dfn=50, name="测试兽", types=("一般",)):
    return {"ref": "t0", "pokedex_no": 999, "name": name, "level": 50,
            "types": list(types), "stats": {"hp": hp, "atk": atk, "def": dfn, "spd": 40},
            "hp": hp, "moves": [], "status": None}

_bt._CUR_SESS[0] = {"kind": "wild", "sid": 99, "my": [], "foe": [], "buffs": {}}
u_slp = _mk(); u_caster = _mk(name="催眠师")
_bt._apply_status_effect(u_caster, u_slp,
    {"id": 1, "skill_name": "催眠术", "skill_type": "超能力", "power": 0, "accuracy": 100,
     "effect_type": "status_sleep", "effect_value": None, "ailment": "sleep", "ailment_chance": 100}, [], True)
assert u_slp["status"] and u_slp["status"]["ailment"] == "sleep", "催眠术未施加睡眠"
u_fir = _mk(name="小火龙", types=("火",))
_bt._try_inflict(u_fir, "burn", [], True)
assert u_fir["status"] is None, "火系应免疫烧伤"
u_rock = _mk(name="小拳石", types=("岩石", "地面"))
_bt._try_inflict(u_rock, "poison", [], True)
assert u_rock["status"] is None, "地/岩系应免疫中毒"
u_psn = _mk(hp=80); u_psn["status"] = {"ailment": "poison", "turns": 99}
_bt._poison_tick(u_psn, [], True)
assert u_psn["hp"] == 70, f"毒伤应为1/8（80→70），实际{u_psn['hp']}"
u_wake = _mk(); u_wake["status"] = {"ailment": "sleep", "turns": 1}
assert _bt._can_act(u_wake, [], True) and u_wake["status"] is None, "睡眠末回合应苏醒并放行"
u_h = _mk(); u_h["hp"] = 10
_bt._apply_status_effect(u_h, u_h,
    {"id": 3, "skill_name": "自我再生", "skill_type": "一般", "power": 0, "accuracy": 100,
     "effect_type": "heal", "effect_value": 0.5, "ailment": None, "ailment_chance": 0}, [], False)
assert u_h["hp"] == 60, f"回复50%应为60，实际{u_h['hp']}"
u_d1, u_d2 = _mk(atk=60), _mk(dfn=40); u_d1["hp"] = 50
_bt._apply_status_effect(u_d1, u_d2,
    {"id": 4, "skill_name": "吸血", "skill_type": "虫", "power": 20, "accuracy": 100,
     "effect_type": "drain", "effect_value": 0.5, "ailment": None, "ailment_chance": 0}, [], True)
assert u_d2["hp"] < 100 and u_d1["hp"] > 50, "吸血应扣对方血并回复自身"
import random as _rnd
_rnd.seed(1)
u_o1, u_o2 = _mk(), _mk()
_bt._apply_status_effect(u_o1, u_o2,
    {"id": 5, "skill_name": "地裂", "skill_type": "地面", "power": 0, "accuracy": 30,
     "effect_type": "ohko", "effect_value": None, "ailment": None, "ailment_chance": 0}, [], True)
assert u_o2["hp"] == 1, f"地裂命中应打至1HP，实际{u_o2['hp']}"
_sess2 = {"buffs": {}}; _bt._CUR_SESS[0] = _sess2
atk_mv = {"id": 6, "skill_name": "暴走", "skill_type": "一般", "power": 50, "accuracy": 100,
          "effect_type": None, "effect_value": None, "ailment": None, "ailment_chance": 0}
# 烧伤(攻击×0.5)与属性倍率均在取整前介入 → 伤害精确减半
d_burn = _bt._dmg(80, 50, 50, 1.0, 1.0, burn=True)
d_norm = _bt._dmg(80, 50, 50, 1.0, 1.0)
assert abs(d_burn * 2 - d_norm) <= 1, f"烧伤应约减半伤害（float取整±1）：{d_burn} vs {d_norm}"
b1, b2 = _mk(atk=80), _mk(dfn=50); b1["status"] = {"ailment": "burn", "turns": 99}
_bt._attack_step(b1, b2, atk_mv, _sess2, True, []); dmg_b = 100 - b2["hp"]
b3, b4 = _mk(atk=80), _mk(dfn=50)
_bt._attack_step(b3, b4, atk_mv, _sess2, True, []); dmg_n = 100 - b4["hp"]
assert abs(dmg_b * 2 - dmg_n) <= 1, f"攻击步烧伤应约减半（float取整±1）：{dmg_b} vs {dmg_n}"
_sess3 = {"buffs": {}}; _bt._CUR_SESS[0] = _sess3
_bt._apply_status_effect(_mk(name="我方"), (tgt := _mk(name="敌方")),
    {"id": 7, "skill_name": "瞪眼", "skill_type": "一般", "power": 0, "accuracy": 100,
     "effect_type": "def_down", "effect_value": 0.7, "ailment": None, "ailment_chance": 0}, [], True)
assert _sess3["buffs"].get(tgt["ref"]) == 0.7, "减益应作用于对手ref"
selfu = _mk(name="剑士"); _sess3["buffs"][selfu["ref"]] = 1.5
_bt._apply_status_effect(selfu, selfu,
    {"id": 8, "skill_name": "剑舞", "skill_type": "一般", "power": 0, "accuracy": 100,
     "effect_type": "atk_up", "effect_value": 2.0, "ailment": None, "ailment_chance": 0}, [], False)
assert _sess3["buffs"][selfu["ref"]] == 2.0, "增益应封顶2.0"
_bt._CUR_SESS[0] = None
print("    >> 状态引擎单元 OK：施加/免疫/毒伤/苏醒/回复/吸血/地裂/烧伤减半/减益对敌/增益封顶")
print("    >> v3 全链路通过 ✅")

print("========== 14. v4 道馆赠礼 + 封印宝可梦 ==========")
import sqlite3 as _sq4
_db4 = _sq4.connect(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "pkm.sqlite3"))
_cols4 = [r[1] for r in _db4.execute("PRAGMA table_info(trainer_pokemon)")]
assert "sealed" in _cols4, "trainer_pokemon 缺 sealed 列（先跑 migrate_v4_seal.py）"
assert "gift_gym_sort" in _cols4, "trainer_pokemon 缺 gift_gym_sort 列（先跑 migrate_v7_gift.py）"
assert "seal_start_date" in _cols4, "trainer_pokemon 缺 seal_start_date 列（先跑 migrate_v8_seal.py）"
_today_str4 = dt.date.today().isoformat()
# A. 指南：道馆礼物表 8 条（馆序↔赠礼对齐）
g4 = call("GET", "/child/guide", token=rt["token"], note="指南含道馆礼物表")
assert g4.get("gym_gifts") and len(g4["gym_gifts"]) == 8, "gym_gifts 应8条"
assert [x["pokedex_no"] for x in g4["gym_gifts"]] == [143, 144, 145, 146, 150, 142, 151, 137], \
    f"赠礼表不符: {[x['pokedex_no'] for x in g4['gym_gifts']]}"
assert g4.get("seal_need") == 7, "seal_need 应为7"
# B. 人工植入封印卡比兽（等价打赢第1馆发放态；v7 gift_gym_sort=1 + v8 起算日=今天）
_db4.execute("DELETE FROM trainer_pokemon WHERE pokedex_no=143")
_db4.execute("INSERT INTO trainer_pokemon(student_id,pokedex_no,level,total_exp,"
             "learned_skill_json,known_skill_json,is_in_team,sealed,gift_gym_sort,seal_start_date) "
             "VALUES(1,143,10,0,'[]','[]',0,1,1,?)", (_today_str4,))
_db4.commit()
pk4 = call("GET", "/child/pokemon", token=rt["token"], note="背包含封印卡比兽")
k_b = [m for m in pk4 if m["pokedex_no"] == 143][0]
assert k_b["sealed"] == 1 and k_b["is_in_team"] == 0, "卡比兽应处于封印态且未出战"
assert k_b["known"] == [] and k_b["moves"] == [], "封印态不应有已学/携带技能"
det_seal = call("GET", f"/child/pokemon/{k_b['id']}", token=rt["token"], note="封印详情(看家招预告)")
assert det_seal["known"] == [] and det_seal.get("seal_hint"), "封印详情应无技能袋但有看家招预告"
assert det_seal["seal_hint"]["skill_name"] == "舌舔", f"卡比兽看家招应为舌舔: {det_seal.get('seal_hint')}"
# C. 封印隔离：不可上阵
call("POST", "/child/team", {"team_ids": [1, k_b["id"]]}, token=rt["token"], expect=400,
     note="封印宝可梦上阵应400")
# D. 隔离经验池：出战皮卡丘获批加经验，卡比兽 total_exp 不动
_db4.execute("UPDATE trainer_pokemon SET is_in_team=0"); _db4.execute("UPDATE trainer_pokemon SET is_in_team=1, slot=0 WHERE id=1")
_db4.execute("DELETE FROM checkin_record WHERE task_date=?", (_today_str4,))
_db4.commit()
# v8 前置：伪造 30 天全局获批流水（今天还没批）——旧口径下这些会借光秒解，v8 必须拦下
_db4.execute("DELETE FROM checkin_record WHERE student_id=1")
for i in range(1, 31):
    _db4.execute("INSERT INTO checkin_record(student_id,task_date,item_json,status,quick_win) "
                 "VALUES(1,?,'[]',2,0)", ((dt.date.today() - dt.timedelta(days=i)).isoformat(),))
_db4.commit()
call("POST", "/child/checkin", {"items": items_e}, token=rt["token"], note="激活前-提交打卡")
pend4 = call("GET", "/parent/pending", token=PTK, note="激活前-待审")
rec4 = [r for r in pend4 if str(r["task_date"]) == str(dt.date.today())][0]
apr4 = call("POST", "/parent/approve", {"checkin_id": rec4["id"], "penalty": 0}, token=PTK,
            note="激活前-批准(全局连击已30天，但封印独立计时仅第1天)")
assert not apr4.get("activated"), \
    f"v8 借旧连击秒解了！全局30连击不应影响当天新获得的封印怪: {apr4.get('activated')}"
kb_exp = _db4.execute("SELECT total_exp FROM trainer_pokemon WHERE id=?", (k_b["id"],)).fetchone()[0]
assert kb_exp == 0, f"封印宝可梦不应吃经验: total_exp={kb_exp}"
# v8：封印中查独立进度——起算日=今天 → seal_progress=1（逐日获批：今天）
today_v8 = call("GET", "/child/today", token=rt["token"], note="v8-封印独立进度查询")
_s143 = [s for s in (today_v8.get("sealed") or []) if s["pokedex_no"] == 143][0]
assert _s143.get("seal_progress") == 1, f"当天获得应进度1/7，实际 {_s143.get('seal_progress')}"
# E. 起算日回拨 6 天前 → 窗口内逐日补"获批"流水（覆盖前轮非获批残留）→ 第 7 天达标触发审批激活
# 等级=来源道馆推荐级（v7：1 馆=Lv16），队伍强拉 Lv40 证明与队伍等级无关
_GYM1_LV = 16
_team_lv = _db4.execute("SELECT MAX(level) FROM trainer_pokemon WHERE student_id=1 AND is_in_team=1").fetchone()[0]
_db4.execute("UPDATE trainer_pokemon SET level=40 WHERE student_id=1 AND is_in_team=1")
_db4.execute("UPDATE trainer_pokemon SET seal_start_date=? WHERE id=?",
             ((dt.date.today() - dt.timedelta(days=6)).isoformat(), k_b["id"]))
# 窗口逐日确保获批态（覆盖前轮 status=3/4 残留：DELETE+重插 status=2，今天已有已批记录跳过）
for i in range(1, 7):
    _d_i = (dt.date.today() - dt.timedelta(days=i)).isoformat()
    _db4.execute("DELETE FROM checkin_record WHERE student_id=1 AND task_date=?", (_d_i,))
    _db4.execute("INSERT INTO checkin_record(student_id,task_date,item_json,status,quick_win) "
                 "VALUES(1,?,'[]',2,0)", (_d_i,))
# 重放审批：把今日记录退回待审（status=1）再批，走完整激活链路
_db4.execute("UPDATE checkin_record SET status=1 WHERE student_id=1 AND task_date=?", (_today_str4,))
_db4.commit()
pend5 = call("GET", "/parent/pending", token=PTK, note="激活日-待审(重放今日)")
rec5 = [r for r in pend5 if str(r["task_date"]) == str(dt.date.today())][0]
apr5 = call("POST", "/parent/approve", {"checkin_id": rec5["id"], "penalty": 0}, token=PTK,
            note="激活日-批准(独立计时第7天达标)")
acts = apr5.get("activated") or []
assert any(a["pokedex_no"] == 143 for a in acts), f"审批未返回激活信息: {apr5}"
kb = acts[0]
assert kb["level"] == _GYM1_LV, \
    f"v7 激活等级应=1馆推荐级Lv{_GYM1_LV}（队伍{_team_lv}/强拉40 无关），实际Lv{kb['level']}"
det_kb = call("GET", f"/child/pokemon/{k_b['id']}", token=rt["token"], note="激活后卡比兽详情")
assert det_kb["sealed"] == 0 and det_kb["level"] == _GYM1_LV and det_kb["total_exp"] > 0, "激活后状态不对"
assert det_kb["known"], "激活后应回填到级技能"
# v7+v8：植入 2 馆急冻鸟（起算=今天）→ 预告 Lv19 + 独立进度 1/7（今天窗口已获批）
_db4.execute("INSERT INTO trainer_pokemon(student_id,pokedex_no,level,total_exp,"
             "learned_skill_json,known_skill_json,is_in_team,sealed,gift_gym_sort,seal_start_date) "
             "VALUES(1,144,10,0,'[]','[]',0,1,2,?)", (_today_str4,))
_db4.commit()
today4 = call("GET", "/child/today", token=rt["token"], note="v7/v8-封印预告+独立进度")
_seal144 = [s for s in (today4.get("sealed") or []) if s["pokedex_no"] == 144][0]
assert _seal144.get("unseal_level") == 19, f"2馆急冻鸟封印应预告 Lv19，实际 {_seal144}"
assert _seal144.get("seal_progress") == 1, f"当天获得进度应1/7，实际 {_seal144.get('seal_progress')}"
# v8 断档检查：植入 7 天窗口但昨天记录被前轮覆盖为 status=3（扣减批）→ 进度只数今天=1
_db4.execute("INSERT INTO trainer_pokemon(student_id,pokedex_no,level,total_exp,"
             "learned_skill_json,known_skill_json,is_in_team,sealed,gift_gym_sort,seal_start_date) "
             "VALUES(1,145,10,0,'[]','[]',0,1,3,?)",
             ((dt.date.today() - dt.timedelta(days=6)).isoformat(),))
_db4.execute("UPDATE checkin_record SET status=4 WHERE student_id=1 AND task_date=?",
             ((dt.date.today() - dt.timedelta(days=1)).isoformat(),))
_db4.commit()
today_break = call("GET", "/child/today", token=rt["token"], note="v8-断档进度(昨天置驳回)")
_s145 = [s for s in (today_break.get("sealed") or []) if s["pokedex_no"] == 145][0]
assert _s145.get("seal_progress") == 1, \
    f"窗口内昨天非获批态，进度应回落1/7，实际 {_s145.get('seal_progress')}"
_db4.execute("DELETE FROM trainer_pokemon WHERE pokedex_no IN (144,145)")
_db4.commit()
# F. 激活后可正常上阵再撤下
call("POST", "/child/team", {"team_ids": [1, k_b["id"]]}, token=rt["token"], note="激活后可上阵")
call("POST", "/child/team", {"team_ids": [1]}, token=rt["token"], note="恢复原队伍")
# G. 野生池 v3：只含未进化/中间形态；御三家+雷丘可遇；赠礼8只不可野遇；总数82
allp4 = [p["pokedex_no"] for reg in g4["regions"] for p in reg["pokemon"]]
assert len(set(allp4)) == 82, f"野生池应82种，实际{len(set(allp4))}"
for pid, nm in [(83, "大葱鸭"), (108, "大舌头"), (122, "魔墙人偶"), (124, "迷唇姐"),
                (138, "菊石兽"), (140, "化石盔"), (1, "妙蛙种子"), (4, "小火龙"),
                (7, "杰尼龟"), (26, "雷丘")]:
    assert pid in allp4, f"{nm} 应在野生池"
for pid in (142, 143, 144, 145, 146, 150, 151, 137):
    assert pid not in allp4, f"赠礼怪{pid}不应出现在野生池"
# v3 口径：进化终点（妙蛙花3/喷火龙6/水箭龟9/比雕18等）不得出现在野生池
for pid in (3, 6, 9, 18, 20, 22, 31, 34, 40, 42, 45, 130):
    assert pid not in allp4, f"进化终点{pid}不应出现在野生池(v3规则)"
# v3 口径：各区平均等级带中值单调不降（难度阶梯，直查库）
# v6 口径：每区 max_level ≤ 本区道馆推荐级 − 4（道馆锚定封顶）
import collections as _cl4
os.environ.setdefault("PKM_DB_ENGINE", "sqlite")
from app import db as _db4
_LV4 = _cl4.defaultdict(list)
_MAX4 = {}
_GYM_REC4 = {1: 16, 2: 19, 3: 24, 4: 28, 5: 32, 6: 36, 7: 40, 8: 46}
for _r in _db4.q("SELECT region_id, min_level lo, max_level hi FROM region_wild_pokemon"):
    _LV4[_r["region_id"]].append((_r["lo"] + _r["hi"]) / 2)
    _MAX4[_r["region_id"]] = max(_MAX4.get(_r["region_id"], 0), _r["hi"])
_avgs4 = [sum(_LV4[i]) / len(_LV4[i]) for i in sorted(_LV4)]
assert all(b >= a for a, b in zip(_avgs4, _avgs4[1:])), f"野生池难度倒挂: {_avgs4}"
for _reg in sorted(_GYM_REC4):
    assert _MAX4[_reg] <= _GYM_REC4[_reg] - 4, \
        f"v6 封顶越带: 区{_reg} 野生上限Lv{_MAX4[_reg]} > 道馆推荐{_GYM_REC4[_reg]}−4"
# H. gift 模块单元：GYM_GIFTS 幂等（重复发放→None）
os.environ["PKM_DB_ENGINE"] = "sqlite"
from app import gift as _g4
assert _g4.GYM_GIFTS == {1: 143, 2: 144, 3: 145, 4: 146, 5: 150, 6: 142, 7: 151, 8: 137}
assert _g4.grant_gym_gift(1, 1, 1) is None, "已拥有的赠礼应幂等跳过"
print(f"    >> v4/v7/v8 赠礼/封印 OK：发放态隔离→获得日起独立计时满7天激活(Lv{kb['level']}=1馆推荐级，全局30连击不借光)→技能回填→可上阵；野生82种(v3阶梯)")
# 清理：移除测试植入的卡比兽，恢复干净背包
_db4.x("DELETE FROM trainer_pokemon WHERE pokedex_no=143")
_db4.x("DELETE FROM checkin_record WHERE student_id=1")

print("========== 15. v5 出手顺序 + PP 体力 ==========")
import sqlite3 as _sq5
_db5 = _sq5.connect(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "pkm.sqlite3"))
_cols5 = [r[1] for r in _db5.execute("PRAGMA table_info(skill_base)")]
assert "priority" in _cols5 and "max_pp" in _cols5, "skill_base 缺 priority/max_pp 列（先跑 migrate_v5_battle.py）"
_p1 = [r[0] for r in _db5.execute("SELECT skill_name FROM skill_base WHERE priority>0").fetchall()]
assert _p1 == ["电光一闪"], f"先制招应仅电光一闪，实际 {_p1}"
_dist = dict(_db5.execute("SELECT max_pp, COUNT(*) FROM skill_base GROUP BY max_pp").fetchall())
assert set(_dist) <= {2, 3, 4, 6, 8} and sum(_dist.values()) == 128, f"max_pp 分布异常 {_dist}"
assert _db5.execute("SELECT max_pp FROM skill_base WHERE skill_name='破坏光线'").fetchone()[0] == 2
assert _db5.execute("SELECT max_pp FROM skill_base WHERE skill_name='吸取'").fetchone()[0] == 3
print(f"    >> v5 数据层 OK：先制仅电光一闪·PP档 {{2:{_dist[2]},3:{_dist[3]},4:{_dist[4]},6:{_dist[6]},8:{_dist[8]}}}")

# —— 定序单元（直调内部函数） ——
os.environ["PKM_DB_ENGINE"] = "sqlite"
from app.routers import battle as _bt5
def _u(spd, para=False, hp=60):
    u = {"ref": f"t{spd}", "name": f"兽{spd}", "stats": {"hp": hp, "atk": 40, "def": 40, "spd": spd},
         "hp": hp, "moves": [], "status": None}
    if para:
        u["status"] = {"ailment": "para", "turns": 99}
    return u
_mv = lambda pri: {"priority": pri}
assert _bt5._first_order(_u(30), _u(100), _mv(1), _mv(0)) is True, "先制招应无视速度先手"
assert _bt5._first_order(_u(30), _u(100), _mv(0), _mv(0)) is False, "高速方应先手"
assert _bt5._first_order(_u(100), _u(49, para=True), _mv(0), _mv(0)) is True, "对方麻痹减半(24.5)后我方先手"
assert _bt5._first_order(_u(100, para=True), _u(51), _mv(0), _mv(0)) is False, "我方麻痹(50)输给51速"
_r = [_bt5._first_order(_u(50), _u(50), _mv(0), _mv(0)) for _ in range(200)]
assert any(_r) and not all(_r), "同速应随机先后"
assert _bt5._speed_eff(_u(64, para=True)) == 32.0
print("    >> v5 定序单元 OK：先制/速度/麻痹减半/同速随机")

# —— PP 与会话结构（HTTP 面） ——
call("PUT", "/config", {"key": "battle_weekday_open", "value": "1"}, token=PTK, note="节15-临时放行战斗")
wt = call("POST", "/child/battle/wild", {}, token=rt["token"], note="节15-野生遭遇(查PP)")
assert wt["my"] and all("pp" in m for m in wt["my"]), "出战单位应带 pp 表"
assert wt["foe"] and all("pp" in f for f in wt["foe"]), "野怪单位应带 pp 表"
_pika = wt["my"][0]
_quick = next((m for m in _pika["moves"] if m["skill_name"] == "电光一闪"), None)
if _quick:
    assert _quick.get("priority") == 1, "电光一闪应带 priority=1 到前端"
    assert _pika["pp"][_quick["id"]] == 8, f"电光一闪 PP 应为8，实际 {_pika['pp']}"
assert all((m["effect_type"] or "") != "drain" or w == 0.5 or w == 0 for m, w in
           zip(wt["foe"][0]["moves"], wt["foe"][0].get("move_weights", []))), "野怪吸血招应零权重"
call("POST", "/child/battle/act", {"action": "run"}, token=rt["token"], note="节15-逃跑收尾")
print("    >> v5 HTTP 面 OK：野怪遭遇带 pp 表·AI 吸血零权重")
# 出手顺序单测：对方先手且击杀我方 → 换人播报（直调 act 原函数，绕过 FastAPI 依赖包装）
_bt5.SESSIONS[999] = {"kind": "wild", "sid": 999, "buffs": {}, "wild": {}, "wild_level": 5,
    "my": [{"ref": "p1", "pokedex_no": 25, "name": "皮卡丘", "level": 5, "types": ["电"],
            "stats": {"hp": 20, "atk": 10, "def": 10, "spd": 10}, "hp": 20, "status": None,
            "moves": [{"id": 1, "skill_name": "撞击", "skill_type": "一般", "power": 40,
                       "accuracy": 100, "effect_type": None, "effect_value": None,
                       "ailment": None, "ailment_chance": 0, "priority": 0, "max_pp": 8}],
            "pp": {1: 8}},
           {"ref": "p2", "pokedex_no": 25, "name": "皮卡丘B", "level": 5, "types": ["电"],
            "stats": {"hp": 40, "atk": 10, "def": 10, "spd": 10}, "hp": 40, "status": None,
            "moves": [{"id": 1, "skill_name": "撞击", "skill_type": "一般", "power": 40,
                       "accuracy": 100, "effect_type": None, "effect_value": None,
                       "ailment": None, "ailment_chance": 0, "priority": 0, "max_pp": 8}],
            "pp": {1: 8}}],
    "foe": [{"ref": "w0", "pokedex_no": 16, "name": "波波", "level": 40, "types": ["飞行"],
             "stats": {"hp": 100, "atk": 500, "def": 200, "spd": 90}, "hp": 100, "status": None,
             "moves": [{"id": 9, "skill_name": "起风", "skill_type": "飞行", "power": 40,
                        "accuracy": 100, "effect_type": None, "effect_value": None,
                        "ailment": None, "ailment_chance": 0, "priority": 0, "max_pp": 8}],
             "move_weights": [1.0], "pp": {9: 8}}]}
_ro = _bt5.act({"action": "attack", "skill_id": 1}, {"uid": 999})   # act 是普通函数，直调
_j = "\n".join(_ro["messages"])
assert "抢得先手" in _j and "倒下了" in _j and "上吧，皮卡丘B" in _j, f"对方先手击杀应换人: {_j}"
assert _ro["my_idx"] == 1, f"应换到第二只，my_idx={_ro['my_idx']}"
_bt5.SESSIONS.pop(999, None)
_bt5._CUR_SESS[0] = None
# PP 耗尽 400 拦截（同进程直调，PP 预设为 0）
_bt5._CUR_SESS[0] = None
_bt5.SESSIONS[998] = {"kind": "wild", "sid": 998, "buffs": {}, "wild": {}, "wild_level": 5,
    "my": [{"ref": "pz", "pokedex_no": 25, "name": "皮卡丘", "level": 5, "types": ["电"],
            "stats": {"hp": 30, "atk": 20, "def": 20, "spd": 30}, "hp": 30, "status": None,
            "moves": [{"id": 77, "skill_name": "试招", "skill_type": "一般", "power": 10,
                       "accuracy": 100, "effect_type": None, "effect_value": None,
                       "ailment": None, "ailment_chance": 0, "priority": 0, "max_pp": 2}],
            "pp": {77: 0}}],
    "foe": [{"ref": "wz", "pokedex_no": 10, "name": "绿毛虫", "level": 5, "types": ["虫"],
             "stats": {"hp": 50, "atk": 5, "def": 20, "spd": 5}, "hp": 50, "status": None,
             "moves": [{"id": 78, "skill_name": "挣扎", "skill_type": "一般", "power": 1,
                        "accuracy": 100, "effect_type": None, "effect_value": None,
                        "ailment": None, "ailment_chance": 0, "priority": 0, "max_pp": 8}],
             "move_weights": [1.0], "pp": {78: 8}}]}
try:
    _bt5.act({"action": "attack", "skill_id": 77}, {"uid": 998})
    FAILS.append("节15-PP耗尽应400未拦截")
except Exception as _e5:
    assert "PP用完了" in str(_e5), f"PP耗尽报错文案异常: {_e5}"
_bt5.SESSIONS.pop(998, None)
_bt5._CUR_SESS[0] = None
print("    >> PP 耗尽 400 拦截 OK")
print("    >> v5 回合引擎单元 OK：对方先手→击杀→换人链路正确")
call("PUT", "/config", {"key": "battle_weekday_open", "value": "0"}, token=PTK, note="节15-恢复仅周末")
print("    >> v5 全链路通过 ✅")

print("========== 16. v9 野外捕捉选区 ==========")
call("PUT", "/config", {"key": "daily_catch_limit", "value": "99"}, token=PTK, note="节16-选区抽样额度")
call("PUT", "/config", {"key": "battle_weekday_open", "value": "1"}, token=PTK, note="节16-临时开学习日")
_sid9 = _cur_sid if "_cur_sid" in dir() else _db.q("SELECT id FROM student_user ORDER BY id LIMIT 1")[0]["id"]
TK9 = STK
# 造进度：孩子 4 枚徽章 → 区1~5 解锁、区6 应拒
_badges9 = json.dumps([g["badge_name"] for g in _db.q("SELECT badge_name FROM gym_base ORDER BY sort LIMIT 4")], ensure_ascii=False)
_db.x("UPDATE student_user SET badge_json=%s, hunt_region_id=0 WHERE id=%s", (_badges9, _sid9))
_db.x("UPDATE student_user SET caught_today=0, catch_date=NULL WHERE id=%s", (_sid9,))  # v11：清当日额度恢复旧断言语义
av9 = call("GET", "/child/battle/availability", token=TK9, note="availability 带 regions")
assert "regions" in av9 and len(av9["regions"]) == 8, "availability 缺 regions(8)"
_r6 = next(r for r in av9["regions"] if r["id"] == 6)
assert _r6["lo"] is not None and _r6["hi"] >= _r6["lo"], f"区6 等级带异常 {_r6}"
assert all(r["unlocked"] for r in av9["regions"] if r["id"] <= 5) and not _r6["unlocked"], "解锁判定错误(徽章4→区5解锁/区6锁)"
# 未解锁区应 400
call("POST", "/child/battle/hunt-region", {"region_id": 6}, token=TK9, expect=400, note="未解锁区应400")
call("POST", "/child/battle/hunt-region", {"region_id": 9}, token=TK9, expect=400, note="越界区应400")
# 已解锁区可选（回到区1）
r9 = call("POST", "/child/battle/hunt-region", {"region_id": 1}, token=TK9, note="选择已通关区1")
assert r9.get("hunt_region") == 1
# 选定后 wild 遭遇必须命中区1 野生池
pool1 = {p["pokedex_no"] for p in _db.q("SELECT pokedex_no FROM region_wild_pokemon WHERE region_id=1")}
seen9 = set()
for _ in range(6):
    w9 = call("POST", "/child/battle/wild", {}, token=TK9, note=f"区1遭遇#{_+1}" if _ == 0 else "")
    _db.x("UPDATE student_user SET caught_today=0, catch_date=NULL WHERE id=%s", (_sid9,))  # 遭遇即扣→逐次清零
    if w9.get("foe"):
        seen9.add(w9["foe"][0]["pokedex_no"])
        call("POST", "/child/battle/act", {"action": "run"}, token=TK9, note="")
_db.x("UPDATE student_user SET caught_today=0, catch_date=NULL WHERE id=%s", (_sid9,))  # v11 当日额度恢复
assert seen9 and seen9 <= pool1, f"区1遭遇应全在区1池：越界 {seen9 - pool1}"
# hunt=0 恢复跟随
r9b = call("POST", "/child/battle/hunt-region", {"region_id": 0}, token=TK9, note="恢复跟随进度")
assert r9b.get("hunt_region") == 0
av9b = call("GET", "/child/battle/availability", token=TK9, note="hunt_region 归零")
assert av9b["hunt_region"] == 0
call("PUT", "/config", {"key": "battle_weekday_open", "value": "0"}, token=PTK, note="节16-恢复仅周末")
print(f"    >> v9 选区通过 ✅（区1 抽样 {len(seen9)} 种全在池内；未解锁区拦截）")

print("========== 17. v10 入袋经验门槛回填 ==========")
# v10 bug：捕捉/赠礼/初始入袋 total_exp 曾写死 0，首笔经验 level_for 反推致掉级
# 注入手法同节15：本进程直接改 SESSIONS/db —— 仅当冒烟服务与本脚本同机同库时有效
import sys as _sys10
_sys10.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PKM_DB_ENGINE"] = "sqlite"
# 会话在服务进程内存，D 步走 HTTP 真实开遭遇；本地仅复用 db 工具函数
from app import gift as _gift10, exp as _exp10, db as _dbx10

# A. 纯函数：exp_floor 与 level_for 互逆
for _g10 in ("fast", "medium", "slow"):
    for _lv10 in (1, 5, 10, 20, 32, 50):
        _e10 = _exp10.exp_floor(_g10, _lv10)
        assert _exp10.level_for(_g10, _e10) == _lv10, f"互逆破裂 {_g10} Lv{_lv10} exp={_e10}"
        if _lv10 > 1:   # 门槛下沿应恰好落回上一级（防多给一档）
            assert _exp10.level_for(_g10, _e10 - 1) == _lv10 - 1, f"门槛偏高 {_g10} Lv{_lv10}"
print("    >> exp_floor/level_for 互逆 OK")
# B. 全表自洽（reset 后的库应全自洽；防"经验归零掉级"回归）
import migrate_v10_expfix as _mx10
_all10 = _dbx10.q("SELECT tp.level, tp.total_exp, COALESCE(pb.exp_group,'medium') g FROM trainer_pokemon tp LEFT JOIN pokemon_base pb ON pb.pokedex_no=tp.pokedex_no")
_bad10 = [r for r in _all10 if _exp10.level_for(r["g"], r["total_exp"]) < r["level"]]
assert not _bad10, f"存量脱钩未修: {_bad10}（本地应先跑 migrate_v10_expfix.py）"
print(f"    >> 全表 {len(_all10)} 只 level/exp 自洽 OK")
# C. 赠礼入库自洽：发放 Lv10 封印怪 → total_exp 应为经验组 Lv10 门槛（非 0）
_dbx10.x("DELETE FROM trainer_pokemon WHERE pokedex_no=143")
_dbx10.x("DELETE FROM battle_record WHERE kind='gym'")
_g10 = _gift10.grant_gym_gift(_sid9, 1, 999)
assert _g10 and _g10["pokedex_no"] == 143
_kb10 = _dbx10.q("SELECT tp.total_exp, COALESCE(pb.exp_group,'medium') g FROM trainer_pokemon tp LEFT JOIN pokemon_base pb ON pb.pokedex_no=tp.pokedex_no WHERE tp.pokedex_no=143")[0]
assert _kb10["total_exp"] == _exp10.exp_floor(_kb10["g"], 10) > 0, f"卡比兽入库经验应=Lv10门槛，实际 {dict(_kb10)}"
print(f"    >> 赠礼入库自洽 OK（卡比兽 Lv10 total_exp={_kb10['total_exp']}）")
_dbx10.x("DELETE FROM trainer_pokemon WHERE pokedex_no=143")
# D+E. 捕捉入库自洽 + 审批发经验不掉级（单循环）：
#  会话在服务进程内存，必须走 HTTP 开遭遇；今天打卡若在更早节次已提交，先清掉再提。
#  抓到怪后留在包中→审批→断言全队零掉级（旧 bug：total_exp=0 → 首笔经验掉回 Lv1）。
_dbx10.x("UPDATE student_user SET caught_today=0, catch_date=NULL WHERE id=%s", (_sid9,))  # v11 当日额度清零
call("PUT", "/config", {"key": "daily_catch_limit", "value": "99"}, token=PTK, note="节17-额度充足")
call("PUT", "/config", {"key": "battle_weekday_open", "value": "1"}, token=PTK, note="节17-临时开学习日")
_today17 = dt.date.today().isoformat()
# 节3 若已有今日已批记录，走**服务端** reject 整日回滚（apply_exp 必须在服务进程执行）；
# 驳回只改状态不发经验，随后删除记录释放唯一约束，保证审批链路从干净态开始。
for _p in _dbx10.q("SELECT id, status FROM checkin_record WHERE student_id=%s AND task_date=%s",
                   (_sid9, _today17)):
    if _p["status"] in (2, 3):
        call("POST", "/parent/reject", {"checkin_id": _p["id"], "reason": "节17-回滚前节"},
             token=PTK, note="")
_dbx10.x("DELETE FROM checkin_record WHERE student_id=%s AND task_date=%s", (_sid9, _today17))
_ck17 = call("POST", "/child/checkin", {"items": items_e[:1] if "items_e" in dir() else [tasks[0]["id"]]},
             token=TK9, note="节17-审批链路打卡")
_rid17 = _dbx10.q("SELECT id FROM checkin_record WHERE student_id=%s AND task_date=%s AND status=1",
                  (_sid9, _today17))[0]["id"]
# 注意：打卡已在服务端创建，此后抓的怪入袋后即属"审批后经验对象"，
# 故先抓 2 只（D 步取样本断言 + 留 1 只跨审批验证不掉级），再审批。
_sample, _keeper = None, None
_seen17 = 0
for _t10 in range(25):
    w17 = call("POST", "/child/battle/wild", {}, token=TK9, note=f"节17-遭遇#{_t10+1}" if _t10 == 0 else "")
    _no17 = w17["foe"][0]["pokedex_no"]
    _seen17 += 1
    c17 = call("POST", "/child/battle/act", {"action": "catch"}, token=TK9, note="")
    if c17.get("result") != "catch":
        call("POST", "/child/battle/act", {"action": "run"}, token=TK9, note="")
        continue
    row17 = _dbx10.q("SELECT tp.id, tp.level, tp.total_exp, COALESCE(pb.exp_group,'medium') g "
                     "FROM trainer_pokemon tp LEFT JOIN pokemon_base pb ON pb.pokedex_no=tp.pokedex_no "
                     "WHERE tp.student_id=%s AND tp.pokedex_no=%s", (_sid9, _no17))
    if not row17:
        continue
    if row17[0]["total_exp"] == 0:
        _sample = row17[0]   # 旧口径残留：门槛未回填（断言会炸出真因）
        break
    if _sample is None:
        _sample = row17[0]
        _dbx10.x("DELETE FROM trainer_pokemon WHERE id=%s", (_sample["id"],))
    elif _keeper is None:
        _keeper = row17[0]
        break   # 样本+留存各一，够用了
call("PUT", "/config", {"key": "battle_weekday_open", "value": "0"}, token=PTK, note="节17-恢复仅周末")
assert _sample is not None, f"{_seen17} 次遭遇+捕获均未取得入库样本"
assert _sample["total_exp"] > 0, "捕捉入库 total_exp 仍为 0（回填未生效！）"
assert _sample["total_exp"] == _exp10.exp_floor(_sample["g"], _sample["level"]), f"入库经验≠门槛: {dict(_sample)}"
assert _exp10.level_for(_sample["g"], _sample["total_exp"]) == _sample["level"], f"入库 level/exp 不自洽: {dict(_sample)}"
print(f"    >> 真实遭遇 {_seen17} 次抽样入库自洽 OK（Lv{_sample['level']} {_sample['g']}组 total_exp={_sample['total_exp']}）")
assert _keeper is not None, "未取得跨审批留存样本"
# 留存怪编入出战队伍（野外怪捕后 is_in_team=0，需与首发组队才能吃到审批经验）
_first = _dbx10.q("SELECT id FROM trainer_pokemon WHERE student_id=%s AND is_in_team=1 ORDER BY slot,id LIMIT 1", (_sid9,))
call("POST", "/child/team", {"team_ids": [r["id"] for r in _first] + [_keeper["id"]]},
     token=TK9, note="节17-野外怪入队")
_before17 = {r["id"]: r["level"] for r in _dbx10.q(
    "SELECT id, level FROM trainer_pokemon WHERE student_id=%s AND is_in_team=1", (_sid9,))}
assert _keeper["id"] in _before17, "野外怪未入队"
_ap17 = call("POST", "/parent/approve", {"checkin_id": _rid17, "penalty": 0}, token=PTK, note="节17-审批发经验")
_after17 = {r["id"]: r["level"] for r in _dbx10.q(
    "SELECT id, level FROM trainer_pokemon WHERE student_id=%s AND is_in_team=1", (_sid9,))}
_drop = {i: (_before17[i], _after17.get(i)) for i in _before17 if _after17.get(i, 99) < _before17[i]}
assert not _drop, f"审批发经验后掉级（v10 回归！）: {_drop}"
print(f"    >> 审批发经验全队在袋怪零掉级 OK（{len(_before17)} 只，含野外抓的 Lv{_keeper['level']}）")
_dbx10.x("DELETE FROM trainer_pokemon WHERE student_id=%s AND is_in_team=0", (_sid9,))
print("    >> v10 经验回填通过 ✅")

print("========== 18. v11 当日捕获额度 + 未收录优先 ==========")
# A. 配置化额度：daily_catch_limit=2 时当日第 3 次遭遇应 400
call("PUT", "/config", {"key": "daily_catch_limit", "value": "2"}, token=PTK, note="节18-额度改2")
call("PUT", "/config", {"key": "battle_weekday_open", "value": "1"}, token=PTK, note="节18-临时开学习日")
_dbx10.x("UPDATE student_user SET caught_today=0, catch_date=NULL WHERE id=%s", (_sid9,))
av18 = call("GET", "/child/battle/availability", token=TK9, note="availability 带 catch_limit")
assert av18["catch_limit"] == 2 and av18["catch_left"] == 2, f"初始应剩2/2: {av18.get('catch_left')}/{av18.get('catch_limit')}"
for _i18 in range(2):
    w18 = call("POST", "/child/battle/wild", {}, token=TK9, note=f"节18-遭遇#{_i18+1}")
    _db_raw = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pkm.sqlite3"))
    _ct18 = _db_raw.execute("SELECT caught_today, catch_date FROM student_user WHERE id=1").fetchone()
    _db_raw.close()
    st18 = call("GET", "/child/battle/availability", token=TK9, note="")
    assert st18["catch_left"] == 1 - _i18, f"遭遇后剩余应={1-_i18}，实际{st18['catch_left']}（遭遇即扣口径）raw={_ct18}"
    call("POST", "/child/battle/act", {"action": "run"}, token=TK9, note="")
w18 = call("GET", "/child/battle/availability", token=TK9, note="两次后")
# 第 3 次遭遇：额度=2 已用尽 → 400
call("POST", "/child/battle/wild", {}, token=TK9, expect=400, note="当日额度用尽应400")
print("    >> 当日额度闸门 OK（limit=2 两遇即扣、第3遇400）")
# B. 懒重置：catch_date 改到昨天 → availability 立即恢复满额度（无需任何定时任务）
_yday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
_dbx10.x("UPDATE student_user SET caught_today=2, catch_date=%s WHERE id=%s", (_yday, _sid9))
av18b = call("GET", "/child/battle/availability", token=TK9, note="跨日懒重置")
assert av18b["catch_left"] == 2, f"catch_date=昨天 应视为新的一天(剩2)，实际{av18b['catch_left']}"
w18b = call("POST", "/child/battle/wild", {}, token=TK9, note="懒重置后可遭遇")
call("POST", "/child/battle/act", {"action": "run"}, token=TK9, note="")
print("    >> 懒重置 OK（catch_date≠今天 → 满额度，天然抗重启无定时器）")
# C. 未收录加权：构造 owned=区1池前6只 → 24 次遭遇断言"非 owned"占比显著（×5 期望≈0.81）
call("PUT", "/config", {"key": "daily_catch_limit", "value": "99"}, token=PTK, note="节18C-额度充足")
_dbx10.x("DELETE FROM trainer_pokemon WHERE student_id=%s AND is_in_team=0", (_sid9,))
_pool18 = _dbx10.q("SELECT pokedex_no FROM region_wild_pokemon WHERE region_id=1")
_owned18 = [p["pokedex_no"] for p in _pool18[:6]]
_grp = {r["pokedex_no"]: r["exp_group"] for r in _dbx10.q("SELECT pokedex_no,exp_group FROM pokemon_base")}
for _no18 in _owned18:
    _dbx10.x("INSERT INTO trainer_pokemon(student_id,pokedex_no,level,total_exp,learned_skill_json,known_skill_json,is_in_team) "
             "VALUES(%s,%s,5,125,'[]','[]',0)", (_sid9, _no18))
_dbx10.x("UPDATE student_user SET caught_today=0, catch_date=NULL WHERE id=%s", (_sid9,))
_new_cnt, _own_cnt = 0, 0
for _i18 in range(24):
    w18c = call("POST", "/child/battle/wild", {}, token=TK9, note="")
    _no18 = w18c["foe"][0]["pokedex_no"]
    if _no18 in _owned18:
        _own_cnt += 1
    else:
        _new_cnt += 1
    call("POST", "/child/battle/act", {"action": "run"}, token=TK9, note="")
_ratio = _new_cnt / 24
assert _ratio >= 0.55, f"未收录加权疑似未生效：新怪占比 {_ratio:.2f}（期望≈0.8，红线0.55）"
print(f"    >> 未收录加权 OK（24 连遇新怪占比 {_ratio:.2f}，owned 6/11 只构造态）")
_dbx10.x("DELETE FROM trainer_pokemon WHERE student_id=%s AND is_in_team=0", (_sid9,))
call("PUT", "/config", {"key": "daily_catch_limit", "value": "3"}, token=PTK, note="节18-恢复默认3")
_dbx10.x("UPDATE student_user SET caught_today=0, catch_date=NULL WHERE id=%s", (_sid9,))
# D. catch 成功消耗口径：limit=2，第1次 run(不捕)+第2次 catch(捕中) 后额度应归 0/拦截
call("PUT", "/config", {"key": "battle_weekday_open", "value": "1"}, token=PTK, note="")
call("PUT", "/config", {"key": "daily_catch_limit", "value": "2"}, token=PTK, note="节18D-limit2")
w18d = call("POST", "/child/battle/wild", {}, token=TK9, note="节18D-遭遇1(run)")
call("POST", "/child/battle/act", {"action": "run"}, token=TK9, note="")
for _t18d in range(8):   # 第2遇必捕中（概率0.9上限，重试兜底）；run 也耗额度，重开即再耗
    _at18d = _dbx10.q("SELECT caught_today c FROM student_user WHERE id=%s", (_sid9,))[0]["c"]
    if _at18d >= 2:
        break
    w18d = call("POST", "/child/battle/wild", {}, token=TK9, note="")
    c18d = call("POST", "/child/battle/act", {"action": "catch"}, token=TK9, note="")
    if c18d.get("result") != "catch":
        call("POST", "/child/battle/act", {"action": "run"}, token=TK9, note="")
av18d = call("GET", "/child/battle/availability", token=TK9, note="节18D-额度")
assert av18d["catch_left"] == 0, f"2 次消耗后剩余应=0，实际{av18d['catch_left']}"
call("POST", "/child/battle/wild", {}, token=TK9, expect=400, note="节18D-耗尽应400")
call("PUT", "/config", {"key": "daily_catch_limit", "value": "3"}, token=PTK, note="")
_dbx10.x("DELETE FROM trainer_pokemon WHERE student_id=%s AND is_in_team=0", (_sid9,))
_dbx10.x("UPDATE student_user SET caught_today=0, catch_date=NULL WHERE id=%s", (_sid9,))
call("PUT", "/config", {"key": "battle_weekday_open", "value": "0"}, token=PTK, note="节18-恢复仅周末")
print("    >> v11 当日额度+图鉴优先通过 ✅")

print()
if FAILS:
    print("!!! 失败项：")
    for f in FAILS:
        print("   -", f)
    raise SystemExit(1)
print("ALL SMOKE TESTS PASSED")
