# -*- coding: utf-8 -*-
"""v21 周末任务验证（由 _smoke_all.py 同进程 runpy 驱动）
A. GET /tasks 返回 weekend_only 字段（默认 0）
B. PUT weekend_only=1 往返（置位/清零，PUT 返回完整行）
C. 孩子端过滤（mock 日期）：周一至周五隐身、周六周日现身
   —— mock 方式：直接调视图函数 child_tasks(tok=...) 并 monkeypatch dt.date，
      HTTP 通路留真实日期断言（今日实时口径）
D. 停用任务仍不出现（enabled 与 weekend_only 正交）
E. 源码断言：parent.html 有 toggleWeekend 按钮
F. 现场还原：删除测试任务
"""
import json
import os
import datetime as dt
import urllib.request
import urllib.error

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    FAILS
except NameError:
    FAILS = []

def _ok(m): print(f"[PASS] v21-{m}")
def _fail(m):
    FAILS.append(f"v21-{m}")
    print(f"[FAIL] v21-{m}")

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

print("=== v21 周末任务验证开始 ===")
from app import db

devs = db.q("SELECT token FROM device_token WHERE role='parent' AND enabled=1")
st, j = _api("POST", "/parent/unlock", {"token": devs[0]["token"], "pin": "admin123"})
assert st == 200 and j.get("token"), f"家长解锁失败 {st} {j}"
PT = j["token"]

kid = db.q("SELECT id FROM student_user ORDER BY id LIMIT 1")[0]["id"]
kdev = db.q("SELECT token FROM device_token WHERE role='kid' AND ref_id=%s AND enabled=1", (kid,))
KT = kdev[0]["token"] if kdev else None
assert KT, "无孩子令牌"

# 前置清扫：上次中断残留的测试任务（task_template 属配置表，冒烟 reset 不清它，
# 脏行会污染 smoke_test "任务应为8个" 计数断言——本测试 F 段虽有删除，中断时不保）
db.x("DELETE FROM task_template WHERE task_name='_v21周末测试'")

# ---------- A. 字段与默认值 ----------
st, _ = _api("POST", "/tasks", {"task_name": "_v21周末测试"}, token=PT)
assert st == 200, f"建任务失败 {st}"
tid = _["id"]
st, tasks = _api("GET", "/tasks", token=PT)
row = next((t for t in tasks if t["id"] == tid), None)
if row and row.get("weekend_only") == 0:
    _ok("GET /tasks 返回 weekend_only 且默认 0")
else:
    _fail(f"weekend_only 字段异常: {row}")

# ---------- B. 开关往返 ----------
st, r1 = _api("PUT", f"/tasks/{tid}", {"weekend_only": 1}, token=PT)
if st == 200 and r1.get("weekend_only") == 1:
    _ok("PUT weekend_only=1 置位并返回完整行")
else:
    _fail(f"置位失败 {st} {r1}")

# ---------- C. 孩子端过滤（mock 日期直调视图） ----------
import types as _types
from app.routers import account as acct

_real_dt = acct._dt
class _MockDateH:
    _fixed = None
    @staticmethod
    def today():
        return _MockDateH._fixed
_mock = _types.SimpleNamespace(date=_MockDateH)   # 视图按 _dt.date.today() 两级访问
try:
    acct._dt = _mock
    seen = {}
    for wd in range(7):   # 0=周一 .. 6=周日
        _MockDateH._fixed = dt.date(2026, 10, 26) + dt.timedelta(days=wd)  # 2026-10-26 是周一
        lst = acct.child_tasks(tok={"uid": kid})
        seen[wd] = any(t["id"] == tid for t in lst)
    if all(not seen[d] for d in range(5)):
        _ok("周一~周五：仅周末任务对孩子端隐身")
    else:
        _fail(f"工作日未隐身: {seen}")
    if all(seen[d] for d in (5, 6)):
        _ok("周六、周日：仅周末任务对孩子端现身")
    else:
        _fail(f"周末未现身: {seen}")
finally:
    acct._dt = _real_dt

# HTTP 真实通路：今日实时口径（无论周几，返回均不含/含该任务=与服务端日期一致）
st, kl = _api("GET", "/child/tasks", token=KT)
_in = any(t["id"] == tid for t in kl) if st == 200 else None
_exp = dt.date.today().weekday() >= 5
if st == 200 and _in == _exp:
    _ok(f"HTTP 孩子端今日(周{'一二三四五六日'[dt.date.today().weekday()]})口径一致")
else:
    _fail(f"HTTP 口径不一致 in={_in} exp={_exp} st={st}")

# ---------- D. enabled 与 weekend_only 正交 ----------
st, r2 = _api("PUT", f"/tasks/{tid}", {"enabled": False}, token=PT)
st2, kl2 = _api("GET", "/child/tasks", token=KT)
gone = st == 200 and st2 == 200 and not any(t["id"] == tid for t in kl2)
# 无论今晨 mock 如何，停用行必须从孩子端消失（周末亦然——enabled=0 优先级最高）
st3, pl3 = _api("GET", "/tasks", token=PT)
gone_p = not any(t["id"] == tid for t in pl3)
if gone and gone_p:
    _ok("停用后孩子端与家长端均消失（enabled 正交于 weekend_only）")
else:
    _fail(f"停用不生效 kid={gone} parent={gone_p}")
st, r3 = _api("PUT", f"/tasks/{tid}", {"task_name": "_v21周末测试", "enabled": True}, token=PT)
st4, kl4 = _api("GET", "/child/tasks", token=KT)
_back = st == 200 and (dt.date.today().weekday() >= 5) == any(t["id"] == tid for t in kl4)
if _back and r3.get("weekend_only") == 1:
    _ok("恢复启用后回到实时口径（weekend_only 保持 1）")
else:
    _fail(f"恢复异常 back={_back} row={r3}")

# ---------- E. 源码断言 ----------
html = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "parent.html"),
            encoding="utf-8").read()
if "toggleWeekend" in html and "weekend_only" in html:
    _ok("parent.html 接入 周末切换")
else:
    _fail("parent.html 缺少周末切换")

# ---------- F. 现场还原 ----------
st, _ = _api("DELETE", f"/tasks/{tid}", token=PT)
if st == 200:
    _ok("测试任务删除还原")
else:
    _fail(f"删除失败 {st}")

print(f"=== v21 验证结束，FAILS+={len(FAILS)} ===")
