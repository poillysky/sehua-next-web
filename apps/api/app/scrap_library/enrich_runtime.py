# -*- coding: utf-8 -*-
"""Enrich job runtime state — locks, job dict, watchers, persist/hydrate helpers."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

_enrich_lock = threading.RLock()

_strategy_epoch = 0

_strategy_epoch_mu = threading.Lock()

_enrich_retry_front: list[dict[str, Any]] = []

_enrich_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "progress": None,
    "log": [],
    "regionLogs": {},
    "currentRegion": "",
    "cancel": False,  # 兼容旧字段：True 表示收到 halt
    "halt": None,  # None | "pause" | "stop"
    "queue": [],
    "current": None,
    "result": None,
    "error": None,
    # region_id -> 暂停检查点（剩余队列，再开即继续）
    "checkpoints": {},
    # 当前轮次元数据（暂停立刻写检查点时用）
    "jobMode": "incremental",
    "jobKinds": [],
    "jobDryRun": False,
}

_enrich_watchers_lock = threading.Lock()

_enrich_watchers: list[threading.Event] = []

_enrich_notify_last = 0.0

_ENRICH_NOTIFY_MIN_GAP = 0.7

_ENRICH_NOTIFY_FORCE_MIN_GAP = 0.35

_enrich_hydrated = False

_enrich_hydrate_lock = threading.Lock()

_QUEUE_SCAN_LOCK = threading.Lock()

_QUEUE_SCAN_STATE: dict[str, Any] = {
    "active": False,
    "region": "",
    "stage": "",
    "label": "",
    "scanned": 0,
    "total": 0,
    "done": 0,
    "soft": 0,
    "fail": 0,
    "pending": 0,
    "samplesDone": [],
    "samplesSoft": [],
    "samplesFail": [],
    "updatedAt": 0.0,
}

_queue_scan_notify_last = 0.0


def subscribe_enrich_updates() -> threading.Event:
    ev = threading.Event()
    with _enrich_watchers_lock:
        _enrich_watchers.append(ev)
    ev.set()  # 立刻推一帧快照
    return ev


def unsubscribe_enrich_updates(ev: threading.Event) -> None:
    with _enrich_watchers_lock:
        try:
            _enrich_watchers.remove(ev)
        except ValueError:
            pass


def notify_enrich_watchers(*, force: bool = False) -> None:
    """唤醒 SSE 订阅端。force=阶段切换；普通进度有最小间隔合并。"""
    global _enrich_notify_last
    now = time.monotonic()
    gap = _ENRICH_NOTIFY_FORCE_MIN_GAP if force else _ENRICH_NOTIFY_MIN_GAP
    if (now - _enrich_notify_last) < gap:
        return
    _enrich_notify_last = now
    with _enrich_watchers_lock:
        watchers = list(_enrich_watchers)
    for ev in watchers:
        ev.set()


def _checkpoint_summaries() -> dict[str, Any]:
    raw = dict(_enrich_job.get("checkpoints") or {})
    out: dict[str, Any] = {}
    for rid, cp in raw.items():
        key = str(rid or "").strip()
        if not key or not isinstance(cp, dict):
            continue
        remaining = cp.get("queue") or []
        sample_n = len(remaining) if isinstance(remaining, list) else 0
        rem_n = max(int(cp.get("remainingCount") or 0), sample_n)
        done = int(cp.get("done") or 0)
        total = int(cp.get("originalTotal") or (done + rem_n))
        out[key] = {
            "region": key,
            "mode": str(cp.get("mode") or "incremental"),
            "dryRun": bool(cp.get("dryRun")),
            "done": done,
            "remaining": rem_n,
            "total": total,
            "ok": int(cp.get("ok") or 0),
            "failed": int(cp.get("failed") or 0),
        }
    return out


def bump_strategy_epoch() -> int:
    global _strategy_epoch
    with _strategy_epoch_mu:
        _strategy_epoch += 1
        return int(_strategy_epoch)


def _persist_enrich_runtime() -> None:
    """把检查点 + 任务快照写入 app_settings（跨重启）。"""
    try:
        from app.core import job_persist
        from app.scrap_library.enrich_checkpoint import _checkpoint_for_persist
        from app.scrap_library.enrich_status import _slim_result_for_status

        with _enrich_lock:
            cps_raw = dict(_enrich_job.get("checkpoints") or {})
            cps_out: dict[str, Any] = {}
            for rid, cp in cps_raw.items():
                if not isinstance(cp, dict):
                    continue
                row = _checkpoint_for_persist(
                    {
                        **cp,
                        "region": str(cp.get("region") or rid),
                    }
                )
                cps_out[str(rid)] = row
            snapshot = {
                "phase": str(_enrich_job.get("phase") or ""),
                "progress": dict(_enrich_job.get("progress") or {}) or None,
                "jobMode": str(_enrich_job.get("jobMode") or "incremental"),
                "jobKinds": list(_enrich_job.get("jobKinds") or []),
                "jobDryRun": bool(_enrich_job.get("jobDryRun")),
                "currentRegion": str(_enrich_job.get("currentRegion") or ""),
                "result": _slim_result_for_status(_enrich_job.get("result")),
                "error": _enrich_job.get("error"),
                "running": bool(_enrich_job.get("running")),
                "halt": _enrich_job.get("halt"),
            }
            status = "idle"
            if snapshot["running"]:
                status = "running"
            elif cps_out or str(snapshot["phase"]) == "paused":
                status = "paused"
            elif str(snapshot["phase"]) in {"stopped", "cleared"}:
                status = "stopped"
            elif str(snapshot["phase"]) == "done":
                status = "done"
            elif str(snapshot["phase"]) == "error":
                status = "error"
            payload = {
                "status": status,
                "checkpoints": cps_out,
                "snapshot": snapshot,
            }
        job_persist.save_job(job_persist.ENRICH_RUNTIME_KEY, payload)
    except Exception as e:  # noqa: BLE001
        log.warning("persist enrich runtime failed: %s", e)


def _hydrate_enrich_runtime(*, force: bool = False) -> None:
    """进程启动后首次从 DB 恢复检查点/快照。"""
    global _enrich_hydrated
    with _enrich_hydrate_lock:
        if _enrich_hydrated and not force:
            return
        _enrich_hydrated = True
    try:
        from app.core import job_persist
        from app.scrap_library.enrich_queue_io import _queue_log_region
        from app.scrap_library.enrich_checkpoint import _CHECKPOINT_PERSIST_QUEUE_MAX
        from app.scrap_library.enrich_queue import (
            _queue_log_reopen_running,
            _queue_log_status_counts,
        )
        from app.scrap_library.enrich_status import _slim_result_for_status

        raw = job_persist.load_job(job_persist.ENRICH_RUNTIME_KEY)
        if not raw:
            return
        cps_in = raw.get("checkpoints") if isinstance(raw.get("checkpoints"), dict) else {}
        snap = raw.get("snapshot") if isinstance(raw.get("snapshot"), dict) else {}
        rebuilt: dict[str, Any] = {}
        need_rewrite = False
        for rid, cp in cps_in.items():
            if not isinstance(cp, dict):
                continue
            key = str(rid or "").strip()
            if not key:
                continue
            queue = [dict(r) for r in list(cp.get("queue") or []) if isinstance(r, dict)]
            rem_n = int(cp.get("remainingCount") or 0) or len(queue)
            if len(queue) > _CHECKPOINT_PERSIST_QUEUE_MAX:
                need_rewrite = True
                rem_n = max(rem_n, len(queue))
                queue = queue[:_CHECKPOINT_PERSIST_QUEUE_MAX]
            rebuilt[key] = {
                "region": str(cp.get("region") or key),
                "mode": str(cp.get("mode") or "incremental"),
                "kinds": list(cp.get("kinds") or []),
                "dryRun": bool(cp.get("dryRun")),
                "ok": int(cp.get("ok") or 0),
                "failed": int(cp.get("failed") or 0),
                "done": int(cp.get("done") or 0),
                "originalTotal": int(cp.get("originalTotal") or 0),
                "queue": queue,
                "remainingCount": rem_n,
                "queueInLog": bool(cp.get("queueInLog")) or rem_n > len(queue),
            }
        with _enrich_lock:
            if _enrich_job.get("running"):
                return
            if rebuilt:
                _enrich_job["checkpoints"] = rebuilt
            if snap and not _enrich_job.get("running"):
                if snap.get("phase") and not _enrich_job.get("phase"):
                    _enrich_job["phase"] = str(snap.get("phase") or "")
                if snap.get("progress") and not _enrich_job.get("progress"):
                    _enrich_job["progress"] = dict(snap.get("progress") or {})
                if snap.get("jobMode"):
                    _enrich_job["jobMode"] = str(snap.get("jobMode") or "incremental")
                if snap.get("jobKinds") is not None:
                    _enrich_job["jobKinds"] = list(snap.get("jobKinds") or [])
                if "jobDryRun" in snap:
                    _enrich_job["jobDryRun"] = bool(snap.get("jobDryRun"))
                if snap.get("result") is not None and _enrich_job.get("result") is None:
                    _enrich_job["result"] = _slim_result_for_status(snap.get("result"))
                if snap.get("error") and not _enrich_job.get("error"):
                    _enrich_job["error"] = snap.get("error")
                _enrich_job["running"] = False
                _enrich_job["halt"] = None
                _enrich_job["cancel"] = False
                st = str(raw.get("status") or "")
                if st == "running" and rebuilt:
                    _enrich_job["phase"] = "paused"
                    prog = dict(_enrich_job.get("progress") or {})
                    prog["label"] = "进程中断 · 可继续"
                    prog["stage"] = "done"
                    _enrich_job["progress"] = prog
                    for rid in rebuilt:
                        _queue_log_reopen_running(region=rid)
                elif st == "running" and not rebuilt:
                    recover_rid = _queue_log_region(
                        str(snap.get("currentRegion") or "")
                    )
                    if not recover_rid:
                        for rid0 in list(
                            (snap.get("result") or {}).get("regions") or []
                        ) if isinstance(snap.get("result"), dict) else []:
                            recover_rid = _queue_log_region(str(rid0 or ""))
                            if recover_rid:
                                break
                    if recover_rid:
                        try:
                            _queue_log_reopen_running(region=recover_rid)
                        except Exception:  # noqa: BLE001
                            pass
                        dbc = _queue_log_status_counts(recover_rid, fresh=True)
                        rem_n = int(dbc.get("pending") or 0)
                        if rem_n > 0:
                            rebuilt_one = {
                                "region": recover_rid,
                                "mode": str(
                                    snap.get("jobMode") or "incremental"
                                ),
                                "kinds": list(snap.get("jobKinds") or []),
                                "dryRun": bool(snap.get("jobDryRun")),
                                "ok": int(dbc.get("done") or 0),
                                "failed": int(dbc.get("fail") or 0),
                                "done": int(dbc.get("done") or 0)
                                + int(dbc.get("fail") or 0),
                                "originalTotal": max(
                                    rem_n
                                    + int(dbc.get("done") or 0)
                                    + int(dbc.get("fail") or 0),
                                    rem_n,
                                ),
                                "queue": [],
                                "remainingCount": rem_n,
                                "queueInLog": True,
                            }
                            _enrich_job["checkpoints"] = {
                                recover_rid: rebuilt_one
                            }
                            rebuilt = {recover_rid: rebuilt_one}
                            _enrich_job["phase"] = "paused"
                            prog = dict(_enrich_job.get("progress") or {})
                            prog["label"] = "进程中断 · 可继续"
                            prog["stage"] = "done"
                            _enrich_job["progress"] = prog
                        else:
                            _enrich_job["phase"] = str(
                                snap.get("phase") or "interrupted"
                            )
                    else:
                        _enrich_job["phase"] = str(
                            snap.get("phase") or "interrupted"
                        )
        if need_rewrite or (
            isinstance(raw, dict) and str(raw.get("status") or "") == "running"
        ):
            try:
                _persist_enrich_runtime()
            except Exception:  # noqa: BLE001
                pass
        if str(raw.get("status") or "") == "running":
            try:
                from app.core import job_persist as jp

                patched = dict(raw)
                patched["status"] = "paused" if rebuilt else "interrupted"
                if patched.get("snapshot") and isinstance(patched["snapshot"], dict):
                    patched["snapshot"] = dict(patched["snapshot"])
                    patched["snapshot"]["running"] = False
                    if rebuilt:
                        patched["snapshot"]["phase"] = "paused"
                jp.save_job(jp.ENRICH_RUNTIME_KEY, patched)
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        log.warning("hydrate enrich runtime failed: %s", e)


def _set_queue_scan_progress(
    *,
    region: str = "",
    stage: str = "",
    label: str = "",
    scanned: int | None = None,
    total: int | None = None,
    done: int | None = None,
    soft: int | None = None,
    fail: int | None = None,
    pending: int | None = None,
    active: bool = True,
    notify: bool = True,
) -> None:
    """更新清空·扫描进度；notify 时唤醒 SSE（节流）。"""
    global _queue_scan_notify_last
    from app.scrap_library.enrich_queue_io import _queue_log_region
    from app.scrap_library.enrich_queue import _QUEUE_SCAN_NOTIFY_GAP

    rid = _queue_log_region(region) if str(region or "").strip() else ""
    with _QUEUE_SCAN_LOCK:
        if not active:
            _QUEUE_SCAN_STATE.update(
                {
                    "active": False,
                    "region": "",
                    "stage": "",
                    "label": "",
                    "scanned": 0,
                    "total": 0,
                    "done": 0,
                    "soft": 0,
                    "fail": 0,
                    "pending": 0,
                    "samplesDone": [],
                    "samplesSoft": [],
                    "samplesFail": [],
                    "updatedAt": time.monotonic(),
                }
            )
        else:
            if rid:
                _QUEUE_SCAN_STATE["region"] = rid
            if stage:
                _QUEUE_SCAN_STATE["stage"] = str(stage)
            if label:
                _QUEUE_SCAN_STATE["label"] = str(label)
            if scanned is not None:
                _QUEUE_SCAN_STATE["scanned"] = max(0, int(scanned))
            if total is not None:
                _QUEUE_SCAN_STATE["total"] = max(0, int(total))
            if done is not None:
                _QUEUE_SCAN_STATE["done"] = max(0, int(done))
            if soft is not None:
                _QUEUE_SCAN_STATE["soft"] = max(0, int(soft))
            if fail is not None:
                _QUEUE_SCAN_STATE["fail"] = max(0, int(fail))
            if pending is not None:
                _QUEUE_SCAN_STATE["pending"] = max(0, int(pending))
            _QUEUE_SCAN_STATE["active"] = True
            _QUEUE_SCAN_STATE["updatedAt"] = time.monotonic()
    if not notify:
        return
    now = time.monotonic()
    force = bool(stage) and scanned is None
    gap = 0.12 if force else _QUEUE_SCAN_NOTIFY_GAP
    if (now - _queue_scan_notify_last) < gap and not force:
        return
    _queue_scan_notify_last = now
    try:
        notify_enrich_watchers(force=force)
    except Exception:  # noqa: BLE001
        pass


def _set_progress(**kwargs: Any) -> None:
    from app.scrap_library.enrich_status import _progress_from_queue_counts

    with _enrich_lock:
        cur = dict(_enrich_job.get("progress") or {})
        cur.update(kwargs)
        counts = _enrich_job.get("queueCounts")
        if isinstance(counts, dict):
            qtot = sum(
                int(counts.get(k) or 0)
                for k in ("pending", "running", "done", "fail")
            )
            if qtot > 0:
                keep_label = cur.get("label")
                keep_stage = cur.get("stage")
                cur = _progress_from_queue_counts(counts, base=cur)
                if "label" in kwargs:
                    cur["label"] = kwargs["label"]
                elif keep_label is not None:
                    cur["label"] = keep_label
                if keep_stage is not None:
                    cur["stage"] = keep_stage
        _enrich_job["progress"] = cur
        if kwargs.get("label"):
            _enrich_job["phase"] = str(kwargs["label"])
    notify_enrich_watchers()


def _enrich_percent(done: int, total: int) -> int:
    """按已完成条数映射 0–100；不再人为从 10% 起跳。"""
    t = int(total or 0)
    if t <= 0:
        return 0
    d = max(0, min(int(done or 0), t))
    if d >= t:
        return 100
    return max(0, min(99, int(round(100.0 * d / t))))
