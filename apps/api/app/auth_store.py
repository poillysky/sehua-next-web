"""User + opaque session store (SQLite meta DB)."""



from __future__ import annotations



import hashlib

import re

import secrets

from datetime import datetime, timedelta, timezone

from typing import Any



import bcrypt



from .db import connect



SESSION_DAYS = 30

COOKIE_NAME = "sns_session"

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")





def _utc_now() -> datetime:

    return datetime.now(timezone.utc)





def _fmt(dt: datetime) -> str:

    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")





def _parse(ts: str) -> datetime:

    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)





def hash_password(password: str) -> str:

    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")





def verify_password(password: str, password_hash: str) -> bool:

    try:

        return bcrypt.checkpw(

            password.encode("utf-8"),

            password_hash.encode("utf-8"),

        )

    except ValueError:

        return False





def hash_token(raw: str) -> str:

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()





def validate_username(username: str) -> str | None:

    u = username.strip()

    if not USERNAME_RE.match(u):

        return "用户名须为 3–32 位字母/数字/下划线"

    return None





def validate_password(password: str) -> str | None:

    if len(password) < 8 or len(password) > 128:

        return "密码须为 8–128 位"

    return None





def create_user(

    username: str,

    password: str,

    *,

    is_admin: bool = False,

) -> dict[str, Any]:

    err = validate_username(username) or validate_password(password)

    if err:

        raise ValueError(err)

    uname = username.strip()

    with connect() as conn:

        exists = conn.execute(

            "SELECT 1 FROM users WHERE username = ? COLLATE NOCASE",

            (uname,),

        ).fetchone()

        if exists:

            raise ValueError("用户名已被占用")

        cur = conn.execute(

            """

            INSERT INTO users (username, password_hash, is_admin)

            VALUES (?, ?, ?)

            """,

            (uname, hash_password(password), 1 if is_admin else 0),

        )

        conn.commit()

        row = conn.execute(

            "SELECT id, username, is_admin, created_at FROM users WHERE id = ?",

            (cur.lastrowid,),

        ).fetchone()

    return dict(row)





def ensure_admin_user(

    username: str,

    password: str,

    *,

    reset_password: bool = False,

) -> dict[str, Any]:

    """从 config 种子管理员：不存在则创建；可选启动时按 config 重置密码。"""

    err = validate_username(username) or validate_password(password)

    if err:

        raise ValueError(f"config.admin 无效: {err}")

    uname = username.strip()

    with connect() as conn:

        row = conn.execute(

            """

            SELECT id, username, password_hash, is_admin, created_at

            FROM users WHERE username = ? COLLATE NOCASE

            """,

            (uname,),

        ).fetchone()

        if not row:

            cur = conn.execute(

                """

                INSERT INTO users (username, password_hash, is_admin)

                VALUES (?, ?, 1)

                """,

                (uname, hash_password(password)),

            )

            conn.commit()

            created = conn.execute(

                "SELECT id, username, is_admin, created_at FROM users WHERE id = ?",

                (cur.lastrowid,),

            ).fetchone()

            return {**dict(created), "seeded": True, "password_reset": False}



        updates: list[str] = []

        params: list[Any] = []

        password_reset = False

        if int(row["is_admin"] or 0) != 1:

            updates.append("is_admin = 1")

        if reset_password:

            updates.append("password_hash = ?")

            params.append(hash_password(password))

            password_reset = True

        if updates:

            params.append(row["id"])

            conn.execute(

                f"UPDATE users SET {', '.join(updates)} WHERE id = ?",

                params,

            )

            conn.commit()

        out = conn.execute(

            "SELECT id, username, is_admin, created_at FROM users WHERE id = ?",

            (row["id"],),

        ).fetchone()

    return {**dict(out), "seeded": False, "password_reset": password_reset}





def get_user_by_username(username: str) -> dict[str, Any] | None:

    with connect() as conn:

        row = conn.execute(

            """

            SELECT id, username, password_hash, is_admin, created_at

            FROM users WHERE username = ? COLLATE NOCASE

            """,

            (username.strip(),),

        ).fetchone()

    return dict(row) if row else None





def get_user_by_id(user_id: int) -> dict[str, Any] | None:

    with connect() as conn:

        row = conn.execute(

            "SELECT id, username, is_admin, created_at FROM users WHERE id = ?",

            (user_id,),

        ).fetchone()

    return dict(row) if row else None





def create_session(user_id: int) -> str:

    raw = secrets.token_urlsafe(32)

    token_hash = hash_token(raw)

    expires = _utc_now() + timedelta(days=SESSION_DAYS)

    with connect() as conn:

        conn.execute(

            """

            INSERT INTO sessions (user_id, token_hash, expires_at)

            VALUES (?, ?, ?)

            """,

            (user_id, token_hash, _fmt(expires)),

        )

        conn.commit()

    return raw





def revoke_session(raw_token: str | None) -> None:

    if not raw_token:

        return

    with connect() as conn:

        conn.execute(

            """

            UPDATE sessions

            SET revoked_at = datetime('now')

            WHERE token_hash = ? AND revoked_at IS NULL

            """,

            (hash_token(raw_token),),

        )

        conn.commit()





def user_from_session(raw_token: str | None) -> dict[str, Any] | None:

    if not raw_token:

        return None

    with connect() as conn:

        row = conn.execute(

            """

            SELECT u.id, u.username, u.is_admin, u.created_at,

                   s.expires_at, s.revoked_at

            FROM sessions s

            JOIN users u ON u.id = s.user_id

            WHERE s.token_hash = ?

            """,

            (hash_token(raw_token),),

        ).fetchone()

    if not row:

        return None

    if row["revoked_at"]:

        return None

    if _parse(row["expires_at"]) <= _utc_now():

        return None

    return {

        "id": row["id"],

        "username": row["username"],

        "is_admin": bool(row["is_admin"]),

        "created_at": row["created_at"],

    }





def public_user(user: dict[str, Any]) -> dict[str, Any]:

    return {

        "id": user["id"],

        "username": user["username"],

        "is_admin": bool(user.get("is_admin")),

        "created_at": user.get("created_at"),

    }




def change_password(
    user_id: int,
    current_password: str,
    new_password: str,
) -> None:
    err = validate_password(new_password)
    if err:
        raise ValueError(err)
    if current_password == new_password:
        raise ValueError("新密码不能与当前密码相同")

    with connect() as conn:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            raise ValueError("用户不存在")
        if not verify_password(current_password, row["password_hash"]):
            raise ValueError("当前密码不正确")
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), user_id),
        )
        conn.commit()


def list_users() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, username, is_admin, created_at
            FROM users
            ORDER BY is_admin DESC, id ASC
            """
        ).fetchall()
    return [public_user(dict(r)) for r in rows]


def admin_set_password(user_id: int, new_password: str) -> None:
    """管理员重置他人密码（无需旧密码）。"""
    err = validate_password(new_password)
    if err:
        raise ValueError(err)
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            raise ValueError("用户不存在")
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), user_id),
        )
        conn.commit()


def delete_user(user_id: int, *, actor_id: int) -> None:
    if int(user_id) == int(actor_id):
        raise ValueError("不能删除当前登录账号")
    with connect() as conn:
        row = conn.execute(
            "SELECT id, is_admin FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            raise ValueError("用户不存在")
        if int(row["is_admin"] or 0) == 1:
            admin_count = conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE is_admin = 1"
            ).fetchone()
            if int(admin_count["c"] or 0) <= 1:
                raise ValueError("不能删除最后一个管理员")
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()


