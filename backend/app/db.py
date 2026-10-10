# -*- coding: utf-8 -*-
"""数据库适配层：
  PKM_DB_ENGINE=mysql   生产/ECS（默认，pymysql）
  PKM_DB_ENGINE=sqlite  本机开发零安装（内置 SQLite：注册 NOW/LEAST 函数 + 方言转换）
业务 SQL 统一 MySQL 风格；sqlite 模式在 q/x 边界转换，业务代码不感知。
"""
import os
import re
import sqlite3
import datetime as _dt
from .config import DB, SQL_DIR

ENGINE = os.environ.get("PKM_DB_ENGINE", "mysql")
DBFILE = os.environ.get("PKM_SQLITE_FILE", os.path.abspath(os.path.join(SQL_DIR, "..", "pkm.sqlite3")))

_T = ["parent_user","student_user","homework_record","trainer_pokemon","pokemon_base",
      "skill_base","pokemon_skill_learn","type_effect","level_exp_table","region_base",
      "region_wild_pokemon","gym_base","gym_trainer_team","sys_config","task_template",
      "checkin_record","student_carry","exp_log","battle_record"]
_Q = re.compile(r"\bpokemon_homework\.(" + "|".join(_T) + r")\b")

def _to_sqlite(sql: str) -> str:
    sql = _Q.sub(r"\1", sql)
    sql = re.sub(r"\bINSERT IGNORE INTO\b", "INSERT OR IGNORE INTO", sql, flags=re.I)
    sql = re.sub(r"\bSET NAMES \w+", "", sql, flags=re.I)
    sql = re.sub(r"\bNOW\(\)", "CURRENT_TIMESTAMP", sql, flags=re.I)
    # LEAST(a,b) → MIN(a,b) 仅在两参数均为“字面量”时安全：
    # sqlite 的标量 min() 遇 NULL 参数返回 NULL，与 MySQL LEAST 语义不同；
    # 含列名/表达式的 LEAST 保持原样，交给已注册的 LEAST 自定义函数处理
    sql = re.sub(r"\bLEAST\(\s*(\d+)\s*,\s*(\d+)\s*\)", r"MIN(\1,\2)", sql, flags=re.I)
    sql = re.sub(r"\bON DUPLICATE KEY UPDATE\s+\w*\.?cfg_value\s*=\s*VALUES\(\s*\w*\.?cfg_value\s*\)",
                 "ON CONFLICT(cfg_key) DO UPDATE SET cfg_value=excluded.cfg_value", sql, flags=re.I)
    if re.match(r"\s*CREATE TABLE", sql, re.I):
        # sqlite: INT PRIMARY KEY AUTO_INCREMENT → INTEGER PRIMARY KEY AUTOINCREMENT（ROWID 别名，才可自增）
        sql = re.sub(r"\bINT\s+PRIMARY\s+KEY\s+AUTO_INCREMENT\b", "INTEGER PRIMARY KEY AUTOINCREMENT", sql, flags=re.I)
        sql = re.sub(r"\bAUTO_INCREMENT\b", "", sql)
        sql = re.sub(r"\bENGINE\s*=\s*\w+", "", sql)
        sql = re.sub(r"\bDEFAULT CHARSET\s*=\s*\w+", "", sql)
        # 表级/列级 COMMENT 'xxx' 与 COMMENT='xxx' → 去掉
        sql = re.sub(r"\s+COMMENT\s*=?\s*'[^']*'", "", sql)
        sql = re.sub(r"\s+COMMENT\s*=?\s*\"[^\"]*\"", "", sql)
        sql = re.sub(r"\bDATETIME\s+DEFAULT\s+CURRENT_TIMESTAMP\s+ON UPDATE CURRENT_TIMESTAMP",
                     "DATETIME DEFAULT CURRENT_TIMESTAMP", sql)
        sql = re.sub(r"\s*,?\s*FOREIGN KEY\s*\(\s*\w+\s*\)\s*REFERENCES\s+\w+\s*\(\s*\w+\s*\)", "", sql)
        sql = re.sub(r"\s*,?\s*UNIQUE KEY\s+\w+\s*\(", ", UNIQUE (", sql)
        sql = re.sub(r"\s*,\s*\)", ")", sql)
        sql = re.sub(r"\(\s*,", "(", sql)
        # sqlite 不支持列级引用其他库/表，REFERENCES 保留同库内即可
        sql = re.sub(r"\s+REFERENCES\s+pokemon_homework\.\w+\s*\(\s*\w+\s*\)", "", sql)
    return sql

# ---------- sqlite ----------
_local = None
def _sqlite_conn():
    global _local
    if _local is None:
        c = sqlite3.connect(DBFILE, check_same_thread=False, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.create_function("NOW", 0, lambda: _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        c.create_function("LEAST", -1, lambda *a: min(a))
        _local = c
    return _local

# ---------- mysql ----------
def _mysql_conn():
    import pymysql
    return pymysql.connect(**DB, cursorclass=pymysql.cursors.DictCursor, autocommit=False)

def conn():
    return _sqlite_conn() if ENGINE == "sqlite" else _mysql_conn()

def _adapt(sql):
    if ENGINE != "sqlite":
        return sql
    sql = _to_sqlite(sql)
    # MySQL 风格 %s 占位 → sqlite qmark（业务 SQL 无字面 % 字符，直接替换安全）
    return sql.replace("%s", "?")

def q(sql, args=None):
    if ENGINE == "sqlite":
        cur = _sqlite_conn().execute(_adapt(sql), args or ())
        return [dict(r) for r in cur.fetchall()]
    c = _mysql_conn()
    try:
        with c.cursor() as cur:
            cur.execute(sql, args or ())
            return cur.fetchall()
    finally:
        c.close()

def x(sql, args=None, ret_id=False):
    """执行写操作，返回 lastrowid（ret_id）或影响行数"""
    if ENGINE == "sqlite":
        cur = _sqlite_conn().execute(_adapt(sql), args or ())
        return cur.lastrowid if ret_id else cur.rowcount
    c = _mysql_conn()
    try:
        with c.cursor() as cur:
            cur.execute(sql, args or ())
            rid = cur.lastrowid
        c.commit()
        return rid if ret_id else cur.rowcount
    finally:
        c.close()

def cfg(key, default=None, cast=str):
    rows = q("SELECT cfg_value FROM sys_config WHERE cfg_key=%s", (key,))
    if not rows:
        return cast(default)
    return cast(rows[0]["cfg_value"])

def set_cfg(key, value):
    x("INSERT INTO sys_config(cfg_key,cfg_value) VALUES(%s,%s) "
      "ON DUPLICATE KEY UPDATE cfg_value=VALUES(cfg_value)", (key, str(value)))
