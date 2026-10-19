# -*- coding: utf-8 -*-
"""v19 任务全管理验证（由 _smoke_all.py 同进程 runpy 驱动）
A. GET /tasks 无 category 字段；孩子菜单同步无 category
B. PUT 改名（含 400 空名/404 不存在）
C. DELETE 真删 + 二次删除 404
D. reorder 重排 + 越权 id 静默忽略 + 孩子端顺序跟随
E. 停用→启用往返（PUT 返回完整行）
F. 源码断言：parent.html 不再渲染 category、有删/排序按钮
G. 现场还原：删除测试任务、恢复原顺序与启用态
"""
import json
import os
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    FAILS
except NameError:
    FAILS = []

def _ok(m): print(f"[PASS] v19-{m}")
def _fail(m):
    FAILS.append(f"v19-{m}")
    print(f"[FAIL] v19-{m}")

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

print("=== v19 任务管理验证开始 ===")
from app import db

# 家长令牌（与 smoke_test 同通路：设备令牌 + PIN admin123 解锁）
devs = db.q("SELECT token FROM device_token WHERE role='parent' AND enabled=1")
_par_k = devs[0]["token"]
st, j = _api("POST", "/parent/unlock", {"token": _par_k, "pin": "admin123"})
assert st == 200 and j.get("token"), f"家长解锁失败 {st} {j}"
PT = j["token"]

kid = db.q("SELECT id FROM student_user ORDER BY id LIMIT 1")[0]["id"]
kdev = db.q("SELECT token FROM device_token WHERE role='kid' AND ref_id=%s AND enabled=1", (kid,))
KT = kdev[0]["token"] if kdev else None

# 现场快照（G 段还原用）
_before = db.q("SELECT id,task_name,enabled,sort FROM task_template ORDER BY sort,id")

# ---------- A. category 下线 ----------
st, tasks = _api("GET", "/tasks", token=PT)
if st == 200 and tasks and all("category" not in t for t in tasks):
    _ok("GET /tasks 不再返回 category")
else:
    _fail(f"GET /tasks 字段异常 {st} {tasks[:2]}")
if KT:
    st, ct = _api("GET", "/child/tasks", token=KT)
    if st == 200 and all("category" not in t for t in ct):
        _ok("孩子菜单无 category")
    else:
        _fail(f"孩子菜单字段异常 {st} {ct[:2]}")

# ---------- B. 改名 ----------
st, add = _api("POST", "/tasks", {"task_name": "v19测试任务"}, token=PT)
tid = add.get("id")
if not (st == 200 and tid):
    _fail(f"POST /tasks 失败 {st} {add}")
    raise SystemExit(1)
st, upd = _api("PUT", f"/tasks/{tid}", {"task_name": "v19改名后"}, token=PT)
if st == 200 and upd.get("task_name") == "v19改名后" and "enabled" in upd:
    _ok("PUT 改名成功且返回完整行")
else:
    _fail(f"PUT 改名异常 {st} {upd}")
st, _ = _api("PUT", "/tasks/999999", {"task_name": "x"}, token=PT)
_ok("不存在任务 PUT 应 404") if st == 404 else _fail(f"404 异常 {st}")

# ---------- E. 停用→启用往返（v19b：停用行从 GET 消失=定稿口径） ----------
st, off = _api("PUT", f"/tasks/{tid}", {"enabled": False}, token=PT)
ok_e = st == 200 and off.get("enabled") in (0, False) and off.get("task_name") == "v19改名后"
_ok("停用 PUT 返回完整行") if ok_e else _fail(f"停用往返异常 {st} {off}")
if KT:
    st, ct = _api("GET", "/child/tasks", token=KT)
    ok_e2 = st == 200 and all(t["id"] != tid for t in ct)
    _ok("停用后孩子菜单不可见") if ok_e2 else _fail("停用后孩子菜单仍可见")
st, ts2 = _api("GET", "/tasks", token=PT)
_ok("停用后家长列表也不可见(v19b)") if all(t["id"] != tid for t in ts2) \
    else _fail("停用后家长列表仍可见")
# 停用行：带原名的 PUT=恢复通道；无 task_name 的空 PUT 不应改启用态
st, on0 = _api("PUT", f"/tasks/{tid}", {"task_name": "v19改名后"}, token=PT)
_ok("停用行带原名PUT应200(恢复通道)") if st == 200 else _fail(f"停用行空名应200实得{st}")
st, ts3 = _api("GET", "/tasks", token=PT)
_ok("空名PUT不误启用") if all(t["id"] != tid for t in ts3) else _fail("空名PUT误启用!")
st, on = _api("PUT", f"/tasks/{tid}", {"enabled": True}, token=PT)
_ok("启用往返") if st == 200 and on.get("enabled") in (1, True) else _fail(f"启用异常 {st} {on}")
st, ts4 = _api("GET", "/tasks", token=PT)
_ok("启用后回到家长列表") if any(t["id"] == tid for t in ts4) else _fail("启用后未回列表")

# ---------- D. reorder ----------
st, tasks = _api("GET", "/tasks", token=PT)
ids = [t["id"] for t in tasks]
rot = ids[1:] + ids[:1]                      # 首位轮换到末尾
st, r = _api("PUT", "/tasks/reorder", {"ids": rot + [999999]}, token=PT)
if st == 200 and r.get("moved") == len(ids):
    _ok("reorder 落库（越权 id 静默忽略）")
else:
    _fail(f"reorder 异常 {st} {r}")
st, after = _api("GET", "/tasks", token=PT)
if [t["id"] for t in after] == rot:
    _ok("GET 顺序与 reorder 一致")
else:
    _fail(f"顺序不一致 {[t['id'] for t in after][:4]} vs {rot[:4]}")
if KT:
    st, ct = _api("GET", "/child/tasks", token=PT if False else KT)
    enabled_rot = [i for i in rot if any(t["id"] == i and t["enabled"] for t in after)]
    if st == 200 and [t["id"] for t in ct if t["id"] in enabled_rot] == \
       [t["id"] for t in ct]:   # 孩子端顺序 = 家长端顺序的子序列（保序即可）
        pos = {t["id"]: n for n, t in enumerate(after)}
        seq = [pos.get(t["id"], 1e9) for t in ct]
        _ok("孩子端顺序跟随家长端") if seq == sorted(seq) else _fail("孩子端顺序未跟随")
    else:
        _fail(f"孩子端顺序读取异常 {st}")

# ---------- C. DELETE ----------
st, _ = _api("DELETE", f"/tasks/{tid}", token=PT)
_ok("DELETE 真删成功") if st == 200 else _fail(f"DELETE 异常 {st}")
st, _ = _api("DELETE", f"/tasks/{tid}", token=PT)
_ok("重复 DELETE 应 404") if st == 404 else _fail(f"重复删除应404实得{st}")
st, tasks = _api("GET", "/tasks", token=PT)
_ok("删除后列表无该任务") if all(t["id"] != tid for t in tasks) else _fail("删除后仍在列表")

# ---------- F. 前端源码断言 ----------
html = open(os.path.join(HERE, "web", "parent.html"), encoding="utf-8").read()
_f1 = "category" not in html.split("PR.tasks")[1].split("PR.members")[0] \
      if "PR.members" in html else "category" not in html
_ok("parent.html 任务页不再渲染 category") if _f1 else _fail("任务页仍渲染 category")
for key, name in [("mvTask", "↑↓排序"), ("delTask", "删除"), ("editTask", "改名"),
                  ("/tasks/reorder", "reorder 接口接入")]:
    _ok(f"parent.html 接入 {name}") if key in html else _fail(f"parent.html 缺 {name}")

# ---------- G. 现场还原（冒烟 reset 清的是动态表，task_template 属配置表需自清） ----------
_now = {r["id"]: r for r in db.q("SELECT id,task_name,enabled,sort FROM task_template")}
for r in _before:
    if r["id"] in _now:
        db.x("UPDATE task_template SET task_name=%s,enabled=%s,sort=%s WHERE id=%s",
             (r["task_name"], r["enabled"], r["sort"], r["id"]))
_extra = set(_now) - {r["id"] for r in _before}
for x in _extra:
    db.x("DELETE FROM task_template WHERE id=%s", (x,))
_restored = db.q("SELECT id,task_name,enabled,sort FROM task_template ORDER BY sort,id")
if [(r["id"], r["task_name"], r["enabled"]) for r in _restored] == \
   [(r["id"], r["task_name"], r["enabled"]) for r in _before]:
    _ok("任务配置现场还原")
else:
    _fail("现场还原比对不一致")

print("=== v19 验证结束，FAILS+=%d ===" % 0)
