"""Postgres meta DB — settings + auth + torrent cache; never resource rows."""

from __future__ import annotations

import logging
import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import urlparse, urlunparse

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"
DEFAULT_META_DSN = "postgresql://postgres:postgres@192.168.2.38:5439/nextweb"

logger = logging.getLogger("app.db")

_pool: ConnectionPool | None = None
_pool_dsn: str | None = None
_init_lock = threading.Lock()
_initialized = False
_nofile_raised = False

_QMARK_RE = re.compile(r"\?")
_INSERT_OR_IGNORE_RE = re.compile(r"INSERT\s+OR\s+IGNORE\s+INTO", re.I)
_INSERT_OR_REPLACE_RE = re.compile(r"INSERT\s+OR\s+REPLACE\s+INTO", re.I)
_COLLATE_NOCASE_RE = re.compile(r"\s+COLLATE\s+NOCASE", re.I)
_INSERT_USERS_RE = re.compile(r"^\s*INSERT\s+INTO\s+users\b", re.I | re.S)


def _raise_nofile_limit() -> None:
    """尽量抬高进程 nofile，避免刮削并发打满默认 1024。"""
    global _nofile_raised
    if _nofile_raised:
        return
    _nofile_raised = True
    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        ceiling = 65535
        if hard != resource.RLIM_INFINITY and hard > 0:
            ceiling = min(ceiling, int(hard))
        if soft >= ceiling:
            return
        resource.setrlimit(resource.RLIMIT_NOFILE, (ceiling, hard))
        logger.info("raised RLIMIT_NOFILE soft %s -> %s (hard=%s)", soft, ceiling, hard)
    except Exception as e:
        logger.debug("could not raise RLIMIT_NOFILE: %s", e)


def data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def db_path() -> Path:
    """兼容旧调用：曾返回 SQLite 文件路径；现指向 data 目录占位路径。"""
    return data_dir() / ".meta-pg"


def meta_dsn() -> str:
    raw = (os.environ.get("SNS_META_DSN") or "").strip()
    return raw or DEFAULT_META_DSN


def meta_dsn_label() -> str:
    """健康检查用：隐藏密码。"""
    dsn = meta_dsn()
    try:
        u = urlparse(dsn)
        if u.password is not None:
            netloc = u.netloc.replace(f":{u.password}", ":***", 1)
            return urlunparse((u.scheme, netloc, u.path, "", "", ""))
    except Exception:
        pass
    return dsn


def get_meta_pool() -> ConnectionPool:
    global _pool, _pool_dsn
    dsn = meta_dsn()
    if _pool is None or _pool_dsn != dsn:
        if _pool is not None:
            try:
                _pool.close()
            except Exception:
                pass
        _pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=12,
            timeout=60,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        _pool_dsn = dsn
        logger.info("meta postgres pool ready: %s", meta_dsn_label())
    return _pool


def close_meta_pool() -> None:
    global _pool, _pool_dsn, _initialized
    if _pool is not None:
        try:
            _pool.close()
        except Exception:
            pass
    _pool = None
    _pool_dsn = None
    _initialized = False


def adapt_sql(sql: str) -> str:
    """把遗留 SQLite 方言尽量转到 Postgres。"""
    s = sql
    s = s.replace("datetime('now')", "CURRENT_TIMESTAMP")
    s = _COLLATE_NOCASE_RE.sub("", s)
    if _INSERT_OR_IGNORE_RE.search(s):
        s = _INSERT_OR_IGNORE_RE.sub("INSERT INTO", s)
        if "ON CONFLICT" not in s.upper():
            s = s.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    if _INSERT_OR_REPLACE_RE.search(s):
        s = _INSERT_OR_REPLACE_RE.sub("INSERT INTO", s)
        if "ON CONFLICT" not in s.upper():
            s = (
                s.rstrip().rstrip(";")
                + """
                ON CONFLICT (task_id, code) DO UPDATE SET
                  region = EXCLUDED.region,
                  maker = EXCLUDED.maker,
                  prefix = EXCLUDED.prefix,
                  kind = EXCLUDED.kind,
                  status = EXCLUDED.status,
                  updated_at = EXCLUDED.updated_at
                """
            )
    s = _QMARK_RE.sub("%s", s)
    return s


class CursorResult:
    __slots__ = ("_cur", "lastrowid", "rowcount", "_rows", "_idx")

    def __init__(
        self,
        cur: Any,
        *,
        lastrowid: int | None = None,
        rows: list[Any] | None = None,
    ) -> None:
        self._cur = cur
        self.lastrowid = lastrowid
        self.rowcount = int(getattr(cur, "rowcount", 0) or 0)
        self._rows = rows
        self._idx = 0

    def fetchone(self) -> Any | None:
        if self._rows is not None:
            if self._idx >= len(self._rows):
                return None
            row = self._rows[self._idx]
            self._idx += 1
            return row
        return self._cur.fetchone()

    def fetchall(self) -> list[Any]:
        if self._rows is not None:
            out = self._rows[self._idx :]
            self._idx = len(self._rows)
            return list(out)
        return list(self._cur.fetchall())


class MetaConnection:
    """兼容旧 SQLite 调用习惯：execute/executemany/commit + ? 占位符。"""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> CursorResult:
        sql_pg = adapt_sql(sql)
        want_id = bool(_INSERT_USERS_RE.match(sql)) and "RETURNING" not in sql_pg.upper()
        if want_id:
            sql_pg = sql_pg.rstrip().rstrip(";") + " RETURNING id"
        cur = self._conn.cursor()
        args: Sequence[Any] = () if params is None else params
        cur.execute(sql_pg, args)
        lastrowid = None
        if want_id:
            row = cur.fetchone()
            if row:
                lastrowid = int(row["id"] if isinstance(row, dict) else row[0])
            return CursorResult(cur, lastrowid=lastrowid, rows=[])
        return CursorResult(cur, lastrowid=lastrowid)

    def executemany(
        self,
        sql: str,
        params_seq: Sequence[Sequence[Any]],
    ) -> CursorResult:
        sql_pg = adapt_sql(sql)
        cur = self._conn.cursor()
        cur.executemany(sql_pg, list(params_seq))
        return CursorResult(cur)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()


@contextmanager
def connect() -> Iterator[MetaConnection]:
    """获取一条 meta Postgres 连接（退出 with 时归还连接池）。"""
    _raise_nofile_limit()
    pool = get_meta_pool()
    with pool.connection() as conn:
        yield MetaConnection(conn)


def _table_columns(conn: MetaConnection, table: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    ).fetchall()
    return {str(r["column_name"]) for r in rows}


def _ensure_column(conn: MetaConnection, table: str, column: str, decl: str) -> None:
    cols = _table_columns(conn, table)
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db() -> None:
    global _initialized
    _raise_nofile_limit()
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        data_dir()
        with connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                  key TEXT PRIMARY KEY,
                  value_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id BIGSERIAL PRIMARY KEY,
                  username TEXT NOT NULL,
                  password_hash TEXT NOT NULL,
                  is_admin INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            _ensure_column(conn, "users", "is_admin", "INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower
                ON users (LOWER(username))
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  id BIGSERIAL PRIMARY KEY,
                  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  token_hash TEXT NOT NULL UNIQUE,
                  expires_at TEXT NOT NULL,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  revoked_at TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS torrent_file_cache (
                  info_hash TEXT PRIMARY KEY,
                  files_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        _initialized = True
        logger.info("meta schema ready on %s", meta_dsn_label())
