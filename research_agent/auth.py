"""
用户认证模块 — 注册/登录/JWT

用户数据存储在 SQLite（users.db），密码用 bcrypt 哈希。
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt, JWTError
from pydantic import BaseModel

# ── 配置 ──────────────────────────────────────────────────────

SECRET_KEY = os.getenv("JWT_SECRET", "research-agent-secret-key-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 72

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "users.db")


# ── 密码工具 ──────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ── 数据模型 ──────────────────────────────────────────────────

class UserRegister(BaseModel):
    username: str
    password: str
    display_name: str = ""


class UserLogin(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    id: int
    username: str
    display_name: str
    created_at: str


# ── 数据库 ────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_user_db():
    """初始化用户表"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


# ── 用户操作 ──────────────────────────────────────────────────

def create_user(username: str, password: str, display_name: str = "") -> UserInfo | str:
    """创建用户，成功返回 UserInfo，失败返回错误信息"""
    if len(username) < 2:
        return "用户名至少 2 个字符"
    if len(password) < 4:
        return "密码至少 4 个字符"

    conn = _get_conn()
    try:
        hashed = hash_password(password)
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)",
            (username, hashed, display_name or username),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return UserInfo(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"],
            created_at=row["created_at"],
        )
    except sqlite3.IntegrityError:
        return "用户名已存在"
    finally:
        conn.close()


def authenticate_user(username: str, password: str) -> UserInfo | None:
    """验证用户，成功返回 UserInfo，失败返回 None"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if not row:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return UserInfo(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        created_at=row["created_at"],
    )


def get_user_by_id(user_id: int) -> UserInfo | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return UserInfo(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        created_at=row["created_at"],
    )


# ── JWT ───────────────────────────────────────────────────────

def create_token(user: UserInfo) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> int | None:
    """验证 token，返回 user_id 或 None"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None
