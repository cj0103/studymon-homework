# 宝可梦素材库（项目自用，不传播）

> 配套《宝可梦作业激励游戏化应用｜初代关都篇》项目使用。
> 全部素材仅本地个人学习用途，不随代码仓库公开传播。

## 积累结果（2026-10-05 完成，已全量校验）

| 素材 | 数量 | 状态 |
|---|---|---|
| 官方立绘 475px | 151/151 | ✅ |
| 初代红蓝战斗精灵（正面/背面） | 151/151 + 151/151 | ✅ |
| 宝可梦叫声 ogg | 151/151 | ✅（25.ogg 为 mp3 封装，浏览器可直接播放） |
| BGM/音效 mp3/wav | 31 个 | ✅（缺 pokechillmusic 20MB+ 超长 BGM、memorice、winrewards，非必需） |
| Veekun 数据表 CSV | 25 张（含 8.3MB 招式学习表） | ✅ 已抽样校验（种族值/经验组/皮卡丘Lv1-43学招全对） |

## 目录结构与用途

| 目录 | 内容 | 来源 | 项目用途 |
|---|---|---|---|
| `artwork/official/` | 1‑151 官方立绘 PNG 475px | PokeAPI/sprites | 图鉴、宝可梦详情页、打卡奖励弹窗 |
| `artwork/gen1-red-blue/` | 1‑151 初代红蓝像素战斗精灵（正面） | PokeAPI/sprites generation-i | 战斗中"敌方"宝可梦显示 |
| `artwork/gen1-red-blue-back/` | 1‑151 初代红蓝像素精灵（背面） | PokeAPI/sprites generation-i back | 战斗中"我方"宝可梦显示 |
| `audio/cries/` | 1‑151 宝可梦叫声 .ogg | PokeAPI/cries | 图鉴点击、出场、捕获成功音效 |
| `pokegenetic-audio/audio/` | 战斗 BGM、捕获/升级音效 mp3 | pokegenetic/pokegenetic-audio | 道馆 BGM、野生战斗 BGM、精灵球音效、升级音效 |
| `veekun-csv/` | 种族值/招式/克制/经验组等 CSV 原始表 | veekun/pokedex | 阶段1 数据清洗导入 MySQL 静态表 |

## 文件命名约定（全部以图鉴编号 1‑151 为键）

```
artwork/official/{pokedex_no}.png          例 25.png = 皮卡丘立绘
artwork/gen1-red-blue/{pokedex_no}.png     敌方战斗精灵
artwork/gen1-red-blue-back/{pokedex_no}.png 我方战斗精灵
audio/cries/{pokedex_no}.ogg               例 6.png 叫声
```

前端引用建议：静态资源挂 Nginx `/static/pokemon/` 路径，按编号直接拼 URL。

## 常用 BGM / 音效映射（实测已到位的文件）

| 场景 | 文件 |
|---|---|
| 野生宝可梦战斗 | `audio/trainerbattle.mp3`（可兼用）或另找 wild battle 曲 |
| 道馆/训练师战斗 | `pokegenetic-audio/audio/gymbattle.mp3`、`trainerbattle.mp3` |
| 胜利 | `audio/sfx/victory.mp3`、`wintrainer.mp3`、`wingym.mp3` |
| 投掷精灵球 | `audio/sfx/pokeballthrow.mp3` / `pokeballopen.mp3` / `pokeballwait.mp3` |
| 捕获成功 | `audio/sfx/pokeballcatch.mp3`、`catchedgo.mp3`、`catchmusic.mp3` |
| 升级（打卡奖励核心音效） | `audio/sfx/levelup.mp3` |
| 获得徽章 | `audio/obtainbadge.mp3` |
| 图鉴/首页 BGM | `audio/pokemongym.mp3`、`casino.mp3`（轻快） |
| 治愈/恢复 | `audio/sfx/heal.mp3`、`pc.mp3` |
| 稀有/闪光出场 | `audio/sfx/shiny.mp3` |

## 数据清洗要点（实测发现，与计划书有出入）

1. **经验组实际 6 组**（veekun growth_rates）：`slow / medium / fast / medium-slow / slow-then-very-fast / fast-then-very-slow`。计划书只有 fast/medium/slow 三组，导入时归并映射：medium-slow→slow、slow-then-very-fast→slow、fast-then-very-slow→fast（或直接扩展为 6 组公式，更还原）。
2. **招式过滤依据**：`move_meta.csv`（drain/crit_rate/flinch_chance 非 0 直接剔除）+ `move_meta_stat_changes.csv`（仅保留 attack/defense 升降，剔除 speed/accuracy/evasion 变化）+ `moves.csv` 的 `generation_id=1` 且 `version_group` ∈ red-blue/yellow。
3. `type_efficacy.csv` 的 `damage_factor/100` 即倍率；stat_id=5 是初代 Special，丢弃。
4. Gen1 学招：`pokemon_moves.csv` 中 `version_group_id=1`(red-blue)/`2`(yellow) 且 `pokemon_move_method_id=1`(level-up)。
5. 中文名：veekun 无官方简中，`pokemon_species_prose.csv` 只有英文/日文。宝可梦 151 中文名使用内置官方简中对照表；招式中文名取自 `move_names.csv` local_language_id=4（繁中）经 **OpenCC**（`opencc-python-reimplemented`）t2s 转简体。若环境缺 OpenCC 脚本会自动降级回英文名。

## 数据表对应关系（veekun-csv → 项目数据库）

| CSV | 导入目标表 | 清洗要点 |
|---|---|---|
| `pokemon.csv` + `pokemon_stats.csv` | `pokemon_base` | 只取 id 1‑151；取 hp/attack/defense/speed 四项，丢弃 special |
| `pokemon_species.csv` + `growth_rates.csv` | `pokemon_base.exp_group` | 经验组 fast/medium/slow |
| `pokemon_species_prose.csv` | `pokemon_base.name` | local_game_id=6（英文）；中文名可后续人工对照补充 |
| `pokemon_types.csv` + `type_names.csv` | `pokemon_base.type1/type2` | |
| `type_efficacy.csv` + `types.csv` | `type_effect` | 删除 fairy(18)/steel(9) 相关行；只保留 Gen1 十七属性 |
| `moves.csv` + `move_names.csv` + `move_meta.csv` | `skill_base` | 按白名单过滤：仅保留纯伤害 + 攻防升降 buff 效果 |
| `pokemon_moves.csv` | `pokemon_skill_learn` | level_up 学习方式；只保留 version_group ∈ red-blue/yellow；仅白名单招式 |
| `growth_rates.csv` 经验公式 | `level_exp_table` | fast=n³ / medium=6/5n³−15n²+100n−140 / slow=5/4n³，取 Lv1‑50 |

## 导入数据集（out/ 目录，阶段1产物，已交叉验证）

| 文件 | 行数 | 内容 |
|---|---|---|
| `00_schema.sql` | 13表 | 建库建表 |
| `01_pokemon_base.sql` | 151 | 种族值(去Special)+中文名+属性+经验组 |
| `02_skill_base.sql` | 65 | 白名单招式：53攻击+12攻防buff（id=veekun move_id） |
| `03_pokemon_skill_learn.sql` | 1403 | 招式学习池：升级学招 + TM(`learn_level=0`随时可学) + 兜底补招（保证每只≥4招） |
| `04_type_effect.sql` | 82 | 克制表非1.0行（Bulbapedia交叉验证PASS） |
| `05_level_exp_table.sql` | 50 | 三组经验公式（fast=125000@50 已验证） |
| `06a-06d` | — | 区域4区/**原版8道馆**/野生池376条(红蓝实导×2.2拉伸)/馆主阵容(原版精灵≤3只) |
| `dropped_moves_review.txt` | 100 | 被过滤招式+原因（人工复核） |

导入顺序：00 → 01 → 02 → 03 → 04 → 05 → 06a-d。数据更新时重跑 `python build_import.py` 即可再生成。

**清洗决策记录**：
1. 攻击招式附带 sp/速度效果（如 Acid 降特防）因项目去 Special 已落空 → 按纯伤害保留（效果不实现）；
2. 皮皮/胖丁等 5 只的现代妖精属性已回溯修正为 Gen1 原属性；
3. 野捕捕获概率、经验发放额度属数值策划项，后端阶段可调，数据层不含；
4. 馆主招式留空，后端按 learn_level≤等级 自动取最新4个白名单招式；
5. **道馆按初代红/绿/蓝原版八馆**（经 52poke/bilibili/百度百科三源交叉确认）：深灰·小刚(岩·灰色) → 华蓝·小霞(水·蓝色) → 枯叶·马志士(电·橙色) → 玉虹·莉佳(草·彩虹) → **浅红·阿桔(毒·粉红)** → 金黄·娜姿(超能·金色) → 红莲·夏伯(火·深红) → 常磐·坂木(地面·绿色)。注意：浅红道馆 Gen1 是阿桔的毒系馆（粉红徽章），Gen2 才改为阿杏的地面系；早期草稿曾遗漏此馆并杜撰"紫苑劲旅"，已修正；
6. 馆主阵容使用原版精灵（每队≤3只与玩家同规）：小刚=小拳石/大岩蛇/隆隆岩；小霞=海星星/宝石海星/角金鱼；马志士=霹雳电球/皮卡丘/雷丘；莉佳=霸王花/大食花/椰蛋树；阿桔=瓦斯弹/臭臭泥/双弹瓦斯；娜姿=勇基拉/魔墙人偶/胡地；夏伯=卡蒂狗/小火马/烈焰马；坂木=钻角犀兽/三地鼠/尼多后；
7. **招式完备性**（`check_moves.py` 全项 PASS）：纯升级学招下 6 只宝可梦（独角虫/凯西/鬼斯三家/百变怪）Lv50 内完全无白名单招式、87 只不足 4 招——因原版的虫旋/催眠/诅咒/变身等招被去 Special 白名单过滤。解法：学习池纳入 **TM 学习途径**（Gen1 原生机制，`learn_level=0` 表示随时可学），仅独角虫/百变怪两只仍不足时按**同属性优先兜底补招**（共 21 条）。最终 151/151 每只学习池≥4招，149 只 Lv1 即可用≥3招；
8. **馆主招式显式授予**：道馆战斗等级常低于技能学习等级（如勇基拉 L36 上但精神强念 L38 才学），按 learn_level 过滤会空招。`06d` JSON 中每只精灵已带 `moves:[4个招式id]`（pick4：等级达标升级招→TM→兜底→无视等级升级招），**后端对战时馆主直接用该 4 招，不过滤学习等级**；玩家宝可梦仍按 learn_level 正常取招。

**重要坑（已修复）**：veekun CSV 全部字段是字符串，白名单 move_id 若 `int()` 转换后再与 CSV 值比较会**静默失配**（曾导致学习池全空、只写出兜底招）。统一以字符串比较。

**TODO（人工一次性）**：65 个招式简中名由繁转简生成（如"大闹一番""聚宝功"为官方繁中习惯用法），建议对照 pokemondb.net 简中站抽查一遍用词（约半小时）。

## 部署形态（用户确认）

孩子操作：**安卓平板**；家长确认：**手机端**。→ 采用 **H5 响应式 Web App**（单一 URL，平板/手机同一套页面自适应，无需分别开发），部署在现有 ECS + Nginx。静态素材（图/音）挂 `/static/pokemon/`，注意仅家庭内网/低带宽访问，不公开传播。

## 版权备注

图片、音频版权归 Nintendo / Creatures / GAME FREAK。本目录素材仅个人学习、家庭自用，
不打包进任何公开分发的代码包，不部署为公开可访问的静态资源。

## 补跑下载

素材已全部完成。个别文件损坏/新增时，在 assets 目录重新执行对应脚本即可断点续传（jsdelivr 优先，raw 兜底）：

```bash
python dl.py          # 立绘 + 红蓝精灵(正/背面) + 叫声
python dl_fast.py     # jsdelivr优先批量补全精灵/叫声
python dl_big.py      # veekun 大CSV（双源竞速断点续传）
python dl_veekun.py   # veekun 小CSV
python dl_audio.py    # BGM/音效
```

> Windows 环境坑（已踩过）：本机 git/curl 直连 GitHub 因 schannel 证书吊销检查失败（CRYPT_E_NO_REVOCATION_CHECK）会永久卡死。curl 必须加 `--ssl-no-revoke`；git clone 基本不可用；Python urllib 正常。raw 直连约 100KB/s 且易超时，**大文件优先走 `https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/{path}`**（偶发 403/503，重试即可）。
