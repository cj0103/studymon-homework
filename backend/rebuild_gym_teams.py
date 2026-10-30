# -*- coding: utf-8 -*-
"""重建道馆阵容（v3 野生池配套）：野生池剔除的进化终点改由道馆教练阵容展示，
"野生抓不到、道馆看得到"——补回原作图鉴感。

规则（用户确认名单 + 难度阶梯）：
- 方案C 定稿：**前 3 馆每馆 3 只、后 5 馆每馆 4 只**——馆主带队数随徽章
  增长有成长感（孩子验收反馈"第一道馆怎么有第四只"，家长拍板前期削编）；
  阵容 = 馆主招牌（原作标志怪）+ 主题怪 + "进化终点展示怪"
  （从被剔出野生池的终点里挑，与主题/地域契合）；
- 方案C 删编三刀：1 馆删钻角犀兽(独角犀牛线区5才遇到，首馆看不懂来路)、
  2 馆删胖可丁(一般系与水主题无关的凑数怪)、3 馆删皮卡丘
  (开档礼赠"不进化伙伴"专属，馆队再放口径撞车)；
- 等级 = gym_base.recommend_level 为基准（主力 Lv、王牌 +2），保证单调；
- 招式不带 moves 字段 → battle._gym_team 现算 learnable(pokedex_no, level) 末4招，
  与 rebuild_gyms_v3.py 的选招策略解耦（那条链路仍可用于显式覆写）。
断言：展示怪全部不在野生池（避免"野生能抓+馆主又用"的口径混乱）；
     主力/招牌若在野生池（如坂木三地鼠线）则必须已是未进化/中间形态合规怪。
用法: python rebuild_gym_teams.py           # 干跑
      PKM_APPLY=1 python rebuild_gym_teams.py
"""
import json
import os
import sqlite3

DBFILE = os.environ.get("PKM_SQLITE_FILE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "pkm.sqlite3")))

# gym sort → 阵容 [(pokedex_no, level_offset, 说明), ...]
# 展示怪=被 v3 野生池剔除的进化终点；(括号内为原作出处/昵称梗)
GYM_TEAMS = {
    1: [  # 深灰·小刚 岩石（方案C：删钻角犀兽→3只）
        (95,  0, "大岩蛇(原作招牌,野生池区8合规)"),
        (75,  0, "隆隆石(中间态,野生区6合规)"),
        (76,  2, "隆隆岩(展示怪:小拳石线终点)"),
    ],
    2: [  # 华蓝·小霞 水（方案C：删胖可丁→3只）
        (121, 0, "宝石海星(展示怪:海星星线终点)"),
        (117, 0, "海刺龙(中间态,野生池外→展示)"),
        (91,  0, "刺甲贝(展示怪:大舌贝线终点)"),
    ],
    3: [  # 枯叶·马志士 电（方案C：删皮卡丘→3只）
        (26,  0, "雷丘(原作招牌,野生区3可遇)"),
        (82,  0, "三合一磁怪(展示怪:小磁怪线终点)"),
        (125, 2, "电击兽(原作招牌,野生区3可遇)"),
    ],
    4: [  # 玉虹·莉佳 草
        (45,  0, "霸王花(展示怪:臭臭花线终点)"),
        (70,  0, "口呆花(中间态,野生区7合规)"),
        (103, 0, "椰蛋树(展示怪:蛋蛋线终点)"),
        (71,  2, "大食花(展示怪:喇叭芽线终点)"),
    ],
    5: [  # 浅红·阿桔 毒
        (110, 0, "双弹瓦斯(展示怪:瓦斯弹线终点)"),
        (89,  0, "臭臭泥(展示怪:臭泥线终点)"),
        (112, 0, "钻角犀兽(展示怪:原作阿桔主力)"),
        (123, 2, "飞天螳螂(原作招牌,野生区5可遇)"),
    ],
    6: [  # 金黄·娜姿 超能
        (97,  0, "引梦貘人(展示怪:催眠貘线终点)"),
        (64,  0, "勇基拉(中间态,野生区5合规)"),
        (80,  0, "呆壳兽(展示怪:呆呆兽线终点)"),
        (65,  2, "胡地(展示怪:娜姿原作王牌,凯西线终点)"),
    ],
    7: [  # 红莲·夏伯 火
        (78,  0, "烈焰马(展示怪:小火马线终点)"),
        (126, 0, "鸭嘴火兽(原作招牌,野生区7可遇)"),
        (59,  0, "风速狗(展示怪:卡蒂狗线终点)"),
        (110, 2, "双弹瓦斯(展示怪:夏伯原作毒瓦斯)"),
    ],
    8: [  # 常磐·坂木 地面/恶——"常磐老大用常磐怪"
        (51,  0, "三地鼠(展示怪:地鼠线终点,常磐标志)"),
        (34,  0, "尼多王(展示怪:尼多朗线终点)"),
        (20,  0, "拉达(展示怪:小拉达线终点,常磐森林)"),
        (22,  2, "大嘴雀(展示怪:烈雀线终点,常磐森林)"),
    ],
}


def main():
    apply = os.environ.get("PKM_APPLY", "0") == "1"
    c = sqlite3.connect(DBFILE)
    c.row_factory = sqlite3.Row
    dex = {r["pokedex_no"]: r["name"] for r in c.execute("SELECT pokedex_no,name FROM pokemon_base")}
    gyms = {r["sort"]: dict(r) for r in c.execute("SELECT id, sort, gym_name, recommend_level FROM gym_base")}
    pool = {r["pokedex_no"] for r in c.execute("SELECT DISTINCT pokedex_no FROM region_wild_pokemon")}
    fr = {r["from_no"] for r in c.execute("SELECT DISTINCT from_no FROM pkm_evolution")}
    to = {r["to_no"] for r in c.execute("SELECT DISTINCT to_no FROM pkm_evolution")}
    ends = to - fr                       # 进化终点集
    gift = {143, 144, 145, 146, 150, 142, 151, 137}

    payload = []
    for sort in sorted(GYM_TEAMS):
        g = gyms[sort]
        base = g["recommend_level"]
        team = []
        for pid, off, why in GYM_TEAMS[sort]:
            lv = min(50, base + off)
            # 断言：展示怪(终点)不得同时出现在野生池；礼物怪不得进任何队
            assert pid not in gift, f"gym{sort} {dex.get(pid)} 是道馆礼物怪，不得入队"
            if pid in ends:
                assert pid not in pool, f"gym{sort} {dex.get(pid)} 是终点且在野生池(口径冲突)"
            team.append({"pokedex_no": pid, "level": lv})
        payload.append((g["id"], json.dumps(team, ensure_ascii=False)))
        print(f"gym{sort} {g['gym_name']} Lv{base}: "
              + "、".join(f"{dex[t['pokedex_no']]}Lv{t['level']}" for t in team))
    # 难度单调断言（各馆王牌等级不降）
    aces = [max(t["level"] for t in json.loads(js)) for _, js in payload]
    assert all(b >= a for a, b in zip(aces, aces[1:])), f"馆主王牌等级倒挂: {aces}"
    # 方案C 队形断言：前 3 馆 3 只、后 5 馆 4 只（随徽章增长）
    sizes = [len(json.loads(js)) for _, js in payload]
    assert sizes == [3, 3, 3, 4, 4, 4, 4, 4], f"方案C 队形不符: {sizes}"

    if apply:
        c.execute("DELETE FROM gym_trainer_team")
        c.executemany("INSERT INTO gym_trainer_team(gym_id, pokemon_json) VALUES(?,?)", payload)
        c.commit()
    c.close()
    print(("APPLIED" if apply else "DRY"), "重建道馆数:", len(payload))


if __name__ == "__main__":
    main()
