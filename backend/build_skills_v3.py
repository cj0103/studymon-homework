# -*- coding: utf-8 -*-
"""P1 数据重建 v3：原作 Gen1 全 165 招式（剔除不可实现招）+ 全宝可梦学习表。

数据源（veekun csv，本地 assets/veekun-csv）：
- moves.csv / move_names.csv(lang 12=简中) —— 招式全集、威力、命中、属性
- move_meta.csv / move_meta_stat_changes.csv —— 效果类别×异常×档位
- pokemon_moves.csv —— 学习表：method 1=升级（等级以红蓝 vg=1 为权威，缺则取 2/3）
  method 4=TM（move_id 直连；其 level 列是各版本组自己的 TM 编号，不作 Gen1 编号用）

效果映射（本引擎语义，skill_base.effect_type / ailment / ailment_chance）：
- 攻击招 effect_type=None；附加异常走 ailment(para/sleep/freeze/burn/poison/confuse/tri)+概率
- 变化招：status_* 施加异常 / atk_up / def_up / atk_down / def_down(作用于对敌) / heal / drain / ohko
- 档位：±1→×1.5/×0.7，±2及以上→×2/×0.5；特攻=攻击、特防=防御；
  自身速度↑→def_up 代偿；降敌命中→对敌 def_down 代偿
- 一击必杀（地裂/角钻/断头钳）孩子友好化：命中打至对手剩1HP，命中强设30
- 睡觉/生蛋/再生化 → 回50%；光墙/反射壁 → def_up×1.5；闪光降命中→对敌def_down×0.7
- 固定/随机伤害招 → 归一化为普通威力（引擎不做固定伤害机制）

学习表规则：
- 池 = 升级招 ∪ TM（超 TM_CAP 时"本属性优先+低威力优先"截断）；不足 MIN_TOTAL 家族借招
- 兜底借招落库前做跨属性清洗：与本属性全不同的借/TM 招剔除（一般属性豁免）——
  宁可池小，不出现"绿毛虫学念力"这类出戏招（用户反馈：小拉达电光一闪观感问题）
- 节奏：按原作升级等级排序（TM招按威力插段），同段专属招优先；
  前 INIT 招 Lv1，其后逐级递增且尽量贴近原作段位，封顶 Lv50
- 皮卡丘(25)：并入雷丘(26)池；Lv1 固定 摇尾巴/叫声；破坏光线强插 Lv28（显式断言）

用法：python build_skills_v3.py               # 干跑报告（不落库）
      PKM_APPLY=1 python build_skills_v3.py   # 落库（须先跑 migrate_v3.py 加 ailment 列）
"""
import csv
import os
import sqlite3
from collections import defaultdict

VEEKUN = os.environ.get("PKM_VEEKUN",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "veekun-csv")))
DBFILE = os.environ.get("PKM_SQLITE_FILE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "pkm.sqlite3")))
GEN1_VG = {"1", "2", "3"}
STEP = int(os.environ.get("PKM_SKILL_STEP", "3"))
INIT = int(os.environ.get("PKM_SKILL_INIT", "2"))
MIN_TOTAL = 10
TM_CAP = int(os.environ.get("PKM_TM_CAP", "6"))   # 每只 TM 上限：本属性→一般→其余 排序截断
                                                  # （全收 15~22 会让学习池爆炸且塞满跨属性招，观感出戏）

TYPE_ID2CN = {"1":"一般","2":"格斗","3":"飞行","4":"毒","5":"地面","6":"岩石",
              "7":"虫","8":"幽灵","9":"钢","10":"火","11":"水","12":"草",
              "13":"电","14":"超能力","15":"冰","16":"龙","17":"恶"}

AIL_CN = {"1":"para","2":"sleep","3":"freeze","4":"burn","5":"poison","6":"confuse"}
STAT_MAP_UP   = {"2":"atk_up","3":"def_up","4":"atk_up","5":"def_up","6":"def_up","7":"atk_up"}
STAT_MAP_DOWN = {"2":"atk_down","3":"def_down","4":"atk_down","5":"def_down",
                 "6":"atk_down","7":"def_down","8":"def_down"}
MULT_UP   = {1: 1.5, 2: 2.0}
MULT_DOWN = {-1: 0.7, -2: 0.5}

# ---- 剔除名单（机制在本引擎不可做/不值得做；均经 Gen1 identifier 核对）----
EXCLUDE_IDENTS = {
    # 复杂状态栈/随机池：
    "transform","metronome","mimic","substitute","mirror-move","disable",
    "conversion","conversion-2","sleep-talk","sketch","reflect-type",
    # 反击/固定反伤/清场（引擎无对应机制）：
    "counter","seismic-toss","night-shade","flail","bide","haze","mist",
    # 束缚多回合锁定：
    "bind","wrap","fire-spin","clamp","whirlpool",
    # 两回合蓄力/多次攻击特殊机制：
    "dig","fly","sky-attack","fury-attack","twineedle","skull-bash",
    # 无战斗价值/语义特殊：
    "splash","struggle","teleport","focus-energy","leech-seed","ingrain",
    "barrage","twister","camouflage","roar","whirlwind",
}
# 注：swift（必中连击）与 hyper-beam（破坏光线，皮卡丘 Lv28 招牌）不剔——
#     multi-hit 在本引擎按单段伤害结算，可接受。
# 一击必杀三招（fissure/guillotine/horn-drill）保留为 ohko 弱化版（打至1HP、命中30）

# 固定/随机伤害招 → 归一化威力（0=按变化招处理）
NORMALIZE_POWER = {
    "dragon-rage": 60, "sonic-boom": 50, "psywave": 65, "low-kick": 60,
    "hyper-fang": 70, "supersonic": 0,
}

# 特例语义改写（无视 meta 分类直接定效果）
SIMPLIFY = {
    "rest":         {"effect_type": "heal", "effect_value": 0.5},
    "soft-boiled":  {"effect_type": "heal", "effect_value": 0.5},
    "recover":      {"effect_type": "heal", "effect_value": 0.5},
    "light-screen": {"effect_type": "def_up", "effect_value": 1.5},
    "reflect":      {"effect_type": "def_up", "effect_value": 1.5},
    "flash":        {"effect_type": "def_down", "effect_value": 0.7},   # 降命中→对敌防降代偿
}


def load_veekun():
    def rd(name):
        return list(csv.DictReader(open(os.path.join(VEEKUN, name), encoding="utf-8-sig")))
    moves = {int(r["id"]): r for r in rd("moves.csv")}
    zh = {int(r["move_id"]): r["name"] for r in rd("move_names.csv") if r["local_language_id"] == "12"}
    meta = {int(r["move_id"]): r for r in rd("move_meta.csv")}
    statc = defaultdict(list)
    for r in rd("move_meta_stat_changes.csv"):
        statc[int(r["move_id"])].append((r["stat_id"], int(r["change"])))
    pkmoves = rd("pokemon_moves.csv")
    return moves, zh, meta, statc, pkmoves


def classify(mv, mm, stat_changes):
    """→ (dict, power) 或 None（剔除）。dict: effect_type/effect_value/ailment/ailment_chance"""
    ident = mv["identifier"]
    if ident in SIMPLIFY:
        out = {"effect_type": None, "effect_value": None, "ailment": None, "ailment_chance": 0}
        out.update(SIMPLIFY[ident])
        return out, 0
    out = {"effect_type": None, "effect_value": None, "ailment": None, "ailment_chance": 0}
    cat = mm["meta_category_id"]; ail = mm["meta_ailment_id"]
    chance = int(mm["ailment_chance"] or 0)
    power = int(mv["power"] or 0)
    if ident in NORMALIZE_POWER:
        power = NORMALIZE_POWER[ident]

    if power == 0:
        if cat == "1":
            if ail in AIL_CN:
                out["effect_type"] = "status_" + AIL_CN[ail]
                out["ailment"] = AIL_CN[ail]
                out["ailment_chance"] = 100
            else:
                return None
        elif cat == "2":
            done = False
            for sid, ch in stat_changes:
                if ch > 0 and sid in STAT_MAP_UP:
                    out["effect_type"] = STAT_MAP_UP[sid]
                    out["effect_value"] = MULT_UP.get(min(ch, 2), 1.5); done = True; break
                if ch < 0 and sid in STAT_MAP_DOWN:
                    out["effect_type"] = STAT_MAP_DOWN[sid]
                    out["effect_value"] = MULT_DOWN.get(max(ch, -2), 0.7); done = True; break
            if not done:
                out["effect_type"] = "def_up"; out["effect_value"] = 1.5   # 变圆/缩壳类兜底
        elif cat == "3":
            out["effect_type"] = "heal"; out["effect_value"] = 0.5
        else:
            return None
    else:
        if cat == "4":
            if ail == "-1":                       # tri-attack 随机三态
                out["ailment"] = "tri"; out["ailment_chance"] = 20
            elif ail in AIL_CN:
                out["ailment"] = AIL_CN[ail]; out["ailment_chance"] = chance
        elif cat in ("5", "6"):                   # 伤害+降档（5=毒嘶吼类按降档做）
            for sid, ch in stat_changes:
                if ch < 0 and sid in STAT_MAP_DOWN:
                    out["effect_type"] = STAT_MAP_DOWN[sid]
                    out["effect_value"] = MULT_DOWN.get(max(ch, -2), 0.7); break
        elif cat == "7":
            for sid, ch in stat_changes:
                if ch > 0 and sid in STAT_MAP_UP:
                    out["effect_type"] = STAT_MAP_UP[sid]
                    out["effect_value"] = MULT_UP.get(min(ch, 2), 1.5); break
        elif cat == "8":
            out["effect_type"] = "drain"
            out["effect_value"] = (int(mm["drain"] or 0) or 50) / 100.0
        elif cat == "9":
            out["effect_type"] = "ohko"
        # cat0/10/11/12/13 的伤害部分按纯伤害保留
    return out, power


def rhythm_of(pool, skills, lv_map, own_set):
    """原作等级驱动的节奏：
    pool: [mid...]；lv_map: {mid: 原作升级等级 或 None(TM/借招)}；own_set: 专属升级招
    → {mid: 学习等级}。前 INIT 个 Lv1；其后按段位单调分配、尽量贴近原作段位，封顶 Lv50。
    规则：排序键 = (段位, 非专属优先靠后, 名)；分配时 lv = max(上一招+1, min(段位, 保底节奏))
    ——段位靠前（原作早学）的招不会被推后，段位稀疏处自然留白。
    """
    n = len(pool)
    if n <= INIT:
        return {m: 1 for m in pool}

    def seg(m):                                   # 排序段位
        lv = lv_map.get(m)
        if lv is not None:
            return min(50, max(1, lv))
        return 10**6                              # TM/借招：原样排最后（保底节奏兜底，避免威力换算把大招压到 Lv28）

    order = sorted(pool, key=lambda m: (seg(m), 0 if m in own_set else 1, skills[m]["skill_name"]))
    assign = {}
    last = 1
    for i, m in enumerate(order):
        if i < INIT:
            lv = 1
        else:
            floor_lv = 1 + STEP * (i - INIT + 1)  # 保底节奏上限（防全挤低段）
            target = seg(m)
            lv = min(50, max(last + 1, min(target, floor_lv)))
        assign[m] = lv
        last = lv
    return assign


# 进化家族（Gen1 关都，兜底借招用）
FAM_LIST = [
    (1,2,3),(4,5,6),(7,8,9),(10,11,12),(13,14,15),(16,17,18),(19,20),(21,22),
    (23,24),(25,26),(27,28),(29,30,31),(32,33),(34,),(35,36),(37,38),(39,40),
    (41,42),(43,44,45),(46,47),(48,49),(50,51),(52,53),(54,55),(56,57),(58,59),
    (60,61,62),(63,64,65),(66,67,68),(69,70),(71,),(72,73),(74,75,76),(77,78),
    (79,80),(81,82),(83,),(84,85),(86,87),(88,89),(90,91),(92,93,94),(95,),
    (96,97),(98,99),(100,101),(102,103),(104,105),(106,),(107,),(108,),
    (109,110),(111,112),(113,),(114,115),(116,117,118),(119,),(120,121),
    (122,),(123,),(124,),(125,),(126,),(127,),(128,),(129,130),(131,),
    (132,),(133,134,135,136),(137,),(138,139),(140,141),(142,),(143,),
    (144,),(145,),(146,),(147,148,149),(150,),(151,),
]
FAM = {}
for fam in FAM_LIST:
    for n in fam:
        FAM[n] = fam


def _reconcile_trainers(conn, name2id, new_skills, zh):
    """重建后把 trainer_pokemon 的 learned/known 技能 id 映射到新 skill_base 行。
    规则：旧 id→旧名→新 id；旧招已剔除/改名丢名的，用该只当前 learnable 前4兜底。"""
    import json as _json
    name_by_oldid = {}
    for r in conn.execute("SELECT id, skill_name FROM skill_base"):
        name_by_oldid[r["id"]] = r["skill_name"]
    learn_by_no = {}
    for r in conn.execute("SELECT pokedex_no, skill_id, learn_level FROM pokemon_skill_learn"):
        learn_by_no.setdefault(r["pokedex_no"], []).append((r["skill_id"], r["learn_level"]))
    for r in conn.execute("SELECT id, pokedex_no, level, learned_skill_json, known_skill_json "
                          "FROM trainer_pokemon").fetchall():
        def remap(js):
            ids = _json.loads(js or "[]")
            out = []
            for sid in ids:
                nm = name_by_oldid.get(sid)
                nid = name2id.get(nm) if nm else None
                if nid and nid not in out:
                    out.append(nid)
            return out
        learned = remap(r["learned_skill_json"])
        known = remap(r["known_skill_json"])
        pool = sorted(learn_by_no.get(r["pokedex_no"], []), key=lambda x: -x[1])
        if not known:
            known = [sid for sid, lv in pool if lv <= r["level"]][:8]
        if not learned:
            learned = [sid for sid, lv in pool if lv <= r["level"]][:4]
        learned = learned[:4]
        learned = [m for m in learned if m in known] or known[:1]
        conn.execute("UPDATE trainer_pokemon SET learned_skill_json=?, known_skill_json=? WHERE id=?",
                     (_json.dumps(learned), _json.dumps(known), r["id"]))


def build(apply=False, verbose=True):
    moves, zh, meta, statc, pkmoves = load_veekun()

    # ========== 1. skill_base ==========
    new_skills = {}
    for mid, mv in moves.items():
        if mv["generation_id"] != "1" or mv["identifier"] in EXCLUDE_IDENTS:
            continue
        mm = meta.get(mid)
        if not mm:
            continue
        r = classify(mv, mm, statc.get(mid, []))
        if r is None:
            continue
        cls, power = r
        acc = int(mv["accuracy"]) if mv["accuracy"] not in ("", None) else 100
        if cls["effect_type"] == "ohko":
            acc = 30
        if mv["identifier"] == "sonic-boom":
            acc = 90
        new_skills[mid] = {
            "skill_name": zh.get(mid, mv["identifier"]),
            "skill_type": TYPE_ID2CN.get(mv["type_id"], "一般"),
            "power": power,
            "accuracy": acc,
            "effect_type": cls["effect_type"],
            "effect_value": cls.get("effect_value"),
            "ailment": cls.get("ailment"),
            "ailment_chance": cls.get("ailment_chance") or 0,
        }

    # ========== 2. 学习表 ==========
    learn = defaultdict(dict)          # no -> {mid: 原作等级}
    tms = defaultdict(set)             # no -> {mid}
    for r in pkmoves:
        vg = r["version_group_id"]
        if vg not in GEN1_VG:
            continue
        no = int(r["pokemon_id"])
        if not (1 <= no <= 151):
            continue
        mid = int(r["move_id"])
        if mid not in new_skills:
            continue
        if r["pokemon_move_method_id"] == "1":
            if int(r["level"] or 0) > 0:
                cur = learn[no].get(mid)
                if vg == "1":
                    learn[no][mid] = int(r["level"])
                elif cur is None:
                    learn[no][mid] = int(r["level"])
        elif r["pokemon_move_method_id"] == "4":
            # TM 池只认红/蓝(vg1/2)——yellow(vg3) 的 method=4 大量是 Gen2 新 TM，会污染
            if vg in ("1", "2"):
                tms[no].add(mid)

    conn = sqlite3.connect(DBFILE)
    conn.row_factory = sqlite3.Row
    pkm_type = {r["pokedex_no"]: [r["type1"] or "", r["type2"] or ""]
                for r in conn.execute("SELECT pokedex_no, type1, type2 FROM pokemon_base")}

    def own_tm_pool(no):                          # TM 跨属性清洗：本属性→一般→其余，cap 截断
        tm_in = set(tms[no]) - set(learn[no])
        mytypes = {t for t in pkm_type.get(no, []) if t}
        order = sorted(tm_in, key=lambda m: (
            0 if new_skills[m]["skill_type"] in mytypes
            else 1 if new_skills[m]["skill_type"] == "一般" else 2,
            -new_skills[m]["power"], new_skills[m]["skill_name"]))
        return order[:TM_CAP]

    rhythm = {}
    for no in range(1, 152):
        if no == 25:
            continue                              # 皮卡丘单独处理
        lv_map = dict(learn[no])
        for m in own_tm_pool(no):
            lv_map[m] = None
        if len(lv_map) < MIN_TOTAL:               # 家族借招（同样跨属性清洗）
            fam = FAM.get(no, (no,))
            own_in = set(learn[no]) | set(lv_map)
            borrow = {}
            for f in fam:
                if f == no:
                    continue
                for m, lv in learn[f].items():
                    borrow.setdefault(m, lv)
                for m in own_tm_pool(f):
                    borrow.setdefault(m, None)
            fam_ok = [m for m in borrow
                      if m not in lv_map and new_skills[m]["skill_type"] == "一般"
                      or (m not in lv_map and new_skills[m]["skill_type"]
                          in {t for t in pkm_type.get(no, []) if t})]
            for m, v in sorted(((m, borrow[m]) for m in fam_ok),
                               key=lambda x: (x[1] if x[1] is not None else 99,
                                              new_skills[x[0]]["power"])):
                if len(lv_map) >= MIN_TOTAL:
                    break
                lv_map[m] = v
        if len(lv_map) < MIN_TOTAL:               # 二次兜底：同属性普通招池（威力升序）
            mytypes = [TYPE_ID2CN.get(t, t) for t in pkm_type.get(no, []) if t]
            pool2 = sorted((m for m, s2 in new_skills.items()
                            if s2["skill_type"] in mytypes and m not in lv_map),
                           key=lambda m: new_skills[m]["power"])
            for m in pool2:
                if len(lv_map) >= MIN_TOTAL:
                    break
                lv_map[m] = None
        if not lv_map:
            continue
        rhythm[no] = rhythm_of(list(lv_map), new_skills, lv_map, set(learn[no]))

    # ---- 皮卡丘：并入雷丘池；Lv1=摇尾巴/叫声；破坏光线 Lv28 ----
    lv_map = dict(learn[25])
    for m, lv in learn[26].items():
        lv_map.setdefault(m, lv)
    tm_extra = ((set(tms[25]) | set(tms[26])) - set(lv_map)) | {63}   # 63=破坏光线（冻结规则：雷丘池并入必含）
    hb = 63
    own25 = set(learn[25]) | set(learn[26])
    for m in tm_extra:
        lv_map[m] = None
    assign = rhythm_of(list(lv_map), new_skills, lv_map, own25)
    for m in lv_map:
        if new_skills[m]["skill_name"] in ("摇尾巴", "叫声"):
            assign[m] = 1
    # 破坏光线后所有招整体后移一位，为 Lv28 腾挪空位；保序且封顶50
    for m in list(assign):
        if m != hb and assign[m] >= 28:
            assign[m] = min(50, assign[m] + 1)
    assign[hb] = 28
    rhythm[25] = assign
    assert rhythm[25][hb] == 28

    # ========== 3. 落库 ==========
    assert len(new_skills) == 130, f"实装招数应为130，当前 {len(new_skills)}"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(skill_base)")}
    if apply and "ailment" not in cols:
        raise SystemExit("skill_base 缺 ailment 列，请先运行 migrate_v3.py")
    if apply:
        # 先清引用再重建：技能名改名会让存量学习表行悬空，学习表反正整表重建；
        # trainer 身上记的技能 id 由收尾 reconcile_learned 对齐到新行。
        conn.execute("DELETE FROM pokemon_skill_learn")
    old_ids = {r["skill_name"]: r["id"] for r in conn.execute("SELECT id, skill_name FROM skill_base")}
    inserted = updated = 0
    name2id = dict(old_ids)
    renames = []                                   # 旧id -> 新行（旧行将被删）
    for mid, s in sorted(new_skills.items(), key=lambda x: x[1]["skill_name"]):
        if s["skill_name"] in old_ids:
            sid = old_ids[s["skill_name"]]; updated += 1
            if apply:
                conn.execute("UPDATE skill_base SET skill_type=?,power=?,accuracy=?,effect_type=?,"
                             "effect_value=?,ailment=?,ailment_chance=? WHERE id=?",
                             (s["skill_type"], s["power"], s["accuracy"], s["effect_type"],
                              s["effect_value"], s["ailment"], s["ailment_chance"], sid))
        else:
            inserted += 1
            if apply:
                cur = conn.execute("INSERT INTO skill_base(skill_name,skill_type,power,accuracy,"
                                   "effect_type,effect_value,ailment,ailment_chance) VALUES(?,?,?,?,?,?,?,?)",
                                   (s["skill_name"], s["skill_type"], s["power"], s["accuracy"],
                                    s["effect_type"], s["effect_value"], s["ailment"], s["ailment_chance"]))
                name2id[s["skill_name"]] = cur.lastrowid
    # 清掉本轮未复用的旧行（改名的招/历史孤儿）：学习表整表重建后这些行不再被引用。
    # 注意顺序：学习表此时为空（apply 时已 DELETE），孤儿判定仅针对未实装/改名的残留。
    keep_ids = set(name2id.values())
    stale = [r["id"] for r in conn.execute("SELECT id FROM skill_base") if r["id"] not in keep_ids]
    if apply and stale:
        conn.executemany("DELETE FROM skill_base WHERE id=?", [(i,) for i in stale])
        renames = stale
    rows = []
    for no, assign in sorted(rhythm.items()):
        for mid, lv in sorted(assign.items(), key=lambda x: (x[1], new_skills[x[0]]["skill_name"])):
            sid = name2id.get(new_skills[mid]["skill_name"])
            if sid:
                rows.append((no, sid, lv))
    rows = list(dict.fromkeys(rows))              # 同只同招去重（保险）
    if apply:
        conn.executemany("INSERT INTO pokemon_skill_learn(pokedex_no,skill_id,learn_level) VALUES(?,?,?)", rows)
        # 落库后清孤儿：按「未被学习表引用」判定（学习表已整表重建为本轮实装招）。
        # 不能按"是否在本轮 name2id"判定——旧版脚本（无剔除名单）跑出的残留行虽在本轮
        # name2id 之外的名字集里匹配不到，但若其名字恰好仍出现在本轮更新集会被漏删，
        # 历史上导致 ECS 残留 飞翔/乱击/挖洞/火箭头锤/投球/挣扎 6 行（136≠130）。
        orphan = [r["id"] for r in conn.execute(
            "SELECT id FROM skill_base WHERE id NOT IN "
            "(SELECT DISTINCT skill_id FROM pokemon_skill_learn)")]
        if orphan:
            conn.executemany("DELETE FROM skill_base WHERE id=?", [(i,) for i in orphan])
            print(f"清理孤儿技能行: {len(orphan)}")
        # trainer 身上的技能 id 对齐：v2 旧 id 若本轮改名换了新行，映射到新 id；
        # 无法映射的（招被剔除）直接丢弃，随后由 ensure_known 兜底重排
        if renames:
            _reconcile_trainers(conn, name2id, new_skills, zh)
        conn.commit()

    # ========== 4. 报告 ==========
    if verbose:
        per = {no: len(a) for no, a in rhythm.items()}
        type_cov = defaultdict(int)
        for s in new_skills.values():
            type_cov[s["skill_type"]] += 1
        print(f"实装招式: {len(new_skills)}（原作165剔 {165 - len(new_skills)}） 新增{inserted} 更新{updated}")
        print(f"学习表条目: {len(rows)} 覆盖 {len(per)}/151  "
              f"每只 min={min(per.values())} max={max(per.values())} avg={sum(per.values())/len(per):.1f}")
        print("属性覆盖:", dict(sorted(type_cov.items(), key=lambda x: -x[1])))
        st = sum(1 for s in new_skills.values() if s["ailment"])
        chg = sum(1 for s in new_skills.values() if s["power"] == 0)
        print(f"带附加异常攻击招: {st}  变化招: {chg}")
        pika = sorted((lv, new_skills[m]["skill_name"]) for m, lv in rhythm[25].items())
        print("皮卡丘节奏:", pika)
        for t in ("火", "电", "幽灵", "冰", "龙", "超能力"):
            lst = [s["skill_name"] for s in new_skills.values() if s["skill_type"] == t and s["power"] > 0]
            print(f"  {t}系攻击招({len(lst)}): {'、'.join(lst[:14])}")
    conn.close()
    return len(new_skills), len(rows)


if __name__ == "__main__":
    build(apply=os.environ.get("PKM_APPLY", "0") == "1")
