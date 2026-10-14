# -*- coding: utf-8 -*-
"""打卡提交 / 家长审批（批准·扣减批准·驳回·补勾）/ 顺延发放 / 明细"""
import datetime as dt
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from .. import db, exp
from ..auth import parent_auth, kid_auth

router = APIRouter()

def _today():
    return dt.date.today()

def _d(v):
    """兼容 sqlite(TEXT)/MySQL(DATE) 两种返回的日期字段"""
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])

def _streak_days(student_id, upto_date, conn=None):
    """连续获批天数（含当日，从 upto_date 往前数；status in (2,3) 计活跃）"""
    cnt, d = 0, upto_date
    while True:
        r = db.q("SELECT status FROM checkin_record WHERE student_id=%s AND task_date=%s "
                 "AND status IN (2,3)", (student_id, d))
        if not r:
            break
        cnt += 1
        d -= dt.timedelta(days=1)
    return cnt

@router.post("/child/checkin")
def submit(body: dict, tok=Depends(kid_auth)):
    sid, today = tok["uid"], _today()
    items = body.get("items", [])          # [{id,name}]
    if not items:
        raise HTTPException(400, "至少勾选一项")
    if db.q("SELECT id,status FROM checkin_record WHERE student_id=%s AND task_date=%s", (sid, today)):
        raise HTTPException(400, "今天已经提交过啦")
    now = dt.datetime.now()
    quick = exp.is_quick(now)
    db.x("INSERT INTO checkin_record(student_id,task_date,item_json,quick_win) VALUES(%s,%s,%s,%s)",
         (sid, today, json.dumps(items, ensure_ascii=False), 1 if quick else 0))
    return {"ok": True, "quick_win": quick}

@router.delete("/child/checkin")
def withdraw(tok=Depends(kid_auth)):
    sid, today = tok["uid"], _today()
    r = db.q("SELECT status FROM checkin_record WHERE student_id=%s AND task_date=%s", (sid, today))
    if not r or r[0]["status"] != 1:
        raise HTTPException(400, "无法撤回（未提交或已审核）")
    db.x("DELETE FROM checkin_record WHERE student_id=%s AND task_date=%s AND status=1", (sid, today))
    return {"ok": True}

@router.get("/child/today")
def child_today(tok=Depends(kid_auth)):
    sid, today = tok["uid"], _today()
    rec = db.q("SELECT * FROM checkin_record WHERE student_id=%s AND task_date=%s", (sid, today))
    carry = db.q("SELECT carry_pending FROM student_carry WHERE student_id=%s", (sid,))
    streak = _streak_days(sid, today - dt.timedelta(days=1))
    hh, mm = map(int, db.cfg("fast_deadline", "21:30").split(":"))
    # 封印进度：gift 侧含今日口径，但今日记录尚未审批时不计今天（与家长审批节奏一致）
    from .. import gift as giftmod
    seal = giftmod.sealed_status(sid)
    today_approved = bool(rec and rec[0]["status"] in (2, 3))
    if not today_approved:
        seal["streak"] = max(0, seal["streak"] - 1)
    if rec:  # 与 parent 侧同口径：把 item_json 解析成 items，前端待审批卡片直接渲染
        try:
            rec[0]["items"] = json.loads(rec[0].get("item_json") or "[]")
        except (ValueError, TypeError):
            rec[0]["items"] = []
    return {"record": rec[0] if rec else None, "streak": streak,
            "carry_pending": carry[0]["carry_pending"] if carry else 0,
            "quick_open": exp.is_quick(dt.datetime.now()),
            "study_day": exp.is_study_day(dt.datetime.now()),
            "fast_deadline": db.cfg("fast_deadline"), "daily_base": db.cfg("daily_base_exp", "230", int),
            "sealed": seal["sealed"], "seal_progress": min(seal["streak"], seal["need"]),
            "seal_need": seal["need"]}

@router.get("/parent/pending")
def pending(tok=Depends(parent_auth)):
    stus = [s["id"] for s in db.q("SELECT id FROM student_user WHERE parent_id=%s", (tok["uid"],))]
    if not stus:
        return []
    ph = ",".join(["%s"] * len(stus))
    rows = db.q(f"SELECT c.*, s.student_name FROM checkin_record c "
                f"JOIN student_user s ON s.id=c.student_id "
                f"WHERE c.student_id IN ({ph}) AND c.status=1 ORDER BY c.submit_time", stus)
    for r in rows:
        r["items"] = json.loads(r["item_json"])
    return rows

@router.get("/parent/history")
def history(limit: int = 30, tok=Depends(parent_auth)):
    stus = [s["id"] for s in db.q("SELECT id FROM student_user WHERE parent_id=%s", (tok["uid"],))]
    if not stus:
        return []
    ph = ",".join(["%s"] * len(stus))
    rows = db.q(f"SELECT c.*, s.student_name FROM checkin_record c "
                f"JOIN student_user s ON s.id=c.student_id "
                f"WHERE c.student_id IN ({ph}) ORDER BY c.task_date DESC LIMIT %s", stus + [limit])
    for r in rows:
        r["items"] = json.loads(r["item_json"])
        if r["adjusted_json"]:
            r["adjusted"] = json.loads(r["adjusted_json"])
    return rows

def _settle(sid: int, rec: dict, penalty: int, adjusted: list | None, penalty_reason: str | None = None):
    """批准/扣减批准共用：算经验→发经验→记顺延→更新记录"""
    base = db.cfg("daily_base_exp", "230", int)
    streak_days = db.cfg("streak_bonus_days", "7", int)
    prev = _streak_days(sid, _d(rec["task_date"]) - dt.timedelta(days=1))
    streak7 = prev + 1 >= streak_days
    parts = exp.calc(base, bool(rec["quick_win"]), streak7)
    pre_cap = max(0, parts["pre_cap"] - penalty)
    carry_row = db.q("SELECT carry_pending FROM student_carry WHERE student_id=%s", (sid,))
    carry_in = carry_row[0]["carry_pending"] if carry_row else 0
    grant_today, carry_to = exp.cap_split(pre_cap, carry_in)
    carry_pending_after = carry_in - min(carry_in, grant_today) + carry_to
    # 前日顺延部分优先计入今日
    used_carry_in = min(carry_in, grant_today)
    fresh = grant_today - used_carry_in
    evolved = []                                  # 本次打卡引发的进化（供前端弹惊喜）
    if fresh > 0:
        res = exp.apply_exp(sid, fresh, "checkin", rec["id"])
        for d in res.get("details", []):
            for nm in (d.get("evolved_to") or []):
                evolved.append(nm)
    db.x("UPDATE student_carry SET carry_pending=%s WHERE student_id=%s", (carry_pending_after, sid))
    db.x("UPDATE checkin_record SET status=%s, approve_time=NOW(), base_exp=%s, quick_exp=%s, "
         "streak_bonus=%s, penalty=%s, penalty_reason=%s, carry_from=%s, carry_to=%s, exp_final=%s, "
         "adjusted_json=%s, evolved_json=%s WHERE id=%s",
         (2 if penalty == 0 else 3, parts["base"], parts["quick"], parts["streak_bonus"],
          penalty, penalty_reason, used_carry_in, carry_to, grant_today,
          json.dumps(adjusted, ensure_ascii=False) if adjusted else None,
          json.dumps(evolved, ensure_ascii=False) if evolved else None, rec["id"]))
    # 封印宝可梦激活：记录已置获批态 → 含归属日连击 ≥ seal_streak_days(7) 即解锁
    from .. import gift as giftmod
    activated = giftmod.activate_sealed(sid, upto_date=_d(rec["task_date"]))
    return {"exp_final": grant_today, "carry_to": carry_to, "parts": parts,
            "penalty": penalty, "evolved": evolved, "activated": activated}

@router.post("/parent/approve")
def approve(body: dict, tok=Depends(parent_auth)):
    rid = body["checkin_id"]
    penalty = int(body.get("penalty", 0))
    adjusted = body.get("adjusted")        # 家长补勾后的完整清单
    rows = db.q("SELECT c.*, s.id AS sid FROM checkin_record c "
                "JOIN student_user s ON s.id=c.student_id AND s.parent_id=%s WHERE c.id=%s",
                (tok["uid"], rid))
    if not rows:
        raise HTTPException(404, "记录不存在")
    rec = rows[0]
    if rec["status"] != 1:
        raise HTTPException(400, "该打卡已处理")
    if penalty:
        allowed = {int(v) for v in db.cfg("penalty_options", "10,20").split(",")}
        if penalty not in allowed:
            raise HTTPException(400, f"扣减档位只能是 {allowed}")
    return _settle(rec["sid"], rec, penalty, adjusted, body.get("penalty_reason"))

@router.post("/parent/reject")
def reject(body: dict, tok=Depends(parent_auth)):
    rid, reason = body["checkin_id"], body.get("reason", "")
    rows = db.q("SELECT c.*, s.id AS sid FROM checkin_record c "
                "JOIN student_user s ON s.id=c.student_id AND s.parent_id=%s WHERE c.id=%s",
                (tok["uid"], rid))
    if not rows:
        raise HTTPException(404, "记录不存在")
    rec = rows[0]
    if rec["status"] not in (2, 3):
        # 待审直接驳回：不扣（本来就没发）
        db.x("UPDATE checkin_record SET status=4, approve_time=NOW(), reject_reason=%s WHERE id=%s",
             (reason, rid))
    else:
        # 已发经验 → 反向扣回并清顺延标记
        exp.apply_exp(rec["sid"], -rec["exp_final"], "reject", rid)
        db.x("UPDATE checkin_record SET status=4, reject_reason=%s, exp_final=0 WHERE id=%s", (reason, rid))
    return {"ok": True}

@router.post("/parent/dispense-carry")
def dispense_carry(student_id: int, tok=Depends(parent_auth)):
    """发放顺延经验（每日首次打开应用时由前端调用，或家长手动）"""
    db.q("SELECT 1")  # 校验连接
    stu = db.q("SELECT s.id FROM student_user s WHERE s.id=%s AND s.parent_id=%s",
               (student_id, tok["uid"]))
    if not stu:
        raise HTTPException(404, "孩子不存在")
    row = db.q("SELECT carry_pending FROM student_carry WHERE student_id=%s", (student_id,))
    amt = row[0]["carry_pending"] if row else 0
    if amt <= 0:
        return {"dispensed": 0}
    db.x("UPDATE student_carry SET carry_pending=0 WHERE student_id=%s", (student_id,))
    exp.apply_exp(student_id, amt, "carry", 0)
    return {"dispensed": amt}
