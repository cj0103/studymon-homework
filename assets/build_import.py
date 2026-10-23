# -*- coding: utf-8 -*-
"""
阶段1 数据清洗：veekun CSV → 项目 MySQL 导入 SQL
产出 out/:
  01_pokemon_base.sql        1-151（4战斗属性，去Special，含中文名/经验组）
  02_skill_base.sql          Gen1 白名单招式（纯伤害+攻防buff，简体中文名：veekun繁中+OpenCC简转）
  03_pokemon_skill_learn.sql 升级学招（红蓝黄合并去重）
  04_type_effect.sql         Gen1 属性克制（仅非1.0行）
  05_level_exp_table.sql     Lv1-50 三组经验公式
  06a_region_base.sql / 06b_gym_base.sql  区域道馆骨架
  dropped_moves_review.txt   被过滤招式清单（人工复核）
"""
import csv, os, collections

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "out")
os.makedirs(OUT, exist_ok=True)

def rd(name):
    return list(csv.DictReader(open(os.path.join(BASE, "veekun-csv", name), encoding="utf-8")))

def esc(s):
    return s.replace("\\", "\\\\").replace("'", "''")

def write_sql(fname, header, rows, stmt):
    with open(os.path.join(OUT, fname), "w", encoding="utf-8") as f:
        f.write(f"-- {header}\nSET NAMES utf8mb4;\n")
        if rows:
            f.write(stmt + "\n" + ",\n".join(f"({v})" for v in rows) + ";\n")
    print(f"  out/{fname}: {len(rows)} rows")

# ---------- 中文名对照 ----------
POKEMON_CN = {1:"妙蛙种子",2:"妙蛙草",3:"妙蛙花",4:"小火龙",5:"火恐龙",6:"喷火龙",7:"杰尼龟",8:"卡咪龟",9:"水箭龟",10:"绿毛虫",11:"铁甲蛹",12:"巴大蝶",13:"独角虫",14:"铁壳蛹",15:"大针蜂",16:"波波",17:"比比鸟",18:"大比鸟",19:"小拉达",20:"拉达",21:"烈雀",22:"大嘴雀",23:"阿柏蛇",24:"阿柏怪",25:"皮卡丘",26:"雷丘",27:"穿山鼠",28:"穿山王",29:"尼多兰",30:"尼多娜",31:"尼多后",32:"尼多朗",33:"尼多力诺",34:"尼多王",35:"皮皮",36:"皮可西",37:"六尾",38:"九尾",39:"胖丁",40:"胖可丁",41:"超音蝠",42:"大嘴蝠",43:"走路草",44:"臭臭花",45:"霸王花",46:"派拉斯",47:"派拉斯特",48:"毛球",49:"摩鲁蛾",50:"地鼠",51:"三地鼠",52:"喵喵",53:"猫老大",54:"可达鸭",55:"哥达鸭",56:"猴怪",57:"火暴猴",58:"卡蒂狗",59:"风速狗",60:"蚊香蝌蚪",61:"蚊香君",62:"蚊香泳士",63:"凯西",64:"勇基拉",65:"胡地",66:"腕力",67:"豪力",68:"怪力",69:"喇叭芽",70:"口呆花",71:"大食花",72:"玛瑙水母",73:"毒刺水母",74:"小拳石",75:"隆隆石",76:"隆隆岩",77:"小火马",78:"烈焰马",79:"呆呆兽",80:"呆壳兽",81:"小磁怪",82:"三合一磁怪",83:"大葱鸭",84:"嘟嘟",85:"嘟嘟利",86:"小海狮",87:"白海狮",88:"臭泥",89:"臭臭泥",90:"大舌贝",91:"刺甲贝",92:"鬼斯",93:"鬼斯通",94:"耿鬼",95:"大岩蛇",96:"催眠貘",97:"引梦貘人",98:"大钳蟹",99:"巨钳蟹",100:"霹雳电球",101:"顽皮雷弹",102:"蛋蛋",103:"椰蛋树",104:"卡拉卡拉",105:"嘎啦嘎啦",106:"飞腿郎",107:"快拳郎",108:"大舌头",109:"瓦斯弹",110:"双弹瓦斯",111:"独角犀牛",112:"钻角犀兽",113:"吉利蛋",114:"蔓藤怪",115:"袋兽",116:"墨海马",117:"海刺龙",118:"角金鱼",119:"金鱼王",120:"海星星",121:"宝石海星",122:"魔墙人偶",123:"飞天螳螂",124:"迷唇姐",125:"电击兽",126:"鸭嘴火兽",127:"凯罗斯",128:"肯泰罗",129:"鲤鱼王",130:"暴鲤龙",131:"拉普拉斯",132:"百变怪",133:"伊布",134:"水伊布",135:"雷伊布",136:"火伊布",137:"多边兽",138:"菊石兽",139:"多刺菊石兽",140:"化石盔",141:"镰刀盔",142:"化石翼龙",143:"卡比兽",144:"急冻鸟",145:"闪电鸟",146:"火焰鸟",147:"迷你龙",148:"哈克龙",149:"快龙",150:"超梦",151:"梦幻"}

TYPE_CN = {1:"一般",2:"格斗",3:"飞行",4:"毒",5:"地面",6:"岩石",7:"虫",8:"幽灵",
           10:"火",11:"水",12:"草",13:"电",14:"超能力",15:"冰",16:"龙"}
GEN1_TYPE_IDS = list(TYPE_CN.keys())
# 现代数据集回溯修正：皮皮/皮可西=妖精(Gen1应一般)、胖丁/胖可丁=一般+妖精(Gen1纯一般)、魔墙人偶=超+妖精(Gen1纯超)
TYPE_OVERRIDE = {35:{1:1},36:{1:1},39:{2:None},40:{2:None},122:{2:None}}

def gen1_types(pid):
    """返回 Gen1 有效属性槽 {slot:type_id}；type_id=9(未知)直接剔除"""
    t = {s: v for s, v in pk_types[pid].items() if v != 9}
    for slot, tv in TYPE_OVERRIDE.get(pid, {}).items():
        if tv is None: t.pop(slot, None)
        else: t[slot] = tv
    # 规范化槽位为 1/(2)
    vals = [t[k] for k in sorted(t)]
    return {1: vals[0], **({2: vals[1]} if len(vals) > 1 else {})}

# ---------- 载入 ----------
pokemon = {r["id"]: r for r in rd("pokemon.csv")}
species = {r["id"]: r for r in rd("pokemon_species.csv")}
growth_rate_identifier = {r["id"]: r["identifier"] for r in rd("growth_rates.csv")}
moves = rd("moves.csv")
move_en = {r["move_id"]: r["name"] for r in rd("move_names.csv") if r["local_language_id"] == "9"}
# 中文招式名：veekun zh-Hant(语言id=4) + OpenCC 繁转简（覆盖全部 Gen1 招式，个别用词差异可接受）
try:
    from opencc import OpenCC
    _cc = OpenCC("t2s")
    move_cn = {r["move_id"]: _cc.convert(r["name"]) for r in rd("move_names.csv") if r["local_language_id"] == "4"}
except ImportError:
    move_cn = {}
meta = {r["move_id"]: r for r in rd("move_meta.csv")}
sc = collections.defaultdict(list)
for r in rd("move_meta_stat_changes.csv"):
    sc[r["move_id"]].append((int(r["stat_id"]), int(r["change"])))

base_stats = collections.defaultdict(dict)
for r in rd("pokemon_stats.csv"):
    pid = int(r["pokemon_id"])
    if 1 <= pid <= 151: base_stats[pid][int(r["stat_id"])] = int(r["base_stat"])
pk_types = collections.defaultdict(dict)
for r in rd("pokemon_types.csv"):
    pid = int(r["pokemon_id"])
    if 1 <= pid <= 151: pk_types[pid][int(r["slot"])] = int(r["type_id"])

# ---------- 1. pokemon_base ----------
GR_MAP = {"fast": "fast", "medium": "medium", "slow": "slow",
          "medium-slow": "slow", "slow-then-very-fast": "slow", "fast-then-very-slow": "fast"}
rows = []
for pid in range(1, 152):
    p = pokemon[str(pid)]
    sp = species[p["species_id"]]
    bs = base_stats[pid]
    t = gen1_types(pid)
    gr = GR_MAP[growth_rate_identifier[sp["growth_rate_id"]]]
    t2 = f"'{TYPE_CN[t[2]]}'" if 2 in t else "NULL"
    rows.append(f"{pid},'{POKEMON_CN[pid]}','{TYPE_CN[t[1]]}',{t2},'{gr}',{bs[1]},{bs[2]},{bs[3]},{bs[4]}")
write_sql("01_pokemon_base.sql", "宝可梦基础表 Gen1 1-151（4战斗属性去Special）", rows,
    "INSERT INTO pokemon_base (pokedex_no,name,type1,type2,exp_group,base_hp,base_atk,base_def,base_speed) VALUES")

# ---------- 2. skill_base 白名单 ----------
# 保留：A 纯伤害(power>0, 无异常/吸血/反伤/暴击加成/畏缩)
#       —— 附带 sp/速度效果者因项目已去 Special/速度buff，效果落空，按纯伤害保留
#       B 纯辅助且 stat 变化仅含 atk/def → atk_up/def_up/atk_down/def_down（倍率 1.5/2.0/0.67/0.5）
# 丢弃：异常状态、吸血反伤、暴击加成、畏缩、束缚、速度/命中/闪避buff、回复、瞬移等
KEEP, DROP = [], []
for m in moves:
    if m["generation_id"] != "1": continue
    mid, ident = m["id"], m["identifier"]
    mt = meta.get(mid)
    name = move_cn.get(mid) or move_en.get(mid, ident)
    power = int(m["power"] or 0)
    acc = int(float(m["accuracy"] or 100))
    if mt is None:
        DROP.append((ident, "no-meta")); continue
    ail, drain = mt["meta_ailment_id"], mt["drain"]
    crit, flinch = mt["crit_rate"], mt["flinch_chance"]
    if ail not in ("0", "-1") or drain not in ("0", "") or crit not in ("0", "") or flinch not in ("0", ""):
        DROP.append((ident, "status/drain/crit/flinch")); continue
    st = sc.get(mid, [])
    ad = [(s, c) for s, c in st if s in (2, 3)]
    other = [(s, c) for s, c in st if s not in (2, 3)]
    if power > 0:
        KEEP.append((mid, name, TYPE_CN.get(int(m["type_id"]), "一般"), power, acc, "None", "NULL"))
    else:
        if other:
            DROP.append((ident, f"aux other-stat {other}")); continue
        if not ad:
            DROP.append((ident, "aux no-stat-effect")); continue
        s, c = ad[0]  # Growth(+攻+速)只留攻
        eff = {(2, 1): "atk_up", (2, 2): "atk_up", (3, 1): "def_up", (3, 2): "def_up",
               (2, -1): "atk_down", (2, -2): "atk_down", (3, -1): "def_down", (3, -2): "def_down"}[(s, max(-2, min(2, c)))]
        mult = {1: "1.5", 2: "2.0", -1: "0.7", -2: "0.5"}[c]
        KEEP.append((mid, name, TYPE_CN.get(int(m["type_id"]), "一般"), 0, acc, eff, mult))

with open(os.path.join(OUT, "dropped_moves_review.txt"), "w", encoding="utf-8") as f:
    for ident, why in DROP:
        f.write(f"{ident}\t{why}\n")
rows = [f"{mid},'{esc(name)}','{t}',{p},{a}," + (f"'{e}',{v}" if e != "None" else "NULL,NULL")
        for mid, name, t, p, a, e, v in KEEP]
write_sql("02_skill_base.sql", f"Gen1白名单招式 keep={len(KEEP)}（简体中文名，veekun繁中经OpenCC t2s转换）", rows,
    "INSERT INTO skill_base (id,skill_name,skill_type,power,accuracy,effect_type,effect_value) VALUES")

# ---------- 3. 招式学习池（升级 + TM，保证每只宝可梦可用招式充足）----------
# 校验发现：仅保留"升级学招"会导致 6 只宝可梦（独角虫/凯西/鬼斯三家/百变怪）Lv50 内
# 完全无白名单招式，另有 87 只不足 4 招。修复：学习表扩展 TM 学习途径（method=4，
# Gen1 游戏原本机制），并加 FILL 兜底保证每只 >=4 招。
# 表结构沿用 pokemon_skill_learn：learn_level=0 表示"可 TM 学习"（后端视为随时可学）。
keep_ids = {str(k[0]) for k in KEEP}                       # veekun CSV 全部是字符串，统一转 str 比较
move_type = {str(k[0]): k[2] for k in KEEP}                # 招式属性（用于补招同属性优先）
move_name = {str(k[0]): k[1] for k in KEEP}
levelup_lv, tm_map = collections.defaultdict(dict), collections.defaultdict(set)
for r in rd("pokemon_moves.csv"):
    pid = int(r["pokemon_id"])
    if not 1 <= pid <= 151: continue
    if r["version_group_id"] not in ("1", "2"): continue
    mid = r["move_id"]                                      # str
    if mid not in keep_ids: continue
    method = r["pokemon_move_method_id"]
    if method == "1":
        lv = int(r["level"] or 1)
        if mid not in levelup_lv[pid] or lv < levelup_lv[pid][mid]:
            levelup_lv[pid][mid] = lv
    elif method == "4":
        tm_map[pid].add(mid)
learn = []
for pid in range(1, 152):
    for mid, lv in sorted(levelup_lv[pid].items(), key=lambda x: (x[1], int(x[0]))):
        learn.append(f"{pid},{int(mid)},{lv}")
    for mid in sorted(tm_map[pid] - set(levelup_lv[pid]), key=int):
        learn.append(f"{pid},{int(mid)},0")          # TM：learn_level=0 表示随时可学
FILL = {144: ["98"], 145: ["89"], 146: ["57"]}        # 急冻鸟+电光一闪 闪电鸟+地震 火焰鸟+冲浪
n_fill = 0
learn_pool_fill = collections.defaultdict(list)       # pid -> [(招式id, 顺序)] 兜底补招（供馆主授予表复用）
for pid in range(1, 152):
    have = set(levelup_lv[pid]) | tm_map[pid] | set(FILL.get(pid, []))
    if len(have) >= 4: continue
    t1 = TYPE_CN[gen1_types(pid)[1]]
    EXCL = {"120", "153", "165", "132", "37", "80"}   # 排除自爆/大爆炸/挣扎/缠绕/大闹一番/花瓣舞（负面或不适合补位）
    pool = [m for m in sorted(keep_ids - have, key=int) if m not in EXCL and move_type[m] in (t1, "一般")]
    if len(pool) < 4 - len(have):                     # 同属性不足则放宽全白名单
        pool += [m for m in sorted(keep_ids - have, key=int) if m not in pool and m not in EXCL]
    for k, mid in enumerate(pool[:4 - len(have)]):
        learn.append(f"{pid},{int(mid)},0")
        learn_pool_fill[pid].append((mid, k))
        n_fill += 1
for pid, mids in FILL.items():
    for k, mid in enumerate(mids):
        learn_pool_fill[pid].append((mid, k))
print(f"  兜底补招: {n_fill} 条")
# 馆主队伍"招式授予"表：道馆战斗等级常低于技能学习等级（如勇基拉 L36 但精神强念 L38 才学），
# 若按 learn_level 过滤会出现空招招架。后端对战时馆主精灵直接使用该表的4招，不走 learn_level 过滤。
def pick4(pid, cap):
    """该精灵在 cap 等级下最优先的4招：升级招(等级达标,高级优先) → TM招 → 学习池兜底 → 无视等级的升级招"""
    learned = sorted([m for m, l in levelup_lv[pid].items() if l <= cap],
                     key=lambda m: -levelup_lv[pid][m])
    out = list(learned[:4])
    for m in sorted(tm_map[pid] - set(out), key=int):
        if len(out) >= 4: break
        out.append(m)
    for m, _ in sorted(learn_pool_fill.get(pid, []), key=lambda x: x[1]):
        if len(out) >= 4: break
        if m not in out: out.append(m)
    for m in sorted(levelup_lv[pid], key=int):        # 仍不足则无视等级取升级招
        if len(out) >= 4: break
        if m not in out: out.append(m)
    return [int(x) for x in out[:4]]
write_sql("03_pokemon_skill_learn.sql", "招式学习池（升级学招+TM(learn_level=0)+兜底补招，每只≥4）", learn,
    "INSERT INTO pokemon_skill_learn (pokedex_no,skill_id,learn_level) VALUES")

# ---------- 4. type_effect ----------
rows = []
for r in rd("type_efficacy.csv"):
    a, d, f_ = int(r["damage_type_id"]), int(r["target_type_id"]), int(r["damage_factor"])
    if a not in GEN1_TYPE_IDS or d not in GEN1_TYPE_IDS or f_ == 100: continue
    rows.append(f"'{TYPE_CN[a]}','{TYPE_CN[d]}',{f_/100:.1f}")
write_sql("04_type_effect.sql", "Gen1属性克制（仅非1.0行，缺省1.0）", rows,
    "INSERT INTO type_effect (attack_type,defend_type,rate) VALUES")

# ---------- 5. level_exp_table ----------
def exp_at(n, g):
    if g == "fast": return int(n ** 3)
    if g == "medium": return int(6/5*n**3 - 15*n**2 + 100*n - 140)
    return int(5/4 * n**3)
rows = [f"{lv},{exp_at(lv,'fast')},{exp_at(lv,'medium')},{exp_at(lv,'slow')}" for lv in range(1, 51)]
write_sql("05_level_exp_table.sql", "Lv1-50 总经验（fast=n³/medium公式/slow=5/4n³）", rows,
    "INSERT INTO level_exp_table (level,exp_fast,exp_medium,exp_slow) VALUES")

# ---------- 6. 区域 / 道馆骨架 ----------
regions = [(1,"真新镇-深灰市",0),(2,"华蓝市-枯叶市",2),(3,"玉虹市-红莲岛",4),(4,"冠军之路-石英高原",6)]
write_sql("06a_region_base.sql", "关都4区域（徽章数解锁）",
          [f"{i},'{n}',{b}" for i,n,b in regions],
          "INSERT INTO region_base (id,region_name,unlock_badge_count) VALUES")
# 初代红/绿/蓝版官方八大道馆（经 52poke + bilibili + 百度百科 三源交叉确认）：
# 顺序按游戏推荐难度推进；浅红道馆·阿桔(Gen1毒系,粉红徽章)为原版第5馆，此前草稿曾遗漏，已修正
gyms = [
    (1, "深灰道馆·小刚", 1, "灰色徽章", 16),     # 岩石 Boulder
    (2, "华蓝道馆·小霞", 2, "蓝色徽章", 19),     # 水 Cascade
    (3, "枯叶道馆·马志士", 3, "橙色徽章", 24),   # 电 Thunder
    (4, "玉虹道馆·莉佳", 4, "彩虹徽章", 28),     # 草 Rainbow
    (5, "浅红道馆·阿桔", 5, "粉红徽章", 32),     # 毒 Marsh（Gen1浅红=阿桔毒系，Gen2才归阿杏地面系）
    (6, "金黄道馆·娜姿", 6, "金色徽章", 36),     # 超能 Soul
    (7, "红莲道馆·夏伯", 7, "深红徽章", 40),     # 火 Volcano
    (8, "常磐道馆·坂木", 8, "绿色徽章", 46),     # 地面 Earth
]
write_sql("06b_gym_base.sql", "初代原版8道馆（深灰/华蓝/枯叶/玉虹/浅红/金黄/红莲/常磐）",
          [f"{i},'{n}',{s},'{b}',{lv}" for i,n,s,b,lv in gyms],
          "INSERT INTO gym_base (id,gym_name,sort,badge_name,recommend_level) VALUES")

# ---------- 6. 野生遭遇池（Gen1红蓝版 encounters.csv 实导）----------
_areas = {r["id"]: r["location_id"] for r in rd("location_areas.csv")}
_locs = {r["id"]: r["identifier"] for r in rd("locations.csv")}
location_by_area = {aid: _locs.get(lid) for aid, lid in _areas.items()}
AREA_REGION = {
    # region1 真新-深灰
    "kanto-route-1":1,"kanto-route-2":1,"viridian-forest":1,"digletts-cave":1,
    "kanto-route-3":1,"kanto-route-4":1,"mt-moon":1,"cerulean-cave":1,
    # region2 华蓝-枯叶
    "kanto-route-5":2,"kanto-route-6":2,"kanto-route-7":2,"kanto-route-8":2,
    "kanto-route-9":2,"kanto-route-10":2,"rock-tunnel":2,
    "kanto-route-11":2,"kanto-route-12":2,"kanto-route-24":2,"kanto-route-25":2,
    # region3 玉虹-红莲
    "kanto-route-13":3,"kanto-route-14":3,"kanto-route-15":3,"kanto-route-16":3,
    "kanto-route-17":3,"kanto-route-18":3,"kanto-route-19":3,"kanto-route-20":3,
    "kanto-route-21":3,"seafoam-islands":3,"powers-plant":3,
    # region4 22/23号路-冠军之路
    "kanto-route-22":4,"kanto-route-23":4,"kanto-route-26":4,"kanto-route-27":4,
    "kanto-route-28":4,"victory-road":4,
}
seen, rows = set(), []
for r in rd("encounters.csv"):
    if r["version_id"] not in ("1", "2"):      # red / blue
        continue
    if not r["pokemon_id"] or int(r["pokemon_id"]) > 151: continue
    ident = location_by_area.get(r["location_area_id"])
    reg = AREA_REGION.get(ident) if ident else None
    if reg is None: continue
    key = (reg, r["pokemon_id"], r["min_level"], r["max_level"])
    if key in seen: continue
    seen.add(key)
    rows.append(f"{reg},{r['pokemon_id']},{r['min_level']},{r['max_level']},10")
# 等级带拉伸：Gen1 遭遇等级普遍 Lv2-15，对 Lv50 上限的篇章做 ×2.2 映射，保证各区梯度
rows2 = []
for reg, pno, mn, mx, w in {tuple(v.split(",")) for v in rows}:
    mn2, mx2 = max(2, int(int(mn) * 2.2)), min(50, max(int(mx) * 2 + 2, 6))
    rows2.append(f"{reg},{pno},{mn2},{mx2},{w}")
rows2 = sorted(set(rows2), key=lambda x: (int(x.split(",")[0]), int(x.split(",")[1])))
write_sql("06c_region_wild_pokemon.sql", "野生池（红蓝版实导，等级带×2.2适配Lv50篇章）", rows2,
          "INSERT INTO region_wild_pokemon (region_id,pokedex_no,min_level,max_level,catch_weight) VALUES")

# ---------- 7. 道馆阵容（原版红绿蓝馆主精灵，等级适配Lv50篇章）----------
# 每队 ≤3 只（与玩家同规）；精灵严格按原版馆主阵容（红绿蓝版）；
# 每只精灵显式授予4招（pick4）——道馆战斗等级常低于学习等级，后端不再按 learn_level 过滤馆主招式
GYM_TEAMS = {
    1: ("小刚(岩石)", [(74,16),(95,16),(76,18)]),            # 小拳石/大岩蛇/隆隆石
    2: ("小霞(水)", [(120,19),(121,19),(118,21)]),           # 海星星/宝石海星/角金鱼
    3: ("马志士(电)", [(100,24),(25,24),(26,26)]),           # 霹雳电球/皮卡丘/雷丘
    4: ("莉佳(草)", [(45,28),(71,28),(103,30)]),             # 霸王花/大食花/椰蛋树
    5: ("阿桔(毒)", [(109,32),(88,32),(110,34)]),            # 瓦斯弹/臭臭泥/双弹瓦斯
    6: ("娜姿(超能)", [(64,36),(122,36),(65,38)]),           # 勇基拉/魔墙人偶/胡地
    7: ("夏伯(火)", [(58,40),(77,40),(78,42)]),              # 卡蒂狗/小火马/烈焰马
    8: ("坂木(地面)", [(112,44),(51,44),(31,46)]),           # 铁甲犀牛/三地鼠/尼多后
}
import json
gym_team_rows = []
for gid, entry in GYM_TEAMS.items():
    leader, team = entry if isinstance(entry, tuple) else (entry[0], entry[1])
    payload = json.dumps([{"pokedex_no": p, "level": lv, "moves": pick4(p, lv)} for p, lv in team], ensure_ascii=False)
    gym_team_rows.append(f"{gid},'{esc(payload)}'")
write_sql("06d_gym_trainer_team.sql", "道馆阵容（原版精灵+显式授予4招，≤3只/队）", gym_team_rows,
          "INSERT INTO gym_trainer_team (gym_id,pokemon_json) VALUES")

print(f"\nkeep={len(KEEP)} drop={len(DROP)} learn={len(learn)}  ALL DONE")
