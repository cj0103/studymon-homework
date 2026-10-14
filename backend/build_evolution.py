# -*- coding: utf-8 -*-
"""建立 Gen1 进化链表 pkm_evolution：from_no → to_no @ min_level。

进化链(from→to 结构)取自 veekun pokemon_species.csv(evolves_from_species_id)；
进化等级用 Gen1 原作内置表（把进化石/亲密度/通信统一折算成等级，规则简单）。
到级自动进化；进化后保留已学技能并并入新形态到级技能。幂等：DROP 重建。
"""
import os
import csv
import sqlite3
from app.db import DBFILE

VEEKUN = os.environ.get("PKM_VEEKUN",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "veekun-csv")))

# Gen1 进化等级（原作为主；进化石/亲密度/通信统一折算为等级）
# key = 进化前的 dex 号
EVO_LEVEL = {
    1: 16, 2: 32,            # 妙蛙种子/月桂
    4: 16, 5: 36,            # 小火龙/火恐龙
    7: 16, 8: 36,            # 杰尼龟/卡咪龟
    10: 7, 11: 10,           # 绿毛虫/铁甲蛹
    13: 7, 14: 10,           # 独角虫/铁壳蛹
    16: 9, 17: 18,           # 波波/比比鸟
    19: 18,                  # 小拉达
    21: 18,                  # 烈雀
    23: 24,                  # 阿柏蛇
    25: 22,                  # 皮卡丘(原石→22级)
    27: 22,                  # 穿山鼠
    29: 24, 30: 26,          # 尼多兰/尼多娜
    32: 24, 33: 26,          # 尼多朗/尼多力诺
    35: 24,                  # 皮宝宝→皮皮(石→24)
    37: 26,                  # 六尾
    39: 28,                  # 胖丁
    41: 22,                  # 超音蝠
    43: 21,                  # 走路草
    46: 24,                  # 派拉斯
    48: 31,                  # 毛球
    50: 26,                  # 地鼠
    52: 26,                  # 喵喵
    54: 28,                  # 可达鸭
    56: 28,                  # 猴怪
    58: 36,                  # 卡蒂狗(石→36)
    60: 25, 61: 36,          # 蚊香蝌蚪/蚊香蛙
    63: 15, 64: 36,          # 凯西/勇基拉
    66: 28, 67: 36,          # 腕力/豪力
    69: 21,                  # 喇叭芽
    72: 30,                  # 玛瑙水母
    74: 25, 75: 36,          # 小拳石/隆隆石
    77: 36,                  # 小火马
    79: 28,                  # 呆呆兽
    81: 30,                  # 小磁怪(石→30)
    84: 14,                  # 嘟嘟
    86: 18,                  # 多多伊
    88: 26,                  # 臭泥
    90: 30,                  # 大舌贝(石→30)
    92: 36,                  # 鬼斯
    95: 36,                  # 大岩蛇(石→36)
    96: 28,                  # 素利普
    98: 28,                  # 大钳蟹
    100: 30,                 # 音波幼虫(石→30)
    102: 28,                 # 蛋蛋
    104: 28,                 # 卡拉卡拉
    108: 26,                 # 大舌头
    109: 30,                 # 瓦斯弹
    111: 42,                 # 独角犀牛
    113: 36,                 # 卡比兽(亲密度→36)
    114: 36,                 # 蔓藤怪(亲密度→36)
    116: 32,                 # 墨海马
    118: 32,                 # 角金鱼
    120: 30,                 # 海星(石→30)
    123: 28,                 # 飞天螳螂(石→28)
    125: 30,                 # 电击兽(石→30)
    126: 30,                 # 鸭嘴火兽(石→30)
    128: 28,                 # 肯泰罗
    129: 32,                 # 鲤鱼王
    131: 36,                 # 迷你龙
    132: 20,                 # 百变怪(无进化，占位忽略)
    137: 36,                 # 多边兽(石→36)
    142: 36,                 # 化石翼龙(无进化，占位忽略)
    147: 30, 148: 55,        # 迷你龙/哈克龙
    165: 36,                 # 芭瓢虫
    167: 22,                 # 圆丝蛛
    170: 31,                 # 灯笼鱼
}


# 新手礼"不进化伙伴"（原作皮卡丘拒进化的浪漫）：这些 dex 号永不进化。
# 皮卡丘(25) 作为开档礼赠 → 从进化链剔除；雷丘(26) 改为只能野外捕捉获得。
STARTERS_NO_EVO = {25}

# Gen1 进化链 from_no → to_no（内嵌，离线可用；已过滤掉二世代宝宝与伊布分支）
# 伊布(133)一对三需进化石，此处不自动进化，保留特殊感。
CHAIN = {
    1: 2, 2: 3, 4: 5, 5: 6, 7: 8, 8: 9, 10: 11, 11: 12, 13: 14, 14: 15,
    16: 17, 17: 18, 19: 20, 21: 22, 23: 24, 27: 28, 29: 30, 30: 31,
    32: 33, 33: 34, 35: 36, 37: 38, 39: 40, 41: 42, 43: 44, 44: 45, 46: 47,
    48: 49, 50: 51, 52: 53, 54: 55, 56: 57, 58: 59, 60: 61, 61: 62, 63: 64,
    64: 65, 66: 67, 67: 68, 69: 70, 70: 71, 72: 73, 74: 75, 75: 76, 77: 78,
    79: 80, 81: 82, 84: 85, 86: 87, 88: 89, 90: 91, 92: 93, 93: 94, 96: 97,
    98: 99, 100: 101, 102: 103, 104: 105, 109: 110, 111: 112, 116: 117,
    118: 119, 120: 121, 129: 130, 138: 139, 140: 141, 147: 148, 148: 149,
}


def build(dbfile=DBFILE, veekun=VEEKUN, apply=True):
    # 进化链 from→to：优先内嵌；若本地有 veekun 则以 veekun 为准（更权威）
    chain = dict(CHAIN)
    sp = os.path.join(veekun, "pokemon_species.csv")
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                frm = row.get("evolves_from_species_id") or ""
                if not frm or frm == "\\N":
                    continue
                to_no, from_no = int(row["id"]), int(frm)
                if 1 <= to_no <= 151 and 1 <= from_no <= 151:
                    chain[from_no] = to_no
    # 排除伊布一对三分支（133→134/135/136）：保留进化链里最后写入的会误进化，强制移除
    chain.pop(133, None)
    # 新手礼不进化伙伴（皮卡丘）：veekun 覆盖路径也要强制剔除
    for no in STARTERS_NO_EVO:
        chain.pop(no, None)

    # 本地中文名
    c = sqlite3.connect(dbfile)
    c.row_factory = sqlite3.Row
    name = {r["pokedex_no"]: r["name"] for r in
            c.execute("SELECT pokedex_no,name FROM pokemon_base")}
    c.execute("DROP TABLE IF EXISTS pkm_evolution")
    c.execute("""CREATE TABLE pkm_evolution(
        from_no INTEGER PRIMARY KEY, to_no INTEGER, min_level INTEGER)""")
    n = 0
    for from_no, to_no in sorted(chain.items()):
        lv = EVO_LEVEL.get(from_no)
        if lv is None:
            lv = 32  # 兜底：未在表中的用 32 级
        c.execute("INSERT OR REPLACE INTO pkm_evolution VALUES(?,?,?)",
                  (from_no, to_no, lv))
        n += 1
    # 新手礼配置（每孩子一只）：皮卡丘·不进化伙伴。init_db/_seed 与 reset_game 消费。
    c.execute("DROP TABLE IF EXISTS pkm_starters")
    c.execute("""CREATE TABLE pkm_starters(
        pokedex_no INTEGER PRIMARY KEY, note TEXT)""")
    for no in sorted(STARTERS_NO_EVO):
        nm = name.get(no, f"#{no}")
        c.execute("INSERT OR REPLACE INTO pkm_starters VALUES(?,?)",
                  (no, f"{nm}（不进化伙伴·开档礼赠）"))
    if apply:
        c.commit()
    c.close()
    return n


if __name__ == "__main__":
    n = build(apply=(os.environ.get("PKM_APPLY", "1") == "1"))
    print(f"进化链生成完成：{n} 条进化关系")
