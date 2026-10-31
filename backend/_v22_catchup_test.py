# -*- coding: utf-8 -*-
"""v22 追赶加成验证（由 _smoke_all.py 同进程 runpy 驱动）
A. 纯函数 exp_permille_p：到基准取消 / 指数单调 / 差10级>差5级 / 封顶 / 死区 / 底数≤1关闭
B. 配置生效：PUT /config catchup_base → exp_permille 随之变化；非 EDITABLE 键被拒
C. base_level：0 徽章→16、全 8 徽章→46（现场备份-改-还原）
D. apply_exp 先分后乘：3 只不同等级，低怪 delta 高、n=1 怪 delta=份额；exp_log 落 delta
E. 驳回等比回收：无发放流水的负发放，sum 严格=-amount、缺口怪多扣
F. 历史实发回收：checkin 发放→改队伍→reject，逐只按 exp_log 实发回收（不随新等级漂移）
G. 现场还原：徽章/sys_config/trainer_pokemon/exp_log 全部回复位
"""
import json
import os
import urllib.request
import urllib.error

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    FAILS
except NameError:
    FAILS = []

def _ok(m): print(f"[PASS] v22-{m}")
def _fail(m):
    FAILS.append(f"v22-{m}")
    print(f"[FAIL] v22-{m}")

def _api(method, path, body=None, token=None):
    req = urllib.request.Request("http://127.0.0.1:8471/api" + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token: req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with _opener.open(req, data) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode() or "{}")
        except Exception: return e.code, {}

print("=== v22 追赶加成验证开始 ===")
from app import db, exp as expmod

# ---------- A. 纯函数曲线 ----------
p = expmod.exp_permille_p
if p(0, 1.30, 8) == 1000 and p(-3, 1.30, 8) == 1000:
    _ok("差距≤0 → n=1 加成自动取消")
else:
    _fail("到基准未取消")
vals = [p(g, 1.30, 8) for g in range(0, 9)]
if all(vals[i] < vals[i+1] for i in range(7)):
    _ok("指数曲线严格单调升 (1.00→%.2f)" % (vals[7]/1000))
else:
    _fail(f"曲线非单调: {vals}")
if p(10, 1.30, 8) > p(5, 1.30, 8):
    _ok(f"差10级({p(10,1.30,8)/1000:.2f})>差5级({p(5,1.30,8)/1000:.2f})，家长口径满足")
else:
    _fail("差10级未多于差5级")
if p(30, 1.30, 8) == 8000:
    _ok("gap=30 触顶 ×8 封顶")
else:
    _fail(f"封顶异常: {p(30,1.30,8)}")
if abs(p(2, 1.30, 99) - 1690) <= 1:
    _ok(f"千分比逐步整除无浮点误差 1.30^2={p(2,1.30,99)}")
else:
    _fail(f"千分比误差: {p(2,1.30,99)} != 1690")
if p(2, 1.30, 8, dead=2) == 1000 and p(3, 1.30, 8, dead=2) == 2197:
    _ok("死区：差距≤2不吃，3级恢复加成(1.30^3=2.197)")
else:
    _fail(f"死区异常: {p(2,1.30,8,dead=2)}/{p(3,1.30,8,dead=2)}")
if p(9, 1.0, 8) == 1000:
    _ok("底数=1 总开关关闭（恒1000）")
else:
    _fail("底数≤1 未关闭")

# ---------- B. 配置接线 ----------
devs = db.q("SELECT token FROM device_token WHERE role='parent' AND enabled=1")
st, j = _api("POST", "/parent/unlock", {"token": devs[0]["token"], "pin": "admin123"})
assert st == 200 and j.get("token"), f"家长解锁失败 {st} {j}"
PT = j["token"]

_catch_keys = ("catchup_base", "catchup_max_mult", "catchup_dead")
_cfg_all = db.q("SELECT cfg_key,cfg_value FROM sys_config WHERE cfg_key IN "
                "(" + ",".join(["%s"] * 3) + ")", _catch_keys)
cfg_backup = {r["cfg_key"]: r["cfg_value"] for r in _cfg_all}
_seeded_before = {r["cfg_key"] for r in _cfg_all}   # 本测试负责补种 SQL 种子（线上幂等脚本同源）
for _k, _v in expmod.CATCHUP_DEFAULTS.items():
    if _k not in _seeded_before:
        db.set_cfg(_k, _v)

st, r = _api("PUT", "/config", {"key": "catchup_base", "value": "1.5"}, token=PT)
v_cfg = expmod.exp_permille(2)
st3, r3 = _api("PUT", "/config", {"key": "_not_exist_key", "value": "1"}, token=PT)
if st == 200 and abs(v_cfg - 2250) <= 2:
    _ok("家长端 catchup_base=1.5 → n(2) 配置驱动生效")
else:
    _fail(f"配置驱动失效 st={st} n(2)={v_cfg}")
if st3 == 400:
    _ok("非 EDITABLE 白名单键被拒")
else:
    _fail(f"白名单未拦截: {st3}")
st, cfgrow = _api("GET", "/config", token=PT)
if all(k in cfgrow for k in _catch_keys):
    _ok("GET /config 返回追赶三参数")
else:
    _fail(f"GET /config 缺追赶键: {sorted(cfgrow)[:20]}")

# ---------- C. base_level 基准级 ----------
kid = db.q("SELECT id, badge_json FROM student_user ORDER BY id LIMIT 1")[0]
badge_backup = kid["badge_json"]
try:
    db.x("UPDATE student_user SET badge_json=NULL WHERE id=%s", (kid["id"],))
    b0 = expmod.base_level(kid["id"])
    db.x("UPDATE student_user SET badge_json=%s WHERE id=%s",
         (json.dumps(["灰色徽章","蓝色徽章","橙色徽章","彩虹徽章","粉红徽章","金色徽章","深红徽章","绿色徽章"], ensure_ascii=False), kid["id"]))
    b8 = expmod.base_level(kid["id"])
    if b0 == 16 and b8 == 46:
        _ok("基准级：0徽章→16(馆1) 全徽章→46(馆8)")
    else:
        _fail(f"基准级异常 b0={b0} b8={b8}")
finally:
    db.x("UPDATE student_user SET badge_json=%s WHERE id=%s",
         (json.dumps(json.loads(badge_backup or "[]"), ensure_ascii=False), kid["id"]))

# ---------- D. apply_exp 先分后乘 ----------
# 现场：3 只不同等级怪入队（medium 组）。先把 catchup_base 校准回 1.30
# （B 段曾置 1.5 验证配置驱动；等级带按 tgt 动态选，保证 n 全部未触顶）
from app import exp as _e
db.set_cfg("catchup_base", "1.30")
db.x("DELETE FROM trainer_pokemon WHERE student_id=%s", (kid["id"],))
db.x("DELETE FROM exp_log WHERE student_id=%s", (kid["id"],))
tgt = expmod.base_level(kid["id"])   # 真实进度口径：冒烟链此节徽章未动，tgt 以实测为准
# pokedex 16（绿毛虫）经验组是 **slow**（探针实锤：勿按"medium"想当然）。
# 等级带按"发放时 n"选：2/4/6 级差距的 n 与 slow 组同级经验跨度匹配，不会触顶
from app import db as _db0
_grp = _db0.q("SELECT exp_group FROM pokemon_base WHERE pokedex_no=16")[0]["exp_group"] or "medium"
lvs = [tgt - 2, tgt - 4, tgt - 6]
# 等级带按"发放时 n"选：差距 2/4/6 级 n=1.69/2.86/4.83 未触顶；
# 后期每级经验门槛差 2500+，低怪拿 n×100 也只涨半级（不升级是曲线正常态），
# 因此"低怪升级"断言只在早段基准（馆1 Lv16，每级门槛差<500）下才验，见下方条件断言
tp_ids = []
for i, lv in enumerate(lvs):
    floor = _e.exp_floor(_grp, lv)
    tid = db.x("INSERT INTO trainer_pokemon(student_id,pokedex_no,level,total_exp,"
               "learned_skill_json,known_skill_json,is_in_team,slot) "
               "VALUES(%s,16,%s,%s,'[]','[]',1,%s)", (kid["id"], lv, floor, i), ret_id=True)
    tp_ids.append(tid)
_lv_at_insert = dict(zip(tp_ids, lvs))      # E 段按"发放时等级"判 n 加权（发放后低怪会连升，等级序可反转）
res = expmod.apply_exp(kid["id"], 300, "checkin", 900001)   # reason 用真实发放口径（①回收只认 checkin/carry）
d = {x["trainer_pokemon_id"]: x["delta"] for x in res["details"]}
# 期望：份额=int(300/3)=100；delta=int(份额×千分比n/1000)
# n 必须走引擎同源函数 exp_permille_p（逐步千分比整除）——禁用浮点幂：
# 1.30**4 浮点=2.8561000000000004 时 floor 差 1（首跑实锤）
exp_d = {}
_pm_map = {g: expmod.exp_permille_p(g, 1.30, 8) for g in (2, 4, 6)}
for tid, lv in zip(tp_ids, lvs):
    exp_d[tid] = 100 * _pm_map[tgt - lv] // 1000
if all(d.get(tid) == exp_d[tid] for tid in tp_ids):
    _ok(f"先分后乘逐只精确 L{tgt-2}:{d[tp_ids[0]]} L{tgt-4}:{d[tp_ids[1]]} L{tgt-6}:{d[tp_ids[2]]}")
else:
    _fail(f"delta 不符 got={d} exp={exp_d}")
if d.get(tp_ids[2], 0) > d.get(tp_ids[1], 0) > d.get(tp_ids[0], 0):
    _ok("低等级怪实得严格更多（家长核心诉求）")
else:
    _fail(f"低怪未更多: {d}")
logs = db.q("SELECT trainer_pokemon_id, exp_delta FROM exp_log WHERE student_id=%s AND ref_id=900001", (kid["id"],))
if len(logs) == 3 and {l["trainer_pokemon_id"]: l["exp_delta"] for l in logs} == d:
    _ok("exp_log 记录的是加成后实发 delta")
else:
    _fail(f"exp_log 不符: {logs}")
lv_low = db.q("SELECT level,total_exp,pokedex_no FROM trainer_pokemon WHERE id=%s", (tp_ids[2],))[0]
_grp_low = _db0.q("SELECT exp_group FROM pokemon_base WHERE pokedex_no=%s", (lv_low["pokedex_no"],))[0]["exp_group"]
_exp_lv = expmod.level_for(_grp_low, lv_low["total_exp"])
if tgt <= 16 and lv_low["level"] == _exp_lv and lv_low["level"] > tgt - 6:
    _ok(f"早段基准：低怪经加成连升 Lv{tgt-6}→Lv{lv_low['level']}")
elif lv_low["level"] == _exp_lv:
    _ok(f"后期基准({tgt})经验落账自洽（每级门槛差2500+，不足门槛不升级=曲线正常态）")
else:
    _fail(f"低怪落账脱钩: {lv_low} level_for={_exp_lv}")

# ---------- E. 等比回收（无发放流水） ----------
before = {r["id"]: r["total_exp"] for r in
          db.q("SELECT id,total_exp FROM trainer_pokemon WHERE student_id=%s", (kid["id"],))}
res2 = expmod.apply_exp(kid["id"], -150, "_v22neg", 900002)
d2 = {x["trainer_pokemon_id"]: x["delta"] for x in res2["details"]}
after = {r["id"]: r["total_exp"] for r in
         db.q("SELECT id,total_exp FROM trainer_pokemon WHERE student_id=%s", (kid["id"],))}
if sum(d2.values()) == -150:
    _ok(f"等比回收总和严格=-150 {d2}")
else:
    _fail(f"回收总额不勾稽: {sum(d2.values())} {d2}")
_lvnow = {r["id"]: r["level"] for r in
          db.q("SELECT id,level FROM trainer_pokemon WHERE student_id=%s", (kid["id"],))}
if abs(d2[tp_ids[2]]) >= abs(d2[tp_ids[0]]):
    _ok("回收也按 n 加权：等级低（n大）的怪多扣")
else:
    _fail(f"回收未按 n 加权: {d2}")
if all(after[i] - before[i] == d2.get(i, 0) for i in before):
    _ok("total_exp 变动与 delta 一致")
else:
    _fail(f"total_exp 变动不符 before={before} after={after} d={d2}")

# ---------- F. 历史实发回收（驳回链路） ----------
# 发放前清扫 D 段流水：①口径按 ref_id 聚合，同 ref_id 两笔发放会串账
db.x("DELETE FROM exp_log WHERE student_id=%s AND ref_id=900001", (kid["id"],))
res3 = expmod.apply_exp(kid["id"], 300, "checkin", 900003)
paid = {x["trainer_pokemon_id"]: x["delta"] for x in res3["details"]}
# 改队伍：把两只移出、剩一只（模拟发放后孩子调整队伍，reject 仍须按发放时的三只回收）
db.x("UPDATE trainer_pokemon SET is_in_team=0 WHERE id IN (%s,%s)", (tp_ids[0], tp_ids[2]))
exp_before = {r["id"]: r["total_exp"] for r in
              db.q("SELECT id,total_exp FROM trainer_pokemon WHERE student_id=%s", (kid["id"],))}
res4 = expmod.apply_exp(kid["id"], -sum(paid.values()), "_v22rej", 900003)
d4 = {x["trainer_pokemon_id"]: x["delta"] for x in res4["details"]}
if d4 == {k: -v for k, v in paid.items()}:
    _ok("按 exp_log 实发逐只回收（含已离队怪，与发放一一对应）")
else:
    _fail(f"实发回收不符 paid={paid} got={d4}")
db.x("UPDATE trainer_pokemon SET is_in_team=1 WHERE id IN (%s,%s)", (tp_ids[0], tp_ids[2]))

# ---------- G. 源码/前端断言 ----------
base_dir = os.path.dirname(os.path.abspath(__file__))
html = open(os.path.join(base_dir, "web", "parent.html"), encoding="utf-8").read()
gd = open(os.path.join(base_dir, "web", "guide.html"), encoding="utf-8").read()
if "catchup_base" in html and "catchup_max_mult" in html:
    _ok("parent.html 追赶三参数输入框接线")
else:
    _fail("parent.html 缺追赶参数界面")
if "每差 1 级多 30%" in gd:
    _ok("guide.html 孩子端追赶话术在位")
else:
    _fail("guide.html 缺追赶话术")

# ---------- 现场还原 ----------
# 注意：不能整进程 reset——task_template（v21 已验证的任务菜单）与 sys_config
# 属配置表不在 reset 范围，但 trainer_pokemon 整删会连带抹掉其它测试建的状态；
# 只回滚本测试动过的三处：宝可梦行、经验流水、追赶配置键。
db.x("DELETE FROM trainer_pokemon WHERE student_id=%s", (kid["id"],))
db.x("DELETE FROM exp_log WHERE student_id=%s", (kid["id"],))
if db.ENGINE == "sqlite":
    db.x("DELETE FROM sqlite_sequence WHERE name='trainer_pokemon'")
# 恢复 driver 约定的出战怪（v16 段同款：1 只 ≤4 招入队）
import json as _json
from app.routers.pokemon import learnable as _lk
from app import exp as _e2
_no = db.q("SELECT pokedex_no FROM pkm_starters ORDER BY pokedex_no")
_starter = _no[0]["pokedex_no"] if _no else 25
_mv = _lk(_starter, 1)
_ids = _json.dumps(_mv)
_grp = db.q("SELECT exp_group FROM pokemon_base WHERE pokedex_no=%s", (_starter,))
db.x("INSERT INTO trainer_pokemon(student_id,pokedex_no,level,total_exp,"
     "learned_skill_json,known_skill_json,is_in_team,slot) VALUES(%s,%s,1,%s,%s,%s,1,0)",
     (kid["id"], _starter, _e2.exp_floor((_grp[0]["exp_group"] if _grp else None) or "medium", 1),
      _ids, _ids))
for k, v in cfg_backup.items():
    db.set_cfg(k, v)
for k in _catch_keys:
    if k not in cfg_backup:
        db.x("DELETE FROM sys_config WHERE cfg_key=%s", (k,))
print(f"=== v22 验证结束，FAILS={len(FAILS)} ===")
