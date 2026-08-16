# -*- coding: utf-8 -*-
"""刮削工作队列中间表：大库目标缓冲，按批领取，避免内存/JSON 卡死控制面。"""

from __future__ import annotations

import logging
import threading
from typing import Any

from . import db

log = logging.getLogger("sns.scrape_queue_store")

_VALID_STATUS = frozenset({"pending", "running"})
_write_lock = threading.Lock()


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_tables() -> None:
    try:
        db.init_db()
    except Exception:
        log.debug("ensure scrape queue via init_db failed", exc_info=True)
    # 热重载时 init_db 可能已跳过：这里再幂等建表
    try:
        with db.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scrape_export_queue (
                  task_id TEXT NOT NULL,
                  code TEXT NOT NULL,
                  region TEXT NOT NULL DEFAULT '',
                  maker TEXT NOT NULL DEFAULT '',
                  prefix TEXT NOT NULL DEFAULT '',
                  kind TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL DEFAULT 'pending',
                  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                  PRIMARY KEY (task_id, code)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_scrape_queue_claim "
                "ON scrape_export_queue(task_id, status, code)"
            )
            conn.commit()
    except Exception:
        log.debug("ensure scrape_export_queue failed", exc_info=True)


def clear_task_queue(task_id: str) -> int:
    tid = str(task_id or "").strip()
    if not tid:
        return 0
    ensure_tables()
    try:
        with db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM scrape_export_queue WHERE task_id = ?",
                (tid,),
            )
            conn.commit()
            return int(cur.rowcount or 0)
    except Exception:
        log.exception("clear scrape queue failed task=%s", tid)
        return 0


def count_queue(task_id: str) -> dict[str, int]:
    tid = str(task_id or "").strip()
    out = {"pending": 0, "running": 0, "total": 0}
    if not tid:
        return out
    ensure_tables()
    try:
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS n FROM scrape_export_queue
                WHERE task_id = ?
                GROUP BY status
                """,
                (tid,),
            ).fetchall()
        for r in rows:
            st = str(r["status"] or "")
            n = int(r["n"] or 0)
            if st in out:
                out[st] = n
            out["total"] += n
        return out
    except Exception:
        log.exception("count scrape queue failed task=%s", tid)
        return out


def replace_task_queue(task_id: str, targets: list[dict[str, Any]]) -> int:
    """清空并写入 pending 队列（分块，避免一次超大事务）。"""
    tid = str(task_id or "").strip()
    if not tid:
        return 0
    ensure_tables()
    now = _now_iso()
    rows: list[tuple[str, str, str, str, str, str, str, str]] = []
    seen: set[str] = set()
    for t in targets:
        if not isinstance(t, dict):
            continue
        c = str(t.get("code") or "").strip()
        if not c or c in seen:
            continue
        seen.add(c)
        rows.append(
            (
                tid,
                c,
                str(t.get("region") or ""),
                str(t.get("maker") or ""),
                str(t.get("prefix") or ""),
                str(t.get("kind") or ""),
                "pending",
                now,
            )
        )
    with _write_lock:
        try:
            with db.connect() as conn:
                conn.execute(
                    "DELETE FROM scrape_export_queue WHERE task_id = ?",
                    (tid,),
                )
                chunk = 800
                for i in range(0, len(rows), chunk):
                    conn.executemany(
                        """
                        INSERT OR REPLACE INTO scrape_export_queue
                          (task_id, code, region, maker, prefix, kind, status, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        rows[i : i + chunk],
                    )
                    conn.commit()
            return len(rows)
        except Exception:
            log.exception("replace scrape queue failed task=%s n=%s", tid, len(rows))
            return 0


def remove_codes(task_id: str, codes: list[str] | set[str]) -> int:
    tid = str(task_id or "").strip()
    if not tid:
        return 0
    uniq = [str(c).strip() for c in codes if str(c or "").strip()]
    if not uniq:
        return 0
    ensure_tables()
    n = 0
    try:
        with db.connect() as conn:
            chunk = 400
            for i in range(0, len(uniq), chunk):
                part = uniq[i : i + chunk]
                placeholders = ",".join("?" * len(part))
                cur = conn.execute(
                    f"""
                    DELETE FROM scrape_export_queue
                    WHERE task_id = ? AND code IN ({placeholders})
                    """,
                    (tid, *part),
                )
                n += int(cur.rowcount or 0)
            conn.commit()
        return n
    except Exception:
        log.exception("remove scrape queue codes failed task=%s", tid)
        return 0


def requeue_running(task_id: str) -> int:
    """暂停：running → pending，便于继续领取。"""
    tid = str(task_id or "").strip()
    if not tid:
        return 0
    ensure_tables()
    try:
        with db.connect() as conn:
            cur = conn.execute(
                """
                UPDATE scrape_export_queue
                SET status = 'pending', updated_at = ?
                WHERE task_id = ? AND status = 'running'
                """,
                (_now_iso(), tid),
            )
            conn.commit()
            return int(cur.rowcount or 0)
    except Exception:
        log.exception("requeue running failed task=%s", tid)
        return 0


def claim_batch(task_id: str, limit: int = 64) -> list[dict[str, Any]]:
    """领取一批 pending → running。"""
    tid = str(task_id or "").strip()
    lim = max(1, min(int(limit or 64), 2000))
    if not tid:
        return []
    ensure_tables()
    now = _now_iso()
    with _write_lock:
        try:
            with db.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT code, region, maker, prefix, kind
                    FROM scrape_export_queue
                    WHERE task_id = ? AND status = 'pending'
                    ORDER BY code ASC
                    LIMIT ?
                    """,
                    (tid, lim),
                ).fetchall()
                if not rows:
                    return []
                codes = [str(r["code"]) for r in rows]
                chunk = 400
                for i in range(0, len(codes), chunk):
                    part = codes[i : i + chunk]
                    placeholders = ",".join("?" * len(part))
                    conn.execute(
                        f"""
                        UPDATE scrape_export_queue
                        SET status = 'running', updated_at = ?
                        WHERE task_id = ? AND status = 'pending'
                          AND code IN ({placeholders})
                        """,
                        (now, tid, *part),
                    )
                conn.commit()
            return [
                {
                    "code": str(r["code"] or ""),
                    "region": str(r["region"] or ""),
                    "maker": str(r["maker"] or ""),
                    "prefix": str(r["prefix"] or ""),
                    "kind": str(r["kind"] or ""),
                }
                for r in rows
                if str(r["code"] or "").strip()
            ]
        except Exception:
            log.exception("claim scrape queue failed task=%s", tid)
            return []


def list_pending(
    task_id: str,
    *,
    limit: int = 50000,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """读 pending（续跑/分区用）；大库分批调用。"""
    tid = str(task_id or "").strip()
    if not tid:
        return []
    ensure_tables()
    lim = max(1, min(int(limit or 50000), 100000))
    off = max(0, int(offset or 0))
    try:
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT code, region, maker, prefix, kind
                FROM scrape_export_queue
                WHERE task_id = ? AND status = 'pending'
                ORDER BY code ASC
                LIMIT ? OFFSET ?
                """,
                (tid, lim, off),
            ).fetchall()
        return [
            {
                "code": str(r["code"] or ""),
                "region": str(r["region"] or ""),
                "maker": str(r["maker"] or ""),
                "prefix": str(r["prefix"] or ""),
                "kind": str(r["kind"] or ""),
            }
            for r in rows
            if str(r["code"] or "").strip()
        ]
    except Exception:
        log.exception("list pending queue failed task=%s", tid)
        return []


def mark_done(task_id: str, code: str) -> None:
    remove_codes(task_id, [code])
