# -*- coding: utf-8 -*-
"""Enrich job control: pause / stop / cancel / budget helpers."""
from __future__ import annotations

import logging
from typing import Any

from app.scrap_library import enrich_monitor as enrich_mon
from app.scrap_library.enrich_runtime import (
    _enrich_job,
    _enrich_lock,
    _enrich_percent,
    _persist_enrich_runtime,
    notify_enrich_watchers,
)

log = logging.getLogger(__name__)


def _fill_mode_to_job_mode(fill_mode: str) -> str:
    raw = str(fill_mode or "incremental").strip().lower()
    if raw in {"overwrite", "cover", "force", "replace", "full"}:
        return "overwrite"
    if raw in {"refresh_weak", "weak", "refresh"}:
        return "refresh_weak"
    return "incremental"


def request_enrich_pause() -> dict[str, Any]:
    """暂停：立刻停投递；进行中/未处理一并退回 pending 检查点，再开续跑。

    不在这里等在飞线程结束——工作线程见 halt=pause 后立即收尾（shutdown wait=False）。
    """
    import app.scrap_library.enrich as _enrich

    with _enrich._enrich_lock:
        if not _enrich._enrich_job.get("running"):
            if _enrich._enrich_job.get("checkpoints"):
                return {"ok": True, "paused": True, "running": False}
            return {"ok": True, "paused": False, "running": False}
        _enrich._enrich_job["halt"] = "pause"
        _enrich._enrich_job["cancel"] = True
        region = str(_enrich._enrich_job.get("currentRegion") or "").strip()
        view = [
            dict(r)
            for r in list(_enrich._enrich_job.get("queue") or [])
            if isinstance(r, dict)
        ]
        remaining: list[dict[str, Any]] = []
        new_view: list[dict[str, Any]] = []
        ok_n = 0
        fail_n = 0
        for r in view:
            st = str(r.get("status") or "pending")
            if st == "done":
                ok_n += 1
                new_view.append(r)
                continue
            if st == "fail":
                fail_n += 1
                new_view.append(r)
                continue
            row = dict(r)
            row["status"] = "pending"
            row.pop("error", None)
            new_view.append(row)
            rem: dict[str, Any] = {
                "itemId": str(r.get("itemId") or ""),
                "code": str(r.get("code") or ""),
                "gaps": list(r.get("gaps") or []),
                "rel_path": str(
                    r.get("rel_path") or r.get("relPath") or ""
                ),
                "relPath": str(
                    r.get("relPath") or r.get("rel_path") or ""
                ),
                "region": region,
            }
            lid = _enrich._queue_log_int_id(r)
            if lid:
                rem["logId"] = lid
            remaining.append(rem)
        pause_log_ids = [
            _enrich._queue_log_int_id(r)
            for r in remaining
            if _enrich._queue_log_int_id(r) > 0
        ]
        done_n = ok_n + fail_n
        total = len(view) if view else done_n + len(remaining)
        try:
            db_pending = int(
                _enrich._queue_log_status_counts(region, fresh=True).get("pending")
                or 0
            )
        except Exception:  # noqa: BLE001
            db_pending = 0
        rem_n = max(len(remaining), db_pending)
        _enrich._enrich_job["queue"] = new_view
        _enrich._enrich_job["queueCounts"] = _enrich._queue_counts_of(new_view)
        _enrich._enrich_job["queueCounts"]["pending"] = rem_n
        _enrich._enrich_job["queueCounts"]["running"] = 0
        ok_n = int(_enrich._enrich_job["queueCounts"].get("done") or 0) + int(
            _enrich._enrich_job["queueCounts"].get("soft") or 0
        )
        fail_n = int(_enrich._enrich_job["queueCounts"].get("fail") or 0)
        _enrich._enrich_job["current"] = None
        _enrich._enrich_job["phase"] = "paused"
        _enrich._enrich_job["progress"] = {
            "stage": "done",
            "label": "已暂停",
            "done": done_n,
            "total": max(total, done_n + rem_n),
            "ok": ok_n,
            "failed": fail_n,
            "percent": _enrich._enrich_percent(done_n, max(total, done_n + rem_n))
            if (done_n + rem_n)
            else 0,
        }
        if region:
            cps = dict(_enrich._enrich_job.get("checkpoints") or {})
            prev = cps.get(region) if isinstance(cps.get(region), dict) else {}
            cps[region] = {
                "region": region,
                "mode": str(
                    prev.get("mode")
                    or _enrich._enrich_job.get("jobMode")
                    or "incremental"
                ),
                "kinds": list(
                    prev.get("kinds") or _enrich._enrich_job.get("jobKinds") or []
                ),
                "dryRun": bool(
                    prev.get("dryRun")
                    if "dryRun" in prev
                    else _enrich._enrich_job.get("jobDryRun")
                ),
                "queue": remaining,
                "ok": ok_n,
                "failed": fail_n,
                "done": done_n,
                "originalTotal": int(
                    prev.get("originalTotal") or max(total, done_n + rem_n)
                ),
                "remainingCount": rem_n,
                "queueInLog": rem_n > len(remaining),
            }
            _enrich._enrich_job["checkpoints"] = cps
        _enrich._enrich_job["running"] = False
    if pause_log_ids:
        _enrich._queue_log_mark_pending(pause_log_ids)
    if region:
        _enrich._queue_log_reopen_running(region=region)
    else:
        _enrich._queue_log_reopen_running()
    _enrich._persist_enrich_runtime()
    _enrich._push_log(
        f"已暂停 · 进行中已退回未处理 · 剩余 {len(remaining)}",
        region=region or "",
    )
    _enrich.notify_enrich_watchers(force=True)
    return {"ok": True, "paused": True, "running": False}


def request_enrich_stop(*, region: str = "") -> dict[str, Any]:
    """停止：清除运行队列与检查点；历史日志/队列记录保留（仅「清空日志」可删）。"""
    import app.scrap_library.enrich as _enrich

    rid = str(region or "").strip()
    with _enrich._enrich_lock:
        running = bool(_enrich._enrich_job.get("running"))
        if running:
            _enrich._enrich_job["halt"] = "stop"
            _enrich._enrich_job["cancel"] = True
            _enrich._enrich_job["phase"] = "stopping"
            cur = dict(_enrich._enrich_job.get("progress") or {})
            cur["label"] = "正在停止…"
            _enrich._enrich_job["progress"] = cur
        else:
            if rid:
                cps = dict(_enrich._enrich_job.get("checkpoints") or {})
                cps.pop(rid, None)
                _enrich._enrich_job["checkpoints"] = cps
            else:
                _enrich._enrich_job["checkpoints"] = {}
            _enrich._enrich_job["queue"] = []
            _enrich._enrich_job["current"] = None
            cur = dict(_enrich._enrich_job.get("progress") or {})
            cur["label"] = "已停止 · 队列已清除 · 历史日志保留"
            cur["stage"] = "cleared"
            cur["done"] = 0
            cur["total"] = 0
            cur["percent"] = 0
            _enrich._enrich_job["progress"] = cur
            _enrich._enrich_job["phase"] = "stopped"
            _enrich._enrich_job["result"] = None
    if rid:
        _enrich._queue_log_reopen_running(region=rid)
    else:
        _enrich._queue_log_reopen_running()
    _enrich._persist_enrich_runtime()
    if not running:
        try:
            enrich_mon.clear_job()
        except Exception:  # noqa: BLE001
            pass
    log.info(
        "enrich stop%s running=%s",
        f" region={rid}" if rid else "",
        running,
    )
    _enrich.notify_enrich_watchers(force=True)
    return {"ok": True, "stopped": True, "cleared": True, "running": running}


def _clear_runtime_queue(*, wipe_checkpoint_region: str = "") -> None:
    """停止后清掉运行时队列/当前项（暂停绝不能调用）。"""
    with _enrich._enrich_lock:
        _enrich._enrich_job["queue"] = []
        _enrich._enrich_job["queueCounts"] = {
            "pending": 0,
            "running": 0,
            "done": 0,
            "fail": 0,
        }
        _enrich._enrich_job["current"] = None
        if wipe_checkpoint_region:
            cps = dict(_enrich._enrich_job.get("checkpoints") or {})
            cps.pop(str(wipe_checkpoint_region).strip(), None)
            _enrich._enrich_job["checkpoints"] = cps
    if wipe_checkpoint_region:
        _enrich._persist_enrich_runtime()


def request_enrich_cancel() -> dict[str, Any]:
    """取消：当前语义等同暂停（保留 checkpoint，下次可续跑）。

    与 stop 区分：stop 清队列/进度；cancel/pause 只发停跑信号。
    """
    return request_enrich_pause()


def _next_budget(budget: int | None, part: dict[str, Any]) -> int | None:
    """多区调度：跨区 limit 预算扣减。

    必须按**实际处理条数**（`processed`）扣，不能按 `queued`：增量模式下
    `queued` 取库内待处理预估（有码区十万级），拿它扣减会让首个分区一口吃光
    整个 limit，后续分区全被「预览额度已用完」跳过。
    某区实际无待处理（processed=0）时预算原样顺延给下一区。
    """
    if budget is None:
        return None
    return max(0, budget - int(part.get("processed") or 0))
