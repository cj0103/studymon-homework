# -*- coding: utf-8 -*-
"""经验结算引擎（规则v2，方案已冻结）：
- 每日定额 daily_base_exp(230)，与勾选数量无关
- 快手：学习日(周一~五) 21:30 前提交且获批 ×1.2（向下取整）
- 连击：连续获批第 streak_days(7) 天额外 +50
- 每日上限 daily_cap(320)：超出部分顺延次日（提交日=归属日，顺延在"次日"发放）
- 扣减批准 -10/-20；驳回 = 当天全扣（已发则经验流水反向扣回）
- 发放对象 = 出战队伍（even平分 / lead主力60%后备各20%），经验只来自打卡
- v22 追赶加成：先分后乘——份额 = 日发÷(按模式折算的只数)，再乘该只的追赶倍率 n。
  n = min(catchup_max_mult, catchup_base ^ 差距)（差距=基准级−自身等级）；
  基准级 = 下一未打道馆 recommend_level（集齐 8 枚后=最后馆 46）；到级 n=1 自动取消。
  重复捕捉经验包/入袋回填/赠礼走 exp_floor 直改，不经过 apply_exp，天然不吃 n。
"""
import datetime as dt
import math
from . import db

CATCHUP_DEFAULTS = {"catchup_base": "1.30",      # 指数底数：每差1级经验×1.30
                    "catchup_max_mult": "8",     # 倍率封顶
                    "catchup_dead": "0"}         # 死区：1=差距≤dead级不吃加成（默认关）

def exp_permille(gap: int) -> int:
    """v22 追赶倍率 n(gap)，返回千分比整数（1000=无加成），配置版。"""
    return exp_permille_p(gap, db.cfg("catchup_base", CATCHUP_DEFAULTS["catchup_base"], float),
                          db.cfg("catchup_max_mult", CATCHUP_DEFAULTS["catchup_max_mult"], float),
                          db.cfg("catchup_dead", CATCHUP_DEFAULTS["catchup_dead"], int))

def exp_permille_p(gap: int, base, cap, dead: int = 0) -> int:
    """纯计算版（参数显式传入，不落配置，供测试与复用）。
    口径：n = min(封顶, 底数^差距)，差距≤0（已到/超过基准）恒 1000；
    底数≤1 整体关闭（恒1000，家长可当总开关）；千分比逐步整除，无浮点误差。"""
    if gap <= 0:
        return 1000
    if dead and gap <= dead:
        return 1000
    bp = int(round(float(base) * 1000))
    if bp <= 1000:
        return 1000
    cp = int(round(float(cap) * 1000))
    pm = 1000
    for _ in range(int(gap)):                     # 逐级连乘千分比，差距≤50 开销可忽略
        pm = pm * bp // 1000
        if pm >= cp:
            return cp
    return max(1000, min(cp, pm))

def base_level(student_id: int) -> int:
    """追赶基准级：下一未打道馆的 recommend_level；集齐 8 枚后=第8馆(46)。
    无徽章记录等异常兜底 16（第1馆）。"""
    rows = db.q("SELECT badge_json FROM student_user WHERE id=%s", (student_id,))
    import json as _json
    badges = set()
    if rows:
        try:
            badges = set(_json.loads(rows[0]["badge_json"] or "[]"))
        except (ValueError, TypeError):
            badges = set()
    gyms = db.q("SELECT badge_name, recommend_level FROM gym_base ORDER BY sort")
    for g in gyms:
        if g["badge_name"] not in badges:
            return int(g["recommend_level"])
    return int(gyms[-1]["recommend_level"]) if gyms else 16

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
    """把 amount 经验按队伍模式发放；v22 先分后乘：份额×该只追赶倍率 n。
    amount<0（驳回扣回）优先按 exp_log 逐只回收本次发放实发值（ref_id 定位），
    找不到流水再按等比回收，兜底按当前 n 重算后取负——保证扣回不超发不少扣。
    返回明细。"""
    mode = db.q("SELECT exp_mode FROM student_user WHERE id=%s", (student_id,))[0]["exp_mode"] \
           or db.cfg("exp_split_mode", "even")
    team = db.q("SELECT tp.id, tp.level, tp.total_exp, pb.exp_group "
                "FROM trainer_pokemon tp JOIN pokemon_base pb ON pb.pokedex_no=tp.pokedex_no "
                "WHERE tp.student_id=%s AND tp.is_in_team=1 ORDER BY tp.slot, tp.id", (student_id,))
    if not team:
        return {"granted": 0, "details": [], "msg": "无出战宝可梦，经验暂存队首获得后补发"}
    n = len(team)
    if mode == "lead" and n > 1:
        shares = [0.6] + [0.4 / (n - 1)] * (n - 1)
    else:
        shares = [1.0 / n] * n

    # ---------- 正向量：逐只 = int(份额 × n(差距)) ----------
    target = base_level(student_id)
    deltas = {}
    if amount > 0:
        for tp, sh in zip(team, shares):
            base_delta = max(1, int(amount * sh))
            pm = exp_permille(max(0, target - tp["level"]))
            deltas[tp["id"]] = max(1, base_delta * pm // 1000)
    else:
        # ---------- 扣减量：两层口径 ----------
        # ① 优先读"原始发放"流水（checkin/carry）逐只回收实发值——
        #    不能用任意 reason 的流水：等比回收自身也带 ref_id，重复驳回会误读上一笔回收
        paid = {}
        if ref_id:
            for r in db.q("SELECT trainer_pokemon_id, SUM(exp_delta) s FROM exp_log "
                          "WHERE student_id=%s AND ref_id=%s AND reason IN ('checkin','carry') "
                          "GROUP BY trainer_pokemon_id", (student_id, ref_id)):
                if r["s"] and r["trainer_pokemon_id"]:
                    paid[r["trainer_pokemon_id"]] = int(r["s"])
        if paid and sum(paid.values()) > 0:
            # ① 按历史实发逐只回收（驳回与发放一一对应，追赶加成自动随实发扣回）。
            #    离队怪临时纳入落账循环（只写回自身 total_exp/level，不触发学招/进化），
            #    否则发放时在册、驳回时已离队的怪会漏扣——账目漂移。
            deltas = {tid: -int(s) for tid, s in paid.items()}
            team_ids = {tp["id"] for tp in team}
            for tid in paid:
                if tid not in team_ids:
                    team.append({"id": tid, "level": 0, "total_exp": 0, "exp_group": None})
        else:
            # ② 等比回收：按"应扣份额×当前n"占比分摊 -amount，
            #    舍入差额微调在最大扣减项上（总和与 amount 严格一致）
            cur = {tp["id"]: max(1, int((-amount) * sh) * exp_permille(max(0, target - tp["level"])) // 1000)
                   for tp, sh in zip(team, shares)}
            s = sum(cur.values())
            deltas = {tid: -max(1, round(-amount * w / s)) for tid, w in cur.items()}
            # 分摊残差：目标总和=-amount，残差=目标−当前（含每只保底1与round双侧偏差）
            diff = -amount + sum(deltas.values())
            if diff:
                big = min(deltas, key=lambda k: deltas[k])
                deltas[big] = min(-1, deltas[big] - diff)
    details = []
    granted = 0
    for tp in team:
        delta = deltas.get(tp["id"], 0)
        if delta == 0:
            continue
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
        if row["exp_group"] is not None and new_lv >= row["level"]:  # 升级或持平都可能触发进化（首次发卡等）
            # （exp_group 为 None 的行是①口径临时纳入的离队怪：只落账，不学招不进化）
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

def exp_floor(exp_group: str, level: int) -> int:
    """level_for 的逆运算：该经验组升到 level 级所需的门槛总经验（入袋即定级时回填用）。
    Lv1 门槛表值为负/0，统一地板 1，与 level_for(…, 0)→Lv1 口径自洽。
    ——修 v10 bug：捕捉/赠礼/初始入袋 total_exp 曾写死 0，
    level 与 total_exp 脱钩，首次获得经验时 level_for 反推导致掉级。"""
    col = {"fast": "exp_fast", "medium": "exp_medium", "slow": "exp_slow"}[exp_group]
    rows = db.q(f"SELECT {col} e FROM level_exp_table WHERE level=%s", (level,))
    return max(1, rows[0]["e"]) if rows else 1

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
