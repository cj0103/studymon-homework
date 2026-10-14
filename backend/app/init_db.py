# -*- coding: utf-8 -*-
"""一键初始化：建表（assets/out/00_schema + backend/sql/01_business）→ 导入静态数据 → 预置账号与任务菜单
用法:  PKM_DB_ENGINE=sqlite python -m app.init_db   本机开发（零安装）
       PKM_DB_ENGINE=mysql  python -m app.init_db   生产 ECS
幂等，可重复执行。"""
import os, re, glob, json, datetime as dt
from .config import DATA_DIR, SQL_DIR
from . import db
from .db import ENGINE, _adapt
from .auth import hash_pw

def _reg_funcs(c):
    c.create_function("NOW", 0, lambda: dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    c.create_function("LEAST", -1, lambda *a: min(a))

def _split(text):
    import sqlparse
    out = []
    for s in sqlparse.split(text):
        s = s.strip()
        # 去掉语句前置的注释行（sqlparse 会把注释粘在语句上）
        while s.startswith("--"):
            s = s.split("\n", 1)[1].strip() if "\n" in s else ""
        if s:
            out.append(s)
    return out

def _run(cur, path, ignore=False):
    for stmt in _split(open(path, encoding="utf-8").read()):
        if re.match(r"^\s*USE\s", stmt, re.I) or stmt.upper().startswith("SET NAMES"):
            continue
        if re.match(r"^\s*CREATE DATABASE", stmt, re.I) and ENGINE == "sqlite":
            continue
        sql = _adapt(stmt) if ENGINE == "sqlite" else stmt
        try:
            cur.execute(sql)
        except Exception as e:
            if ignore and any(k in str(e).lower() for k in ("exists", "duplicate")):
                continue
            if not ignore:
                raise

def _v(row, key, idx):
    return row[key] if isinstance(row, dict) else row[idx]

def _E(sql):
    return _adapt(sql) if ENGINE == "sqlite" else sql

def _seed(cur):
    # 表名不带库前缀（MySQL 已 USE 当前库，sqlite 无库概念）
    cur.execute(_E("SELECT id FROM parent_user WHERE phone=%s"), ("13800000000",))
    r = cur.fetchone()
    if not r:
        cur.execute(_E("INSERT INTO parent_user(phone,password) VALUES(%s,%s)"),
                    ("13800000000", hash_pw("admin123")))
        pid = cur.lastrowid
    else:
        pid = _v(r, "id", 0)
    cur.execute(_E("SELECT id FROM student_user WHERE parent_id=%s"), (pid,))
    r = cur.fetchone()
    if not r:
        cur.execute(_E("INSERT INTO student_user(parent_id,student_name,pin,current_region_id) "
                       "VALUES(%s,%s,%s,1)"), (pid, "小训练家", hash_pw("1234")))
        sid = cur.lastrowid
    else:
        sid = _v(r, "id", 0)
    cur.execute(_E("INSERT IGNORE INTO student_carry(student_id,carry_pending) VALUES(%s,0)"), (sid,))
    cur.execute(_E("SELECT task_name FROM task_template WHERE parent_id=%s"), (pid,))
    have = {_v(r, "task_name", 0) for r in cur.fetchall()}
    for i, (n, ic, cat) in enumerate([("语文作业", "book", "study"), ("数学作业", "calc", "study"),
                                      ("英语作业", "abc", "study"), ("课外阅读", "read", "study"),
                                      ("背诵/听写", "pen", "study"), ("吃饭快", "rice", "life"),
                                      ("睡觉早", "moon", "life"), ("自己整理书包", "bag", "life")]):
        if n not in have:
            cur.execute(_E("INSERT INTO task_template(parent_id,task_name,icon,category,sort) "
                           "VALUES(%s,%s,%s,%s,%s)"), (pid, n, ic, cat, i))
    cur.execute(_E("SELECT COUNT(*) FROM trainer_pokemon WHERE student_id=%s"), (sid,))
    if not _v(cur.fetchone(), 0, 0):
        # 全新开档：礼赠"不进化伙伴"皮卡丘（参考原作：拒进化的浪漫，雷丘只能野外捕捉）
        _give_starter(cur, sid)

def _give_starter(cur, sid):
    """按 pkm_starters 配置发放开档礼（当前=皮卡丘Lv5×1）；表缺失时兜底发皮卡丘"""
    try:
        cur.execute(_E("SELECT pokedex_no FROM pkm_starters ORDER BY pokedex_no"))
        nos = [_v(r, "pokedex_no", 0) for r in cur.fetchall()]
    except Exception:
        nos = []
    if not nos:
        nos = [25]
    for no in nos:
        cur.execute(_E("SELECT skill_id FROM pokemon_skill_learn "
                       "WHERE pokedex_no=%s AND learn_level<=5 ORDER BY learn_level DESC LIMIT 4"), (no,))
        skills = [_v(r, "skill_id", 0) for r in cur.fetchall()] or [33]
        # v10：入袋经验=经验组 Lv5 门槛（原写死 0 与 level 脱钩，扣经验场景会掉级）
        cur.execute(_E("SELECT pb.exp_group g, le.exp_fast f, le.exp_medium m, le.exp_slow s "
                       "FROM pokemon_base pb JOIN level_exp_table le ON le.level=5 "
                       "WHERE pb.pokedex_no=%s"), (no,))
        er = cur.fetchone()
        exp_val = 1
        if er:
            raw = {"fast": _v(er, "f", 1), "medium": _v(er, "m", 2),
                   "slow": _v(er, "s", 3)}.get(_v(er, "g", 0) or "medium", 1)
            exp_val = max(1, raw or 1)
        cur.execute(_E("INSERT INTO trainer_pokemon(student_id,pokedex_no,level,"
                       "total_exp,learned_skill_json,known_skill_json,is_in_team) "
                       "VALUES(%s,%s,5,%s,%s,%s,1)"),
                    (sid, no, exp_val, json.dumps(skills), json.dumps(skills)))

def _seed_tokens(cur, saved=None):
    """生成设备令牌；saved 提供旧 token 映射则原样恢复（重初始化不作废用户手里的链接）"""
    cur.execute(_E("SELECT COUNT(*) FROM device_token"))
    if _v(cur.fetchone(), 0, 0):
        return
    import secrets as _sec
    cur.execute(_E("SELECT id FROM parent_user WHERE phone=%s"), ("13800000000",))
    pid = _v(cur.fetchone(), "id", 0)
    cur.execute(_E("SELECT id FROM student_user WHERE parent_id=%s LIMIT 1"), (pid,))
    sid = _v(cur.fetchone(), "id", 0)
    for role, ref, label in [("kid", sid, "学习平板"), ("parent", pid, "爸爸手机"), ("parent", pid, "妈妈手机")]:
        key = (role, label)
        tk = (saved or {}).get(key) or \
            ("kid_" if role == "kid" else "par_") + _sec.token_urlsafe(18)
        cur.execute(_E("INSERT INTO device_token(token,role,ref_id,label) VALUES(%s,%s,%s,%s)"),
                    (tk, role, ref, label))
        print(f"  设备令牌 [{label}]: {'/?k=' if role == 'kid' else '/parent/?k='}{tk}")

class _Wrap:
    """包装 sqlite3.Connection：记录最后一次游标，支持 with + fetchone 习惯用法"""
    def __init__(self, c):
        self.c = c
        self._cur = None
    def execute(self, sql, args=()):
        self._cur = self.c.execute(sql, args)
        return self._cur
    def fetchone(self):
        return self._cur.fetchone()
    def fetchall(self):
        return self._cur.fetchall()
    @property
    def lastrowid(self):
        return self._cur.lastrowid
    def __enter__(self):
        return self
    def __exit__(self, *a):
        self.c.commit()

def main():
    if ENGINE == "sqlite":
        saved_tokens = {}
        if os.path.exists(db.DBFILE):
            # 原地重置：删表重建（避免删除文件触发回收站拦截，也避免服务连接持有文件句柄）
            con = db._sqlite_conn()
            # 先抢救设备令牌：重建后按标签恢复，用户收藏的链接不失效
            for tk, role, label in con.execute(
                    "SELECT token,role,label FROM device_token WHERE enabled=1").fetchall():
                saved_tokens[(role, label)] = tk
            con.execute("PRAGMA foreign_keys=OFF")
            for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                    "AND name NOT LIKE 'sqlite_%'").fetchall():
                con.execute(f"DROP TABLE IF EXISTS [{t}]")
            con.execute("DELETE FROM sqlite_sequence")
            con.execute("PRAGMA foreign_keys=ON")
        c = _Wrap(db._sqlite_conn())
        _reg_funcs(db._sqlite_conn())
        _run(c, os.path.join(DATA_DIR, "00_schema.sql"), ignore=True)
        _run(c, os.path.join(SQL_DIR, "01_business.sql"), ignore=True)
        _run(c, os.path.join(SQL_DIR, "02_device_token.sql"), ignore=True)
        for f in sorted(glob.glob(os.path.join(DATA_DIR, "0[1-6]*.sql"))):
            _run(c, f, ignore=True)
        for col, table, ddl in [("pin", "student_user", "VARCHAR(10)"),
                                ("exp_mode", "student_user", "VARCHAR(10)"),
                                ("slot", "trainer_pokemon", "TINYINT"),
                                ("known_skill_json", "trainer_pokemon", "TEXT"),
                                ("sealed", "trainer_pokemon", "TINYINT DEFAULT 0"),
                                ("evolved_json", "checkin_record", "TEXT"),
                                ("gift_gym_sort", "trainer_pokemon", "INT"),
                                ("seal_start_date", "trainer_pokemon", "DATE"),
                                ("hunt_region_id", "student_user", "INT NOT NULL DEFAULT 0"),
                                ("caught_today", "student_user", "INT NOT NULL DEFAULT 0"),
                                ("catch_date", "student_user", "DATE")]:
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
            if col not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        _seed(c)
        _seed_tokens(c, saved_tokens)
    else:
        import pymysql
        root = pymysql.connect(host=db.DB["host"], port=db.DB["port"], user=db.DB["user"],
                               password=db.DB["password"], autocommit=True)
        with root.cursor() as cur:
            _run(cur, os.path.join(DATA_DIR, "00_schema.sql"))
            _run(cur, os.path.join(SQL_DIR, "01_business.sql"))
            _run(cur, os.path.join(SQL_DIR, "02_device_token.sql"), ignore=True)
            for col, table, ddl in [("pin", "student_user", "VARCHAR(10) NULL"),
                                    ("exp_mode", "student_user", "VARCHAR(10) NULL"),
                                    ("slot", "trainer_pokemon", "TINYINT NULL"),
                                    ("known_skill_json", "trainer_pokemon", "TEXT NULL"),
                                    ("sealed", "trainer_pokemon", "TINYINT NOT NULL DEFAULT 0"),
                                    ("evolved_json", "checkin_record", "TEXT NULL"),
                                    ("gift_gym_sort", "trainer_pokemon", "INT NULL"),
                                    ("seal_start_date", "trainer_pokemon", "DATE NULL"),
                                    ("hunt_region_id", "student_user", "INT NOT NULL DEFAULT 0"),
                                    ("caught_today", "student_user", "INT NOT NULL DEFAULT 0"),
                                    ("catch_date", "student_user", "DATE NULL")]:
                cur.execute(f"SHOW COLUMNS FROM {table} LIKE %s", (col,))
                if not cur.fetchone():
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            for f in sorted(glob.glob(os.path.join(DATA_DIR, "0[1-6]*.sql"))):
                _run(cur, f, ignore=True)
            _seed(cur)
            _seed_tokens(cur)
        root.close()
    # 附加数据表：宝可梦档案(图鉴简介/身高体重) + 进化链（幂等重建，内嵌数据离线可用）
    try:
        from build_profile import build as build_profile
        from build_evolution import build as build_evo
        build_profile(dbfile=db.DBFILE, apply=True)
        build_evo(dbfile=db.DBFILE, apply=True)
    except Exception as e:
        print("WARN 附加表生成失败(可稍后手动跑 build_profile/build_evolution):", e)
    print(f"INIT OK ({ENGINE})  parent=13800000000/admin123  student=孩子小名/1234")

if __name__ == "__main__":
    main()
