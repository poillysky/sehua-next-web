"""SQLite meta DB — settings + auth + scrape logs; never resource rows."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "app.sqlite"


def db_path() -> Path:
    raw = os.environ.get("SNS_META_DB")
    return Path(raw) if raw else DEFAULT_DB


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=15000")
    except Exception:
        pass
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    cols = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
              key TEXT PRIMARY KEY,
              value_json TEXT NOT NULL,
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE COLLATE NOCASE,
              password_hash TEXT NOT NULL,
              is_admin INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        _ensure_column(conn, "users", "is_admin", "INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              token_hash TEXT NOT NULL UNIQUE,
              expires_at TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              revoked_at TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)"
        )
        # 刮削过程日志：按番号无限追加，不进 status.json
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scrape_export_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              task_id TEXT NOT NULL DEFAULT '',
              code TEXT NOT NULL,
              ts TEXT NOT NULL DEFAULT '',
              phase TEXT NOT NULL DEFAULT '',
              level TEXT NOT NULL DEFAULT 'info',
              text TEXT NOT NULL DEFAULT '',
              source TEXT NOT NULL DEFAULT '',
              ms INTEGER
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scrape_events_code_id "
            "ON scrape_export_events(code, id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scrape_events_task_code "
            "ON scrape_export_events(task_id, code, id)"
        )
        # 任务结果番号列表：支持数万条，不塞轮询 JSON
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scrape_export_codes (
              task_id TEXT NOT NULL,
              bucket TEXT NOT NULL,
              code TEXT NOT NULL,
              updated_at TEXT NOT NULL DEFAULT (datetime('now')),
              PRIMARY KEY (task_id, bucket, code)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scrape_codes_task_bucket "
            "ON scrape_export_codes(task_id, bucket)"
        )
        # 磁力无 dn 时按 infohash 解析出的文件树（避免每次外网拉 .torrent）
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS torrent_file_cache (
              info_hash TEXT PRIMARY KEY,
              files_json TEXT NOT NULL,
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()
