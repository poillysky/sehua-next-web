# -*- coding: utf-8 -*-
"""Embed job runtime state — locks, job dicts, caches, poster download pool."""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any

log = logging.getLogger(__name__)

_job_lock = threading.Lock()

_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "progress": None,
    "log": [],
    "result": None,
    "error": None,
}

_job_hydrated = False

_job_hydrate_lock = threading.Lock()

_blank_cover_cache: dict[str, bool] = {}

_POSTER_DL_WORKERS = 3

_poster_dl_q: queue.Queue[tuple[str, str, str]] | None = None

_poster_dl_lock = threading.Lock()

_poster_dl_inflight: set[str] = set()

_poster_dl_fail_until: dict[str, float] = {}

_POSTER_DL_FAIL_CAP = 4096

_ITEMS_HUB_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

_FACETS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}

_facets_snap_lock = threading.Lock()

_RECOMMEND_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

_ACTRESS_OPT_LOCK = threading.Lock()

_actress_opt_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "progress": None,
    "log": [],
    "result": None,
    "error": None,
}

_actress_opt_hydrated = False

_actress_opt_hydrate_lock = threading.Lock()


def _persist_embed_job(**extra: Any) -> None:
    try:
        from app.core import job_persist

        with _job_lock:
            payload = {
                "status": "running" if _job.get("running") else str(extra.get("status") or _job.get("phase") or "idle"),
                "phase": str(_job.get("phase") or ""),
                "progress": dict(_job.get("progress") or {}) or None,
                "log": list(_job.get("log") or [])[-40:],
                "result": _job.get("result"),
                "error": _job.get("error"),
                "running": bool(_job.get("running")),
            }
        for k, v in extra.items():
            if k == "status" and _job.get("running"):
                payload["status"] = "running"
            else:
                payload[k] = v
        if payload.get("running"):
            payload["status"] = "running"
        job_persist.save_job(job_persist.EMBED_JOB_KEY, payload)
    except Exception as e:  # noqa: BLE001
        log.warning("persist embed job failed: %s", e)


def _hydrate_embed_job(*, force: bool = False) -> dict[str, Any]:
    """从 DB 恢复上次任务快照；若上次崩溃中 running→interrupted。"""
    global _job_hydrated
    with _job_hydrate_lock:
        if _job_hydrated and not force:
            return {}
        _job_hydrated = True
    try:
        from app.core import job_persist

        raw = job_persist.load_job(job_persist.EMBED_JOB_KEY)
        if not raw:
            return {}
        with _job_lock:
            if _job.get("running"):
                return raw
            if not _job.get("phase") and raw.get("phase"):
                _job["phase"] = str(raw.get("phase") or "")
            if not _job.get("progress") and raw.get("progress"):
                _job["progress"] = dict(raw.get("progress") or {})
            if not _job.get("log") and raw.get("log"):
                _job["log"] = list(raw.get("log") or [])[-40:]
            if _job.get("result") is None and raw.get("result") is not None:
                _job["result"] = raw.get("result")
            if not _job.get("error") and raw.get("error"):
                _job["error"] = raw.get("error")
            st = str(raw.get("status") or "")
            if st == "running":
                _job["phase"] = "interrupted"
                prog = dict(_job.get("progress") or {})
                prog["label"] = "进程中断 · 可继续"
                _job["progress"] = prog
                raw = dict(raw)
                raw["status"] = "interrupted"
                raw["running"] = False
                job_persist.save_job(job_persist.EMBED_JOB_KEY, raw)
        return raw
    except Exception as e:  # noqa: BLE001
        log.warning("hydrate embed job failed: %s", e)
        return {}


def get_job_status() -> dict[str, Any]:
    _hydrate_embed_job()
    with _job_lock:
        return {
            "running": bool(_job["running"]),
            "phase": _job.get("phase") or "",
            "progress": _job.get("progress"),
            "log": list(_job.get("log") or [])[-12:],
            "result": _job.get("result"),
            "error": _job.get("error"),
        }


def _push_log(msg: str) -> None:
    with _job_lock:
        log_list = list(_job.get("log") or [])
        log_list.append(str(msg))
        _job["log"] = log_list[-40:]


def _set_progress(**kwargs: Any) -> None:
    with _job_lock:
        cur = dict(_job.get("progress") or {})
        cur.update(kwargs)
        _job["progress"] = cur
        if kwargs.get("label"):
            _job["phase"] = str(kwargs["label"])


def _ensure_poster_dl_pool() -> None:
    global _poster_dl_q
    from app.scrap_library.embed_poster import _poster_dl_worker_loop

    with _poster_dl_lock:
        if _poster_dl_q is not None:
            return
        _poster_dl_q = queue.Queue()
        for i in range(_POSTER_DL_WORKERS):
            threading.Thread(
                target=_poster_dl_worker_loop,
                name=f"scrap-poster-dl-{i}",
                daemon=True,
            ).start()


def _hydrate_actress_opt_job(*, force: bool = False) -> dict[str, Any]:
    global _actress_opt_hydrated
    with _actress_opt_hydrate_lock:
        if _actress_opt_hydrated and not force:
            return {}
        _actress_opt_hydrated = True
    try:
        from app.core import job_persist

        raw = job_persist.load_job(job_persist.ACTRESS_OPTIMIZE_JOB_KEY)
        if not raw:
            return {}
        with _ACTRESS_OPT_LOCK:
            if _actress_opt_job.get("running"):
                return raw
            if not _actress_opt_job.get("phase") and raw.get("phase"):
                _actress_opt_job["phase"] = str(raw.get("phase") or "")
            if not _actress_opt_job.get("progress") and raw.get("progress"):
                _actress_opt_job["progress"] = dict(raw.get("progress") or {})
            if not _actress_opt_job.get("log") and raw.get("log"):
                _actress_opt_job["log"] = list(raw.get("log") or [])[-40:]
            if (
                _actress_opt_job.get("result") is None
                and raw.get("result") is not None
            ):
                _actress_opt_job["result"] = raw.get("result")
            if not _actress_opt_job.get("error") and raw.get("error"):
                _actress_opt_job["error"] = raw.get("error")
            if str(raw.get("status") or "") == "running":
                _actress_opt_job["phase"] = "interrupted"
                prog = dict(_actress_opt_job.get("progress") or {})
                prog["label"] = "进程中断 · 可继续"
                _actress_opt_job["progress"] = prog
                raw = dict(raw)
                raw["status"] = "interrupted"
                raw["running"] = False
                job_persist.save_job(job_persist.ACTRESS_OPTIMIZE_JOB_KEY, raw)
        return raw
    except Exception as e:  # noqa: BLE001
        log.warning("hydrate actress optimize job failed: %s", e)
        return {}
