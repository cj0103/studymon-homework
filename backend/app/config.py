import os

# 数据库连接（开发默认本机 root 无密码；部署 ECS 时用环境变量覆盖）
DB = dict(
    host=os.environ.get("PKM_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("PKM_DB_PORT", "3306")),
    user=os.environ.get("PKM_DB_USER", "root"),
    password=os.environ.get("PKM_DB_PASS", ""),
    database="pokemon_homework",
    charset="utf8mb4",
)

JWT_SECRET = os.environ.get("PKM_JWT_SECRET", "dev-only-secret-change-me")
JWT_DAYS = 30
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
SQL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sql")
DATA_DIR = os.path.abspath(os.path.join(SQL_DIR, "..", "..", "assets", "out"))
ASSETS_DIR = os.path.abspath(os.path.join(SQL_DIR, "..", "..", "assets"))
