# -*- coding: utf-8 -*-
"""重置游戏数据（保留账号/设备令牌/静态资料）：
清空打卡、经验流水、顺延、战斗记录，宝可梦恢复开档礼赠（皮卡丘 Lv1）。

【何时使用】开学重置 / 正式交给孩子前 / 冒烟测试前（smoke_test 假定干净库）。
【等级口径沿革】曾冻结为 Lv5；2026-10-07 家长拍板改为 **Lv1 起步**——经验主要来自
每日打卡（230~320/日），中等经验组 Lv1→Lv5 约需 135 经验，当天即可连升数级，无卡关
风险。Lv1 携带习得等级<=1 的全部招式（皮卡丘：电击40/叫声/摇尾巴 共 3 招）。
【保留】parent_user / student_user 账号、device_token 三种子令牌
（学习平板/爸爸手机/妈妈手机——孩子收藏的登录链接不会失效）。
【清除】其余全部动态数据；徽章/区域/每周捕捉次数复位（0 徽章、区 1、捕捉 3 次）。
用法: PKM_DB_ENGINE=sqlite python reset_game.py   （ECS: venv/bin/python，跑前先备份库）
"""
import datetime as dt
from app import db
from app.auth import hash_pw

STARTER_LEVEL = 1  # 开档礼赠入库等级（家长定档：Lv1 起步，打卡经验当天即连升）


def main():
    db.x("DELETE FROM checkin_record")
    db.x("DELETE FROM exp_log")
    db.x("DELETE FROM battle_record")
    db.x("UPDATE student_carry SET carry_pending=0")
    # 宝可梦回到开档礼赠（pkm_starters：皮卡丘，不进化伙伴，STARTER_LEVEL 起步）
    db.x("DELETE FROM trainer_pokemon")
    # 复位自增序列，保证首发 id 稳定为 1（测试脚本按此约定引用）
    if db.ENGINE == "sqlite":
        db.x("DELETE FROM sqlite_sequence WHERE name='trainer_pokemon'")
    else:
        db.x("ALTER TABLE trainer_pokemon AUTO_INCREMENT=1")
    import json
    try:
        nos = [r["pokedex_no"] for r in db.q("SELECT pokedex_no FROM pkm_starters ORDER BY pokedex_no")]
    except Exception:
        nos = []
    if not nos:
        nos = [25]
    rows = db.q("SELECT id FROM student_user")
    for s in rows:
        for no in nos:
            # 携带习得等级<=起步等级的招式（最多 4 个，末 4 招口径）
            skills = db.q("SELECT skill_id FROM pokemon_skill_learn "
                          "WHERE pokedex_no=%s AND learn_level<=%s ORDER BY learn_level DESC LIMIT 4",
                          (no, STARTER_LEVEL))
            ids = [r["skill_id"] for r in skills] or [33]
            db.x("INSERT INTO trainer_pokemon(student_id,pokedex_no,level,total_exp,"
                 "learned_skill_json,known_skill_json,is_in_team) VALUES(%s,%s,%s,0,%s,%s,1)",
                 (s["id"], no, STARTER_LEVEL, json.dumps(ids), json.dumps(ids)))
    db.x("UPDATE student_user SET badge_json=NULL, current_region_id=1, week_catch_times=3")
    # 设备令牌恢复为干净 3 条（1 个孩子 + 爸爸/妈妈）：清掉测试期间签发/吊销/删除的残留，
    # 三个种子标签令牌原样保留（用户收藏链接不失效）
    db.x("DELETE FROM device_token WHERE label NOT IN ('学习平板','爸爸手机','妈妈手机')")
    db.x("UPDATE device_token SET enabled=1")
    import secrets
    par = db.q("SELECT id FROM parent_user ORDER BY id LIMIT 1")
    kid = db.q("SELECT id FROM student_user WHERE parent_id=%s LIMIT 1", (par[0]["id"],)) if par else []
    if par and kid:
        have = {r["label"] for r in db.q("SELECT label FROM device_token")}
        for role, ref, label in [("kid", kid[0]["id"], "学习平板"),
                                 ("parent", par[0]["id"], "爸爸手机"),
                                 ("parent", par[0]["id"], "妈妈手机")]:
            if label not in have:
                tk = ("kid_" if role == "kid" else "par_") + secrets.token_urlsafe(18)
                db.x("INSERT INTO device_token(token,role,ref_id,label) VALUES(%s,%s,%s,%s)",
                     (tk, role, ref, label))
    print(f"RESET OK — 打卡/战斗/经验已清空，恢复开档礼赠（皮卡丘 Lv{STARTER_LEVEL}），账号与设备令牌保留")


if __name__ == "__main__":
    main()
