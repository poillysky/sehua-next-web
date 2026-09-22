# -*- coding: utf-8 -*-
"""enrich_checkpoint —— 自 scrap_library/enrich.py 拆出（机械搬移，行为不变）。"""

from __future__ import annotations
import json
import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from fastapi import HTTPException
import app.scrap_library.embed as embed_svc
from app.ai.config import resolve_embed_config
from app.ai.embed import encode_texts_sync
from app.core.db import get_meta_pool, media_dir
from app.scrap_library import enrich_log_sink
from app.scrap_library.nfo import (
    build_mdcx_nfo_root,
    fields_from_movie_root,
    format_nfo_xml,
    parse_nfo,
    write_nfo,
)
from app.scrap_library import enrich_monitor as enrich_mon

import app.scrap_library.enrich as _enrich
import app.scrap_library.enrich_queue as _enrich_queue
from app.scrap_library.enrich import (log)
from app.scrap_library.enrich_runtime import (_enrich_job, _enrich_lock, _hydrate_enrich_runtime, _persist_enrich_runtime)


def _save_checkpoint(region: str, payload: dict[str, Any]) -> None:
    rid = str(region or "").strip()
    if not rid:
        return
    row = dict(payload or {})
    queue_list = [
        dict(r) for r in list(row.get("queue") or []) if isinstance(r, dict)
    ]
    # 剩余以队列表为准，禁止只用内存抽样长度（重启后续跑会「假完成」）
    try:
        db_pending = int(_enrich_queue._queue_log_status_counts(rid, fresh=True).get("pending") or 0)
    except Exception:  # noqa: BLE001
        db_pending = 0
    rem_n = max(
        int(row.get("remainingCount") or 0),
        len(queue_list),
        db_pending,
    )
    row["queue"] = queue_list
    row["remainingCount"] = rem_n
    row["queueInLog"] = bool(row.get("queueInLog")) or rem_n > len(queue_list) or db_pending > len(
        queue_list
    )
    with _enrich._enrich_lock:
        cps = dict(_enrich._enrich_job.get("checkpoints") or {})
        cps[rid] = row
        _enrich._enrich_job["checkpoints"] = cps
    _enrich._persist_enrich_runtime()


def _clear_checkpoint(region: str = "") -> None:
    rid = str(region or "").strip()
    with _enrich._enrich_lock:
        if not rid:
            _enrich._enrich_job["checkpoints"] = {}
        else:
            cps = dict(_enrich._enrich_job.get("checkpoints") or {})
            cps.pop(rid, None)
            _enrich._enrich_job["checkpoints"] = cps
    _enrich._persist_enrich_runtime()


def _take_checkpoint(region: str) -> dict[str, Any] | None:
    rid = str(region or "").strip()
    if not rid:
        return None
    with _enrich._enrich_lock:
        cps = dict(_enrich._enrich_job.get("checkpoints") or {})
        raw = cps.pop(rid, None)
        _enrich._enrich_job["checkpoints"] = cps
    _enrich._persist_enrich_runtime()
    return dict(raw) if isinstance(raw, dict) else None


def _peek_checkpoint(region: str) -> dict[str, Any] | None:
    rid = str(region or "").strip()
    if not rid:
        return None
    _enrich._hydrate_enrich_runtime()
    with _enrich._enrich_lock:
        raw = (dict(_enrich._enrich_job.get("checkpoints") or {})).get(rid)
    return dict(raw) if isinstance(raw, dict) else None


def _slim_checkpoint_queue(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        item: dict[str, Any] = {
            "itemId": str(r.get("itemId") or ""),
            "code": str(r.get("code") or ""),
            "gaps": list(r.get("gaps") or []),
        }
        lid = _enrich_queue._queue_log_int_id(r)
        if lid:
            item["logId"] = lid
        rel = str(r.get("rel_path") or r.get("relPath") or "")
        if rel:
            item["rel_path"] = rel
            item["relPath"] = rel
        out.append(item)
    return out


_CHECKPOINT_PERSIST_QUEUE_MAX = 200


def _checkpoint_for_persist(cp: dict[str, Any]) -> dict[str, Any]:
    """落盘检查点：只保留抽样队列 + remainingCount，完整续跑靠 enrich_queue_log。"""
    queue_raw = cp.get("queue") or []
    queue_list = [r for r in queue_raw if isinstance(r, dict)] if isinstance(queue_raw, list) else []
    declared = int(cp.get("remainingCount") or 0)
    rem_n = max(declared, len(queue_list))
    slim = _slim_checkpoint_queue(queue_list[:_CHECKPOINT_PERSIST_QUEUE_MAX])
    return {
        "region": str(cp.get("region") or ""),
        "mode": str(cp.get("mode") or "incremental"),
        "kinds": list(cp.get("kinds") or []),
        "dryRun": bool(cp.get("dryRun")),
        "ok": int(cp.get("ok") or 0),
        "failed": int(cp.get("failed") or 0),
        "done": int(cp.get("done") or 0),
        "originalTotal": int(cp.get("originalTotal") or 0),
        "queue": slim,
        "remainingCount": rem_n,
        "queueInLog": rem_n > len(slim),
    }


def _rebuild_checkpoint_queue_from_log(region: str) -> list[dict[str, Any]]:
    """检查点队列丢失/截断时，用 enrich_queue_log 的 pending 分页重建。"""
    rid = _enrich._queue_log_region(region)
    out: list[dict[str, Any]] = []
    if not rid:
        return out
    try:
        from app.core.db import connect, init_db

        init_db()
        last_id = 0
        log_off = 0
        with connect() as conn:
            while True:
                rows = conn.execute(
                    """
                    SELECT id, item_id, code, status, gaps_json, error, source,
                           fetch_ms, detail_title, payload_json
                    FROM enrich_queue_log
                    WHERE region=? AND status='pending'
                    ORDER BY updated_at DESC NULLS LAST, id DESC
                    LIMIT 2000 OFFSET ?
                    """,
                    (rid, log_off),
                ).fetchall()
                batch = list(rows or [])
                if not batch:
                    break
                log_off += len(batch)
                for r in batch:
                    if isinstance(r, dict):
                        it = _enrich_queue._queue_log_row_to_item(r)
                        last_id = int(r.get("id") or last_id)
                    else:
                        it = _enrich_queue._queue_log_row_to_item(
                            {
                                "id": r[0],
                                "item_id": r[1],
                                "code": r[2],
                                "status": r[3],
                                "gaps_json": r[4],
                                "error": r[5],
                                "source": r[6],
                                "fetch_ms": r[7],
                                "detail_title": r[8],
                                "payload_json": r[9],
                            }
                        )
                        last_id = int(r[0] or last_id)
                    out.append(
                        {
                            "itemId": str(it.get("itemId") or ""),
                            "code": str(it.get("code") or ""),
                            "gaps": list(it.get("gaps") or []),
                            **(
                                {"logId": int(it["logId"])}
                                if it.get("logId")
                                else {}
                            ),
                            **(
                                {
                                    "rel_path": str(
                                        it.get("rel_path") or it.get("relPath") or ""
                                    ),
                                    "relPath": str(
                                        it.get("relPath") or it.get("rel_path") or ""
                                    ),
                                }
                                if (it.get("rel_path") or it.get("relPath"))
                                else {}
                            ),
                        }
                    )
                if len(batch) < 2000:
                    break
    except Exception as e:  # noqa: BLE001
        log.warning("rebuild checkpoint queue from log failed region=%s: %s", rid, e)
    return out
