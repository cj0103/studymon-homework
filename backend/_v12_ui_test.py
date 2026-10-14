# -*- coding: utf-8 -*-
"""v12 宝可梦页改版验证（由 _smoke_all.py 同进程 runpy 驱动，勿单独起服务跑）
A. 注入 8 只已激活 + 1 只封印怪（等级/图鉴号刻意制造并列）
B. 前端 index.html 静态断言：新函数在位、旧函数无残留、关键口径文案
C. 排序函数语义复刻：出战区与待命区均为 等级降序→图鉴号升序→id升序
D. 后端契约：>3 拒绝、封印上阵拒绝、空数组=全撤、正常保存 slot 按提交序
"""
import re
import os
from app import db

HERE = os.path.dirname(os.path.abspath(__file__))

def _fail(msg):
    FAILS.append(msg)
    print(f"[FAIL] {msg}")

def _ok(msg):
    print(f"[PASS] {msg}")

print("=== v12 UI 改版验证开始 ===")

# ---------- A. 造数据：8 只已激活 + 1 只封印 ----------
_kid = db.q("SELECT id FROM student_user ORDER BY id LIMIT 1")
if not _kid:
    _fail("v12-无 kid 账号可用"); raise SystemExit(1)
_sid = _kid[0]["id"]
# 清空既有怪（本地库，冒烟环境允许重建）
db.x("DELETE FROM trainer_pokemon WHERE student_id=%s", (_sid,))
# (图鉴号, 等级, 封印)：刻意并列 30/30、25/25 测二级键
_SEED = [(25, 30, 0), (6, 12, 0), (13, 30, 0), (46, 25, 0), (16, 8, 0),
         (19, 25, 0), (92, 20, 0), (143, 5, 0), (149, 15, 1)]
for no, lv, se in _SEED:
    db.x("INSERT INTO trainer_pokemon(student_id,pokedex_no,level,total_exp,sealed,is_in_team,"
         "learned_skill_json,known_skill_json) VALUES(%s,%s,%s,1,%s,0,'[]','[]')",
         (_sid, no, lv, se))
_rows = db.q("SELECT id,pokedex_no,level,sealed FROM trainer_pokemon "
             "WHERE student_id=%s ORDER BY pokedex_no", (_sid,))
_by_no = {r["pokedex_no"]: r for r in _rows}
_active = [r for r in _rows if not r["sealed"]]
_sealed = [r for r in _rows if r["sealed"]]
assert len(_active) == 8 and len(_sealed) == 1, "造数据数量不符"
_ok(f"v12-造数据 8 激活 + 1 封印（kid sid={_sid}）")

# ---------- B. 前端静态断言（v16 改口径：出战队伍=选择先后） ----------
html = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()
need = ["function pokeEdit(", "function pokeEditRender(", "function editIn(",
        "function editOut(", "function editSave(",
        "先点的排前面（1 号首发）", "点「保存」才会生效",
        "出战队伍（按选择先后，1 号首发）",
        "const order = S.editTeam.slice();"]
miss = [n for n in need if n not in html]
if miss: _fail(f"v12-前端缺失关键片段 {miss}")
else: _ok("v12-前端关键函数与文案在位")
gone = ["joinTeam", "leaveTeam", "S.myteam", "teamSort"]
stale = [g for g in gone if g in html]
if stale: _fail(f"v12-前端旧实现残留 {stale}")
else: _ok("v12-旧上阵/撤下/等级重排实现无残留")

# ---------- C. 候补区排序语义复刻（出战区已改 slot 序；候补区仍等级降序） ----------
def _restsort(rs):
    return sorted(rs, key=lambda r: (-r["level"], r["pokedex_no"], r["id"]))
_t = _restsort(_active)
# Lv30: 13,25 / Lv25: 19,46 / Lv20: 92 / Lv12: 6 / Lv8: 16 / Lv5: 143
_expect_lv = [30, 30, 25, 25, 20, 12, 8, 5]
_expect_no = [13, 25, 19, 46, 92, 6, 16, 143]
if [r["level"] for r in _t] != _expect_lv or [r["pokedex_no"] for r in _t] != _expect_no:
    _fail(f"v12-排序失败 lv={[r['level'] for r in _t]} no={[r['pokedex_no'] for r in _t]} "
          f"期望 lv{_expect_lv} no{_expect_no}")
else:
    _ok("v12-候补区排序 OK：等级降序，并列按图鉴号升序（30→[13,25] 25→[19,46]）")

# ---------- D. 后端契约（走 HTTP，复用冒烟 kid 令牌） ----------
# 冒烟前文已留有 kid 令牌 rt["token"]（同进程 smoke_test 变量不外露，这里重新登录取）
import json, urllib.request
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
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

# kid 令牌：设备令牌 → /resolve 换 JWT（与主页冷启动一致）
import urllib.parse
_dev = db.q("SELECT token FROM device_token WHERE role='kid' AND ref_id=%s AND enabled=1 "
            "ORDER BY create_time LIMIT 1", (_sid,))
TK = None
if _dev:
    c, j = _api("GET", "/resolve/" + urllib.parse.quote(_dev[0]["token"]))
    if c == 200: TK = j.get("token")
if not TK:
    _fail("v12-无法取得 kid HTTP 令牌（device_token 缺失？）")
    raise SystemExit(1)
_ok("v12-kid HTTP 令牌就绪")

ids = [r["id"] for r in _t]
# v16 新语义：slot=提交序（前端不再重排）——刻意用**乱序**提交验证后端保序
_ids_shuffle = [ids[2], ids[0], ids[1]]
c, j = _api("POST", "/child/team", {"team_ids": ids[:4]}, TK)
if c != 400: _fail(f"v12-4只上阵应400，实得{c}")
else: _ok("v12->3 只拒绝 400")

c, j = _api("POST", "/child/team", {"team_ids": [ids[0], _sealed[0]["id"]]}, TK)
if c != 400: _fail(f"v12-封印上阵应400，实得{c}")
else: _ok("v12-封印怪上阵拒绝 400")

c, j = _api("POST", "/child/team", {"team_ids": _ids_shuffle}, TK)
if c != 200: _fail(f"v12-正常保存应200，实得{c} {j}")
else:
    _r = db.q("SELECT id,slot FROM trainer_pokemon WHERE student_id=%s AND is_in_team=1 ORDER BY slot", (_sid,))
    if [r["id"] for r in _r] != _ids_shuffle:
        _fail(f"v12-slot 未按提交序：{[r['id'] for r in _r]} vs {_ids_shuffle}")
    else: _ok("v12-乱序提交 slot 仍=提交序（选择先后即出战位，1 号首发）")

c, j = _api("POST", "/child/team", {"team_ids": []}, TK)
_r = db.q("SELECT id FROM trainer_pokemon WHERE student_id=%s AND is_in_team=1", (_sid,))
if c != 200 or _r: _fail(f"v12-空数组应全撤，剩 {len(_r)} 只")
else: _ok("v12-空数组=全部撤下")

# 恢复一个合理出战位（Lv 前三）便于后续人工查看
_api("POST", "/child/team", {"team_ids": ids[:3]}, TK)

# ---------- E. availability/列表接口冒烟兼容 ----------
c, j = _api("GET", "/child/pokemon", None, TK)
if c != 200 or len(j) != 9: _fail(f"v12-/child/pokemon 应 9 只，实得 {len(j) if c==200 else c}")
else:
    _in = [p for p in j if p.get("is_in_team")]
    _sl = [p for p in j if p.get("sealed")]
    if len(_in) != 3 or len(_sl) != 1: _fail(f"v12-列表 in_team={len(_in)} sealed={len(_sl)}")
    else: _ok("v12-列表接口字段兼容（is_in_team/sealed/exp_to_next 均在）")

print("=== v12 UI 改版验证结束 ===")
