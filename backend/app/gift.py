# -*- coding: utf-8 -*-
"""道馆赠礼 + 封印宝可梦（家庭规则，方案已确认）：
- 每过第 i 馆送一只"传说伙伴"（GYM_GIFTS），入库 Lv10、sealed=1，
  gift_gym_sort 记录来源道馆：不进背包出战、不参与经验分配与进化检查，
  图鉴可见（保持名字，突出神秘感）
- 激活条件（v8 家长定稿：独立计时）：**从获得当日起**（seal_start_date），
  每一天都打卡获批、连续满 seal_streak_days(7) 天，在家长审批结算时检查；
  封印期内漏卡/驳回 → 该只从断后重新起算；与全局连击（+50 奖励）互不影响；
  **激活等级 = 来源道馆的推荐等级**（v7 家长定稿：1 馆卡比兽→Lv16、
  2 馆急冻鸟→Lv19 … 8 馆多边兽→Lv46；缺 sort/起算日的存量数据兜底
  Lv16/迁移日重新起算），total_exp 对齐经验表，到级技能自动入已学袋
- 伊布三分支（水伊布/雷伊布/火伊布）主线暂不可得，留节日赠送
"""
import datetime as dt
import json
from . import db

# gym_base.sort → 赠礼 pokedex_no（8 馆 8 只，传说/幻兽/化石翼龙/多边兽）
GYM_GIFTS = {1: 143, 2: 144, 3: 145, 4: 146, 5: 150, 6: 142, 7: 151, 8: 137}
GIFT_LEVEL = 10                    # 封印入库等级
FALLBACK_LEVEL = 16                # 存量数据缺 gift_gym_sort 时的兜底激活等级
# 封印态展示技能：不回填真实学习池（"解封才见真招"的神秘感），给孩子一个看家招
SEAL_DISPLAY_MOVE = {143: "舌舔", 144: "冰冻光束", 145: "打雷", 146: "大字爆炎",
                     150: "念力", 142: "翅膀攻击", 151: "精神强念", 137: "幻象光线"}
GIFT_INTRO = {
    143: "沉睡了亿万年的卡比兽被你的坚持唤醒了！它需要连续打卡一周才会真正加入战斗。",
    144: "急冻鸟掠过华蓝市上空，留下一根闪耀的冰羽——坚持一周，它就会成为你的伙伴。",
    145: "发电厂上空雷云翻滚，闪电鸟注视着你。连续打卡一周，得到它的认可吧！",
    146: "远方火山喷出火光，火焰鸟朝你飞来。坚持一周打卡，接受烈焰的考验。",
    150: "宝可梦屋深处，最强的超梦认可了你的努力。连续打卡一周，与它并肩作战。",
    142: "化石在红莲岛复活了！化石翼龙冲破蛋壳——连续打卡一周，它就能展翅陪你飞翔。",
    151: "幻之宝可梦梦幻悄悄跟上了你。连续打卡一周，它就想和你做朋友。",
    137: "宝可梦屋的科学家把珍贵的多边兽托付给你。连续打卡一周，完成启动程序。",
}


def grant_gym_gift(sid: int, gym_sort: int, gym_id: int):
    """打赢第 gym_sort 馆 → 发放对应封印宝可梦（幂等：已拥有同一只则跳过）。
    返回赠礼信息 {pokedex_no, name, level, sealed, intro} 或 None。"""
    no = GYM_GIFTS.get(gym_sort)
    if no is None:
        return None
    exists = db.q("SELECT id FROM trainer_pokemon WHERE student_id=%s AND pokedex_no=%s",
                  (sid, no))
    if exists:
        return None
    # 首杀才发（重打同馆不重发）：battle_record 里该馆已有 win 记录则跳过。
    # 注：reset_game.py 清 battle_record 后重打会重发，属于"重置即恢复初始态"，可接受。
    prev_win = db.q("SELECT id FROM battle_record WHERE student_id=%s AND kind='gym' "
                    "AND ref_id=%s AND result='win' LIMIT 1", (sid, gym_id))
    if prev_win:
        return None
    pb = db.q("SELECT name FROM pokemon_base WHERE pokedex_no=%s", (no,))
    name = pb[0]["name"] if pb else f"#{no}"
    # 封印状态：不携带技能、不入已学袋（激活时按等级回填）
    # gift_gym_sort：v7 记录来源道馆（激活等级=该馆推荐级）
    # seal_start_date：v8 封印独立计时起算日=获得当日（逐日获批满 7 天才解锁）
    db.x("INSERT INTO trainer_pokemon(student_id,pokedex_no,level,total_exp,"
         "learned_skill_json,known_skill_json,is_in_team,sealed,gift_gym_sort,seal_start_date) "
         "VALUES(%s,%s,%s,0,'[]','[]',0,1,%s,%s)",
         (sid, no, GIFT_LEVEL, gym_sort, dt.date.today()))
    return {"pokedex_no": no, "name": name, "level": GIFT_LEVEL,
            "sealed": 1, "intro": GIFT_INTRO.get(no, "")}


def _exp_at_level(exp_group: str, level: int) -> int:
    """反查经验组在指定等级对应的总经验（激活时把 total_exp 对齐，保证后续升级曲线正常）"""
    col = {"fast": "exp_fast", "medium": "exp_medium", "slow": "exp_slow"}[exp_group]
    rows = db.q(f"SELECT {col} e FROM level_exp_table WHERE level<=%s ORDER BY level DESC LIMIT 1",
                (level,))
    return rows[0]["e"] if rows else 0


def _streak_days(student_id, upto_date):
    """连续获批天数（含 upto_date，往前数；status in (2,3) 计活跃）——与 checkin 同口径"""
    cnt, d = 0, upto_date
    while True:
        r = db.q("SELECT status FROM checkin_record WHERE student_id=%s AND task_date=%s "
                 "AND status IN (2,3)", (student_id, d))
        if not r:
            break
        cnt += 1
        d -= dt.timedelta(days=1)
    return cnt


def _approved_on(student_id, d) -> bool:
    """某日是否打卡获批（status 2/3）——封印独立计时逐日检查用"""
    r = db.q("SELECT status FROM checkin_record WHERE student_id=%s AND task_date=%s "
             "AND status IN (2,3)", (student_id, d))
    return bool(r)


def _seal_progress(student_id, start_date, upto_date) -> int:
    """v8 封印独立进度：从起算日到 upto_date 逐日检查获批，
    遇缺卡/驳回即断（该段重新起算）。返回当前连续天数（封顶 need）。
    返回 (进度, 最新连续段起算日)——断档时调用方把 seal_start_date 前移。"""
    need = db.cfg("seal_streak_days", "7", int)
    d, run = upto_date, 0
    while d >= start_date and run < need:
        if not _approved_on(student_id, d):
            break
        run += 1
        d -= dt.timedelta(days=1)
    return run, d + dt.timedelta(days=1)


def activate_sealed(sid: int, upto_date=None):
    """v8：对每只封印怪按**独立计时**检查——从 seal_start_date（获得当日）起
    逐日打卡获批满 seal_streak_days(7) 天才激活（不再借全局连击的光）。
    断档则 seal_start_date 前移到最新连续段起算日（孩子端进度随之归零重数）。
    激活等级=来源道馆推荐级（v7），经验对齐、到级技能入袋。
    返回激活列表 [{pokedex_no,name,level}]。upto_date=本次审批的打卡归属日。"""
    need = db.cfg("seal_streak_days", "7", int)
    ref = upto_date or dt.date.today()
    sealed = db.q("SELECT tp.id, tp.pokedex_no, pb.name, pb.exp_group, tp.gift_gym_sort, "
                  "tp.seal_start_date "
                  "FROM trainer_pokemon tp JOIN pokemon_base pb ON pb.pokedex_no=tp.pokedex_no "
                  "WHERE tp.student_id=%s AND tp.sealed=1", (sid,))
    if not sealed:
        return []
    # 道馆 sort → 推荐等级（一次取全，8 行小表）
    rec_by_sort = {r["sort"]: r["recommend_level"] for r in
                   db.q("SELECT sort, recommend_level FROM gym_base")}
    from . import skills
    out = []
    for r in sealed:
        # 存量兜底：缺起算日的旧封印怪从本次审批归属日起算
        start = r["seal_start_date"]
        if hasattr(start, "date"):
            start = start.date()
        if not isinstance(start, dt.date):
            import datetime as _dtm
            start = _dtm.date.fromisoformat(str(start)) if start else ref
            db.x("UPDATE trainer_pokemon SET seal_start_date=%s WHERE id=%s", (start, r["id"]))
        prog, new_start = _seal_progress(sid, start, ref)
        if prog < need:
            if new_start != start:   # 断档：起算日前移到最新连续段
                db.x("UPDATE trainer_pokemon SET seal_start_date=%s WHERE id=%s",
                     (new_start, r["id"]))
            continue
        target_lv = rec_by_sort.get(r["gift_gym_sort"], FALLBACK_LEVEL)
        exp_val = _exp_at_level(r["exp_group"] or "medium", target_lv)
        db.x("UPDATE trainer_pokemon SET sealed=0, level=%s, total_exp=%s WHERE id=%s",
             (target_lv, exp_val, r["id"]))
        skills.ensure_known(r["id"], r["pokedex_no"], target_lv, "[]", "[]")
        out.append({"pokedex_no": r["pokedex_no"], "name": r["name"], "level": target_lv})
    return out


def _today_streak(sid: int):
    """含今日的连续获批天数（封印进度展示；今日记录须已置 2/3）"""
    return _streak_days(sid, dt.date.today())


def sealed_status(sid: int):
    """封印宝可梦状态（供孩子端展示）——v8 每只按**独立计时**给进度：
    [{pokedex_no,name,level,unseal_level,seal_progress,intro}]；
    全局连击 streak/need 保留（首页大联击进度仍用全局口径，与封印互不干扰）"""
    rows = db.q("SELECT tp.pokedex_no, tp.level, tp.gift_gym_sort, tp.seal_start_date, "
                "pb.name FROM trainer_pokemon tp "
                "JOIN pokemon_base pb ON pb.pokedex_no=tp.pokedex_no "
                "WHERE tp.student_id=%s AND tp.sealed=1", (sid,))
    rec_by_sort = {r["sort"]: r["recommend_level"] for r in
                   db.q("SELECT sort, recommend_level FROM gym_base")}
    need = db.cfg("seal_streak_days", "7", int)
    today = dt.date.today()
    import datetime as _dtm
    out = []
    for r in rows:
        start = r["seal_start_date"]
        if hasattr(start, "date"):
            start = start.date()
        if not isinstance(start, dt.date):
            start = _dtm.date.fromisoformat(str(start)) if start else today
        prog, _ = _seal_progress(sid, start, today)
        out.append({"pokedex_no": r["pokedex_no"], "name": r["name"], "level": r["level"],
                    "unseal_level": rec_by_sort.get(r["gift_gym_sort"], FALLBACK_LEVEL),
                    "seal_progress": prog,
                    "intro": GIFT_INTRO.get(r["pokedex_no"], "")})
    return {"sealed": out, "streak": _today_streak(sid), "need": need}
