# 素材自备与数据库构建指引

本文回答两个问题：**图片放哪里、叫什么名字**；**跑起来需要哪些数据表、数据从哪来、怎么派生**。

本仓库不含任何图片素材与上游数据集，请自行获取后按以下约定放入本地目录。本项目为家庭自用、非盈利的个人学习用途：获取的素材仅在本地/自有设备使用，**请勿将素材本身打包传播**；素材版权归原作者/权利人所有，如权利人要求请立即删除。

---

## 〇、先建立正确心智：哪些要"自备"，哪些程序自动生成

| 层 | 内容 | 来源 | 你需要做的 |
|---|---|---|---|
| 图片素材 | 立绘 / 战斗精灵（正面+背面）/ 缩略图 | 第三方 sprite 镜像站自行下载 | **手动放入** `assets/artwork/`；缩略图可脚本生成 |
| 上游数据表 | veekun 导出的 CSV 原始集 | `github.com/veekun/pokedex` releases | **手动下载**，解压到 `assets/veekun-csv/` |
| 派生静态数据 | `assets/out/*.sql` 十张表 | 由 `build_import.py` / `build_*.py` / `rebuild_*.py` / `trim_moves.py` 从上面两类输入派生 | **跑脚本生成**，全程不用手写一行数值 |
| 业务表 + 种子数据 | 账号/打卡/令牌表、任务菜单、规则配置 | 仓库自带 `sql/01_business.sql` `02_device_token.sql` | `python app/init_db.py` 自动建 |
| 玩法口径 | 区域划分、道馆推荐级、野生带、招式精简表、进化等级折算 | **本项目原创**（手写在本仓库 py 文件里） | 无需获取，脚本已内置 |

**关于"能不能让 AI 帮我获取"**：可以。AI 工具完全可以替你完成"clone 数据集、批量下载、按规则派生"这些机械步骤。侵权风险从来不在"用没用 AI"，而在最终**你传播了什么**——只要素材和数据始终停留在你本地、不打包分发，过程用什么工具无所谓。但注意两条红线：
- 不要让 AI 从图鉴百科类站点**爬取图鉴介绍文字**并入库——本项目的做法是介绍文字由使用者自行编写/仿写（脚本有 `CURATED` 钩子，见 §3.3）；
- 不要生成"素材包"发给别人，包括网盘链接。

---

## 一、图片素材清单（共 3 类，实际只需下载 2 类）

前端全部以图鉴编号 `1-151` 为文件名，缺失时自动隐藏占位，**不影响任何玩法**。
（叫声与 BGM：当前前端代码零引用，`audio/` 整个目录都可以不建。）

### 1.1 官方立绘 `official/`（151 张）

```
assets/artwork/official/{pokedex_no}.png     例 25.png = 皮卡丘
```

- 用途：图鉴列表、宝可梦详情页、进化预告、打卡奖励弹窗
- 尺寸：约 475px 透明底 PNG；其他尺寸也能跑（前端按容器缩放）
- 获取：PokeAPI 生态的公开 sprite 镜像（`github.com/PokeAPI/sprites`，raw 直链即可批量下载），例如：
  `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{no}.png`

### 1.2 初代战斗精灵（正面 + 背面各 151 张，v15 对战画面用）

```
assets/artwork/gen1-red-blue/{pokedex_no}.png        敌方（正面）
assets/artwork/gen1-red-blue-back/{pokedex_no}.png   我方（背面）
```

- 用途：战斗画面上（敌）下（我）对峙台面
- 尺寸：初代红蓝版像素精灵（96px 上下），同一目录命名规则
- 获取：PokeAPI sprites 的 `generation-i/red-blue` 系列，正面与背面（`back/`）两套目录分别对应上面两个目录

### 1.3 缩略图 `thumb/`（不用下载，本地生成）

```
assets/artwork/thumb/{pokedex_no}.png        96px，约 5KB/张
```

- 用途：指南页/图鉴批量加载（40px 灰显小图），避免整页拉 151 张 150KB 立绘
- 获取：放好 `official/` 后跑 `python backend/make_thumbs.py`（PIL 缩放，幂等可重跑）

### 1.4 完整性自检

```bash
# 在 assets/artwork/ 下分别执行，三个目录都应输出 151
ls official | grep -c png
ls gen1-red-blue | grep -c png
ls gen1-red-blue-back | grep -c png
```

---

## 二、数据库构建指引

### 2.1 跑起来到底需要哪些表

`python app/init_db.py` 一键初始化会按顺序导入：业务表（账号/打卡/令牌）→ `assets/out/0[1-6]*.sql` 静态数据表。静态数据共十张：

| 表 | 内容 | 数据性质 |
|---|---|---|
| `pokemon_base` | 151 只：属性、经验组、四项种族值 | **上游数值**（veekun） |
| `skill_base` | 招式池：威力/命中/PP/优先度/异常效果 | **上游数值**（veekun，招式名经繁转简） |
| `pokemon_skill_learn` | 每只的升级学习表（约 5-10 招/只） | **本项目口径**（红蓝 level-up 白名单 + 家长冻结规则，手写于 `trim_moves.py`） |
| `type_effect` | 属性克制表（15 属性 × 82 格） | **上游数值**（veekun Gen1 口径） |
| `level_exp_table` | Lv1-50 三经验组总经验 | **纯公式**（fast=n³ / medium / slow=5/4n³） |
| `pkm_evolution` | 进化链 from→to + 等级折算 | 结构=veekun；**等级为项目折算**（进化石/亲密/通信统一折级） |
| `region_base` / `region_wild_pokemon` | 8 区域与野生遭遇池 | **本项目原创剧情表**（手写于 `rebuild_wild.py`） |
| `gym_base` / `gym_trainer_team` | 8 道馆与馆主队伍 | **本项目原创**（手写于 `rebuild_gym_teams.py`） |
| `pkm_starters` | 开档礼赠（皮卡丘） | 项目设定 |

### 2.2 上游数据集：veekun/pokedex（CSV 导出）

- 获取：`github.com/veekun/pokedex` 的 releases 页下载 CSV 压缩包（MIT 授权），解压到 `assets/veekun-csv/`
- 本构建链实际用到的表（缺表时脚本会明确报错）：
  `pokemon.csv`、`pokemon_species.csv`、`pokemon_stats.csv`、`pokemon_types.csv`、
  `moves.csv`、`move_names.csv`（需要 `local_language_id=4` 繁中行做简转）、`move_meta.csv`、
  `move_meta_stat_changes.csv`、`pokemon_moves.csv`、`type_efficacy.csv`、`growth_rates.csv`、
  `locations.csv`、`location_areas.csv`、`encounters.csv`
- 中文招式名依赖 OpenCC 繁转简：`pip install opencc-python-reimplemented`

### 2.3 构建顺序（从零重建整套静态数据）

在 `backend/` 工作目录、`PKM_DB_ENGINE=sqlite` 下依次执行（脚本内部路径指向 `../assets/veekun-csv`）：

```bash
# 1) 总装配：veekun CSV → assets/out/01~06 静态 SQL（pokemon_base/技能/学习表初版/克制/经验表/野生池）
python ../assets/build_import.py

# 2) 身高体重/图鉴档案（读 pokemon.csv 覆盖内嵌表；介绍文字见 §3.3）
python build_profile.py

# 3) 进化表（veekun 结构 + 项目 Gen1 等级折算表）
python build_evolution.py

# 4) 技能表 v3（升级招∪TM、跨属性清洗、节奏插段）
PKM_APPLY=1 python build_skills_v3.py

# 5) 学习表定稿（红蓝 level-up 白名单覆盖第 1 步初版——孩子选招减负口径）
PKM_APPLY=1 python trim_moves.py

# 6) 剧情层：区域/野生池（82 只入池）与道馆队伍（8 馆）
PKM_APPLY=1 python rebuild_wild.py
PKM_APPLY=1 python rebuild_gym_teams.py
```

> 提示：第 1、4、5 步存在"先全量后精简"的覆盖关系属有意设计（脚本幂等，重跑安全）。如果你不打算改口径，也可以跳过整段构建——`init_db.py` 导入的 `assets/out/` 若已存在即可直接用；仓库未附带 `out/` 时按本节重建。

### 2.4 验证

```bash
cd backend
python reset_game.py       # 重置动态数据（保留账号），冒烟前置
python _smoke_all.py       # 全量回归：应输出 ALL PASSED（smoke + v12 + v15 + v17）
```

冒烟里内置多条**口径断言**（皮卡丘无进化链、破坏光线 Lv28、克制表前后端 82 格一致等），任何一步构建跑歪都会在这里红给你看。

---

## 三、容易遗漏的四件事

### 3.1 前端用到的不止立绘和战斗精灵

**缩略图 `thumb/`** 是第三个必需目录（跑 `make_thumbs.py` 即得）。除此之外 PWA 图标（`web/icon-192/512.png`）仓库已自带。叫声/BGM 当前代码未引用，可全部跳过。

### 3.2 中文招式名不是现成的

veekun 只有繁中招式名，项目流水线用 **OpenCC 繁转简**（个别用词差异可接受，`trim_moves.py` 里有 ALIAS 表兜底归一）。自建时不要直接取日文名或英文名，否则 `pokemon_skill_learn` 的名字匹配（1-151 张学习表全靠招式名对齐 `skill_base`）会大面积失配。

### 3.3 图鉴介绍文字：请自行编写

图鉴详情页的"分类词 + 介绍"（`pkm_profile` 表）在官方原作里是受版权保护的文字。本仓库 `build_profile.py` 的 `CURATED` 字典是**使用者自行撰写的仿写文案**——你可以让 AI 根据数值和属性帮你**原创撰写**151 条，但不要让 AI 从 52poke 等百科站点抓取官方图鉴原文入库。仿写示例风格：`"背上有一颗种子，出生起与种子一起生活，随成长逐渐发芽长大。常趴在阳光下积蓄力量。"`

### 3.4 数值口径差异是"特性"不是 bug

本项目**冻结在 Gen1（红/蓝）口径**：招式威力、学习等级、属性克制都按初代；与 Let's Go / 现行正作大量不同（例：小拉达加速特性、必杀门牙威力等）。用 AI 从现行图鉴核对时看到差异**不要盲目"修正"**，对照 `backend/moves_compare.md`（招式全量审计）和 `backend/MOVES_AUDIT_151.md` 再动手。进化等级方面，原作进化石/亲密度/通信三种机制在本项目统一折算成等级（`build_evolution.py` 内嵌表），这也是有意简化。

---

## 四、获取方式速查（AI 可自动执行版）

把下面这段直接贴给你的 AI 编码工具即可启动（路径按你的仓库位置调整）：

```text
任务：为本地项目 studymon-homework 准备运行素材与静态数据。
1. 下载 https://github.com/veekun/pokedex 最新 release 的 CSV 压缩包，
   解压到 assets/veekun-csv/（校验存在 pokemon.csv / move_names.csv /
   type_efficacy.csv / encounters.csv 四张表）。
2. 从 github.com/PokeAPI/sprites 批量下载三套 1-151 PNG 到：
   assets/artwork/official/（official-artwork，{no}.png）、
   assets/artwork/gen1-red-blue/（red-blue 正面）、
   assets/artwork/gen1-red-blue-back/（red-blue back）。
   每套完成后校验恰好 151 个文件、无 0 字节文件。
3. cd backend && 用 make_thumbs.py 生成 thumb/。
4. pip 安装 fastapi uvicorn bcrypt pyjwt opencc-python-reimplemented 后，
   按 README「快速开始」init_db + 起服务，访问 /api/health 应返回 {"ok":true}。
红线：所有素材仅存本地，不上传网盘、不打包分享。
```

祝玩得开心。玩法设计（经验曲线、封印伙伴、捕捉谱系这些）欢迎随意取用——那部分才是这个项目真正想分享的东西。
