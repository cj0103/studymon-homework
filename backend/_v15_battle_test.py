# -*- coding: utf-8 -*-
"""v15 对战画面改版验证（由 _smoke_all.py 同进程 runpy 驱动，勿单独起服务跑）
A. 前端静态断言：台面/动画/箭头/徽章等关键标识在位，旧纯文本日志实现无残留
B. TYPE_CHG 与后端 type_effect 表逐格一致性（15 属性 × 非 1.0 倍率）
C. 后端契约：gym/wild/act 返回新增 moves_effect / buffs / buff / fainted 字段
D. 演出事件解析复刻：伤害/回复/MISS/中毒的主语侧向判定
"""
import json
import os
import re
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
B = "http://127.0.0.1:8471/api"
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    FAILS
except NameError:
    FAILS = []

def _call(method, path, body=None, token=None, expect=200, note=""):
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
    if code != expect:
        FAILS.append(f"v15-{note} -> {code}(期望{expect}) {txt[:120]}")
        print(f"[FAIL] v15-{note}: {code}")
        return None
    print(f"[PASS] v15-{note}")
    return json.loads(txt)

print("=== v15 对战画面验证开始 ===")

# ---------- A. 前端静态断言 ----------
html = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()
need = ["const TYPE_CHG", "const effMark", "function eventOf", "function buffBadges",
        "function unitShell", "function paintUnit", "function renderMoves",
        "function floatTxt", "function refreshHpBars", "function animateMsgs",
        "gen1-red-blue-back/", "class=\"mvarrow\"", "class=\"mvnoeff\"",
        "@keyframes hitflash", "@keyframes floatup", "@keyframes faintdrop",
        ".hpfill { height:100%; background:#2fbf5c; border-radius:4px; transition:width .6s ease; }",
        "精灵球弹开"]
miss = [n for n in need if n not in html]
if miss:
    FAILS.append(f"v15-前端缺失: {miss}")
    print(f"[FAIL] v15-前端缺失 {miss}")
else:
    print("[PASS] v15-前端关键实现全部在位")
# 捕获失败文案：后端 messages 数组化修复（原 msg 字段错位 bug）
from app.routers import battle as _bmod
_bsrc = open(os.path.join(HERE, "app", "routers", "battle.py"), encoding="utf-8").read()
if 'messages=["精灵球弹开了！"]' in _bsrc:
    print("[PASS] v15-捕获失败文案已入 messages（字段错位修复）")
else:
    FAILS.append("v15-捕获失败文案未进 messages")
    print("[FAIL] v15-捕获失败文案缺失")
# 旧实现无残留（旧版 renderArena(log) 的 pre-wrap 文本块、旧 bar 战斗行）
stale = ["white-space:pre-wrap\">${(log", "background:#e3350d\"></i></div></div>"]
st = [s for s in stale if s in html]
if st:
    FAILS.append(f"v15-旧战斗实现残留: {st}")
    print(f"[FAIL] v15-残留 {st}")
else:
    print("[PASS] v15-旧战斗实现无残留")

# ---------- B. TYPE_CHG 与后端 type_effect 一致性 ----------
from app import db as _db
_rows = _db.q("SELECT attack_type,defend_type,rate FROM type_effect")
_backend = {(r["attack_type"], r["defend_type"]): float(r["rate"])
            for r in _rows if float(r["rate"]) != 1.0}
_m = re.search(r"const TYPE_CHG = \{(.*?)\n\};", html, re.S)
_front = {}
for line in _m.group(1).splitlines():
    am = re.match(r'\s*"(.+?)":\{(.*)\},?\s*$', line)
    if not am:
        continue
    atk, body = am.group(1), am.group(2)
    for k, v in re.findall(r'"(.+?)":([\d.]+)', body):
        _front[(atk, k)] = float(v)
bad = []
for k, v in _backend.items():
    if k not in _front or abs(_front[k] - v) > 1e-9:
        bad.append(("后端有前端缺/错", k, v))
for k in _front:
    if k not in _backend:
        bad.append(("前端多出", k, _front[k]))
if bad:
    FAILS.append(f"v15-TYPE_CHG 与后端不一致: {bad}")
    print(f"[FAIL] v15-相克表不一致 {bad[:5]}")
else:
    print(f"[PASS] v15-TYPE_CHG 与后端 type_effect 一致（{len(_backend)} 格非中性倍率）")

# ---------- C. 后端契约：新字段 ----------
pt = _call("POST", "/parent/login", {"phone": "13800000000", "password": "admin123"}, note="家长登录")
PTK = pt["token"]
devs = _call("GET", "/parent/devices", token=PTK, note="设备列表")
kid_dev = [d["token"] for d in devs if d["role"] == "kid" and d.get("enabled")]
if not kid_dev:
    iss = _call("POST", "/parent/device/issue", {"role": "kid", "label": "v15临时", "student_id": 1},
                token=PTK, note="签发临时孩子令牌")
    kid_dev = [iss["token"]]
    _cleanup_dev = iss["token"]
else:
    _cleanup_dev = None
rj = _call("GET", f"/resolve/{kid_dev[0]}", note="孩子令牌 resolve")
STK = rj["token"]
_call("PUT", "/config", {"key": "battle_weekday_open", "value": "1"}, token=PTK, note="放行战斗")

# 组队：确保出战 1 只且**有招**（v12 专项会清空 learned_skill_json，空队报"先设置出战队伍"400）
from app.routers.pokemon import learnable as _learnable
_rows = _db.q("SELECT id,pokedex_no,level,learned_skill_json FROM trainer_pokemon WHERE student_id=%s", (1,))
if not _rows:
    _db.x("INSERT INTO trainer_pokemon(student_id,pokedex_no,level,total_exp,sealed,is_in_team,"
          "learned_skill_json,known_skill_json) VALUES(1,25,10,610,0,1,'[]','[]')")
    _rows = _db.q("SELECT id,pokedex_no,level,learned_skill_json FROM trainer_pokemon WHERE student_id=1", ())
_mv0 = _learnable(_rows[0]["pokedex_no"], _rows[0]["level"])
_db.x("UPDATE trainer_pokemon SET learned_skill_json=%s WHERE id=%s",
      (json.dumps(_mv0), _rows[0]["id"]))
_ids = [r["id"] for r in _rows]
_call("POST", "/child/team", {"team_ids": _ids[:1]}, token=STK, note="组队 1 只")

g = _call("POST", "/child/battle/gym", {}, token=STK, note="开道馆战")
assert g is not None
for k in ("moves_effect", "buffs", "my", "foe"):
    if k not in g:
        FAILS.append(f"v15-gym 返回缺 {k}")
        print(f"[FAIL] v15-gym 缺 {k}")
    else:
        print(f"[PASS] v15-gym 返回带 {k}")
if "buffs" in g and not any(u["ref"] in g["buffs"] for u in g["my"]):
    pass  # buffs 键为 ref，初值为 1 时可缺省
if not all("buff" in u and "fainted" in u for u in g["my"] + g["foe"]):
    FAILS.append("v15-单位缺 buff/fainted 字段")
    print("[FAIL] v15-单位缺 buff/fainted")
else:
    print("[PASS] v15-单位带 buff/fainted 展示字段")
me0 = g["my"][0]
foe0 = g["foe"][g.get("foe_idx", 0)]
me_types, foe_types = set(me0["types"]), set(foe0["types"])
for e in g.get("moves_effect", []):
    if not (e["rate"] in (0, 0.25, 0.5, 1.0, 2.0, 4.0)):
        FAILS.append(f"v15-rate 异常 {e}")
print(f"[PASS] v15-moves_effect {len(g.get('moves_effect', []))} 条倍率合法（我={me0['name']}{sorted(me_types)} vs 敌={foe0['name']}{sorted(foe_types)}）")

# 打若干回合直到战斗结束或 25 次，检查 act 返回契约
rounds = 0
while rounds < 25:
    mv = next((m for m in me0["moves"] if m["power"] > 0), me0["moves"][0] if me0["moves"] else None)
    if not mv:
        break
    r = _call("POST", "/child/battle/act", {"action": "attack", "skill_id": mv["id"]},
              token=STK, note=f"攻击回合{rounds+1}")
    if r is None:
        break
    for k in ("my", "foe", "buffs"):
        assert k in r, f"act 返回缺 {k}"
    if rounds == 0 and not r.get("moves_effect"):
        FAILS.append("v15-act(continue) 缺 moves_effect")
        print("[FAIL] v15-act 缺 moves_effect")
    rounds += 1
    if r["result"] in ("win", "lose", "catch"):
        print(f"[PASS] v15-战斗在 {rounds} 回合内结束（{r['result']}），契约字段齐备")
        break
else:
    _call("POST", "/child/battle/act", {"action": "run"}, token=STK, note="逃跑收尾")
# 会话可能已销毁，逃跑兜底（若已结束则 400 可接受）
_call("POST", "/child/battle/act", {"action": "run"}, token=STK, expect=400,
      note="会话已销毁后再逃跑应400") if rounds and rounds < 25 else None

# 野生遭遇返回契约
w = _call("POST", "/child/battle/wild", {}, token=STK, note="野生遭遇契约")
if w is not None:
    if "moves_effect" not in w or "buffs" not in w:
        FAILS.append("v15-wild 缺 moves_effect/buffs")
    else:
        print("[PASS] v15-wild 返回带 moves_effect/buffs")
    _call("POST", "/child/battle/act", {"action": "run"}, token=STK, note="野生逃跑收尾")
_call("PUT", "/config", {"key": "battle_weekday_open", "value": "0"}, token=PTK, note="恢复仅周末")
if _cleanup_dev:
    _call("DELETE", f"/parent/device/{_cleanup_dev}", token=PTK, note="删除临时令牌")

# ---------- D. 演出解析复刻（与前端 eventOf 同步的语义断言） ----------
def event_of(l):
    foe_actor = bool(re.match(r"^对方的", l))
    who = "me" if foe_actor else "foe"
    if re.search(r"精灵球弹开|没有命中", l):
        return ("miss", who, None)
    if re.search(r"打到自己", l):
        return ("self", "foe" if foe_actor else "me", 1)
    mh = re.search(r"使用 \S+，恢复了 (\d+) 点体力", l)
    mc = re.search(r"造成 (\d+) 伤害", l)
    mz = re.search(r"因中毒受到 (\d+) 伤害", l)
    if mz:
        return ("dmg", "foe" if foe_actor else "me", int(mz.group(1)))
    if mc:
        return ("dmg", who, int(mc.group(1)))
    if mh:
        return ("heal", "foe" if foe_actor else "me", int(mh.group(1)))
    return (None, who, None)

cases = [
    ("皮卡丘 使用 电击，造成 12 伤害", ("dmg", "foe", 12)),
    ("对方的 大针蜂 使用 毒针，造成 8 伤害", ("dmg", "me", 8)),
    ("你的 皮卡丘 使用 自我再生，恢复了 20 点体力！", ("heal", "me", 20)),
    ("对方的 派拉斯 使用 吸取，造成 5 伤害并吸取了 2 点体力！", ("dmg", "me", 5)),
    ("皮卡丘 的电击 没有命中", ("miss", "foe", None)),
    ("精灵球弹开了！", ("miss", "foe", None)),
    ("对方的 大针蜂 因中毒受到 9 伤害！", ("dmg", "foe", 9)),
    ("你的 皮卡丘 因中毒受到 9 伤害！", ("dmg", "me", 9)),
    ("你的 皮卡丘 使用 电击，造成 12 伤害", ("dmg", "foe", 12)),
    ("对方的 卡比兽 混乱了，打到自己！", ("self", "foe", 1)),
    ("上吧，雷丘！", (None, "foe", None)),
]
dbad = [(l, event_of(l), want) for l, want in cases if event_of(l) != want]
if dbad:
    FAILS.append(f"v15-eventOf 复刻失配: {dbad}")
    print(f"[FAIL] v15-事件解析 {dbad}")
else:
    print(f"[PASS] v15-事件解析 {len(cases)} 例语义正确（伤害/回复/MISS/中毒主客侧）")

print(f"=== v15 验证结束，FAILS+={len([f for f in FAILS if f.startswith('v15')])} ===")
