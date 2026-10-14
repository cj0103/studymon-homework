# -*- coding: utf-8 -*-
"""单进程冒烟驱动：reset 干净库 → 起 uvicorn 服务线程 → smoke_test → v12 专项（同进程同库）
用法: python _smoke_all.py
"""
import os, sys, threading, time
os.environ["PKM_DB_ENGINE"] = "sqlite"
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import db  # noqa: E402
assert db.ENGINE == "sqlite", "必须 sqlite 模式"
import reset_game  # noqa: E402
reset_game.main()
print("[DRIVER] reset done", flush=True)

import uvicorn  # noqa: E402
from app.main import app  # noqa: E402

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

import runpy  # noqa: E402
_rc = 0
try:
    runpy.run_path("smoke_test.py", run_name="__main__")
    print("[DRIVER] ===== v12 专项开始 =====", flush=True)
    _g = runpy.run_path("_v12_ui_test.py", run_name="__main__")
    print("[DRIVER] ===== v15 专项开始 =====", flush=True)
    runpy.run_path("_v15_battle_test.py", run_name="__main__")
    print("[DRIVER] ===== v17 专项开始 =====", flush=True)
    _t17 = runpy.run_path("_v17_dexline_test.py", run_name="__main__")
    _f17 = _t17.get("FAILS", [])
    if _f17:
        print("[DRIVER] v17 专项 FAILS:", _f17, flush=True)
        raise SystemExit(1)
    # v16：v12 把队伍清空后未恢复（历史遗留，v15 组队依赖此修复）
    import json as _json
    from app import db as _d
    from app.routers.pokemon import learnable as _lk
    _t = _d.q("SELECT id,pokedex_no,level FROM trainer_pokemon WHERE student_id=1 ORDER BY id LIMIT 1")
    if _t:
        _mvv = _lk(_t[0]["pokedex_no"], _t[0]["level"])
        _d.x("UPDATE trainer_pokemon SET is_in_team=1, slot=0, learned_skill_json=%s WHERE id=%s",
             (_json.dumps(_mvv), _t[0]["id"]))
        print("[DRIVER] v16 恢复出战 1 只有招怪 id=", _t[0]["id"], flush=True)
    print("[DRIVER] ALL PASSED (smoke + v12 + v15 + v17)", flush=True)
except SystemExit as e:
    _rc = e.code or 0
except BaseException:
    import traceback
    traceback.print_exc()
    _rc = 1
finally:
    server.should_exit = True
    th.join(timeout=5)
sys.exit(_rc)
