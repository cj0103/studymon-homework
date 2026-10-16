# 素材自备与数据库构建指引

> 本指引配合 README 使用：README 讲"这是个什么项目、怎么玩"，本文件讲"**从零跑起来还要补哪些东西、怎么补**"。
> 版权边界见文末第 6 节。所有获取动作都可以交给 AI 编码工具执行，文末附可直接粘贴的任务描述。

---

## 1. 全景：跑起来需要补什么

仓库提供了完整代码 + 业务表建表 SQL + 全部玩法口径脚本。缺的只有两类东西——**图片**和**静态数据表**（因版权不随仓库分发）：

```
                    上游素材站                本仓库脚本                  运行时
                ┌──────────────┐         ┌──────────────┐        ┌──────────────┐
  图片 ───────▶│ sprite 镜像站 │──下载──▶│              │        │              │
                └──────────────┘         │ build/rebuild │  导入  │  SQLite 库    │──▶ 网页
                ┌──────────────┐         │  系列脚本     │──────▶ │ pkm.sqlite3  │
  数据 ───────▶│ veekun CSV    │──下载──▶│  （口径内置） │        │ assets/out/  │
                └──────────────┘         └──────────────┘        └──────────────┘
```

**最短路径其实只要三步**：

1. **图片**：两个目录各下 151 张 PNG（第 2 节）+ 跑一个脚本生成缩略图
2. **数据**：clone 一个 veekun 数据集（一个命令）——**十张静态数据表的 SQL 产物由你本地跑一次构建流水线生成**（第 3、4 节）
3. **启动**：回到 README「快速开始」，`python app/init_db.py` 一键建库起服务

图片和数据互不依赖，可以并行做。全程没有一处需要手写数值。

---

## 2. 图片素材（3 类，只需下载 2 类）

前端所有图片以**图鉴编号 1-151** 为文件名（25.png = 皮卡丘），缺失时自动隐藏占位、不影响玩法。**音频/叫声当前版本没有用到，整个 audio/ 目录不用建。**

| # | 目录 | 内容 | 数量 | 怎么来 |
|---|---|---|---|---|
| ① | `assets/artwork/official/` | 官方立绘（图鉴、详情页、奖励弹窗） | 151 | 下载 |
| ② | `assets/artwork/gen1-red-blue/` | 初代红蓝战斗精灵·**正面**（战斗画面上方=敌方） | 151 | 下载 |
| ③ | `assets/artwork/gen1-red-blue-back/` | 初代红蓝战斗精灵·**背面**（战斗画面下方=我方） | 151 | 下载 |
| ④ | `assets/artwork/thumb/` | 96px 缩略图（指南页批量加载用） | 151 | **本地生成**，放好①后跑 `python backend/make_thumbs.py` |

下载地址（PokeAPI 生态的公开 sprite 镜像，raw 直链可按编号批量拉）：

```
立绘:   https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{no}.png
正面:   .../sprites/pokemon/images/backup/generation-i/red-blue/{name}.png 一类的 red-blue 正面目录
背面:   同上 back/ 目录
```

（red-blue 精灵的文件名有连字符规则，如 `venasaur.png` / `venonat.png`，建议让 AI 工具按编号→英文名映射处理。）

**完整性自检**（三个下载目录都应输出 151，且无 0 字节文件）：

```bash
cd assets/artwork && for d in official gen1-red-blue gen1-red-blue-back; do echo -n "$d: "; ls $d | grep -c png; done
```

---

## 3. 数据库构建（一）：先看懂三层数据模型

这是本指引最容易迷路的地方。游戏数据库分两大区，理解了这个分层，后面每一步都是机械操作：

### A 区 · 业务表 —— 什么都不用做

账号、打卡记录、审核流水、对战记录、设备令牌等"孩子产生的数据"。建表 SQL 与规则配置种子**全部在仓库里**（`backend/sql/01_business.sql`、`02_device_token.sql`），`init_db.py` 自动执行。

### B 区 · 静态数据表 —— 本指引的主体

游戏"世界观"的十张表。按**数据性质**分三层，这也是理解构建流水线的钥匙：

| 层 | 表 | 装什么 | 数据性质 | 谁提供数据 |
|---|---|---|---|---|
| **L1 原作数值** | `pokemon_base` | 151 只的属性、经验组、四项种族值 | veekun 原始数值 | **你下载** veekun |
| | `skill_base` | 招式威力/命中/PP/优先度/异常效果 | veekun 原始数值（中文名经繁转简） | 同上 |
| | `type_effect` | 15 属性 × 82 格克制表 | veekun Gen1 口径 | 同上 |
| | `level_exp_table` | Lv1-50 三经验组总经验 | 纯公式（n³ 系列） | 脚本内置 |
| | `pkm_evolution` | 进化链 结构 from→to | veekun 结构 | 同上 |
| **L1.5 原作结构+项目折算** | `pkm_evolution` 的**进化等级** | 进化石/亲密度/通信统一折算成等级 | 本项目的简化规则 | 仓库脚本内置 |
| **L2 项目原创玩法** | `pokemon_skill_learn` | 每只的升级学招表（约 5-10 招/只） | **本项目口径**：红蓝 level-up 白名单 + 家长冻结规则（破坏光线统一 Lv28 等） | 仓库脚本内置 |
| | `region_base` / `region_wild_pokemon` | 8 个冒险区域 + 野生遭遇池 | 本项目剧情表（手工编排，非原作分布复刻） | 仓库脚本内置 |
| | `gym_base` / `gym_trainer_team` | 8 道馆推荐级 + 馆主队伍 | 本项目设计（"野生抓不到、道馆看得到"的展示怪规则） | 仓库脚本内置 |
| | `pkm_profile` | 图鉴分类词/身高体重/**介绍文字** | 身高体重=veekun；**介绍=使用者自行撰写**（见 5.3） | 你/你的 AI 撰写 |
| | `pkm_starters` | 开档礼赠（皮卡丘） | 项目设定 | 仓库脚本内置 |

**结论：你唯一需要"搞到数据"的地方就是 veekun CSV；L2 玩法口径全部已经手写在仓库脚本里，跑脚本即得。**

### B 区产物的落地形态

构建流水线的输出是十个 SQL 文件，放在 `assets/out/`（00 建表 + 01~06 数据）。`init_db.py` 启动时先建业务表，再按文件名顺序导入 `assets/out/0[1-6]*.sql`——所以"构建数据库"的全部含义就是：**把 out/ 目录产出，然后交给 init_db**。

### C 区 · 图鉴档案表 `pkm_profile`

由 `build_profile.py` 写入（分类词、介绍、身高体重），随下面流水线一起跑即可，不单列。

---

## 4. 数据库构建（二）：六步流水线

### 4.1 前置准备（一次性）

```bash
# ① Python 依赖
pip install fastapi uvicorn bcrypt pyjwt pillow opencc-python-reimplemented

# ② 下载 veekun 数据集（MIT 授权，release 页的 CSV 压缩包）
#    解压后目录里应能直接看到 pokemon.csv、moves.csv 等文件（不要多套一层目录）
git clone --depth 1 https://github.com/veekun/pokedex.git /tmp/pk  # 或直接下 release zip
# 把其中 data/pokemon 下的 CSV 放到项目根：assets/veekun-csv/

# ③ 建空库并建表（此时还不导数据，out/ 尚不存在也没关系，会跳过）
cd backend && PKM_DB_ENGINE=sqlite python app/init_db.py
```

veekun 解压后核对四张关键表存在即可：`pokemon.csv`、`move_names.csv`、`type_efficacy.csv`、`encounters.csv`。

### 4.2 六步执行（工作目录始终是 `backend/`）

> 落库约定：带 `PKM_APPLY=1` 的脚本才真正写库，不带则**干跑**只打印报告（首次建议先干跑看报告）。

```bash
export PKM_DB_ENGINE=sqlite          # Windows PowerShell: $env:PKM_DB_ENGINE="sqlite"

# ── L1 原作数值：从 veekun 提数 ──────────────────────────────
# S1 总装配：读 veekun CSV，**产出 assets/out/01~06d 十个 SQL 文件**（本步不写库）
#    内容=pokemon_base / skill_base / 学习表初版 / 克制表 / 经验表 / 区域道馆底表 / 野生底表
python ../assets/build_import.py

# 导一次库：让 S1 产物进入 SQLite（后续 S3~S6 都在库内加工）
python app/init_db.py

# ── L2 项目口径：用仓库内置的手写规则覆盖/精修 ────────────────
# S2 图鉴档案 pkm_profile（身高体重=veekun；介绍=CURATED 文案钩子，见 5.3）
PKM_APPLY=1 python build_profile.py

# S3 进化表（链结构=veekun；等级覆盖为项目 Gen1 折算表）
PKM_APPLY=1 python build_evolution.py

# S4 技能池 v3（升级招∪TM 全量池 → 跨属性清洗 → 节奏插段；写 skill/learn 中间态）
PKM_APPLY=1 python build_skills_v3.py

# S5 学习表定稿 ★ 孩子选招减负口径：红蓝 level-up 白名单整表覆盖 S4 结果
#    （约 5-10 招/只；破坏光线统一 Lv28；皮卡丘特例表。手写表在脚本内）
PKM_APPLY=1 python trim_moves.py

# S6 剧情层：8 区域 + 野生池 + 8 道馆队伍（手写表在脚本内）
PKM_APPLY=1 python rebuild_wild.py
PKM_APPLY=1 python rebuild_gym_teams.py
```

**看懂这条链的关键**：S1 是"从上游提数、产出 SQL 文件"，随后"入库"；S2→S4 是"把原作全量规则搬进库"，S5→S6 是"用我们的口径做减法、定稿"。S4 与 S5 对同一张 `pokemon_skill_learn` 先后写入，**S5 是最终口径**——有意设计，不是冲突。

**依赖顺序不能乱**：S1 必须先跑（建出 skill_base 的 id 体系，S4/S5 按招式名对齐引用）；S5 必须在 S4 之后（覆盖关系）；S6 独立，最后跑即可。

> 注：`out/` 里的 03 学习表与 06c 野生池是 S1 阶段底稿，与 S5/S6 的最终口径存在"先全量后精简"的历史差异——所以 4.3 的干净重放之后，务必再跑一遍 S5/S6 对齐（或直接以第 7 节 AI 任务单为准，已包含该步）。

### 4.3 干净重放 + 定稿对齐（推荐）

流水线跑完后做一次"从零重放"，验证产物自洽：

```bash
rm pkm.sqlite3                        # 删掉边算边写的库
python app/init_db.py                 # 全新 init_db：建表 + 导入 assets/out/ 全部产物
PKM_APPLY=1 python trim_moves.py      # out/03 是 S1 底稿 → 用最终口径覆盖
PKM_APPLY=1 python rebuild_wild.py    # out/06c 同理
PKM_APPLY=1 python rebuild_gym_teams.py
```

干净重放 + 定稿对齐都成功，才算"数据产物自洽"，之后升级迭代随便 reset 都不慌。

---

## 5. 验收与常见坑

### 5.1 一键验收

```bash
cd backend
python reset_game.py        # 清动态数据（保留账号）——冒烟前置，必须跑
python _smoke_all.py        # 全量回归，期望末行：
                            # [DRIVER] ALL PASSED (smoke + v12 + v15 + v17)
```

冒烟内置一组**口径哨兵断言**：皮卡丘无进化链、破坏光线 Lv28、前后端克制表 82 格逐格一致、开档皮卡丘带 3 招等。流水线哪步跑歪，这里会红给你看。

### 5.2 常见坑速查

| 症状 | 原因 | 处理 |
|---|---|---|
| S1 报 `FileNotFoundError: xxx.csv` | veekun 解压多套了一层目录 | 保证 `assets/veekun-csv/pokemon.csv` 直接可见 |
| 中文招式名缺失 / S5 大面积"招式名未收录" | 未装 OpenCC，或跳过了 S1 直接跑 S4/S5（学习表按招式名对齐 skill_base） | `pip install opencc-python-reimplemented`；严格按 S1→S5 顺序 |
| 冒烟 1b 节失败"设备令牌不是 3 条" | 测试前没 reset | 先 `python reset_game.py` 再跑 `_smoke_all.py` |
| 页面图片全是空白占位 | 素材路径/文件名不对 | 对照第 2 节三目录；文件名必须是纯编号（`25.png`，不是 `025.png`） |
| 和现行图鉴数值对不上 | 本项目**冻结 Gen1 口径**，差异是特性不是 bug | 动手"修正"前先读 `backend/moves_compare.md`、`MOVES_AUDIT_151.md` |
| 想换 SQLite→MySQL | 同一套 SQL 双方言 | 见 README「快速开始」MySQL 段；构建脚本环境变量同 README |

### 5.3 图鉴介绍文字：自己写，别去爬

`pkm_profile.intro` 在官方原作里是受版权保护的文字。`build_profile.py` 预留了 `CURATED` 字典钩子——请使用者（或你的 AI）**原创撰写** 151 条介绍，可参考数值/属性自由发挥，风格示例："背上有一颗种子，出生起与种子一起生活，随成长逐渐发芽长大。常趴在阳光下积蓄力量。" **不要**从图鉴百科站点爬取官方原文入库。

---

## 6. 版权边界（请花一分钟读完）

1. **仓库为什么没有素材**：代码与玩法口径是自制（MIT）；立绘、精灵、图鉴文字、名称数据的版权各归其权利人，不分发是最基本的尊重，也让这个项目能一直放着。
2. **你自备素材的正确姿势**：仅在本地/自有家庭设备使用（个人学习用途）。**不要**把素材打包给任何人（含网盘链接、压缩包、"私信发你"）——"打包再分发"是新的独立侵权分发，比"网络上存在"严重得多。
3. **服务端同理**：不要把素材部署到对公众开放的服务器上供人下载或访问。自用部署（仅自己家庭设备访问）不在讨论范围。
4. **营销物料克制**：分享/演示项目时，截图封面尽量用自家打码的界面或纯文字，避免直接用宝可梦形象做宣传物料。
5. **AI 获取的边界**：用 AI 自动化"下载 + 构建"没有问题——风险取决于**最终传播了什么**，不取决于过程用什么工具。红线同第 2、3 条 + 第 5.3 条（不爬官方图鉴文字入库）。
6. 如权利人认为不妥，删除相应素材即可，本项目无意也无法与权利人对抗。

---

## 7. 一键投喂 AI 的完整任务描述

把下面整段贴给任何 AI 编码工具（Trae / Cursor / Claude Code 等），把 `<项目路径>` 换成实际路径即可从零执行：

```text
任务：为本地项目 <项目路径>/studymon-homework 准备运行素材与静态数据，使其通过全量测试。

阶段一 · 图片（可并行）：
1. 从 github.com/PokeAPI/sprites 批量下载编号 1-151 三套 PNG：
   assets/artwork/official/           ← other/official-artwork/{no}.png
   assets/artwork/gen1-red-blue/      ← generation-i red-blue 正面（注意英文名连字符映射）
   assets/artwork/gen1-red-blue-back/ ← 同系列 back/ 背面
   校验：每套恰好 151 个 .png，无 0 字节，文件名为纯编号。
2. 运行 python <项目路径>/backend/make_thumbs.py 生成 assets/artwork/thumb/。

阶段二 · 数据：
3. 下载 github.com/veekun/pokedex 最新 CSV 导出，CSV 文件平铺放入 assets/veekun-csv/
  （校验 pokemon.csv / move_names.csv / type_efficacy.csv / encounters.csv 存在）。
4. pip 安装 fastapi uvicorn bcrypt pyjwt pillow opencc-python-reimplemented。
5. 在 backend/ 下按 ASSETS_GUIDE 第 4.2 节顺序执行（全程 PKM_DB_ENGINE=sqlite）：
   python ../assets/build_import.py
   python app/init_db.py
   PKM_APPLY=1 python build_profile.py
   PKM_APPLY=1 python build_evolution.py
   PKM_APPLY=1 python build_skills_v3.py
   PKM_APPLY=1 python trim_moves.py
   PKM_APPLY=1 python rebuild_wild.py
   PKM_APPLY=1 python rebuild_gym_teams.py
6. 图鉴介绍文案：为 build_profile.py 的 CURATED 字典原创撰写 151 条中文介绍
  （根据该只属性/种族值/进化链自由发挥，每条约 40-60 字；禁止抓取任何图鉴百科原文）。

阶段三 · 验证：
7. rm backend/pkm.sqlite3 && python app/init_db.py（应完整导入 assets/out/ 产物），
   再依次重跑 trim_moves.py / rebuild_wild.py / rebuild_gym_teams.py（带 PKM_APPLY=1，
   把 out/ 底稿对齐到最终口径）。
8. python reset_game.py && python _smoke_all.py，直到末行输出
   ALL PASSED (smoke + v12 + v15 + v17)，任何 FAIL 都要定位修复而不是跳过。

红线：所有素材与数据仅存本地，不上传网盘、不打包分享、不部署到公网供他人访问。
```

---

## 附：文档索引

| 想了解 | 看哪里 |
|---|---|
| 这是什么、玩法规则、快速开始 | `README.md` |
| 素材目录与构建（本文） | `ASSETS_GUIDE.md` |
| 招式数值审计（Gen1 vs 现行） | `backend/moves_compare.md`、`backend/MOVES_AUDIT_151.md` |
| 本地素材库目录约定（自用记录） | `assets/README.md` |
