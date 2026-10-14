# -*- coding: utf-8 -*-
"""v17 捕捉谱系统一口径：三处共用（图鉴/指南点亮、野外遭遇加权、重复捕捉落点）。

图口径（关键，别再写反）：
  fwd: from_no -> {to_no,...}   后代方向：持有 X 会进化成 fwd*(X)
  rev: to_no  -> {from_no,...}  前身方向：形态 n 的前身 = rev*(n)（多分支均有）
  编号例：13 独角虫 --fwd--> 14 铁壳蛹 --fwd--> 15 大针蜂；rev 反之。

口径定义（家长确认）：
  曾经抓到 lit = 当前背包 dex 号 ∪ 背包每只成员的进化链前身
              = 背包 ∪ walk(背包, rev)
  持有独角虫 → 点亮独角虫（它自己就是最前身，rev 闭包无新增）；
  持有铁壳蛹 → 点亮铁壳蛹 + 独角虫。
  不向进化后穿透：只抓过独角虫不点亮没见过的大针蜂；持蛹不点亮蜂。
  注意：不能按"连通分量"整组点亮——三段链持蛹也会误亮蜂。
  家长原始 bug 场景：绿毛虫(#10)进化为铁甲蛹(#11)后，#10 在指南回退？？？——
  因旧口径只查背包 DISTINCT pokedex_no，进化换号即丢。lit_set 用 rev 回溯修复。

落点（catch_target）：重复捕捉时经验包加在背包中"谱系上最接近"的那只——
  1) dex 号完全相同的持有者优先；
  2) 否则找"会进化成它"的持有者：caught_no 是持有者的前身，
     即 caught_no ∈ walk({持有者}, rev)（等价于 持有者 ∈ walk({caught_no}, fwd)）。
     小拉达(#19)进化成拉达(#20)后，再遇小拉达 → 喂给拉达。
  3) 都没有 → None（正常入袋为新怪）。多只命中按获得先后取最早一只。
"""
from . import db


def chain_maps(edges):
    """进化图双向邻接表：fwd: from→set(to)（后代），rev: to→set(from)（前身）。"""
    fwd, rev = {}, {}
    for e in edges:
        fwd.setdefault(e["from_no"], set()).add(e["to_no"])
        rev.setdefault(e["to_no"], set()).add(e["from_no"])
    return fwd, rev


def walk(start, adj):
    """沿邻接表做传递闭包（结果含 start 本身）。"""
    seen = set(start)
    stack = list(start)
    while stack:
        for nxt in adj.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _evo_graph():
    # 进化表进程内不变量（同一 seed 数据），缓存安全；空表不缓存（防脏启动）
    if not _evo_graph.cache:
        edges = db.q("SELECT from_no, to_no FROM pkm_evolution")
        if edges:
            _evo_graph.cache = chain_maps(edges)
    return _evo_graph.cache
_evo_graph.cache = None


def lit_set(sid):
    """曾经抓到（含进化前身）的 dex 号集合 = 背包 ∪ walk(背包, rev)。"""
    owned = {r["pokedex_no"] for r in db.q(
        "SELECT DISTINCT pokedex_no FROM trainer_pokemon WHERE student_id=%s", (sid,))}
    fwd, rev = _evo_graph()
    return walk(owned, rev)


def catch_target(sid, caught_no):
    """重复捕捉落点：背包中与 caught_no 同谱系的最近一只的 id；无谱系持有者 → None。"""
    rows = db.q("SELECT id,pokedex_no FROM trainer_pokemon WHERE student_id=%s ORDER BY id", (sid,))
    if not rows:
        return None
    fwd, rev = _evo_graph()
    exact = [r for r in rows if r["pokedex_no"] == caught_no]
    if exact:
        return exact[0]["id"]
    descendants = walk({caught_no}, fwd)   # caught_no 的全部后代形态
    for r in rows:                         # 按获得先后，多只命中取最早的一只
        if r["pokedex_no"] in descendants:
            return r["id"]
    return None
