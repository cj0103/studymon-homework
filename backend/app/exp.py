# -*- coding: utf-8 -*-
"""经验结算引擎（规则v2，方案已冻结）：
- 每日定额 daily_base_exp(230)，与勾选数量无关
- 快手：学习日(周一~五) 21:30 前提交且获批 ×1.2（向下取整）
- 连击：连续获批第 streak_days(7) 天额外 +50
- 每日上限 daily_cap(320)：超出部分顺延次日（提交日=归属日，顺延在"次日"发放）
- 扣减批准 -10/-20；驳回 = 当天全扣（已发则经验流水反向扣回）
- 发放对象 = 出战队伍（even平分 / lead主力60%后备各20%），经验只来自打卡
"""
import datetime as dt
import math
from . import db

def calc(base: int, quick: bool, streak7: bool) -> dict:
    """纯函数：算出各分项与实发/顺延（cap 前）"""
    # 快手加成：用 十分比 避免二进制浮点误差（1.2 → int(230*12/10)=int(276)=276，而非 int(230*0.2)=45）
    fm = db.cfg("fast_multiplier", "1.2", float)
    permille = int(round(fm * 1000))                      # 1200
    qexp = base * (permille - 1000) // 1000 if quick else 0
    sb = db.cfg("streak_bonus_exp", "50", int) if streak7 else 0
    total = base + qexp + sb
    return {"base": base, "quick": qexp, "streak_bonus": sb, "pre_cap": total}

def apply_exp(student_id: int, amount: int, reason: str, ref_id: int = 0):
    """把 amount 经验按队伍模式发放；amount<0 时从队伍按同比例扣回。返回明细。"""
    mode = db.q("SELECT exp_mode FROM student_user WHERE id=%s", (student_id,))[0]["exp_mode"] \
           or db.cfg("exp_split_mode", "even")
    team = db.q("SELECT id, level, total_exp FROM trainer_pokemon "
                "WHERE student_id=%s AND is_in_team=1 ORDER BY slot, id", (student_id,))
    if not team:
        return {"granted": 0, "details": [], "msg": "无出战宝可梦，经验暂存队首获得后补发"}
    n = len(team)
    if mode == "lead" and n > 1:
        shares = [0.6] + [0.4 / (n - 1)] * (n - 1)
    else:
        shares = [1.0 / n] * n
    details = []
    granted = 0
    for tp, sh in zip(team, shares):
        delta = int(amount * sh)
        if delta == 0 and amount != 0:
            delta = 1 if amount > 0 else -1
        row = db.q("SELECT tp.id, tp.total_exp, tp.level, pb.exp_group "
                   "FROM trainer_pokemon tp JOIN pokemon_base pb ON pb.pokedex_no=tp.pokedex_no "
                   "WHERE tp.id=%s", (tp["id"],))[0]
        new_exp = max(0, row["total_exp"] + delta)
        new_lv = level_for(row["exp_group"], new_exp)
        db.x("UPDATE trainer_pokemon SET total_exp=%s, level=%s WHERE id=%s",
             (new_exp, new_lv, tp["id"]))
        if new_lv > row["level"]:            # 升级→到级新招自动进入"已学袋"（不遗忘，孩子自选上场）
            from . import skills
            cur = db.q("SELECT pokedex_no, learned_skill_json, known_skill_json FROM trainer_pokemon WHERE id=%s", (tp["id"],))[0]
            skills.ensure_known(tp["id"], cur["pokedex_no"], new_lv, cur["known_skill_json"], cur["learned_skill_json"])
        evolved = []
        if new_lv >= row["level"]:           # 升级或持平都可能触发进化（首次发卡等）
            from . import evolve
            evolved = evolve.maybe_evolve(tp["id"])
        db.x("INSERT INTO exp_log(student_id,trainer_pokemon_id,exp_delta,reason,ref_id) "
             "VALUES(%s,%s,%s,%s,%s)", (student_id, tp["id"], delta, reason, ref_id))
        details.append({"trainer_pokemon_id": tp["id"], "delta": delta,
                        "level": new_lv, "level_up": new_lv > row["level"],
                        "evolved_to": evolved})
        granted += delta
    return {"granted": granted, "details": details}

def level_for(exp_group: str, total_exp: int) -> int:
    """Lv 上限 50；按经验组查总经验表"""
    col = {"fast": "exp_fast", "medium": "exp_medium", "slow": "exp_slow"}[exp_group]
    rows = db.q(f"SELECT level FROM level_exp_table WHERE {col}<=%s ORDER BY level DESC LIMIT 1",
                (total_exp,))
    return rows[0]["level"] if rows else 1

def cap_split(pre_cap: int, carry_in: int) -> tuple[int, int]:
    """按每日上限拆分：本日可发 = min(上限-前日顺延, 本日额+顺延)；返回(本日实发, 顺延至次日)"""
    cap = db.cfg("daily_cap", "320", int)
    avail_today = max(0, cap - carry_in)
    grant = min(pre_cap, avail_today)
    carry_to = pre_cap - grant
    return grant, carry_to

def is_study_day(t: dt.datetime) -> bool:
    """今天是否学习日（快手奖励仅学习日开放）"""
    study = {int(x) for x in db.cfg("study_weekdays", "0,1,2,3,4").split(",")}
    return t.weekday() in study

def is_quick(submit_time: dt.datetime) -> bool:
    if not is_study_day(submit_time):
        return False
    hh, mm = map(int, db.cfg("fast_deadline", "21:30").split(":"))
    return submit_time.time() <= dt.time(hh, mm)
