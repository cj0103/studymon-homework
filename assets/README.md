# 素材目录（本仓库不含素材，需自备）

应用的运行时依赖一组宝可梦题材素材（立绘、战斗精灵、叫声音频、BGM、图鉴静态数据）。
因这些素材的著作权/商标归任天堂、Game Freak、The Pokémon Company 及其上游数据汇编者所有，
**本仓库不分发任何素材文件**。请使用者自行准备（个人学习用途），按下方目录约定放入本目录。

> 应用对素材缺失是优雅降级的：缺图前端自动隐藏占位、缺音频不影响玩法，可先跑通再补素材。

## 目录约定（全部以图鉴编号 1–151 为键）

```
assets/
  artwork/official/{no}.png               官方立绘（详情页/图鉴/弹窗）
  artwork/gen1-red-blue/{no}.png          初代红蓝战斗精灵·正面（敌方显示）
  artwork/gen1-red-blue-back/{no}.png     初代红蓝战斗精灵·背面（我方显示）
  artwork/thumb/{no}.png                  96px 缩略图（指南页，用 make_thumbs.py 从 official 生成）
  audio/cries/{no}.ogg                    宝可梦叫声
  audio/*.mp3                             战斗 BGM / 捕获 / 升级等音效（文件名见下）
  veekun-csv/*.csv                        Veekun pokedex 数据表（构建静态表用）
  out/*.sql                               构建产物：派生静态数据 SQL（由 build_* 脚本生成）
```

例：`artwork/official/25.png` = 皮卡丘立绘。后端把 `assets/` 挂在 `/static` 下，前端按编号拼 URL。

## 静态数据表（out/）如何生成

后端运行需要以下派生表（宝可梦基础数值、招式、学习池、属性克制、等级经验、区域/道馆配置），
由 `backend/` 下脚本从 `veekun-csv/` 与脚本内嵌数据构建：

| 产物 | 构建脚本 | 输入 |
|---|---|---|
| `01_pokemon_base`（种族值/属性/经验组/中文名） | `backend/app/init_db.py` 内置流程 | veekun-csv（pokemon/stats/species/types 等） |
| `02_skill_base` + `03_pokemon_skill_learn` | `backend/build_skills_v3.py`（需 `PKM_VEEKUN` 指向 CSV 目录） | moves / move_names / move_meta / move_meta_stat_changes / pokemon_moves 共 5 张 CSV |
| `pkm_evolution`（69 条进化链） | `backend/build_evolution.py` | 脚本内嵌数据（pokemon_species.csv 可选校验） |
| `pkm_profile`（151 条手写图鉴简介） | `backend/build_profile.py` | 脚本内嵌 CURATED 字典，无需外部输入 |
| 区域野生池 / 道馆阵容 | `backend/rebuild_wild.py`、`backend/rebuild_gym_teams.py` | 脚本内嵌手工剧情表（不依赖外部数据） |

veekun CSV 的获取方式与字段映射细节不在本仓库展开（各表列义见 Veekun pokedex 项目文档）；
常见字段映射要点：种族值取 hp/attack/defense/speed 四项（Gen1 special 丢弃）；
学招只取 `version_group ∈ {red-blue, yellow}` 且 `level-up` 方式；招式中文名可经繁中转简体处理。

## 常用音频文件名映射

| 场景 | 文件 |
|---|---|
| 野生宝可梦战斗 | `audio/trainerbattle.mp3`（可兼用）或另找 wild battle 曲 |
| 道馆战斗 | `audio/gym.mp3` |
| 训练家战胜 | `audio/vs trainer win_jable.mp3` |
| 捕获成功 | `audio/catch.mp3` |
| 升级 | `audio/levelup (1).mp3` |
| 图鉴/首页 BGM | `audio/pokemongym.mp3`、`casino.mp3`（轻快） |

## 合规提醒

素材仅供个人/家庭学习环境使用，请勿随代码公开分发或用于任何商业用途。
