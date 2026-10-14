# 宝可梦作业激励游戏 · 后端（阶段2 已通）

FastAPI + 双数据库引擎（开发 SQLite / 生产 MySQL），前端为 `web/index.html` 单文件响应式 H5（孩子平板 + 家长手机同一 URL）。

## 本地启动（零安装，SQLite）

```bash
cd backend
PKM_DB_ENGINE=sqlite python -m app.init_db      # 建表+静态数据+种子账号（可重复执行，原地重置）
PKM_DB_ENGINE=sqlite python -m uvicorn app.main:app --host 127.0.0.1 --port 8300
```

- 家长端：`13800000000 / admin123`；孩子端：`孩子昵称(1号) / PIN 1234`（上线前必改）
- 冒烟测试（先起服务）：`PKM_DB_ENGINE=sqlite python smoke_test.py`（31 项断言）

## 生产部署（ECS · MySQL）

设计时已为 ECS 留好口子：**默认引擎就是 `mysql`**，本机测试才显式设 `sqlite`。所有敏感项走环境变量覆盖。

### 1. 准备
- ECS 装 Python 3.11+ 与 MySQL 8；建库：`CREATE DATABASE pokemon_homework CHARACTER SET utf8mb4;`
- 上传整个项目目录（`backend/` + `assets/`，二者同级，`config.py` 按 `../../assets` 定位静态素材）
- 装依赖：`pip install fastapi uvicorn pyjwt bcrypt pymysql sqlparse`

### 2. 环境变量（写进 systemd 或 .env，不要硬编码）
```bash
PKM_DB_ENGINE=mysql
PKM_DB_HOST=127.0.0.1        # 同机 MySQL
PKM_DB_USER=pkm
PKM_DB_PASS=<强密码>
PKM_JWT_SECRET=<openssl rand -hex 32 生成>   # 必须改！默认值是 dev-only
```

### 3. 初始化 + 常驻运行
```bash
cd backend
python -m app.init_db        # 建表+静态数据+种子；首次会打印三张设备链接，收藏到对应设备
```
用 systemd 常驻（崩溃自拉起、开机自启），避免"进程随会话结束被回收"：
```ini
# /etc/systemd/system/pkm.service
[Unit]
Description=PKMN Homework
After=network.target mysql.service
[Service]
WorkingDirectory=/opt/pkmn-homework/backend
Environment=PKM_DB_ENGINE=mysql
Environment=PKM_DB_HOST=127.0.0.1
Environment=PKM_DB_USER=pkm
Environment=PKM_DB_PASS=xxx
Environment=PKM_JWT_SECRET=xxx
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8300
Restart=always
[Install]
WantedBy=multi-user.target
```
`systemctl daemon-reload && systemctl enable --now pkm`

### 4. 网络与访问
- **安全组放行 80/443**（给 Nginx），**不要**直接放行 8300；uvicorn 只监听 127.0.0.1
- Nginx 反代 8300；静态素材 `/static/artwork|audio` 可由 Nginx 直接指向 `assets/` 减压
- 强烈建议上 HTTPS（Let's Encrypt）：设备令牌在 URL query 里，明文 HTTP 下局域网可接受、公网必须加密
- 换域名后，三条设备链接的 host 部分要更新（令牌本身不变），重新收藏一次

### 3.9 移动端使用（二维码 + PWA）
- **免敲链接**：家长端「👪成员 / 📱设备」每条设备链接可一键出示二维码（`web/qrcode.min.js` 本地渲染，无外部依赖），手机/平板相机扫码直达
- **PWA 装桌面**：`web/manifest.json` + `icon-192/512.png`（皮卡丘+精灵球色带），安卓 Chrome 打开后"安装应用"即钉到桌面，全屏独立窗口日常零输入进入；家长端 JWT 存 localStorage（关页面不掉登录，重开免 PIN）
- 设备命名规范：孩子端设备统一叫**「学习平板」**（种子 init_db/reset_game 及 ECS 现库已改；标签可在家长端设备管理随时改名，令牌不变）。孩子昵称是用户数据，家长端可改，代码不硬编码
- 换域名后 PWA 页面零改动——重新出示二维码、重新"安装"一次即可

### 5. 上线前必改（安全）
- 家长密码 `admin123` → 家长页「👪成员」改
- 孩子 PIN `1234` → 同上
- `PKM_JWT_SECRET` 必须换成随机长串（默认值泄露=可伪造任意登录）

### 6. 令牌迁移提醒
本机测试期的三条链接令牌存在**本机 SQLite**里。ECS 用全新 MySQL，`init_db` 会生成**全新令牌**——把新 init_db 打印的三条链接重新收藏到平板/手机即可（旧的作废无妨）。

业务 SQL 本身就是 MySQL 风格，SQLite 仅是开发期适配（见 `app/db.py` `_to_sqlite`）。

## 设备访问方式（无 MAC 读取能力，用专属链接等效绑定）

- **孩子平板**：扫「学习平板登录码」→ Chrome 菜单「安装应用」钉到桌面 → 点图标零登录直进首页（令牌存 localStorage，重启不丢）。注意：**http+IP 下 Chrome 不弹"安装应用"**，菜单里是"添加到主屏幕"，功能等效；上域名+HTTPS 后自动升级为完整的 PWA 安装
- **家长手机**：扫家长设备二维码 → 输一次家长密码，之后本设备免输（localStorage，关页面不丢）；全系统密码框明文显示（家庭监督应用，无敏感密码）
- **兜底**：`/parent` 手动粘贴 par_ 令牌；家长登录 `13800000000/admin123` 仍可用
- 管理入口：家长页「📱设备」标签可签发/吊销/改名任意设备链接（孩子端统一命名"学习平板"），吊销即时生效
- `init_db` 首次会打印三张设备链接（学习平板/爸爸手机/妈妈手机），扫码即可

## 重置游戏数据

`PKM_DB_ENGINE=sqlite python reset_game.py` — 清空打卡/战斗/经验，宝可梦回到 Lv5 御三家；账号与设备令牌保留。

## 家长管理页能力

- **👪成员**：改孩子昵称/PIN、重新生成平板链接（旧链接立失效）、改家长密码（=链接解锁密码）、学习日战斗开放开关 `battle_weekday_open`（1=测试期常开 / 0=仅周末，默认 1）
- **📱设备**：签发/吊销任意设备链接
- 孩子端宝可梦卡：四维参数（HP/攻/防/速）+ 上阵⬆/撤下⬇（点别人上阵自动排队满提示；撤下即时生效）

## 技能机制（v2·孩子自主选招）

- **已学袋**（`known_skill_json`）：升级到达级新招自动入袋，**永不被遗忘**；捕获入库一次性入袋
- **上场技能**（`learned_skill_json`）：孩子在宝可梦页从已学袋里点格子自由勾选，**最多 4 个**、至少 1 个，点"💾 保存技能"生效；战斗只用携带的技能
- 服务端校验：非已学袋技能 / 超 4 个 / 空列表 / 别人的宝可梦 均拒绝
- 详情页（点宝可梦卡片进入）：档案（分类/身高体重/图鉴介绍）+ 四维进度条 + 技能勾选 + 未来可学预告 + **进化之路预告**（下一形态与所需等级）

## 开档礼赠·不进化伙伴

- 新开档发 **皮卡丘 Lv5 ×1**（`pkm_starters` 表配置，`build_evolution.py` 维护）；参考原作它**永不进化**（进化链已剔除 25→26）
- **雷丘只能野外捕捉**：区域2（发电厂，Lv50 稀有）；伊布(133)可抓但不自动进化（3 分支留作后续彩蛋）
- 已开旧档不追溯（保留现有御三家）；`reset_game.py` 按新口径重置
- 详情页 `evolution=null` 时不显示"进化之路"卡

## 野生分布与冒险指南（v5 · 剧情难度阶梯版）

- **8 区域 × 8 道馆严格 1:1**（区 i ↔ 第 i 馆 ↔ 解锁需 i-1 徽章）：深灰周边 / 华蓝周边 / 枯叶周边 / 玉虹~双子岛群岛 / 浅红狩猎区 / 金黄~紫苑 / 红莲岛·宝可梦屋 / 常磐森林~冠军之路。`_on_foe_down` 打完第 n 馆 → `current_region_id=LEAST(8, n+1)`
- `rebuild_wild.py`（**v3 重写，不再依赖 veekun**）手工剧情归属表 `PLOT_HOME`：
  - **只含未进化形态 + 中间形态**（断言拦截一切进化终点；蛹类 11/14 额外剔除）——"地图只需未进化宝可梦"，进化终点改由道馆阵容展示；雷丘(26，用户点名可抓)为唯一终点特例
  - **御三家(1,4,7)入池**（稀有权重 3）：妙蛙种子→区2华蓝水手梗、小火龙→区3枯叶10号道路梗、杰尼龟→区4玉虹海边梗；雷丘→区3发电厂
  - **8 区难度阶梯**：区1 虫线开局（均值 Lv9）逐区递增 → 区8 常磐~冠军之路最强（均值 Lv37），脚本断言各区等级带中值均值单调不降（修复了旧版区8 绿毛虫倒挂问题）
  - 合计 82 种、每只唯一区（跨区重复=0 断言）
- **道馆阵容重配**（`rebuild_gym_teams.py` 新建）：每馆 4 只 = 招牌 + 主题怪 + 被野生池剔除的**进化终点展示怪**（"野生抓不到、道馆看得到"）；小刚+隆隆岩/钻角犀兽、小霞+宝石海星/胖可丁、马志士+雷丘/皮卡丘/三合一磁怪、莉佳+霸王花/椰蛋树/大食花、阿桔+双弹瓦斯/臭臭泥、娜姿+引梦貘人/呆壳兽/胡地、夏伯+烈焰马/风速狗、坂木+三地鼠/尼多王/拉达/大嘴雀（"常磐老大用常磐怪"）；不带显式 moves → battle 现算 learnable 末4招；断言展示怪与野生池零交集、馆主等级单调
- **图鉴"拥有过即点亮"**（`/child/pokedex`）：当前背包（含封印怪）+ 进化链前身回溯（持有妙蛙花→种子/草同点亮）；只显名称不显等级；前端图鉴卡去 Lv、标题"点亮=拥有过，进化后前身也保留"
- 修了旧拉伸 bug：veekun 异常等级带（min=114）产出过 Lv123-50 倒挂区间，现强制 lo≤hi；旧 4 区学生进度自动迁移 `region*2-1`
- **指南图加载提速**：`make_thumbs.py` 从 official 立绘（20.9MB）批量生成 96px 透明缩略图（1.8MB）到 `assets/artwork/thumb/`，guide 页改用 `/static/artwork/thumb/{no}.png` + `loading="lazy"`（ECS 无 Pillow，缩略图 SFTP 直传）
- **已抓显名 bug 修复**：guide 前端原读 `p.own` 但后端返回 `owned`，导致已捕捉仍显示"？？？"；现后端双字段兼容 + 前端统一读 `owned`
- 冒险指南页 `/guide`：每区可抓清单（缩略图/已抓变绿显名）、对应道馆与解锁徽章、进化说明、战斗小课堂（命中率/增减益/异常状态）；接口 `GET /child/guide`
- **veekun ECS 依赖**：build_skills_v3 需 5 个 CSV（rebuild_wild v3 起不再需要 veekun，已放 `backend/assets/veekun-csv` 的 8 个 CSV 保留仅供回溯）
- **招式观感核查结论**（用户质疑"小拉达的电系电光一闪"）：电光一闪是**普通系**招（库内 skill_type='一般'），小拉达 RB 原作 Lv7 升级可学——非 bug；跨属性借招清洗后（TM 按本属性→一般→其余截断 cap6、家族借招仅限一般+本属性），学习表 3059→1900 条、130 招/151 覆盖不变，审计仅剩一般系豁免项


## v3 招式系统（原作 165 招 → 实装 130）

- 数据源 veekun-csv（`../assets/veekun-csv`，ECS 只需 5 个 CSV：moves/move_names(lang12=简中)/move_meta/move_meta_stat_changes/pokemon_moves，放 `backend/assets/veekun-csv`，跑 build 时 `PKM_VEEKUN` 指过去）
- `build_skills_v3.py`：**实装 130 / 剔除 35**（剔除=复杂状态栈 transform/metronome、反击反伤 counter/bide、束缚 bind/wrap、两回合蓄力 dig/fly、无战斗价值 splash/struggle 等，见 EXCLUDE_IDENTS）。TM 只取红蓝 vg∈{1,2}；定威力招归一化（dragon-rage 60、hyper-fang 70 等）
- 学习表 `pokemon_skill_learn` 整表重建：**3059 条、151/151 全覆盖**（每只 10~42 招）；皮卡丘冻结规则保持（破坏光线 Lv28、16 级起学雷丘线）
- 一次性迁移顺序（sqlite 本地/ECS 相同）：`migrate_v3.py`（加 ailment 列）→ `migrate_v3b.py`（skill_base 重建为 INTEGER PRIMARY KEY，修复历史 NULL id 污染）→ `PKM_APPLY=1 build_skills_v3.py` → `PKM_APPLY=1 rebuild_gyms_v3.py`（8 馆按新学习表段位重配招）
- **孤儿清理教训**：旧版 build 曾把「是否在本轮 name2id」当孤儿判定，导致 ECS 残留 6 个已剔除招（飞翔/乱击/挖洞/火箭头锤/投球/挣扎，136≠130）；现按「未被学习表引用」判定，重跑幂等
- **sqlite 致命陷阱**：建表 `id INT PRIMARY KEY` 不是 rowid 别名（无自增、无 NOT NULL），所有不显式给 id 的插入静默写 NULL——migrate_v3b 已把 skill_base/pokemon_skill_learn 重建为 `INTEGER PRIMARY KEY`；新库建表 DDL（sql/01_business.sql）后续宜同步改

## 状态异常系统（v3，6 种全实装）

- **poison 中毒**：每次出手前扣 1/8 最大HP（不递增）｜**para 麻痹**：25% 不能行动｜**sleep 睡眠**：1~3 回合不能行动，醒来可动｜**burn 烧伤**：攻击×0.5（取整前介入，精确减半）｜**freeze 冰冻**：每回合 25% 解冻｜**confuse 混乱**：35% 自伤 1/10 不致死
- 免疫（Gen1 简化）：火免烧、冰免冻、地/岩/钢免毒；捕获率：目标带异常 ×1.5（上限 0.95）
- 招式标注：`skill_base.ailment + ailment_chance`——攻击招附加异常 20 个（按概率，tri=麻痹/睡眠/冰冻三选一）；变化异常招 13 个（status_sleep/para/poison/confuse，命中即施加）；共 33 个异常招
- 会话内状态随单位 dict 存续（换人不消，战斗结束随会话销毁）；响应 `my/foe` 单位带 `status` 字段，前端 HP 行显示彩色徽章（紫/橙/灰/橙红/蓝/粉），技能按钮副文本带异常标签；`/guide` 战斗小课堂含异常一览表
- 野怪异常招出招权重 ×0.5（对小孩友好）；单次行动伤害上限 BATTLE_CAP=50（防馆主越级一击杀娃）
- 增益封顶 ×2.0 / 减益下限 ×0.5（会话内乘算，战斗结束内存清零）

## 战斗机制速览

- **命中率**：攻击招全部有 `accuracy`（数据 75~100），判定 `randint(1,100)<=accuracy`；空/NULL 兜底按 100
- **增益/减益已区分**：变化招按 `effect_type` 分 `atk_up/def_up`（增益自己）与 `atk_down/def_down`（**减益作用于对手**，v3 修正旧语义），`effect_value` 为倍率（剑舞×2、叫声×0.7、刺耳声×0.5）
- **属性倍率**：在取整前介入（`int(raw*rate)`），×0.5 恰好精确减半
- **持续回合**：当前实现**整场战斗有效**（会话内乘算叠加，战斗结束随内存会话清零）——简化设计，如需原作"能力阶级6档/换人重置"后续可升级
- **前端透明化**（`web/index.html` `moveSub()`）：技能配置卡/未来可学/战斗按钮均显示完整参数——攻击招 `属性·威力N·命中N%`；变化招 `增益·自身攻击↑↑`（绿）/ `减益·对方防御↓↓`（红）`·整场有效`，档位按 `effect_value`（1.5/0.7→单箭头，2/0.5→双箭头）
- **上场技能下限**：最多 4 个、**至少 1 个**（战斗至少要有一招）——`set_moves` 空列表 400 + 前端 `tglMove` 回弹拦截，界面提示语已写明；想只带 2 个：把其余逐个点掉即可
- **技能选择 bug 修复**（第四轮）：`pokeDetail` 原本每次渲染都用服务器数据重置 `detailSel`，导致点取消后立刻回弹——改为 `pokeDetail(id, keepSel)`，`tglMove` 本地切换后保留选择态，点「保存技能配置」才落库
- **野生等级动态跟随进度**：`battle.dynamic_level(sid,lo,hi)` 按 `T=max(6, 出战队伍最高级+2)` 缩放静态等级带——低段（hi≤T）不动，高段成比例下移、天花板 `T+4`。Lv5 开档时全区野生上限 Lv8；队伍练强后同一地点野怪逐渐接近原带（保留发电厂雷丘 Lv50 等后期挑战）
- **指南不标等级**：野生等级既然是浮动的，`/child/guide` 清单不再返回 lo/hi（只留 `team_top_level` 供"等级跟着你涨"文案），避免展示即失真
- **野怪选招 = 末4招**：`learnable(no,lv)` 取"≤当前等级的学习池"按学习等级升序的**末尾 4 项**（即最后习得的 4 个招式，不足 4 全取），出招顺序新→旧——低等级野怪自然只用初始招，等级越高招式越"当家"
- 道馆/野生战斗等级带见 `region_wild_pokemon`；道馆馆主阵容 06d 显式授予 4 招

## 进化机制（到级自动进化）

- 数据表 `pkm_evolution(from_no, to_no, min_level)` 由 `build_evolution.py` 生成（Gen1 69 条，内嵌数据离线可用，init_db 收尾幂等重建）
- **统一等级进化**：原作进化石/亲密度/通信一律折算成等级（如皮卡丘 22 级、卡比兽 36 级）；伊布(133)一对三需分支选择，**不参与自动进化**，保留特殊感
- **不进化皮卡丘的招式成长**（正式上线档已应用，本地/ECS 一致）：`pokemon_skill_learn(pokedex_no=25)` = 皮卡丘+雷丘全池去重（含雷丘专属破坏光线），按 reskill_learn 统一节奏重排（前 2 个 Lv1、每 3 级解锁 1 个）——Lv1 摇尾巴/叫声 → Lv16 百万吨重拳 → **Lv28 破坏光线封顶**，16 级后照常学雷丘线大招；注意 reskill_learn.py 若重跑会把此重排覆盖回通用规则，需保留本重排或重跑后再对 25 执行一次同节奏重建
- 升级结算后自动检查：达到 `min_level` 即把 `pokedex_no` 换成进化形态（一次可连锁跨多级），**已学袋保留并并入新形态到级新招，上场 4 招配置不变**
- 进化是"惊喜"：家长审批响应带 `evolved` 名单；进化事件写入 `checkin_record.evolved_json`，孩子首页显示"🎊 你的宝可梦进化了！"金卡；详情页"进化之路"卡预告下一形态
- 学习等级为原作近似重排（`reskill_learn.py` 按威力升序+攻击招优先；原 TM/教学招 learn_level=0 的占位数据已全部重算）

## 已冻结的经验规则（v2）

每日定额 230（家长可调）｜学习日(一~五) 21:30 前提交获批 ×1.2｜连击第 7 天 +50｜每日上限 320 超出顺延｜扣减批准 -10/-20｜驳回当日 0（已发可撤销扣回）｜经验只来自打卡；队伍 3 只平分（可切主力 60/20/20）；道馆/野生战斗仅周末，捕获每周 3 次。

## 已知边界

- 战斗增益/状态异常只存内存（服务重启即失效，符合规则设计）；会话按学生 id 单例，两端不可同时开打。
- uvicorn 勿用 `--reload`（Windows 监视不可靠）；**改 battle.py 等后端代码后必须重启服务**（`__pycache__` 不会自动失效，曾因此白测半小时）。
- 快手加成用千分比整数避免浮点误差（勿改回 `base*(mult-1)`）。
- `ensure_known` 兜底回填 learned 是"先读后更"，同一次 GET 响应里看不到回填结果（断言/测试需二次读取）。
- 本机如有系统代理（HTTP_PROXY），测试脚本访问 127.0.0.1 必须 `ProxyHandler({})` 直连，否则被代理劫持成 502。

## 道馆赠礼 · 封印宝可梦（v4，2026-10-07）

- **发放**：每过第 i 馆首杀送一只封印伙伴（`app/gift.py GYM_GIFTS`）：1馆卡比兽143 → 2馆急冻鸟144 → 3馆闪电鸟145 → 4馆火焰鸟146 → 5馆超梦150 → 6馆化石翼龙142 → 7馆梦幻151 → 8馆多边兽137。入库 Lv10、`sealed=1`、不入队不入经验；`_on_foe_down` 发徽章同帧发放（battle_record 有该馆 win 记录即不重发，reset_game 清记录后重打视为重开）。
- **激活**：家长审批 `_settle` 末尾检查——含归属日连击获批 ≥ `seal_streak_days`(7) 天 → 全部封印怪激活：等级=出战队伍最高（空队兜底 Lv16），total_exp 对齐经验表，到级技能回填已学袋；审批响应带 `activated` 名单（家长页 toast 展示）。
- **隔离**：`sealed=1` 不进 `_team_payload`/set_team/exp/evolve；列表与详情走"封印态封装"（技能袋显示为空，详情给一个"看家招"预告 `SEAL_DISPLAY_MOVE`）；野生池不含赠礼怪。
- **前端**：首页"🔮 封印中的伙伴"卡（灰度图+连击进度条 x/7）；指南"🎁 道馆礼物"板块（8 馆发放表+状态）；收集口径=主线可收齐 **148 只**，伊布三分支（134/135/136）节日限定。
- **野生补池 6 只**（rebuild_wild `MANUAL_SPAWN`，凑 106 种）：大舌头108→区1、大葱鸭83/魔墙人偶122→区4、迷唇姐124/菊石兽138→区7、化石盔140→区8。
- 迁移：`migrate_v4_seal.py`（幂等 ALTER，本地/ECS 已执行）；init_db 两处 DDL 清单已加 sealed 列。
- 冒烟：smoke_test 第 14 节全链路（植入→隔离→连击7天激活→等级=队最强→可上阵→幂等）。

## 151 只技能全量核查（2026-10-07）

结论：**没有胡乱的技能**。自动比对 139/151 与原作 RB 完全一致；其余 12 只 62 项全部归入
"皮卡丘雷丘线豁免 / 保留决策（梦幻催眠术等4项）/ 低位兜底补池（绿毛虫线、鲤鱼王、凯西、百变怪——全是本系或一般系招）"。
招牌招抽查 26 命中、4 项"缺失"均为抽查清单笔误（暗影球是 Gen2 招等）；完整性四查全绿
（等级越界0、Lv5无招可学0、池<3招0、无本系招0）。详见 `MOVES_AUDIT_151.md`；复跑 `python _audit_moves.py`。

## ECS 部署备忘（v3 轮，2026-10-06）

- 服务：systemd `pkm`（sqlite 引擎），端口 8002；部署脚本 `backend/_deploy_ecs6*.py`（paramiko，备份→上传→停服→迁移→重建→启服→验证）
- ECS 库迁移链已跑通：migrate_v3 → migrate_v3b（65 行重建，学习表 1404→733 悬空清零）→ build_skills_v3（65→130 招、学习表 3059）→ 孤儿清理 6 行 → rebuild_gyms_v3（APPLIED 8）
- 公网验证：health/index/guide 200；定向战斗端到端观测「冰冻」状态生效；存量 4 只 trainer 技能已对齐 v3 新 id
- 备份：`/home/ubuntu/pkm_bak6_appweb_*.tgz`、`/home/ubuntu/pkm_db_bak6_*.sqlite3`

## 图鉴介绍 v2（2026-10-07 · _deploy_ecs10.py）

- 起因：旧 `build_profile.py` 用「属性→模板」兜底生成 intro，产生"小拉达是鸟/哺乳类、性格温顺"等 136 条错误文案
- 现在：`build_profile.py` 改为 **CURATED 全量 151 条手写**（分类词 + 图鉴正文，参照红/蓝版图鉴中文通行译本风格），TYPE_DESC 模板已删除；断言保证 151 全覆盖、无占位残留、genus 无英文
- 部署序：备份库 → 上传 build_profile.py → `PKM_DB_ENGINE=sqlite PKM_APPLY=1 venv/bin/python build_profile.py`（幂等重建表）→ sqlite probe（无旧模板词）→ 重启 pkm
- 身高体重（HW 内嵌字典）不变；`pkm_profile` 表结构不变，前端无需改动
- 备份：`pkm.sqlite3.bak_profile_*`、`build_profile.py.bak_*`

## ECS 部署备忘（v5 轮，2026-10-07 · _deploy_ecs9.py）
- 上传 6 文件：rebuild_wild.py(v3重写)、rebuild_gym_teams.py(新)、pokemon.py、index.html、guide.html、smoke_test.py
- 执行序：停服 → `rebuild_wild.py`（82种/阶梯单调断言）→ `rebuild_gym_teams.py`（8馆×4只/终点零交集断言）→ py_compile → 清 __pycache__ → 启服 → sqlite probe → 公网验证（首页"拥有过"、指南"野生可遇"均命中）
- v3 野生池**不再依赖 veekun CSV**（手工 PLOT_HOME 剧情表）
- 备份：`/opt/pkmn-homework/backend/app_bak_v3_*`、`pkm.sqlite3.bak_v3_*`
- 冒烟第 14 节口径更新：野生 82 种、御三家/雷丘在池、终点 12 只抽检不在池、区均带单调（db.q 直查 region_wild_pokemon）

## ECS 部署备忘（v4 轮，2026-10-07 · _deploy_ecs8.py）

- 迁移链新增：`migrate_v4_seal.py`（trainer_pokemon.sealed，幂等）；`rebuild_wild.py` 带 `MANUAL_SPAWN` 补录 6 只（重跑幂等，先清后灌）
- 本轮上传 13 个文件（gift.py 为新增模块）；公网验证：health/index/guide 200、首页含"封印"文案、野生 106 种/跨区重复 0、赠礼 8 只不在野遇池
- 备份：`/home/ubuntu/pkm_bak8_appweb_*.tgz`、`/home/ubuntu/pkm_db_bak8_*.sqlite3`
- 冒烟提醒：smoke 第 14 节会伪造 7 天 checkin_record 并在结尾自清（DELETE 当日与测试流水）；本地/ECS 复用同库前先 `reset_game.py`
