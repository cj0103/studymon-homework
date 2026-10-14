# -*- coding: utf-8 -*-
"""v17 捕捉谱系统一口径验证（由 _smoke_all.py 同进程 runpy 驱动）
场景：孩子只持有独角虫(#13) Lv8 → 引擎进化为铁壳蛹(#14) → 指南/图鉴 lit、
野外加权、重复捕捉落点。真表口径：13→14 Lv7，14→15 Lv10。
A. lit_set：背包 ∪ rev 前身回溯。持虫恰 {13}（不向后穿透）；持蛹 {13,14}；
   持蜂整链亮；无关怪不亮
B. maybe_evolve Lv8 独角虫→铁壳蛹；catch_target 前身落点/无链 None/后代不穿透
C. guide/pokedex HTTP：进化为蛹后前身 #13 不再回退？？？（bug 主现场回归）
D. 源码断言（加权与结算接入口径）
"""
import json
import os
import urllib.request
import urllib.error
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    FAILS
except NameError:
    FAILS = []

def _ok(m): print(f"[PASS] v17-{m}")
def _fail(m):
    FAILS.append(f"v17-{m}")
    print(f"[FAIL] v17-{m}")

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

print("=== v17 捕捉谱系验证开始 ===")
from app import db
from app import dexline
from app.evolve import maybe_evolve

_kid = db.q("SELECT id FROM student_user ORDER BY id LIMIT 1")
_sid = _kid[0]["id"]

# 真表口径防御性核对：13→14 Lv7，14→15 Lv10（链={13,14,15}）
_e13 = db.q("SELECT to_no,min_level FROM pkm_evolution WHERE from_no=13")
_e14 = db.q("SELECT to_no,min_level FROM pkm_evolution WHERE from_no=14")
if not (_e13 and _e13[0]["to_no"] == 14 and _e14 and _e14[0]["to_no"] == 15):
    _fail(f"进化表口径异常 13→{_e13} 14→{_e14}")
_CHAIN = {13, 14, 15}
_UNRELATED = {10, 11, 12, 16, 19}   # 绿毛虫链/波波链/小拉达——都不应被点亮

# ---------- A. lit_set（口径：背包 ∪ 沿 rev 回溯前身，不向后进化穿透） ----------

db.x("DELETE FROM trainer_pokemon WHERE student_id=%s", (_sid,))
db.x("INSERT INTO trainer_pokemon(student_id,pokedex_no,level,total_exp,sealed,is_in_team,"
     "learned_skill_json,known_skill_json) VALUES(%s,13,8,560,0,0,'[]','[]')", (_sid,))
mon = db.q("SELECT id FROM trainer_pokemon WHERE student_id=%s", (_sid,))[0]
lit = dexline.lit_set(_sid)
if lit != {13}:
    _fail(f"持虫(最前身) lit 应恰为 {{13}}（不向后进化穿透）: {sorted(lit)}")
else:
    _ok("lit_set：持有独角虫（最前身）→ 恰 {13}，不点亮未见过的蛹/蜂")
if lit & _UNRELATED:
    _fail(f"lit_set 不应点亮无关怪: {sorted(lit & _UNRELATED)}")
else:
    _ok("lit_set：无关怪（10-12/16/19）不点亮")

# 进化前史：持蛹(#14)点亮前身虫(#13)；不向后穿透点亮蜂(#15)
db.x("UPDATE trainer_pokemon SET pokedex_no=14 WHERE id=%s", (mon["id"],))
lit2 = dexline.lit_set(_sid)
if lit2 != {13, 14}:
    _fail(f"持蛹 lit 应为 {{13,14}}（含前身不含蜂）: {sorted(lit2)}")
else:
    _ok("lit_set：持有铁壳蛹 → {虫,蛹}，蜂未进化过不点亮")
# 三段链全点亮仅在持有最终形态（蜂）时成立
db.x("UPDATE trainer_pokemon SET pokedex_no=15 WHERE id=%s", (mon["id"],))
lit3 = dexline.lit_set(_sid)
if not _CHAIN <= lit3:
    _fail(f"持蜂(最终形态)应点亮整链: {sorted(lit3)}")
else:
    _ok("lit_set：持有大针蜂（最终形态）→ 整链 {13,14,15} 点亮（进化前史）")

# ---------- B. catch_target ----------
# 回到 Lv8 独角虫，用进化引擎进化为铁壳蛹（模拟真实进化后背包无原始形态）
db.x("UPDATE trainer_pokemon SET pokedex_no=13, level=8 WHERE id=%s", (mon["id"],))
res = maybe_evolve(mon["id"])
_now = db.q("SELECT pokedex_no FROM trainer_pokemon WHERE id=%s", (mon["id"],))[0]["pokedex_no"]
if _now == 14:
    _ok(f"maybe_evolve Lv8 独角虫→铁壳蛹（chain={res}）")
else:
    _fail(f"进化未发生 pokedex_no={_now} res={res}")
# 当前背包：独角虫已进化为铁壳蛹(#14)。再遇前身 #13 → 应喂给 #14
t = dexline.catch_target(_sid, 13)
if t == mon["id"]:
    _ok("catch_target：再遇小形态(13) → 落点=同链持有者（进化后的那只）")
else:
    _fail(f"catch_target 同链落点错: {t} vs {mon['id']}")
t2 = dexline.catch_target(_sid, 19)
if t2 is None:
    _ok("catch_target：无同链持有者 → None（正常入袋新怪）")
else:
    _fail(f"catch_target 无链应 None，实得 {t2}")
# 方向性回归：背包只有蛹(#14)，再遇进化后形态 #15 → 无前身可喂，应 None 入袋
t3 = dexline.catch_target(_sid, 15)
if t3 is None:
    _ok("catch_target：背包只有蛹，遇蜂(15) → None（不向后穿透误喂）")
else:
    _fail(f"catch_target 不应把蜂喂给蛹，实得 {t3}")

# ---------- C. guide HTTP ----------
_dev = db.q("SELECT token FROM device_token WHERE role='kid' AND ref_id=%s AND enabled=1 "
            "ORDER BY create_time LIMIT 1", (_sid,))
TK = None
if _dev:
    c, j = _api("GET", "/resolve/" + urllib.parse.quote(_dev[0]["token"]))
    TK = j.get("token")
if not TK:
    _fail("无 kid HTTP 令牌，跳过 C/D-HTTP")
else:
    c, g = _api("GET", "/child/guide", token=TK)
    if c != 200:
        _fail(f"guide 接口 {c}")
    # 当前背包=进化后的蛹(#14)，前身虫(#13)必须仍 owned（bug 主现场回归）
    c, g = _api("GET", "/child/guide", token=TK)
    if c != 200:
        _fail(f"guide 接口 {c}")
    else:
        pk = {p["pokedex_no"]: p for reg in g["regions"] for p in reg["pokemon"]}
        bad = [n for n in (13, 14) if n in pk and not pk[n]["owned"]]
        if bad:
            _fail(f"进化后指南仍显未抓: {bad}")
        else:
            _ok("guide：进化为蛹后，前身虫 #13 仍 owned=true（不再回退？？？）")
        c2, dex = _api("GET", "/child/pokedex", token=TK)
        dmap = {d["pokedex_no"]: d for d in dex} if c2 == 200 else {}
        # guide 只列各区野怪清单（蛹/蜂不刷新野即不在清单）→ 仅比共有号
        _common = [n for n in (13, 14, 15) if n in pk and n in dmap]
        if all(pk[n]["owned"] == dmap[n]["owned"] for n in _common) and _common:
            _ok(f"pokedex 与 guide 同口径（共有号 {_common}）")
        else:
            _fail(f"pokedex/guide 口径不一致: "
                  f"{ {n: (pk[n]['owned'], dmap[n]['owned']) for n in _common} }")

# ---------- D. 源码断言（加权与结算接入口径） ----------
bsrc = open(os.path.join(HERE, "app", "routers", "battle.py"), encoding="utf-8").read()
if "dexline.lit_set(sid)" in bsrc and "dexline.catch_target(sid, no)" in bsrc:
    _ok("battle.py：野外加权用 lit_set、重复捕捉结算用 catch_target")
else:
    _fail("battle.py 未接入谱系口径")
psrc = open(os.path.join(HERE, "app", "routers", "pokemon.py"), encoding="utf-8").read()
if psrc.count("dexline.lit_set") >= 2:
    _ok("pokemon.py：guide 与 pokedex 双入口用 lit_set")
else:
    _fail(f"pokemon.py lit_set 引用 {psrc.count('dexline.lit_set')} 处")

# 恢复干净（避免影响后续专项）
db.x("DELETE FROM trainer_pokemon WHERE student_id=%s", (_sid,))
print(f"=== v17 验证结束，FAILS+={len([f for f in FAILS if f.startswith('v17')])} ===")
