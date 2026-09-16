# -*- coding: utf-8 -*-
"""长任务状态/检查点落库（app_settings），跨 API 重启可恢复。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

import app.core.settings_store as settings_store

log = logging.getLogger(__name__)

# 各任务独立 key，避免互相覆盖
ENRICH_RUNTIME_KEY = "scrap.enrich.runtime"
EMBED_JOB_KEY = "scrap.embed.job"
ACTRESS_AVATAR_JOB_KEY = "scrap.actress_avatar.job"
ACTRESS_OPTIMIZE_JOB_KEY = "scrap.actress_optimize.job"
STRM_SYNC_JOB_KEY = "prefix.strm_sync.job"
LOCAL_INDEX_JOB_KEY = "prefix.local_index.job"

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        lk = _locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _locks[key] = lk
        return lk


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_job(key: str) -> dict[str, Any]:
    raw = settings_store.get_setting(key)
    return dict(raw) if isinstance(raw, dict) else {}


def save_job(key: str, value: dict[str, Any]) -> dict[str, Any]:
    payload = dict(value or {})
    payload["updatedAt"] = _now()
    with _lock_for(key):
        return settings_store.put_setting(key, payload)


def patch_job(key: str, **fields: Any) -> dict[str, Any]:
    with _lock_for(key):
        cur = load_job(key)
        for k, v in fields.items():
            if v is None and k in cur:
                cur.pop(k, None)
            else:
                cur[k] = v
        cur["updatedAt"] = _now()
        settings_store.put_setting(key, cur)
        return cur


def clear_job(key: str) -> None:
    with _lock_for(key):
        try:
            settings_store.put_setting(key, {})
        except Exception as e:  # noqa: BLE001
            log.warning("clear job state failed key=%s: %s", key, e)


def is_resumable(raw: dict[str, Any] | None) -> bool:
    if not isinstance(raw, dict) or not raw:
        return False
    status = str(raw.get("status") or "").strip().lower()
    return status in {"paused", "interrupted", "running"}
