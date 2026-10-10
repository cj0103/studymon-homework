# -*- coding: utf-8 -*-
"""周末战斗：道馆挑战 / 野生遭遇与捕获。
战斗增益（buff）与异常状态均仅存内存会话，从不落库；战斗不产经验；道馆胜利发徽章。
v3：状态异常子系统（中毒/麻痹/睡眠/烧伤/冰冻/混乱）+ 变化招效果处理器。
v5a：出手顺序遵照原作——先制招(priority)>速度(spd，麻痹减半)>同速随机；
     先手击杀则对手本回合失去行动（我方被先手击杀时走换人/败北结算）。
v5b：PP 体力系统——每招每场限用 max_pp 次（skill_base 按威力归档），会话内扣减；
     我方换人上场时该只 PP 全部回满（原作"换人 PP 独立"的儿童化简化）；
     对方 AI 选招剔除吸血类（防孩子面对无限吸盾，单向体验）。
"""
import datetime as dt
import json
import random
import uuid
from fastapi import APIRouter, Depends, HTTPException
from .. import db
from ..auth import kid_auth
from .pokemon import stats_at, learnable

router = APIRouter()
SESSIONS: dict[str, dict] = {}          # 内存会话，服务重启即失效（符合"增益不持久"规则）

# 变化招式效果中文（buff=增益 atk_up/def_up，debuff=减益 *_down；整场战斗有效）
EFFECT_CN = {"atk_up": "攻击提升了！", "def_up": "防御提升了！",
             "atk_down": "对方的攻击下降了！", "def_down": "对方的防御下降了！"}

# 异常状态（简化版，面向小学生）：
#   poison 中毒   每次出手前扣 1/8 最大HP（不递增，剧毒暂不区分）
#   para   麻痹   25% 概率不能行动
#   sleep  睡眠   随机 1~3 回合不能行动，醒来后下回合可行动
#   burn   烧伤   攻击招式伤害减半
#   freeze 冰冻   每回合 25% 概率解冻，否则不能行动
#   confuse 混乱  35% 概率打自己（简化：自伤，不占对手回合）
# 一场战斗内有效，战斗结束随会话销毁；换人异常保留（与原作一致）。
AILMENT_CN = {"poison": "中毒", "para": "麻痹", "sleep": "睡眠",
              "burn": "烧伤", "freeze": "冰冻", "confuse": "混乱"}
# 属性免疫表（Gen1 简化）：地/岩/钢免疫中毒（毒系自身可被其他属性毒，此处与原作一致仅排除地岩钢）
IMMUNE = {"poison": {"地面", "岩石", "钢"}, "para": set(), "sleep": set(),
          "burn": {"火"}, "freeze": {"冰"}, "confuse": set()}
BATTLE_CAP = 50                          # 单次行动伤害上限（防高倍增益/馆主越级一击杀娃）

# v6：_team_top_level / dynamic_level 动态跟随已下线——野生等级完全由
# region_wild_pokemon 的静态等级带决定（rebuild_wild 按"本区道馆推荐级−4"
# 锚定，区内错开）。

def _rate(atk_type, def_types):
    rows = db.q("SELECT rate FROM type_effect WHERE attack_type=%s AND defend_type IN (%s)"
                % ("%s", ",".join(["%s"] * len(def_types))), [atk_type] + list(def_types))
    r = 1.0
    for row in rows:
        r *= float(row["rate"])
    return r

def _dmg(atk_stat, def_stat, power, type_rate, buff=1.0, burn=False):
    # 项目公式: base = ((22*power*atk/def)/50)+2，
    # 烧伤(×0.5)与属性倍率均在取整前介入——×0.5 恰好精确减半（取整后再 //2 会丢精度）
    atk_eff = atk_stat * buff * (0.5 if burn else 1.0)   # Gen1 烧伤：攻击输出减半
    raw = ((22 * power * atk_eff) / (def_stat * 50)) + 2
    return max(1, int(raw * type_rate))

# ---------------- 异常状态辅助 ----------------

def _status(unit):
    """取该单位当前异常状态（None=健康）。unit 即 sess["my"]/sess["foe"] 里的 dict。"""
    return unit.get("status")

def _can_act(unit, msgs, foe_side=False):
    """行动前结算：睡眠/麻痹/冰冻/混乱判定。返回 True=可以继续出手。
    中毒毒伤在 _poison_tick 中单独结算（出手前扣血）。"""
    who = f"对方的 {unit['name']}" if foe_side else unit["name"]
    st = _status(unit)
    if not st:
        return True
    a = st["ailment"]
    if a == "sleep":
        st["turns"] -= 1
        if st["turns"] > 0:
            msgs.append(f"{who} 正在呼呼大睡……")
        else:
            unit["status"] = None
            msgs.append(f"{who} 醒过来了！")
            return True
        return False
    if a == "freeze":
        if random.random() < 0.25:
            unit["status"] = None
            msgs.append(f"{who} 冰融化了！")
            return True
        msgs.append(f"{who} 被冻住了，无法动弹！")
        return False
    if a == "para":
        if random.random() < 0.25:
            msgs.append(f"{who} 麻痹了，身体无法动弹！")
            return False
        return True
    if a == "confuse":
        if st.get("turns", 0) > 0:
            st["turns"] -= 1
            if random.random() < 0.35:
                self_dmg = max(1, unit["stats"]["hp"] // 10)
                unit["hp"] = max(1, unit["hp"] - self_dmg)   # 混乱自伤不会打死自己
                msgs.append(f"{who} 混乱了，打到自己！")
                return False
            if st["turns"] == 0:
                unit["status"] = None
                msgs.append(f"{who} 恢复了理智！")
        return True
    return True

def _poison_tick(unit, msgs, foe_side=False):
    """中毒：每次尝试出手前扣 1/8 最大HP。"""
    st = _status(unit)
    if st and st["ailment"] == "poison":
        d = max(1, unit["stats"]["hp"] // 8)
        unit["hp"] = max(0, unit["hp"] - d)
        who = f"对方的 {unit['name']}" if foe_side else unit["name"]
        msgs.append(f"{who} 因中毒受到 {d} 伤害！")

def _try_inflict(target, ailment, msgs, foe_side=False):
    """尝试对 target 施加异常状态（已有异常/免疫则忽略）。"""
    if not ailment or ailment not in AILMENT_CN:
        return
    if _status(target):
        return
    if ailment in IMMUNE and set(target["types"]) & IMMUNE[ailment]:
        return
    who = f"对方的 {target['name']}" if foe_side else target["name"]
    if ailment == "sleep":
        target["status"] = {"ailment": ailment, "turns": random.randint(1, 3)}
    elif ailment == "confuse":
        target["status"] = {"ailment": ailment, "turns": random.randint(2, 5)}
    else:
        target["status"] = {"ailment": ailment, "turns": 99}
    msgs.append(f"{who} {AILMENT_CN[ailment]}了！")

def _apply_status_effect(caster, target, mv, msgs, target_foe_side):
    """变化招式效果处理器。返回 'hit'/'miss' 仅用于播报缺省。"""
    et = mv["effect_type"] or ""
    acc = mv["accuracy"] or 100
    if random.randint(1, 100) > acc:
        msgs.append(f"{caster['name']} 的 {mv['skill_name']} 没有命中")
        return "miss"
    caster_name = caster["name"]
    if et.startswith("status_"):
        _try_inflict(target, mv["ailment"] or et[7:], msgs, foe_side=target_foe_side)
    elif et in ("atk_up", "def_up"):
        key = caster["ref"]
        sess = _CUR_SESS[0]
        cur = sess["buffs"].get(key, 1.0)
        mult = max(float(mv["effect_value"] or 1.5), 1.0)
        sess["buffs"][key] = min(cur * mult, 2.0)
        msgs.append(f"{caster_name} 使用 {mv['skill_name']}，{EFFECT_CN[et]}")
    elif et in ("atk_down", "def_down"):
        key = target["ref"]
        sess = _CUR_SESS[0]
        cur = sess["buffs"].get(key, 1.0)
        mult = min(float(mv["effect_value"] or 0.7), 1.0)
        sess["buffs"][key] = max(cur * mult, 0.5)
        msgs.append(f"{caster_name} 使用 {mv['skill_name']}，{EFFECT_CN[et]}")
    elif et == "heal":
        frac = min(max(float(mv["effect_value"] or 0.5), 0.05), 1.0)
        miss = caster["stats"]["hp"] - caster["hp"]
        gain = min(int(round(caster["stats"]["hp"] * frac)), miss)
        if gain <= 0:
            msgs.append(f"{caster_name} 使用 {mv['skill_name']}，但没有可恢复的体力")
        else:
            caster["hp"] += gain
            msgs.append(f"{caster_name} 使用 {mv['skill_name']}，恢复了 {gain} 点体力！")
    elif et == "drain":
        # 吸血：以威力折算伤害，按 effect_value 比例回血
        r = _rate(mv["skill_type"], target["types"])
        burn_c = bool(_status(caster) and _status(caster)["ailment"] == "burn")
        dmg = _dmg(caster["stats"]["atk"], target["stats"]["def"], mv["power"] or 20, r,
                   _CUR_SESS[0]["buffs"].get(caster["ref"], 1.0), burn=burn_c)
        dmg = min(dmg, target["hp"], BATTLE_CAP)
        target["hp"] -= dmg
        frac = min(max(float(mv["effect_value"] or 0.5), 0.05), 1.0)
        gain = min(max(1, int(round(dmg * frac))), caster["stats"]["hp"] - caster["hp"])
        caster["hp"] += gain
        msgs.append(f"{caster_name} 使用 {mv['skill_name']}，造成 {dmg} 伤害并吸取了 {gain} 点体力！")
    elif et == "ohko":
        if target["hp"] > 1:
            target["hp"] = 1
            who = f"对方的 {target['name']}" if target_foe_side else target["name"]
            msgs.append(f"{caster_name} 使用 {mv['skill_name']}！{who} 只剩 1 点体力了！")
        else:
            msgs.append(f"{caster_name} 使用 {mv['skill_name']}，但对方已经没有更多体力可扣了")
    else:
        msgs.append(f"{caster_name} 使用 {mv['skill_name']}")
    return "hit"

_CUR_SESS = [None]  # 当前会话引用（供 _apply_status_effect 访问 buffs；单请求内使用）

# ---------------- 会话构建 ----------------

def _team_payload(sid):
    rows = db.q("SELECT tp.id, tp.pokedex_no, tp.level, tp.learned_skill_json, "
                "pb.name, pb.type1, pb.type2, pb.base_hp, pb.base_atk, pb.base_def, pb.base_speed "
                "FROM trainer_pokemon tp JOIN pokemon_base pb ON pb.pokedex_no=tp.pokedex_no "
                "WHERE tp.student_id=%s AND tp.is_in_team=1 AND tp.sealed=0 ORDER BY tp.slot", (sid,))
    out = []
    for r in rows:
        st = stats_at(r, r["level"])
        moves = json.loads(r["learned_skill_json"] or "[]") or learnable(r["pokedex_no"], r["level"])
        out.append({"ref": f"p{r['id']}", "pokedex_no": r["pokedex_no"], "name": r["name"],
                    "level": r["level"], "types": [t for t in (r["type1"], r["type2"]) if t],
                    "stats": st, "hp": st["hp"], "moves": _move_details(moves), "status": None})
    _init_pp(out)
    return out

def _move_details(ids):
    if not ids:
        return []
    ph = ",".join(["%s"] * len(ids))
    rows = db.q(f"SELECT id,skill_name,skill_type,power,accuracy,effect_type,effect_value,"
                f"ailment,ailment_chance,priority,max_pp "
                f"FROM skill_base WHERE id IN ({ph})", ids)
    order = {mid: i for i, mid in enumerate(ids)}
    return sorted(rows, key=lambda r: order[r["id"]])

# ---------------- v5：PP 初始化与出手定序 ----------------

def _init_pp(units):
    """会话创建时为每只单位生成 PP 表 {skill_id: 剩余次数}（max_pp 缺省兜底 8）。"""
    for u in units:
        u["pp"] = {m["id"]: int(m.get("max_pp") or 8) for m in u["moves"]}

def _speed_eff(unit):
    """定序用速度：麻痹减半（原作 Gen1 口径）。"""
    st = _status(unit)
    spd = unit["stats"]["spd"]
    return spd * 0.5 if (st and st["ailment"] == "para") else spd

def _first_order(my, foe, my_mv, foe_mv):
    """返回 True=我方先手。先制招 > 速度值 > 同速随机。"""
    p_my, p_foe = int(my_mv.get("priority") or 0), int(foe_mv.get("priority") or 0)
    if p_my != p_foe:
        return p_my > p_foe
    s_my, s_foe = _speed_eff(my), _speed_eff(foe)
    if s_my != s_foe:
        return s_my > s_foe
    return random.random() < 0.5

def _gym_team(gym_id):
    row = db.q("SELECT pokemon_json FROM gym_trainer_team WHERE gym_id=%s", (gym_id,))
    if not row:
        raise HTTPException(404, "道馆阵容缺失")
    team = json.loads(row[0]["pokemon_json"])
    out = []
    for i, t in enumerate(team):
        pb = db.q("SELECT * FROM pokemon_base WHERE pokedex_no=%s", (t["pokedex_no"],))[0]
        st = stats_at(pb, t["level"])
        moves = t.get("moves") or learnable(t["pokedex_no"], t["level"])
        out.append({"ref": f"g{i}", "pokedex_no": pb["pokedex_no"], "name": pb["name"],
                    "level": t["level"], "types": [x for x in (pb["type1"], pb["type2"]) if x],
                    "stats": st, "hp": st["hp"], "moves": _move_details(moves), "status": None})
    _init_pp(out)
    return out

def _battle_open():
    """周末默认开放；学习日由家长开关 battle_weekday_open 决定（测试期可开）"""
    return dt.date.today().weekday() >= 5 or db.cfg("battle_weekday_open", "1") == "1"

@router.get("/child/battle/availability")
def availability(tok=Depends(kid_auth)):
    stu = db.q("SELECT * FROM student_user WHERE id=%s", (tok["uid"],))[0]
    today = dt.date.today()
    weekend = today.weekday() >= 5
    open_now = _battle_open()
    badges = json.loads(stu["badge_json"] or "[]")
    gyms = db.q("SELECT * FROM gym_base ORDER BY sort")
    nxt = next((g for g in gyms if g["badge_name"] not in badges), None)
    return {"weekend": weekend, "badges": badges,
            "next_gym": nxt, "can_battle": open_now,
            "catch_left": stu["week_catch_times"],
            "region": stu["current_region_id"]}

@router.post("/child/battle/gym")
def gym_battle(tok=Depends(kid_auth)):
    if not _battle_open():
        raise HTTPException(400, "道馆战只在周末开放")
    sid = tok["uid"]
    stu = db.q("SELECT * FROM student_user WHERE id=%s", (sid,))[0]
    badges = json.loads(stu["badge_json"] or "[]")
    gym = db.q("SELECT * FROM gym_base ORDER BY sort LIMIT 1 OFFSET %s", (len(badges),))
    if not gym:
        raise HTTPException(400, "八馆已全部通关！")
    team = _team_payload(sid)
    if not team:
        raise HTTPException(400, "先设置出战队伍")
    sess = {"kind": "gym", "sid": sid, "gym": gym[0],
            "my": team, "foe": _gym_team(gym[0]["id"]),
            "buffs": {}}
    SESSIONS[sid] = sess
    return {"session_id": sid, "gym": sess["gym"], "kind_gym": True, "my": team, "foe": sess["foe"]}

def _wild_pool(region_id):
    return db.q("SELECT pokedex_no, min_level, max_level, catch_weight FROM region_wild_pokemon "
                "WHERE region_id=%s", (region_id,))

@router.post("/child/battle/wild")
def wild_battle(tok=Depends(kid_auth)):
    if not _battle_open():
        raise HTTPException(400, "野外捕获只在周末开放")
    sid = tok["uid"]
    stu = db.q("SELECT * FROM student_user WHERE id=%s", (sid,))[0]
    if stu["week_catch_times"] <= 0:
        raise HTTPException(400, "本周捕获次数用完了，下周再来")
    pool = _wild_pool(stu["current_region_id"])
    if not pool:
        raise HTTPException(400, "本区域野生池为空")
    pick = random.choices(pool, weights=[p["catch_weight"] for p in pool])[0]
    no = pick["pokedex_no"]
    # v6：不再动态跟随队伍等级，直接在本怪静态带 [min,max] 内均匀随机
    lv = random.randint(pick["min_level"], min(pick["max_level"], 50))
    pb = db.q("SELECT * FROM pokemon_base WHERE pokedex_no=%s", (no,))[0]
    st = stats_at(pb, lv)
    moves = _move_details(learnable(no, lv))
    # v5a：异常降权基础上再剔除吸血类（对方 AI 不贪吸血，防"永不动盾"体验）
    def _ailment_heavy(m):
        if (m["effect_type"] or "") == "drain":
            return True   # 吸血招权重 0：AI 永不选
        if m["power"] > 0:
            return bool(m.get("ailment"))
        return (m["effect_type"] or "").startswith("status_")
    weights = [0.5 if _ailment_heavy(m) else 1.0 for m in moves]
    foe = [{"ref": "w0", "pokedex_no": no, "name": pb["name"], "level": lv,
            "types": [x for x in (pb["type1"], pb["type2"]) if x], "stats": st, "hp": st["hp"],
            "moves": moves, "move_weights": weights, "status": None}]
    _init_pp(foe)
    sess = {"kind": "wild", "sid": sid, "wild": pick, "wild_level": lv,
            "my": _team_payload(sid), "foe": foe, "buffs": {}}
    if not sess["my"]:
        raise HTTPException(400, "先设置出战队伍")
    SESSIONS[sid] = sess
    return {"session_id": sid, "kindWild": True, "my": sess["my"], "foe": foe}

def _foe_move_pick(foe):
    """野怪按权重选招（异常招×0.5、吸血招×0），道馆怪均匀（兜底也剔除吸血）。"""
    moves = [m for m in foe["moves"] if (m["effect_type"] or "") != "drain"] or foe["moves"]
    weights = foe.get("move_weights")
    if weights and len(weights) == len(foe["moves"]):
        wmap = {m["id"]: w for m, w in zip(foe["moves"], weights)}
        ws = [wmap.get(m["id"], 1.0) for m in moves]
        return random.choices(moves, weights=ws)[0]
    return random.choice(moves)

def _attack_step(attacker, defender, mv, sess, defender_foe_side, msgs):
    """执行一次攻击/变化招行动（不含命中前的异常阻塞）。"""
    if mv["power"] > 0:
        acc = mv["accuracy"] or 100
        if random.randint(1, 100) > acc:
            msgs.append(f"{attacker['name']} 的 {mv['skill_name']} 没有命中")
            return
        r = _rate(mv["skill_type"], defender["types"])
        buff = sess["buffs"].get(attacker["ref"], 1.0)
        st = _status(attacker)
        burn_a = bool(st and st["ailment"] == "burn")
        dmg = _dmg(attacker["stats"]["atk"], defender["stats"]["def"], mv["power"], r, buff,
                   burn=burn_a)
        dmg = min(dmg, defender["hp"], BATTLE_CAP)
        defender["hp"] -= dmg
        eff = ("（效果拔群！）" if r >= 2 else "（效果不太好……）" if 0 < r < 1
               else "（没有效果！）" if r == 0 else "")
        msgs.append(f"{attacker['name']} 使用 {mv['skill_name']}，造成 {dmg} 伤害{eff}")
        # 攻击附带异常（effect_type=None）按概率；变化招式型异常招（status_*，chance=100）直接施加
        if defender["hp"] > 0 and mv.get("ailment"):
            chance = int(mv.get("ailment_chance") or 0)
            if (mv.get("effect_type") or "").startswith("status_") or random.randint(1, 100) <= chance:
                ail = mv["ailment"]
                if ail == "tri":
                    ail = random.choice(["para", "sleep", "freeze"])
                _try_inflict(defender, ail, msgs, foe_side=defender_foe_side)
    else:
        _apply_status_effect(attacker, defender, mv, msgs, defender_foe_side)

@router.post("/child/battle/act")
def act(body: dict, tok=Depends(kid_auth)):
    sid = tok["uid"]
    sess = SESSIONS.get(sid)
    if not sess:
        raise HTTPException(400, "战斗会话不存在（可能已结束或服务重启）")
    _CUR_SESS[0] = sess
    action = body.get("action", "attack")     # 缺省 attack（前端历史协议允许省略）
    if action == "run":
        SESSIONS.pop(sid, None)
        return {"result": "flee"}
    if action == "catch":
        if sess["kind"] != "wild":
            raise HTTPException(400, "只有野生战斗可捕获")
        lv = sess["wild_level"]
        first = min(m["level"] for m in sess["my"])   # 出战最低等级参战（防高等级碾压捕低级）
        # 捕获概率：等级劣势越大越难，基础0.9→0.25；异常状态加捕（麻痹/睡眠/冰冻/中毒 ×1.5）
        p = max(0.25, min(0.9, 0.9 - max(0, lv - first) * 0.05))
        if _status(sess["foe"][0]):
            p = min(0.95, p * 1.5)
        if random.random() < p:
            no = sess["foe"][0]["pokedex_no"]
            exists = db.q("SELECT id FROM trainer_pokemon WHERE student_id=%s AND pokedex_no=%s", (sid, no))
            if exists and db.q("SELECT id FROM trainer_pokemon WHERE id=%s AND sealed=1",
                               (exists[0]["id"],)):
                # 已拥有封印中的同款（理论上野生池不含赠礼怪，防御性兜底）：不升级不入袋
                db.x("UPDATE student_user SET week_catch_times=week_catch_times-1 WHERE id=%s", (sid,))
                db.x("INSERT INTO battle_record(student_id,kind,ref_id,result) VALUES(%s,'wild',%s,'catch')", (sid, no))
                SESSIONS.pop(sid, None)
                return {"result": "catch", "pokedex_no": no}
            if exists:
                db.x("UPDATE trainer_pokemon SET level=MIN(50,level+1) WHERE id=%s", (exists[0]["id"],))
                row = db.q("SELECT level, learned_skill_json, known_skill_json FROM trainer_pokemon WHERE id=%s", (exists[0]["id"],))[0]
                from .. import skills as skillmod
                skillmod.ensure_known(exists[0]["id"], no, row["level"], row["known_skill_json"], row["learned_skill_json"])
            else:
                skills = learnable(no, lv)
                db.x("INSERT INTO trainer_pokemon(student_id,pokedex_no,level,total_exp,learned_skill_json,known_skill_json,is_in_team) "
                     "VALUES(%s,%s,%s,0,%s,%s,0)", (sid, no, lv, json.dumps(skills), json.dumps(skills)))
            db.x("UPDATE student_user SET week_catch_times=week_catch_times-1 WHERE id=%s", (sid,))
            db.x("INSERT INTO battle_record(student_id,kind,ref_id,result) VALUES(%s,'wild',%s,'catch')", (sid, no))
            SESSIONS.pop(sid, None)
            return {"result": "catch", "pokedex_no": no}
        return {"result": "continue", "msg": "精灵球弹开了！", "foe": sess["foe"], "my": sess["my"]}
    # attack —— v5a 三段式回合：双方选招 → 定序 → 按序执行（被击杀者失去行动）
    my = sess["my"][sess.get("my_idx", 0)]
    foe = sess["foe"][sess.get("foe_idx", 0)]
    mv = next((m for m in my["moves"] if m["id"] == body["skill_id"]), None)
    if not mv:
        raise HTTPException(400, "无效招式")
    # v5b：PP 校验（旧会话无 pp 表则惰性补一份，防御服务热更新导致的结构错位）
    if "pp" not in my:
        _init_pp(sess["my"])
    if my["pp"].get(mv["id"], 99) <= 0:
        raise HTTPException(400, f"{mv['skill_name']} 的PP用完了，换一招吧")
    my["pp"][mv["id"]] -= 1                        # 出手即耗 1（命中与否）
    fm = _foe_move_pick(foe)                       # 对方回合开始即锁招（定序需要其先制/速度）
    msgs = []
    result, badge, gift = "continue", None, None
    my_first = _first_order(my, foe, mv, fm)

    def _my_step():
        """我方行动步：毒结算→异常阻塞→攻击→击杀判定。返回 True=可继续敌方步。"""
        nonlocal result, badge, gift
        _poison_tick(my, msgs)
        if my["hp"] > 0 and _can_act(my, msgs):
            _attack_step(my, foe, mv, sess, True, msgs)
        if foe["hp"] <= 0:
            msgs.append(f"对方的 {foe['name']} 倒下了！")
            result, badge, gift = _on_foe_down(sess)
            if gift:
                msgs.append(f"🎁 道馆礼物到手：{gift['name']} 加入了你的队伍（封印中）！")
            return False
        return result == "continue" and foe["hp"] > 0 and my["hp"] > 0

    def _foe_step():
        """对方行动步：毒结算→异常阻塞→攻击→我方倒下换人/败北。"""
        nonlocal result
        _poison_tick(foe, msgs, foe_side=True)
        if foe["hp"] > 0 and my["hp"] > 0 and _can_act(foe, msgs, foe_side=True):
            _attack_step(foe, my, fm, sess, False, msgs)
        if my["hp"] <= 0:
            msgs.append(f"你的 {my['name']} 倒下了！")
            if sess.get("my_idx", 0) + 1 < len(sess["my"]):
                sess["my_idx"] = sess.get("my_idx", 0) + 1
                nxt = sess["my"][sess["my_idx"]]
                # v5b：新上场 PP 全回满（原作换人 PP 独立；异常/敌方增益按会话延续）
                nxt["pp"] = {m["id"]: int(m.get("max_pp") or 8) for m in nxt["moves"]}
                msgs.append(f"上吧，{nxt['name']}！")
            else:
                result = "lose"

    if my_first:
        if _my_step():
            _foe_step()
    else:
        msgs.append(f"对方的 {foe['name']} 速度更快，抢得先手！")
        _foe_step()
        if result == "continue" and my["hp"] > 0 and foe["hp"] > 0:
            _my_step()
    if result in ("win", "lose", "catch"):
        # 会话销毁后 my/foe 仍是会话内 dict，清状态前先浅拷贝，避免污染后续请求
        out = {"result": result, "messages": msgs,
               "my": [{**u, "status": None} for u in sess["my"]],
               "foe": [{**u, "status": None} for u in sess["foe"]],
               "my_idx": sess.get("my_idx", 0), "foe_idx": sess.get("foe_idx", 0),
               "badge": badge, "gift": gift}
        if result == "catch":
            out["pokedex_no"] = sess["foe"][0]["pokedex_no"]
        SESSIONS.pop(sid, None)
        return out
    return {"result": result, "messages": msgs, "my": sess["my"], "foe": sess["foe"],
            "my_idx": sess.get("my_idx", 0), "foe_idx": sess.get("foe_idx", 0),
            "badge": badge, "gift": gift}

def _on_foe_down(sess):
    """返回 (result, badge, gift)：过馆发徽章+推进区域+发放封印赠礼"""
    sess["foe_idx"] = sess.get("foe_idx", 0) + 1
    if sess["foe_idx"] < len(sess["foe"]):
        return "continue", None, None
    badge = None
    gift = None
    if sess["kind"] == "gym":
        gym = sess["gym"]
        sid = sess["sid"]
        stu = db.q("SELECT badge_json FROM student_user WHERE id=%s", (sid,))[0]
        badges = json.loads(stu["badge_json"] or "[]")
        first_clear = gym["badge_name"] not in badges
        if first_clear:
            badges.append(gym["badge_name"])
            # 8 区 1:1 对应道馆：打完第 n 馆 → 推进到区 n+1（封顶 8=常磐~冠军之路）
            db.x("UPDATE student_user SET badge_json=%s, current_region_id=LEAST(8, %s) WHERE id=%s",
                 (json.dumps(badges, ensure_ascii=False), len(badges) + 1, sid))
            # 道馆赠礼：每过第 i 馆送一只封印传说伙伴（入库 Lv10，连击7天激活）
            from .. import gift as giftmod
            gift = giftmod.grant_gym_gift(sid, gym["sort"], gym["id"])
        db.x("INSERT INTO battle_record(student_id,kind,ref_id,result) VALUES(%s,'gym',%s,'win')",
             (sid, gym["id"]))
        badge = gym["badge_name"]
    else:
        db.x("INSERT INTO battle_record(student_id,kind,ref_id,result) VALUES(%s,'wild',%s,'win')",
             (sess["sid"], sess["foe"][0]["pokedex_no"]))
    return "win", badge, gift
