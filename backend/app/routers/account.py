# -*- coding: utf-8 -*-
"""登录注册 / 设备令牌 / 任务菜单 / 配置"""
import datetime as dt
import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from .. import db
from ..auth import parent_auth, kid_auth, hash_pw, verify_pw, make_token

router = APIRouter()

class ParentLogin(BaseModel):
    phone: str
    password: str

class StudentLogin(BaseModel):
    student_id: int
    pin: str

class TaskIn(BaseModel):
    task_name: str
    icon: str = "book"
    category: str = "study"

class CfgIn(BaseModel):
    key: str
    value: str

@router.post("/parent/login")
def parent_login(body: ParentLogin):
    rows = db.q("SELECT * FROM parent_user WHERE phone=%s", (body.phone,))
    if not rows or not verify_pw(body.password, rows[0]["password"]):
        raise HTTPException(400, "手机号或密码错误")
    stu = db.q("SELECT id,student_name,pin FROM student_user WHERE parent_id=%s", (rows[0]["id"],))
    return {"token": make_token("parent", rows[0]["id"]),
            "students": [{"id": s["id"], "name": s["student_name"], "has_pin": bool(s["pin"])} for s in stu]}

@router.post("/student/login")
def student_login(body: StudentLogin):
    rows = db.q("SELECT * FROM student_user WHERE id=%s", (body.student_id,))
    if not rows:
        raise HTTPException(404, "孩子账号不存在")
    if not verify_pw(body.pin, rows[0]["pin"] or ""):
        raise HTTPException(400, "密码错误")
    return {"token": make_token("student", rows[0]["id"], rows[0]["parent_id"]),
            "name": rows[0]["student_name"]}

@router.post("/parent/change-pin")
def change_pin(body: dict, tok=Depends(parent_auth)):
    db.x("UPDATE student_user SET pin=%s WHERE id=%s AND parent_id=%s",
         (hash_pw(str(body["pin"])), body["student_id"], tok["uid"]))
    return {"ok": True}

# ---------- 设备令牌（孩子平板免登录 / 家长专用链接+PIN） ----------

@router.get("/resolve/{token}")
def resolve_token(token: str):
    """前端冷启动：凭 ?k= 令牌判断身份。kid 直接发 JWT 免登录；parent 只回 hint 待输 PIN"""
    rows = db.q("SELECT role, ref_id FROM device_token WHERE token=%s AND enabled=1", (token,))
    if not rows:
        raise HTTPException(404, "链接无效或已被家长吊销")
    r = rows[0]
    if r["role"] == "kid":
        stu = db.q("SELECT id,student_name,parent_id FROM student_user WHERE id=%s", (r["ref_id"],))
        if not stu:
            raise HTTPException(404, "孩子账号不存在")
        return {"role": "kid", "name": stu[0]["student_name"],
                "token": make_token("student", stu[0]["id"], stu[0]["parent_id"])}
    par = db.q("SELECT id,phone FROM parent_user WHERE id=%s", (r["ref_id"],))
    if not par:
        raise HTTPException(404, "家长账号不存在")
    return {"role": "parent", "hint": par[0]["phone"][-4:]}

@router.post("/parent/unlock")
def parent_unlock(body: dict):
    """家长链接解锁：专用令牌 + 数字PIN（bcrypt 与登录密码同字段）→ 发 JWT"""
    token, pin = str(body.get("token", "")), str(body.get("pin", ""))
    rows = db.q("SELECT ref_id FROM device_token WHERE token=%s AND role='parent' AND enabled=1", (token,))
    if not rows:
        raise HTTPException(404, "链接无效或已被吊销")
    par = db.q("SELECT * FROM parent_user WHERE id=%s", (rows[0]["ref_id"],))
    if not par or not verify_pw(pin, par[0]["password"]):
        raise HTTPException(400, "家长密码错误")
    stu = db.q("SELECT id,student_name FROM student_user WHERE parent_id=%s", (par[0]["id"],))
    return {"token": make_token("parent", par[0]["id"]),
            "students": [{"id": s["id"], "name": s["student_name"]} for s in stu]}

@router.get("/parent/devices")
def list_devices(tok=Depends(parent_auth)):
    return db.q("SELECT token,role,ref_id,label,enabled,create_time FROM device_token "
                "WHERE (role='parent' AND ref_id=%s) OR role='kid' ORDER BY role, create_time",
                (tok["uid"],))

@router.post("/parent/device/issue")
def issue_device(body: dict, tok=Depends(parent_auth)):
    """签发设备令牌：role=kid 需 student_id；role=parent 用当前家长。返回完整链接"""
    role, label = body.get("role", "kid"), body.get("label", "")
    if role == "kid":
        sid = int(body["student_id"])
        own = db.q("SELECT id FROM student_user WHERE id=%s AND parent_id=%s", (sid, tok["uid"]))
        if not own:
            raise HTTPException(404, "孩子不存在")
        ref = sid
    else:
        role, ref = "parent", tok["uid"]
    tk = ("kid_" if role == "kid" else "par_") + secrets.token_urlsafe(18)
    db.x("INSERT INTO device_token(token,role,ref_id,label) VALUES(%s,%s,%s,%s)", (tk, role, ref, label))
    return {"token": tk, "url": "/?k=" + tk if role == "kid" else "/parent/?k=" + tk}

@router.put("/parent/device/{token}")
def toggle_device(token: str, body: dict, tok=Depends(parent_auth)):
    """吊销/恢复设备令牌（吊销后对应设备立即失效）；带 label 时同时改名"""
    rows = db.q("SELECT role,ref_id FROM device_token WHERE token=%s", (token,))
    if not rows:
        raise HTTPException(404, "令牌不存在")
    if rows[0]["role"] == "parent" and rows[0]["ref_id"] != tok["uid"]:
        raise HTTPException(403, "只能管理自己的设备")
    if body.get("label") is not None:
        label = str(body["label"]).strip()[:20]
        if not label:
            raise HTTPException(400, "名称不能为空")
        db.x("UPDATE device_token SET label=%s WHERE token=%s", (label, token))
    if "enabled" in body:
        db.x("UPDATE device_token SET enabled=%s WHERE token=%s",
             (1 if body.get("enabled") else 0, token))
    return {"ok": True}

@router.delete("/parent/device/{token}")
def delete_device(token: str, tok=Depends(parent_auth)):
    """永久删除签发链接（与吊销不同：列表不再显示）"""
    rows = db.q("SELECT role,ref_id FROM device_token WHERE token=%s", (token,))
    if not rows:
        raise HTTPException(404, "令牌不存在")
    if rows[0]["role"] == "parent" and rows[0]["ref_id"] != tok["uid"]:
        raise HTTPException(403, "只能管理自己的设备")
    db.x("DELETE FROM device_token WHERE token=%s", (token,))
    return {"ok": True}

@router.get("/tasks")
def list_tasks(tok=Depends(parent_auth)):
    # v19：category 不再返回（纯展示字段无业务用途；表列保留避免迁移）
    # v19b 家长定稿：停用任务不展示（停用=不占用列表；恢复走 PUT enabled=true）
    return db.q("SELECT id,task_name,icon,enabled,sort FROM task_template "
                "WHERE parent_id=%s AND enabled=1 ORDER BY sort,id", (tok["uid"],))

@router.get("/child/tasks")
def child_tasks(tok=Depends(kid_auth)):
    stu = db.q("SELECT parent_id FROM student_user WHERE id=%s", (tok["uid"],))[0]
    return db.q("SELECT id,task_name,icon FROM task_template "
                "WHERE parent_id=%s AND enabled=1 ORDER BY sort,id", (stu["parent_id"],))

@router.post("/tasks")
def add_task(body: TaskIn, tok=Depends(parent_auth)):
    cur = db.q("SELECT COALESCE(MAX(sort)+1,0) m FROM task_template WHERE parent_id=%s", (tok["uid"],))
    rid = db.x("INSERT INTO task_template(parent_id,task_name,icon,category,sort) VALUES(%s,%s,%s,%s,%s)",
               (tok["uid"], body.task_name, body.icon, body.category, cur[0]["m"]), ret_id=True)
    return {"id": rid}

@router.put("/tasks/reorder")
def reorder_tasks(body: dict, tok=Depends(parent_auth)):
    """v19 任务排序：ids=家长页当前顺序全量 id 列表，按序重排 sort=0,1,2...
    仅接受属于本家长的 id，多余/不存在的静默忽略。"""
    ids = [int(i) for i in body.get("ids", [])]
    owned = {r["id"] for r in db.q("SELECT id FROM task_template WHERE parent_id=%s", (tok["uid"],))}
    s = 0
    for tid in ids:
        if tid in owned:
            db.x("UPDATE task_template SET sort=%s WHERE id=%s AND parent_id=%s", (s, tid, tok["uid"]))
            s += 1
    return {"ok": True, "moved": s}

@router.put("/tasks/{tid}")
def update_task(tid: int, body: dict, tok=Depends(parent_auth)):
    """v19：可改 task_name / enabled（原仅 enabled）；返回更新后的完整行。"""
    rows = db.q("SELECT id,task_name,icon,enabled,sort FROM task_template "
                "WHERE id=%s AND parent_id=%s", (tid, tok["uid"]))
    if not rows:
        raise HTTPException(404, "没有这个任务")
    if "task_name" in body:
        name = str(body["task_name"]).strip()
        if not name:
            if len(rows) and not rows[0]["enabled"]:
                # v19b UI：任务留空=停用（停用的行不出现在列表，✏️恢复需带原提交名）
                db.x("UPDATE task_template SET task_name=%s WHERE id=%s", (name, tid))
            else:
                raise HTTPException(400, "任务名称不能为空且不超过50字")
        elif len(name) > 50:
            raise HTTPException(400, "任务名称不能为空且不超过50字")
        else:
            db.x("UPDATE task_template SET task_name=%s WHERE id=%s", (name, tid))
    if "enabled" in body:
        db.x("UPDATE task_template SET enabled=%s WHERE id=%s",
             (1 if body["enabled"] else 0, tid))
    return db.q("SELECT id,task_name,icon,enabled,sort FROM task_template WHERE id=%s", (tid,))[0]

@router.delete("/tasks/{tid}")
def delete_task(tid: int, tok=Depends(parent_auth)):
    """v19 真删（UI 二次确认）。历史打卡 item_json 为任务名快照，删任务不影响历史记录。"""
    n = db.x("DELETE FROM task_template WHERE id=%s AND parent_id=%s", (tid, tok["uid"]))
    if not n:
        raise HTTPException(404, "没有这个任务")
    return {"ok": True}

EDITABLE = {"daily_base_exp", "daily_cap", "fast_deadline", "fast_multiplier",
            "streak_bonus_days", "streak_bonus_exp", "penalty_options",
            "exp_split_mode", "study_weekdays", "battle_weekday_open",
            "daily_catch_limit", "new_pokemon_weight_mult"}

@router.get("/config")
def get_config(tok=Depends(parent_auth)):
    return {r["cfg_key"]: r["cfg_value"] for r in
            db.q("SELECT cfg_key,cfg_value FROM sys_config WHERE cfg_key IN (%s)" %
                 ",".join(["%s"] * len(EDITABLE)), tuple(EDITABLE))}

@router.put("/config")
def put_config(body: CfgIn, tok=Depends(parent_auth)):
    if body.key not in EDITABLE:
        raise HTTPException(400, "该配置项不允许修改")
    db.set_cfg(body.key, body.value)
    return {"ok": True}

# ---------- 成员管理（家长页「成员」标签） ----------

@router.get("/parent/members")
def members(tok=Depends(parent_auth)):
    par = db.q("SELECT id,phone FROM parent_user WHERE id=%s", (tok["uid"],))[0]
    kids = db.q("SELECT s.id, s.student_name, "
                "(SELECT COUNT(*) FROM trainer_pokemon t WHERE t.student_id=s.id) mon_count, "
                "(SELECT COALESCE(SUM(1),0) FROM checkin_record c WHERE c.student_id=s.id AND c.status IN (2,3)) approved_days "
                "FROM student_user s WHERE s.parent_id=%s", (tok["uid"],))
    for k in kids:
        k["kid_token"] = None
        rows = db.q("SELECT token FROM device_token WHERE role='kid' AND ref_id=%s AND enabled=1", (k["id"],))
        if rows:
            k["kid_token"] = rows[0]["token"]
    return {"parent": par, "kids": kids}

@router.put("/parent/child/{sid}")
def update_child(sid: int, body: dict, tok=Depends(parent_auth)):
    own = db.q("SELECT id FROM student_user WHERE id=%s AND parent_id=%s", (sid, tok["uid"]))
    if not own:
        raise HTTPException(404, "孩子不存在")
    if body.get("name") is not None:
        name = str(body["name"]).strip()[:12]
        if not name:
            raise HTTPException(400, "昵称不能为空")
        db.x("UPDATE student_user SET student_name=%s WHERE id=%s", (name, sid))
    if body.get("pin") is not None:
        pin = str(body["pin"]).strip()
        if not (4 <= len(pin) <= 8 and pin.isdigit()):
            raise HTTPException(400, "PIN 需为 4-8 位数字")
        db.x("UPDATE student_user SET pin=%s WHERE id=%s", (hash_pw(pin), sid))
    return {"ok": True}

@router.post("/parent/child/{sid}/regen-token")
def regen_kid_token(sid: int, tok=Depends(parent_auth)):
    """吊销旧孩子链接并签发新链接（平板丢失时用）"""
    own = db.q("SELECT id FROM student_user WHERE id=%s AND parent_id=%s", (sid, tok["uid"]))
    if not own:
        raise HTTPException(404, "孩子不存在")
    db.x("UPDATE device_token SET enabled=0 WHERE role='kid' AND ref_id=%s", (sid,))
    tk = "kid_" + secrets.token_urlsafe(18)
    db.x("INSERT INTO device_token(token,role,ref_id,label) VALUES(%s,'kid',%s,'平板')", (tk, sid))
    return {"token": tk, "url": "/?k=" + tk}

@router.put("/parent/self")
def update_parent(body: dict, tok=Depends(parent_auth)):
    if body.get("password"):
        if not body.get("old_password") or not db.q(
                "SELECT id FROM parent_user WHERE id=%s AND password=%s",
                (tok["uid"], hash_pw(body["old_password"]))):
            raise HTTPException(400, "原密码错误")
        if len(str(body["password"])) < 6:
            raise HTTPException(400, "新密码至少 6 位")
        db.x("UPDATE parent_user SET password=%s WHERE id=%s", (hash_pw(body["password"]), tok["uid"]))
    return {"ok": True}
