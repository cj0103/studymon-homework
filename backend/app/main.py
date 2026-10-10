# -*- coding: utf-8 -*-
"""宝可梦作业激励游戏 · 关都篇 后端入口
启动: python -m uvicorn app.main:app --host 127.0.0.1 --port 8300   (工作目录 backend/)
"""
import os
import re
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse
from .config import STATIC_DIR, ASSETS_DIR
from .routers import account, checkin, pokemon, battle

class NoCacheStatic(StaticFiles):
    """开发期禁用缓存，避免前端改动被旧缓存挡住"""
    def file_response(self, *a, **kw):
        resp = super().file_response(*a, **kw)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

app = FastAPI(title="宝可梦作业激励游戏", version="0.3.0")
app.include_router(account.router, prefix="/api")
app.include_router(checkin.router, prefix="/api")
app.include_router(pokemon.router, prefix="/api")
app.include_router(battle.router, prefix="/api")

# 静态素材：/static/artwork/... /static/audio/... → assets/
if os.path.isdir(ASSETS_DIR):
    app.mount("/static", StaticFiles(directory=ASSETS_DIR), name="assets")

@app.get("/api/health")
def health():
    return {"ok": True}

if os.path.isdir(STATIC_DIR):
    @app.get("/parent")
    @app.get("/parent/")
    def parent_page():
        return FileResponse(os.path.join(STATIC_DIR, "parent.html"))
    @app.get("/guide")
    @app.get("/guide/")
    def guide_page():
        return FileResponse(os.path.join(STATIC_DIR, "guide.html"))
    app.mount("/", NoCacheStatic(directory=STATIC_DIR, html=True), name="web")
