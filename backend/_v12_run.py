# -*- coding: utf-8 -*-
"""单进程驱动：起 uvicorn 8471 + 跑 _v12_ui_test.py（v12 专项，不 reset 库）"""
import os, sys, threading, time
os.environ["PKM_DB_ENGINE"] = "sqlite"
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uvicorn
from app.main import app

cfg = uvicorn.Config(app, host="127.0.0.1", port=8471, log_level="warning")
server = uvicorn.Server(cfg)
th = threading.Thread(target=server.run, daemon=True)
th.start()
for _ in range(60):
    if server.started:
        break
    time.sleep(0.5)
assert server.started, "服务未能启动"
print("[DRIVER] server started in-process", flush=True)

import runpy
try:
    runpy.run_path("_v12_ui_test.py", run_name="__main__")
finally:
    server.should_exit = True
    th.join(timeout=5)
