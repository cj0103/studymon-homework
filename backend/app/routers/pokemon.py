# -*- coding: utf-8 -*-
"""我的宝可梦 / 图鉴 / 换人上阵（≤3只）/ 自主选技（≤4个，来自已学袋）"""
import json
from fastapi import APIRouter, Depends, HTTPException
from .. import db
from ..auth import kid_auth
from ..skills import ensure_known, MAX_CARRY

router = APIRouter()

STAT_COLS = {"hp": "base_hp", "atk": "base_atk", "def": "base_def", "spd": "base_speed"}

def stats_at(base, level):
    """DV=7：stat=int(((base+7)*2*lv)/100)+5；HP 另 +lv+10"""
    out = {}
    for k, col in STAT_COLS.items():
        v = int(((base[col] + 7) * 2 * level) / 100) + 5
        out[k] = v + (level + 10) if k == "hp" else v
    return out

def learnable(pokedex_no, level):
    """学习池（野怪/NPC 无训练记录时按等级现算用）。
    规则：取当前等级下<b>最后习得的 4 项</b>（学习等级从低到高排序取末尾 4 个，
    再按学习等级新→旧作为出招顺序）；不足 4 项则全取。"""
    rows = db.q("SELECT skill_id, learn_level FROM pokemon_skill_learn "
                "WHERE pokedex_no=%s AND learn_level<=%s ORDER BY learn_level, skill_id",
                (pokedex_no, level))
    return [r["skill_id"] for r in rows][-4:][::-1]

def skill_details(ids):
    if not ids:
        return []
    ph = ",".join(["%s"] * len(ids))
    sd = db.q(f"SELECT id,skill_name,skill_type,power,accuracy,effect_type,effect_value,"
              f"ailment,ailment_chance "
              f"FROM skill_base WHERE id IN ({ph})", ids)
    order = {mid: i for i, mid in enumerate(ids)}
    return sorted(sd, key=lambda x: order[x["id"]])

@router.get("/child/pokemon")
def my_pokemon(tok=Depends(kid_auth)):
    rows = db.q("SELECT tp.*, pb.name, pb.type1, pb.type2, pb.exp_group, "
                "pb.base_hp, pb.base_atk, pb.base_def, pb.base_speed "
                "FROM trainer_pokemon tp JOIN pokemon_base pb ON pb.pokedex_no=tp.pokedex_no "
                "WHERE tp.student_id=%s ORDER BY tp.is_in_team DESC, tp.slot, tp.id", (tok["uid"],))
    for r in rows:
        r["stats"] = stats_at(r, r["level"])
        r["stats_names"] = {"hp": "HP", "atk": "攻击", "def": "防御", "spd": "速度"}
        if r.get("sealed"):                      # 封印中：不回填技能袋（激活后按等级解锁）
            r["move_details"] = []
            r["known_details"] = []
            r["moves"] = []
            r["known"] = []
            r["exp_to_next"] = 0
            continue
        # v2：确保已学袋覆盖当前等级学习池（旧数据/升级遗漏自动回填）
        known = json.loads(ensure_known(r["id"], r["pokedex_no"], r["level"],
                                        r.get("known_skill_json"),
                                        r["learned_skill_json"]) or "[]")
        ids = json.loads(r["learned_skill_json"] or "[]")
        r["move_details"] = skill_details(ids)     # 当前携带（≤4，孩子自选）
        r["known_details"] = skill_details(known)  # 已学袋（永不遗忘）
        r["moves"] = ids
        r["known"] = known
        grp = {"fast": "exp_fast", "medium": "exp_medium", "slow": "exp_slow"}[r["exp_group"]]
        nxt = db.q(f"SELECT {grp} e FROM level_exp_table WHERE level>%s ORDER BY level LIMIT 1",
                   (r["level"],))
        r["exp_to_next"] = (nxt[0]["e"] - r["total_exp"]) if nxt else 0
    return rows

@router.get("/child/pokemon/{tid}")
def pokemon_detail(tid: int, tok=Depends(kid_auth)):
    """单只详情：档案(分类/身高体重/图鉴简介) + 四维 + 已学技能袋 + 携带 + 下一技能预告"""
    rows = db.q("SELECT tp.*, pb.name, pb.type1, pb.type2, pb.exp_group, "
                "pb.base_hp, pb.base_atk, pb.base_def, pb.base_speed "
                "FROM trainer_pokemon tp JOIN pokemon_base pb ON pb.pokedex_no=tp.pokedex_no "
                "WHERE tp.id=%s AND tp.student_id=%s", (tid, tok["uid"]))
    if not rows:
        raise HTTPException(404, "这只宝可梦不是你的")
    r = rows[0]
    r["stats"] = stats_at(r, r["level"])
    r["stats_names"] = {"hp": "HP", "atk": "攻击", "def": "防御", "spd": "速度"}
    if r.get("sealed"):                          # 封印中：技能袋加密封装，仅展示一个"看家招"吊胃口
        from .. import gift as giftmod
        r["move_details"] = r["known_details"] = []
        r["moves"] = r["known"] = []
        r["exp_to_next"] = 0
        r["upcoming"] = []
        r["evolution"] = None
        prof = db.q("SELECT genus,height,weight,intro FROM pkm_profile WHERE pokedex_no=%s",
                    (r["pokedex_no"],))
        r["profile"] = prof[0] if prof else None
        hint = giftmod.SEAL_DISPLAY_MOVE.get(r["pokedex_no"])
        hint_row = db.q("SELECT id,skill_name,skill_type,power,accuracy,effect_type,effect_value,"
                        "ailment,ailment_chance FROM skill_base WHERE skill_name=%s", (hint,)) if hint else []
        r["seal_hint"] = hint_row[0] if hint_row else None
        return r
    known = json.loads(ensure_known(r["id"], r["pokedex_no"], r["level"],
                                    r.get("known_skill_json"), r["learned_skill_json"]) or "[]")
    ids = json.loads(r["learned_skill_json"] or "[]")
    r["move_details"] = skill_details(ids)
    r["known_details"] = skill_details(known)
    r["moves"] = ids
    r["known"] = known
    grp = {"fast": "exp_fast", "medium": "exp_medium", "slow": "exp_slow"}[r["exp_group"]]
    nxt = db.q(f"SELECT {grp} e FROM level_exp_table WHERE level>%s ORDER BY level LIMIT 1",
               (r["level"],))
    r["exp_to_next"] = (nxt[0]["e"] - r["total_exp"]) if nxt else 0
    # 档案（未抓到/无档案时优雅降级）
    prof = db.q("SELECT genus,height,weight,intro FROM pkm_profile WHERE pokedex_no=%s",
                (r["pokedex_no"],))
    r["profile"] = prof[0] if prof else None
    # 下一个待解锁技能预告
    upc = db.q("SELECT skill_id, learn_level FROM pokemon_skill_learn "
               "WHERE pokedex_no=%s AND learn_level>%s ORDER BY learn_level LIMIT 3",
               (r["pokedex_no"], r["level"]))
    if upc:
        det = {d["id"]: d for d in skill_details([u["skill_id"] for u in upc])}
        r["upcoming"] = [{"level": u["learn_level"],
                          "skill": det.get(u["skill_id"])} for u in upc if det.get(u["skill_id"])]
    else:
        r["upcoming"] = []
    # 进化预告：下一形态 + 所需等级（无进化则为 None）
    evo = db.q("SELECT e.to_no, e.min_level, pb.name FROM pkm_evolution e "
               "JOIN pokemon_base pb ON pb.pokedex_no=e.to_no WHERE e.from_no=%s",
               (r["pokedex_no"],))
    r["evolution"] = ({"to_no": evo[0]["to_no"], "name": evo[0]["name"],
                       "min_level": evo[0]["min_level"]} if evo else None)
    return r

@router.post("/child/pokemon/{tid}/moves")
def set_moves(tid: int, body: dict, tok=Depends(kid_auth)):
    """孩子为某只宝可梦配置上场技能：≤4个且必须来自已学袋"""
    rows = db.q("SELECT id, pokedex_no, level, known_skill_json, learned_skill_json "
                "FROM trainer_pokemon WHERE id=%s AND student_id=%s", (tid, tok["uid"]))
    if not rows:
        raise HTTPException(404, "这只宝可梦不是你的")
    r = rows[0]
    ensure_known(r["id"], r["pokedex_no"], r["level"], r["known_skill_json"], r["learned_skill_json"])
    known = json.loads(db.q("SELECT known_skill_json k FROM trainer_pokemon WHERE id=%s",
                            (tid,))[0]["k"] or "[]")
    moves = body.get("moves", [])
    if not isinstance(moves, list) or not moves:
        raise HTTPException(400, "至少选择1个技能上场")
    moves = [int(m) for m in moves]
    if len(moves) > MAX_CARRY:
        raise HTTPException(400, f"最多携带{MAX_CARRY}个技能")
    if len(set(moves)) != len(moves):
        raise HTTPException(400, "技能重复")
    bad = [m for m in moves if m not in known]
    if bad:
        raise HTTPException(400, "有技能尚未学会，不能上场")
    db.x("UPDATE trainer_pokemon SET learned_skill_json=%s WHERE id=%s",
         (json.dumps(moves), tid))
    return {"ok": True, "moves": moves}

@router.post("/child/team")
def set_team(body: dict, tok=Depends(kid_auth)):
    ids = body.get("team_ids", [])
    if len(ids) > 3:
        raise HTTPException(400, "最多出战3只")
    sid = tok["uid"]
    if not ids:                                   # 空数组 = 全部撤下
        db.x("UPDATE trainer_pokemon SET is_in_team=0, slot=NULL WHERE student_id=%s", (sid,))
        return {"ok": True}
    ph = ",".join(["%s"] * len(ids))
    rows = db.q(f"SELECT id FROM trainer_pokemon WHERE student_id=%s AND id IN ({ph})",
                [sid] + [int(i) for i in ids])
    if len(rows) != len(ids):
        raise HTTPException(400, "存在不属于你的宝可梦")
    # 封印中的宝可梦不能上阵（连击满 7 天自动激活后解锁）
    sealed_ids = {r["id"] for r in db.q(
        f"SELECT id FROM trainer_pokemon WHERE student_id=%s AND sealed=1 AND id IN ({ph})",
        [sid] + [int(i) for i in ids])}
    if sealed_ids:
        raise HTTPException(400, "有宝可梦还处于封印状态，连续打卡满7天就会激活")
    db.x("UPDATE trainer_pokemon SET is_in_team=0, slot=NULL WHERE student_id=%s", (sid,))
    for i, pid in enumerate(ids):
        db.x("UPDATE trainer_pokemon SET is_in_team=1, slot=%s WHERE id=%s AND student_id=%s", (i, pid, sid))
    return {"ok": True}

def _team_top_level(sid):
    rows = db.q("SELECT level FROM trainer_pokemon WHERE student_id=%s AND is_in_team=1", (sid,))
    return max((r["level"] for r in rows), default=5)

@router.get("/child/guide")
def guide(tok=Depends(kid_auth)):
    """图鉴指南：8 区域（每区恰好 1 道馆，区 i ↔ 第 i 馆）× 可捕捉宝可梦清单 + 进化/战斗小知识。
    v6：野生等级为静态带（本区道馆推荐级−4 锚定，区内错开），清单恢复标注 lo/hi 等级带。"""
    team_top = _team_top_level(tok["uid"])
    regions = db.q("SELECT id, region_name, unlock_badge_count FROM region_base ORDER BY id")
    gyms = db.q("SELECT gym_name, badge_name, recommend_level, sort FROM gym_base ORDER BY sort")
    # 区域↔道馆：8 区 1:1 —— 区 i 对应第 i 馆（sort=i），区解锁=打完前 i-1 馆
    region_gyms = {r["id"]: gyms[i:i + 1] for i, r in enumerate(regions)}
    # v17 谱系统一口径：进化后前身在指南不再回退？？？（与图鉴/野外加权共用 lit_set）
    from .. import dexline
    owned = dexline.lit_set(tok["uid"])
    badges_now = len(json.loads(db.q("SELECT badge_json FROM student_user WHERE id=%s",
                                     (tok["uid"],))[0]["badge_json"] or "[]"))
    out = []
    for reg in regions:
        rows = db.q(
            "SELECT w.pokedex_no, b.name, b.type1, b.type2, "
            "MIN(w.min_level) lo, MAX(w.max_level) hi, SUM(w.catch_weight) w "
            "FROM region_wild_pokemon w JOIN pokemon_base b ON b.pokedex_no=w.pokedex_no "
            "WHERE w.region_id=%s GROUP BY w.pokedex_no ORDER BY lo, w.pokedex_no",
            (reg["id"],))
        need = reg["unlock_badge_count"]
        out.append({
            "id": reg["id"], "name": reg["region_name"],
            "unlock_badges": reg["unlock_badge_count"],
            "unlocked": badges_now >= need,
            "gyms": region_gyms.get(reg["id"], []),
            # own/owned 双字段：own 为旧前端兼容别名，owned 为规范字段（修复已抓显？？？）
            "pokemon": [{"pokedex_no": r["pokedex_no"], "name": r["name"],
                         "type1": r["type1"], "type2": r["type2"],
                         "lo": r["lo"], "hi": r["hi"],
                         "owned": r["pokedex_no"] in owned,
                         "own": r["pokedex_no"] in owned} for r in rows],
        })
    total = db.q("SELECT COUNT(*) n FROM pokemon_base")[0]["n"]
    # 道馆礼物：过第 i 馆送一只封印传说伙伴（连击满 7 天激活，等级跟随队伍最强）
    from .. import gift as giftmod
    owned_sealed = {r["pokedex_no"] for r in db.q(
        "SELECT pokedex_no FROM trainer_pokemon WHERE student_id=%s AND sealed=1", (tok["uid"],))}
    gift_table = []
    dex = {r["pokedex_no"]: r["name"] for r in db.q("SELECT pokedex_no,name FROM pokemon_base")}
    for g in gyms:
        no = giftmod.GYM_GIFTS.get(g["sort"])
        if no:
            gift_table.append({"gym_sort": g["sort"], "gym_name": g["gym_name"],
                               "badge_name": g["badge_name"], "pokedex_no": no,
                               "name": dex.get(no, f"#{no}"),
                               "obtained": no in owned,
                               "sealed": no in owned_sealed})
    return {"total": total, "owned": len(owned), "regions": out, "gyms": gyms,
            "team_top_level": team_top, "gym_gifts": gift_table,
            "seal_need": db.cfg("seal_streak_days", "7", int)}

@router.get("/child/pokedex")
def pokedex(tok=Depends(kid_auth)):
    """图鉴"拥有过即点亮"：当前背包（含封印怪）或曾经拥有过（进化链前身）
    都算点亮。v17：改用 dexline.lit_set 统一谱系口径（与指南/野外加权一致）。"""
    from .. import dexline
    lit = dexline.lit_set(tok["uid"])
    rows = db.q("SELECT pokedex_no,name,type1,type2 FROM pokemon_base ORDER BY pokedex_no")
    for r in rows:
        r["owned"] = r["pokedex_no"] in lit
        if not r["owned"]:
            r["name"] = "？？？"          # 未点亮不泄露名字，保持新鲜感
    return rows
