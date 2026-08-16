"""刮削日志 / 结果番号落 SQLite，支撑数万级任务且不拖死轮询。"""

from __future__ import annotations

import logging
import threading
from typing import Any

from . import db

log = logging.getLogger("sns.scrape_log_store")

_write_lock = threading.Lock()
_BATCH: list[tuple[Any, ...]] = []
_BATCH_MAX = 64
_FLUSH_EVERY = 0.4
_last_flush_mono = 0.0

# 强制重刮清空时标记；读侧无需关心
# incomplete=字段不全；failed=网络/连不上等可重试失败
_VALID_BUCKETS = frozenset({"done", "skipped", "failed", "empty", "incomplete"})


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_tables() -> None:
    """幂等建表（init_db 已建；热重载时再确保一次）。"""
    try:
        db.init_db()
    except Exception:
        log.debug("ensure scrape log tables failed", exc_info=True)


def enqueue_event(
    *,
    task_id: str,
    code: str,
    ts: str,
    phase: str,
    level: str,
    text: str,
    source: str = "",
    ms: int | None = None,
) -> None:
    """异步批量写入；调用方勿持导出主锁。"""
    c = str(code or "").strip()
    if not c:
        return
    row = (
        str(task_id or "").strip(),
        c,
        str(ts or "") or _now_iso(),
        str(phase or ""),
        str(level or "info"),
        str(text or ""),
        str(source or ""),
        int(ms) if ms is not None else None,
    )
    global _last_flush_mono
    import time

    with _write_lock:
        _BATCH.append(row)
        now = time.monotonic()
        if len(_BATCH) >= _BATCH_MAX or (now - _last_flush_mono) >= _FLUSH_EVERY:
            _flush_locked()


def flush_events() -> None:
    with _write_lock:
        _flush_locked()


def _flush_locked() -> None:
    global _last_flush_mono
    import time

    if not _BATCH:
        _last_flush_mono = time.monotonic()
        return
    rows = list(_BATCH)
    _BATCH.clear()
    _last_flush_mono = time.monotonic()
    try:
        with db.connect() as conn:
            conn.executemany(
                """
                INSERT INTO scrape_export_events
                  (task_id, code, ts, phase, level, text, source, ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
    except Exception:
        log.exception("flush scrape_export_events failed n=%s", len(rows))
        # 已持锁：失败放回队首，避免丢日志（有上限防炸内存）
        overflow = rows + _BATCH
        del _BATCH[:]
        _BATCH.extend(overflow[-2000:])


def clear_code_events(code: str, *, task_id: str | None = None) -> None:
    """强制重刮：清该番号归档（可限本任务）。"""
    c = str(code or "").strip()
    if not c:
        return
    flush_events()
    tid = str(task_id or "").strip()
    try:
        with db.connect() as conn:
            if tid:
                conn.execute(
                    "DELETE FROM scrape_export_events WHERE code = ? AND task_id = ?",
                    (c, tid),
                )
            else:
                conn.execute(
                    "DELETE FROM scrape_export_events WHERE code = ?",
                    (c,),
                )
            conn.commit()
    except Exception:
        log.exception("clear scrape events failed code=%s", c)


def clear_task_events(task_id: str) -> int:
    """删除任务卡：清该任务全部过程日志。"""
    tid = str(task_id or "").strip()
    if not tid:
        return 0
    flush_events()
    try:
        with db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM scrape_export_events WHERE task_id = ?",
                (tid,),
            )
            conn.commit()
            return int(cur.rowcount or 0)
    except Exception:
        log.exception("clear task events failed task=%s", tid)
        return 0


def purge_task_logs(task_id: str) -> dict[str, int]:
    """删任务卡时清理：过程日志 + 结果番号桶。"""
    tid = str(task_id or "").strip()
    if not tid:
        return {"events": 0, "codes": 0}
    n_ev = clear_task_events(tid)
    n_codes = 0
    try:
        with db.connect() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) AS n FROM scrape_export_codes WHERE task_id = ?",
                (tid,),
            ).fetchone()
            n_codes = int(cur["n"] if cur else 0)
    except Exception:
        pass
    clear_task_result_codes(tid)
    return {"events": n_ev, "codes": n_codes}


def lookup_events(code: str, *, limit: int = 2000) -> list[dict[str, Any]]:
    """按番号取全量日志（默认最多 2000 条尾部，避免一次拖爆前端）。"""
    c = str(code or "").strip()
    if not c:
        return []
    flush_events()
    lim = max(1, min(int(limit or 2000), 20000))
    try:
        with db.connect() as conn:
            # 取尾部：先按 id 倒序 limit，再正序返回
            rows = conn.execute(
                """
                SELECT ts, phase, level, text, source, ms, code, task_id
                FROM (
                  SELECT id, ts, phase, level, text, source, ms, code, task_id
                  FROM scrape_export_events
                  WHERE code = ?
                  ORDER BY id DESC
                  LIMIT ?
                )
                ORDER BY id ASC
                """,
                (c, lim),
            ).fetchall()
    except Exception:
        log.exception("lookup scrape events failed code=%s", c)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        ev: dict[str, Any] = {
            "ts": str(r["ts"] or ""),
            "phase": str(r["phase"] or ""),
            "level": str(r["level"] or "info"),
            "text": str(r["text"] or ""),
            "code": str(r["code"] or c),
            "source": str(r["source"] or ""),
        }
        if r["ms"] is not None:
            try:
                ev["ms"] = int(r["ms"])
            except Exception:
                pass
        out.append(ev)
    return out


def upsert_result_code(task_id: str, bucket: str, code: str) -> None:
    tid = str(task_id or "").strip()
    b = str(bucket or "").strip()
    c = str(code or "").strip()
    if not tid or not c or b not in _VALID_BUCKETS:
        return
    try:
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO scrape_export_codes (task_id, bucket, code, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(task_id, bucket, code) DO UPDATE SET
                  updated_at = excluded.updated_at
                """,
                (tid, b, c, _now_iso()),
            )
            # 同一番号只留一个终态桶：成功/失败/跳过互斥
            conn.execute(
                """
                DELETE FROM scrape_export_codes
                WHERE task_id = ? AND code = ? AND bucket != ?
                """,
                (tid, c, b),
            )
            conn.commit()
    except Exception:
        log.exception("upsert result code failed %s %s %s", tid, b, c)


def bulk_upsert_result_codes(
    task_id: str,
    *,
    skipped: list[str] | None = None,
    failed: list[str] | None = None,
    done: list[str] | None = None,
    empty: list[str] | None = None,
    incomplete: list[str] | None = None,
) -> None:
    """预跳过等批量落库：单事务，避免逐条开关库卡死 building。"""
    tid = str(task_id or "").strip()
    if not tid:
        return
    now = _now_iso()
    rows: list[tuple[str, str, str, str]] = []
    codes_all: list[str] = []
    for bucket, codes in (
        ("done", done or []),
        ("skipped", skipped or []),
        ("failed", failed or []),
        ("empty", empty or []),
        ("incomplete", incomplete or []),
    ):
        for c in codes:
            s = str(c or "").strip()
            if not s:
                continue
            rows.append((tid, bucket, s, now))
            codes_all.append(s)
    if not rows:
        return
    try:
        with db.connect() as conn:
            # 清掉这些番号的旧桶，再插入新终态
            # SQLite 变量上限保守分块
            chunk = 400
            for i in range(0, len(codes_all), chunk):
                part = codes_all[i : i + chunk]
                placeholders = ",".join("?" * len(part))
                conn.execute(
                    f"""
                    DELETE FROM scrape_export_codes
                    WHERE task_id = ? AND code IN ({placeholders})
                    """,
                    (tid, *part),
                )
            conn.executemany(
                """
                INSERT OR IGNORE INTO scrape_export_codes
                  (task_id, bucket, code, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
    except Exception:
        log.exception("bulk upsert result codes failed %s n=%s", tid, len(rows))


def move_result_code(task_id: str, code: str, *, to_bucket: str) -> None:
    """skipped → failed 等升级。"""
    upsert_result_code(task_id, to_bucket, code)


def list_result_codes(
    task_id: str,
    bucket: str,
    *,
    limit: int = 50000,
    offset: int = 0,
) -> list[str]:
    tid = str(task_id or "").strip()
    b = str(bucket or "").strip()
    if not tid or b not in _VALID_BUCKETS:
        return []
    lim = max(1, min(int(limit or 50000), 100000))
    off = max(0, int(offset or 0))
    try:
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT code FROM scrape_export_codes
                WHERE task_id = ? AND bucket = ?
                ORDER BY updated_at ASC, code ASC
                LIMIT ? OFFSET ?
                """,
                (tid, b, lim, off),
            ).fetchall()
        return [str(r["code"]) for r in rows]
    except Exception:
        log.exception("list result codes failed %s %s", tid, b)
        return []


def list_all_result_codes(
    task_id: str,
    *,
    buckets: list[str] | None = None,
) -> set[str]:
    """取任务卡已入桶番号全集（续跑过滤用，不截断）。"""
    tid = str(task_id or "").strip()
    if not tid:
        return set()
    want = [b for b in (buckets or list(_VALID_BUCKETS)) if b in _VALID_BUCKETS]
    if not want:
        return set()
    try:
        with db.connect() as conn:
            placeholders = ",".join("?" * len(want))
            rows = conn.execute(
                f"""
                SELECT DISTINCT code FROM scrape_export_codes
                WHERE task_id = ? AND bucket IN ({placeholders})
                """,
                (tid, *want),
            ).fetchall()
        return {str(r["code"]).strip() for r in rows if str(r["code"] or "").strip()}
    except Exception:
        log.exception("list all result codes failed %s", tid)
        return set()


def count_result_codes(task_id: str, bucket: str | None = None) -> dict[str, int]:
    tid = str(task_id or "").strip()
    if not tid:
        return {
            "done": 0,
            "skipped": 0,
            "failed": 0,
            "empty": 0,
            "incomplete": 0,
        }
    try:
        with db.connect() as conn:
            if bucket and bucket in _VALID_BUCKETS:
                n = conn.execute(
                    "SELECT COUNT(*) AS n FROM scrape_export_codes "
                    "WHERE task_id = ? AND bucket = ?",
                    (tid, bucket),
                ).fetchone()
                return {bucket: int(n["n"] if n else 0)}
            rows = conn.execute(
                """
                SELECT bucket, COUNT(*) AS n FROM scrape_export_codes
                WHERE task_id = ?
                GROUP BY bucket
                """,
                (tid,),
            ).fetchall()
        out = {
            "done": 0,
            "skipped": 0,
            "failed": 0,
            "empty": 0,
            "incomplete": 0,
        }
        for r in rows:
            b = str(r["bucket"] or "")
            if b in out:
                out[b] = int(r["n"] or 0)
        return out
    except Exception:
        log.exception("count result codes failed %s", tid)
        return {
            "done": 0,
            "skipped": 0,
            "failed": 0,
            "empty": 0,
            "incomplete": 0,
        }


def clear_result_bucket(task_id: str, bucket: str) -> int:
    """清空某任务某一结果桶（失败重试前清 failed）。返回删除行数。"""
    tid = str(task_id or "").strip()
    b = str(bucket or "").strip()
    if not tid or b not in _VALID_BUCKETS:
        return 0
    try:
        with db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM scrape_export_codes WHERE task_id = ? AND bucket = ?",
                (tid, b),
            )
            conn.commit()
            return int(cur.rowcount or 0)
    except Exception:
        log.exception("clear result bucket failed %s %s", tid, b)
        return 0


def clear_task_result_codes(task_id: str) -> None:
    tid = str(task_id or "").strip()
    if not tid:
        return
    try:
        with db.connect() as conn:
            conn.execute(
                "DELETE FROM scrape_export_codes WHERE task_id = ?",
                (tid,),
            )
            conn.commit()
    except Exception:
        log.exception("clear result codes failed %s", tid)


def replace_task_result_codes(
    task_id: str,
    *,
    done: list[str] | None = None,
    skipped: list[str] | None = None,
    failed: list[str] | None = None,
    empty: list[str] | None = None,
    incomplete: list[str] | None = None,
) -> None:
    """用完整列表覆盖（任务卡重置 / 大合并后落库）。"""
    tid = str(task_id or "").strip()
    if not tid:
        return
    now = _now_iso()
    rows: list[tuple[str, str, str, str]] = []
    for bucket, codes in (
        ("done", done or []),
        ("skipped", skipped or []),
        ("failed", failed or []),
        ("empty", empty or []),
        ("incomplete", incomplete or []),
    ):
        for c in codes:
            s = str(c or "").strip()
            if s:
                rows.append((tid, bucket, s, now))
    try:
        with db.connect() as conn:
            conn.execute(
                "DELETE FROM scrape_export_codes WHERE task_id = ?",
                (tid,),
            )
            if rows:
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO scrape_export_codes
                      (task_id, bucket, code, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    rows,
                )
            conn.commit()
    except Exception:
        log.exception("replace result codes failed %s n=%s", tid, len(rows))
