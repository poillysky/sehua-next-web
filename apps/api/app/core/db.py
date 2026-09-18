"""Postgres meta DB — settings + auth + torrent cache; never resource rows."""

from __future__ import annotations

import logging
import os
import re
import threading
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import urlparse, urlunparse

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# app/core/db.py → parents[4] = repo root (sehua-next-web)
ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = ROOT / "data"
MEDIA_DIR = ROOT / "media"
DEFAULT_META_DSN = "postgresql://postgres:postgres@192.168.2.38:5439/nextweb"

logger = logging.getLogger("app.db")

_pool: ConnectionPool | None = None
_pool_dsn: str | None = None
_init_lock = threading.Lock()
_initialized = False
_nofile_raised = False


def _replace_qmarks(sql: str) -> str:
    """把参数占位 `?` 换成 `%s`，**跳过单引号字符串字面量内**的 `?`。

    原实现是 `re.sub(r"\\?", "%s", sql)`：`WHERE note = 'a?b'` 里的 `?` 也会被
    替换掉，导致占位符与参数数量错位（报错或错值）。这里逐字符扫描并正确
    处理 `''` 转义。无 `?` 时直接原样返回（快路径）。
    """
    if "?" not in sql:
        return sql
    out: list[str] = []
    in_str = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            out.append(ch)
            if in_str and i + 1 < n and sql[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            in_str = not in_str
        elif ch == "?" and not in_str:
            out.append("%s")
        else:
            out.append(ch)
        i += 1
    return "".join(out)
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


def _ensure_dir(p: Path) -> Path:
    """返回目录，**只在缺失时** mkdir。

    ⚠️ 不要退回「每次调用都 `mkdir(parents=True, exist_ok=True)`」：
    Windows 上实测 `mkdir(exist_ok=True)` **0.26 ms/次**，而 `is_dir()` 探测只要
    **0.003 ms**（≈90×）。这些 helper（`media_dir()` / `data_dir()` / `mirrors_dir()`）
    被 `embed.resolve_root()` → `embed.get_settings()` 这类**每番号**路径反复调用，
    `enrich_one_row` 一个番号就要付 4 次 —— 12.3 万番号合计约 **8.5 分钟**纯 syscall。
    """
    if not p.is_dir():
        p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    return _ensure_dir(DATA_DIR)


def media_dir() -> Path:
    """片库类目录根（STRM / 刮削库等），与 data/ 运行时缓存分开。"""
    return _ensure_dir(MEDIA_DIR)


def mirrors_dir() -> Path:
    return _ensure_dir(data_dir() / "mirrors")


def prefix_runtime_dir() -> Path:
    return _ensure_dir(data_dir() / "prefix")


def prefix_catalog_dir() -> Path:
    p = _ensure_dir(prefix_runtime_dir() / "catalog")
    legacy = data_dir() / "prefix_catalog"
    if legacy.is_dir() and not (p / "catalog.json").is_file():
        # one-shot: 旧扁平目录 → data/prefix/catalog/
        try:
            for child in list(legacy.iterdir()):
                dest = p / child.name
                if not dest.exists():
                    child.replace(dest)
        except OSError:
            pass
    return p


def prefix_code_ranges_cache() -> Path:
    new = prefix_runtime_dir() / "code-ranges.json"
    legacy = data_dir() / "prefix-code-ranges.json"
    if legacy.is_file() and not new.is_file():
        try:
            legacy.replace(new)
        except OSError:
            return legacy
    return new


def cover_cache_dir() -> Path:
    p = data_dir() / "cache" / "cover"
    legacy = data_dir() / "cover-cache"
    if not p.exists() and legacy.is_dir():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            legacy.replace(p)
        except OSError:
            pass
    return _ensure_dir(p)


def facets_cache_dir() -> Path:
    p = data_dir() / "cache" / "facets"
    legacy = data_dir() / "scrap_facets_snap"
    if not p.exists() and legacy.is_dir():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            legacy.replace(p)
        except OSError:
            pass
    return _ensure_dir(p)


def debug_dir() -> Path:
    """脚本报告 / 探针输出（原 data/_debug）。"""
    return _ensure_dir(data_dir() / "debug")


def site_mirrors_path() -> Path:
    return mirrors_dir() / "site-mirrors.json"


def iqqtv_mirror_legacy_path() -> Path:
    return mirrors_dir() / "iqqtv-mirror.json"


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


@lru_cache(maxsize=1024)
def adapt_sql(sql: str) -> str:
    """把遗留 SQLite 方言尽量转到 Postgres。

    纯函数（str → str）且 SQL 模板数量有限，故结果缓存：原先每次
    `conn.execute` 都要跑 5 个正则替换，高频查询下是纯浪费。
    """
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
    s = _replace_qmarks(s)
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scrap_favorites (
                  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  item_id TEXT NOT NULL,
                  hub_region TEXT NOT NULL DEFAULT '',
                  payload_json TEXT NOT NULL DEFAULT '{}',
                  favorited_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY (user_id, item_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scrap_favorites_user_time
                ON scrap_favorites (user_id, favorited_at DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS enrich_logs (
                  id BIGSERIAL PRIMARY KEY,
                  region TEXT NOT NULL DEFAULT '',
                  line TEXT NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_enrich_logs_region_id
                ON enrich_logs (region, id DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS enrich_queue_log (
                  id BIGSERIAL PRIMARY KEY,
                  region TEXT NOT NULL DEFAULT '',
                  item_id TEXT NOT NULL DEFAULT '',
                  code TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL DEFAULT 'pending',
                  gaps_json TEXT NOT NULL DEFAULT '[]',
                  error TEXT NOT NULL DEFAULT '',
                  source TEXT NOT NULL DEFAULT '',
                  fetch_ms INTEGER,
                  detail_title TEXT NOT NULL DEFAULT '',
                  payload_json TEXT NOT NULL DEFAULT '{}',
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            # 索引存在则跳过，避免多 worker 同时 CREATE INDEX 堵死表
            idx_rows = conn.execute(
                """
                SELECT 1 FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname = 'idx_enrich_queue_log_region_status_id'
                LIMIT 1
                """
            ).fetchall()
            if not idx_rows:
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_enrich_queue_log_region_status_id
                    ON enrich_queue_log (region, status, id DESC)
                    """
                )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_enrich_queue_log_region_code
                ON enrich_queue_log (region, code)
                WHERE code <> ''
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_enrich_queue_log_region_item
                ON enrich_queue_log (region, item_id)
                WHERE item_id <> ''
                """
            )
            # 有界重试提示：记录「本该更好但没拿到」的番号（封面抓不到 / 高优先源故障降级）。
            # 目的：既不每轮无脑重刮（12 万番号的固定税），也不永久放弃。
            # kind ∈ {'cover','src_down'}；giveup=True 后增量扫描不再自动入队，
            # 用户可用「覆盖模式重扫」或单号重刮解除。
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS enrich_retry_hint (
                  region TEXT NOT NULL DEFAULT '',
                  code TEXT NOT NULL DEFAULT '',
                  kind TEXT NOT NULL DEFAULT '',
                  attempts INTEGER NOT NULL DEFAULT 0,
                  giveup BOOLEAN NOT NULL DEFAULT FALSE,
                  last_error TEXT NOT NULL DEFAULT '',
                  item_id TEXT NOT NULL DEFAULT '',
                  rel_path TEXT NOT NULL DEFAULT '',
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                  PRIMARY KEY (region, code, kind)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_enrich_retry_hint_region_kind
                ON enrich_retry_hint (region, kind, giveup)
                """
            )
            conn.commit()
        _initialized = True
        logger.info("meta schema ready on %s", meta_dsn_label())
