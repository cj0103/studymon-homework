# -*- coding: utf-8 -*-
"""v13 图鉴介绍换 Let's Go 原文——专项验证（由 _smoke_all.py 同进程驱动，勿单起服务）
A. pkm_profile 与 _flavor/entries.jsonl「皮卡丘」版本文案逐条一致（半角化口径）
B. HTTP 详情接口返回的 intro 为 LGPE 原文（抽查派拉斯/皮卡丘）
"""
import json
import os
import re
from app import db

HERE = os.path.dirname(os.path.abspath(__file__))

def _fail(m): FAILS.append(m); print(f"[FAIL] {m}")
def _ok(m): print(f"[PASS] {m}")

print("=== v13 图鉴介绍验证开始 ===")

FW = {chr(c): chr(c - 0xFEE0) for c in range(0xFF10, 0xFF1A)}
def half(s): return "".join(FW.get(ch, ch) for ch in s)

ent = {}
with open(os.path.join(HERE, "_flavor", "entries.jsonl"), encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        ent[r["no"]] = r

rows = {r["pokedex_no"]: r for r in db.q("SELECT pokedex_no,genus,intro FROM pkm_profile")}
mismatch = []
for no in range(1, 152):
    want = half(ent[no]["entries"]["皮卡丘"].strip())
    got = rows.get(no, {}).get("intro")
    if got != want:
        mismatch.append((no, (got or "")[:30], want[:30]))
if mismatch:
    _fail(f"v13-文案不一致 {len(mismatch)} 条: {mismatch[:5]}")
else:
    _ok("v13-151 条 intro 与 Let's Go 官方原文逐条一致（全角数字已半角化）")

genus_bad = [n for n in range(1, 152) if "宝可梦" not in (rows.get(n, {}).get("genus") or "")]
if genus_bad: _fail(f"v13-genus 异常 {genus_bad}")
else: _ok("v13-genus 分类词 151 条均为官方「××宝可梦」格式")

# B. HTTP 抽查（走服务接口，确认线上读取路径无误）
import urllib.request, urllib.parse
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def _api(method, path, token=None):
    req = urllib.request.Request("http://127.0.0.1:8471/api" + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token: req.add_header("Authorization", "Bearer " + token)
    try:
        with _opener.open(req, data=None) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}

_sid = db.q("SELECT id FROM student_user ORDER BY id LIMIT 1")[0]["id"]
_dev = db.q("SELECT token FROM device_token WHERE role='kid' AND ref_id=%s AND enabled=1 "
            "ORDER BY create_time LIMIT 1", (_sid,))
TK = None
if _dev:
    c, j = _api("GET", "/resolve/" + urllib.parse.quote(_dev[0]["token"]))
    if c == 200: TK = j.get("token")
if not TK:
    _fail("v13-无 kid 令牌，跳过 HTTP 抽查")
else:
    for dexno, key in ((46, "蘑菇"), (25, "尾巴")):
        c, j = _api("GET", "/child/pokedex", TK)
        # 详情接口按 trainer_pokemon.id 读；从列表找一个对应 dex 的怪
        c2, lst = _api("GET", "/child/pokemon", TK)
        hit = [p for p in (lst if isinstance(lst, list) else []) if p.get("pokedex_no") == dexno]
        if not hit:
            print(f"[SKIP] 本地库无 #dex{dexno}，HTTP 抽查跳过")
            continue
        c3, d = _api("GET", "/child/pokemon/" + str(hit[0]["id"]), TK)
        intro = (d.get("profile") or {}).get("intro") or ""
        if c3 == 200 and key in intro:
            _ok(f"v13-HTTP 详情 #{dexno} intro 为 LGPE 原文：{intro[:24]}…")
        else:
            _fail(f"v13-HTTP 详情 #{dexno} intro 异常: {intro[:40]}")

print("=== v13 图鉴介绍验证结束 ===")
