import datetime as dt
import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from . import db
from .config import JWT_SECRET, JWT_DAYS

_bearer = HTTPBearer(auto_error=False)

def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()

def verify_pw(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False

def make_token(role: str, uid: int, parent_id: int | None = None) -> str:
    payload = {"role": role, "uid": uid, "pid": parent_id,
               "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=JWT_DAYS)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def _decode(cred) -> dict:
    if not cred:
        raise HTTPException(401, "请先登录")
    try:
        return jwt.decode(cred.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "登录已过期，请重新登录")

def parent_auth(cred: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    tok = _decode(cred)
    if tok.get("role") != "parent":
        raise HTTPException(403, "需要家长身份")
    return tok

def student_auth(cred: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    tok = _decode(cred)
    if tok.get("role") != "student":
        raise HTTPException(403, "需要孩子身份")
    return tok

def kid_auth(cred: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    """孩子端写操作：JWT 或 平板设备令牌（?k= 免登录）均可"""
    if cred and cred.credentials[:4] != "kid_":
        return student_auth(cred)
    rows = db.q("SELECT role, ref_id FROM device_token WHERE token=%s AND enabled=1",
                (cred.credentials,))
    if not rows or rows[0]["role"] != "kid":
        raise HTTPException(401, "设备令牌无效，请联系家长重新绑定")
    return {"uid": rows[0]["ref_id"]}
