# -*- coding: utf-8 -*-
"""Public retry_enrich_fails/softs + prune/total/skip-cache helpers."""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

import app.scrap_library.enrich as _enrich
from app.scrap_library.enrich_runtime import (
    _enrich_job,
    _enrich_lock,
    _enrich_retry_front,
    _persist_enrich_runtime,
    notify_enrich_watchers,
)

log = logging.getLogger(__name__)

_stale_running_last: dict[str, float] = {}


_STALE_RUNNING_MIN_INTERVAL_SEC = 3.0


def retry_enrich_fails(*, region: str = "") -> dict[str, Any]:
    """失败批量重试：转入未处理，并尽量插到当前任务最前优先跑。"""
    global _enrich_retry_front
    rid = _enrich._queue_log_region(region)
    if not rid:
        return {"ok": False, "reopened": 0, "error": "region required"}
    rows = _enrich._queue_log_reopen_fails(rid)
    n = len(rows)
    if n <= 0:
        # 仍可能因 overlay 显示有失败：以库内真实值为准同步角标
        raw = _enrich._queue_log_status_counts_db(rid)
        tip = _enrich._LOCAL_STATUS_TOTALS.get(rid) if rid else None
        if tip:
            _enrich._set_local_status_totals(
                rid,
                done=int(raw.get("done") or tip.get("done") or 0),
                soft=int(raw.get("soft") or tip.get("soft") or 0),
                fail=int(raw.get("fail") or 0),
            )
        _enrich._counts_cache.pop(rid, None)
        counts = _enrich._queue_log_status_counts(rid, fresh=True)
        counts["fail"] = int(raw.get("fail") or 0)
        # pending 以队列表为准，不用向量估算覆盖
        return {
            "ok": True,
            "reopened": 0,
            "region": rid,
            "counts": counts,
            "injected": False,
        }

    # 解除封面/源放弃，否则重开后仍会被跳过
    try:
        codes = [
            str(r.get("code") or "").strip().upper()
            for r in rows
            if str(r.get("code") or "").strip()
        ]
        _enrich._retry_hint_clear_codes(rid, codes)
    except Exception:  # noqa: BLE001
        pass

    injected = False
    with _enrich._enrich_lock:
        cur_reg = _enrich._queue_log_region(str(_enrich._enrich_job.get("currentRegion") or ""))
        running = bool(_enrich._enrich_job.get("running"))
        # 检查点：插到剩余队列头，失败计数下调
        cps = dict(_enrich._enrich_job.get("checkpoints") or {})
        cp = cps.get(rid) if isinstance(cps.get(rid), dict) else None
        if isinstance(cp, dict):
            old_q = [dict(r) for r in list(cp.get("queue") or []) if isinstance(r, dict)]
            # 去重：已在剩余队列的不重复插
            seen_keys = {
                str(r.get("itemId") or r.get("code") or "").strip()
                for r in old_q
            }
            head = [
                r
                for r in rows
                if str(r.get("itemId") or r.get("code") or "").strip() not in seen_keys
            ]
            cp = dict(cp)
            cp["queue"] = head + old_q
            cp["remainingCount"] = max(
                int(cp.get("remainingCount") or 0) + len(head),
                len(cp["queue"]),
            )
            cp["failed"] = max(0, int(cp.get("failed") or 0) - n)
            cps[rid] = cp
            _enrich._enrich_job["checkpoints"] = cps
        if running and cur_reg == rid:
            # 插到投递前端；同键去重
            existing = {
                str(r.get("itemId") or r.get("code") or "").strip()
                for r in _enrich_retry_front
                if isinstance(r, dict)
            }
            add = [
                dict(r)
                for r in rows
                if str(r.get("itemId") or r.get("code") or "").strip() not in existing
            ]
            _enrich_retry_front = add + list(_enrich_retry_front)
            injected = True
            # 本轮进度失败数下调（避免角标虚高）
            prog = _enrich._enrich_job.get("progress")
            if isinstance(prog, dict):
                prog = dict(prog)
                prog["failed"] = max(0, int(prog.get("failed") or 0) - n)
                _enrich._enrich_job["progress"] = prog
        # 运行中 SSE 只读内存 queueCounts。失败数写成重开后的真实剩余，不能只减一截旧角标。
        if cur_reg == rid or not cur_reg:
            qc_mem = dict(_enrich._enrich_job.get("queueCounts") or {})
            if qc_mem:
                qc_mem["pending"] = int(qc_mem.get("pending") or 0) + n
                _enrich._enrich_job["queueCounts"] = qc_mem

    try:
        _enrich._persist_enrich_runtime()
    except Exception:  # noqa: BLE001
        pass

    # 角标：失败 overlay 必须跟库内走，否则会一直钉在扫描时的全量失败数
    raw = _enrich._queue_log_status_counts_db(rid)
    tip = _enrich._LOCAL_STATUS_TOTALS.get(rid) if rid else None
    fail_left = int(raw.get("fail") or 0)
    _enrich._set_local_status_totals(
        rid,
        done=int(raw.get("done") or (tip or {}).get("done") or 0),
        soft=int(raw.get("soft") or (tip or {}).get("soft") or 0),
        fail=fail_left,
    )
    with _enrich._enrich_lock:
        qc_mem = dict(_enrich._enrich_job.get("queueCounts") or {})
        if qc_mem:
            qc_mem["fail"] = fail_left
            _enrich._enrich_job["queueCounts"] = qc_mem
    _enrich._counts_cache.pop(rid, None)

    _enrich._push_log(f"失败重试 · {n} 条 → 未处理优先", region=rid)
    try:
        _enrich.notify_enrich_watchers(force=True)
    except Exception:  # noqa: BLE001
        pass
    counts = _enrich._queue_log_status_counts(rid, fresh=True)
    counts["fail"] = fail_left
    return {
        "ok": True,
        "reopened": n,
        "region": rid,
        "counts": counts,
        "injected": injected,
        "running": bool(_enrich._enrich_job.get("running")),
    }


def retry_enrich_softs(*, region: str = "") -> dict[str, Any]:
    """软成功批量重试：转入未处理，并尽量插到当前任务最前优先跑。"""
    global _enrich_retry_front
    rid = _enrich._queue_log_region(region)
    if not rid:
        return {"ok": False, "reopened": 0, "error": "region required"}
    rows = _enrich._queue_log_reopen_softs(rid)
    n = len(rows)
    if n <= 0:
        raw = _enrich._queue_log_status_counts_db(rid)
        tip = _enrich._LOCAL_STATUS_TOTALS.get(rid) if rid else None
        if tip:
            _enrich._set_local_status_totals(
                rid,
                done=int(raw.get("done") or tip.get("done") or 0),
                soft=int(raw.get("soft") or 0),
                fail=int(raw.get("fail") or tip.get("fail") or 0),
            )
        _enrich._counts_cache.pop(rid, None)
        counts = _enrich._queue_log_status_counts(rid, fresh=True)
        return {
            "ok": True,
            "reopened": 0,
            "region": rid,
            "counts": counts,
            "injected": False,
        }

    try:
        codes = [
            str(r.get("code") or "").strip().upper()
            for r in rows
            if str(r.get("code") or "").strip()
        ]
        _enrich._retry_hint_clear_codes(rid, codes)
    except Exception:  # noqa: BLE001
        pass

    injected = False
    with _enrich._enrich_lock:
        cur_reg = _enrich._queue_log_region(str(_enrich._enrich_job.get("currentRegion") or ""))
        running = bool(_enrich._enrich_job.get("running"))
        cps = dict(_enrich._enrich_job.get("checkpoints") or {})
        cp = cps.get(rid) if isinstance(cps.get(rid), dict) else None
        if isinstance(cp, dict):
            old_q = [dict(r) for r in list(cp.get("queue") or []) if isinstance(r, dict)]
            seen_keys = {
                str(r.get("itemId") or r.get("code") or "").strip()
                for r in old_q
            }
            head = [
                r
                for r in rows
                if str(r.get("itemId") or r.get("code") or "").strip() not in seen_keys
            ]
            cp = dict(cp)
            cp["queue"] = head + old_q
            cp["remainingCount"] = max(
                int(cp.get("remainingCount") or 0) + len(head),
                len(cp["queue"]),
            )
            # 软成功原先计入 ok
            cp["ok"] = max(0, int(cp.get("ok") or 0) - n)
            cps[rid] = cp
            _enrich._enrich_job["checkpoints"] = cps
        if running and cur_reg == rid:
            existing = {
                str(r.get("itemId") or r.get("code") or "").strip()
                for r in _enrich_retry_front
                if isinstance(r, dict)
            }
            add = [
                dict(r)
                for r in rows
                if str(r.get("itemId") or r.get("code") or "").strip() not in existing
            ]
            _enrich_retry_front = add + list(_enrich_retry_front)
            injected = True
            prog = _enrich._enrich_job.get("progress")
            if isinstance(prog, dict):
                prog = dict(prog)
                prog["ok"] = max(0, int(prog.get("ok") or 0) - n)
                _enrich._enrich_job["progress"] = prog
        if cur_reg == rid or not cur_reg:
            qc_mem = dict(_enrich._enrich_job.get("queueCounts") or {})
            if qc_mem:
                qc_mem["pending"] = int(qc_mem.get("pending") or 0) + n
                _enrich._enrich_job["queueCounts"] = qc_mem

    try:
        _enrich._persist_enrich_runtime()
    except Exception:  # noqa: BLE001
        pass

    raw = _enrich._queue_log_status_counts_db(rid)
    tip = _enrich._LOCAL_STATUS_TOTALS.get(rid) if rid else None
    soft_left = int(raw.get("soft") or 0)
    _enrich._set_local_status_totals(
        rid,
        done=int(raw.get("done") or (tip or {}).get("done") or 0),
        soft=soft_left,
        fail=int(raw.get("fail") or (tip or {}).get("fail") or 0),
    )
    with _enrich._enrich_lock:
        qc_mem = dict(_enrich._enrich_job.get("queueCounts") or {})
        if qc_mem:
            qc_mem["soft"] = soft_left
            _enrich._enrich_job["queueCounts"] = qc_mem
    _enrich._counts_cache.pop(rid, None)

    _enrich._push_log(f"软成功重试 · {n} 条 → 未处理优先", region=rid)
    try:
        _enrich.notify_enrich_watchers(force=True)
    except Exception:  # noqa: BLE001
        pass
    counts = _enrich._queue_log_status_counts(rid, fresh=True)
    counts["soft"] = soft_left
    counts["done"] = int(raw.get("done") or counts.get("done") or 0)
    return {
        "ok": True,
        "reopened": n,
        "region": rid,
        "counts": counts,
        "injected": injected,
        "running": bool(_enrich._enrich_job.get("running")),
    }


def _maybe_prune_done_logs(region: str) -> None:
    """完成若干条后异步裁剪 done，避免拖慢主路径。"""
    global _finish_prune_counter
    with _enrich._finish_prune_lock:
        _enrich._finish_prune_counter += 1
        n = int(_enrich._finish_prune_counter)
    if n % int(_enrich._QUEUE_LOG_PRUNE_EVERY) != 0:
        return
    rid = str(region or "").strip()
    if not rid:
        return

    def _run() -> None:
        try:
            dropped = _enrich._queue_log_prune_done_keep(rid)
            if dropped:
                _enrich._push_log(f"队列表裁剪 done · -{dropped}", region=rid)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_run, name="enrich-prune-done", daemon=True).start()


_incomplete_cache: dict[str, tuple[float, int, int]] = {}


_INCOMPLETE_CACHE_TTL_SEC = 45.0


def _fresh_vector_library_total(region: str, *, force: bool = False) -> int:
    """向量库该区番号总数（轻量 COUNT）。

    tip.total 会在双库扫描/骨架重建后落后；扫描与未处理角标必须以库为准。
    默认走短缓存，扫描传 force=True 强制刷新。
    """
    rid = _enrich._queue_log_region(region)
    if not rid:
        return 0
    now = time.time()
    if not force:
        hit = _incomplete_cache.get(rid)
        if hit and now - float(hit[0]) < _INCOMPLETE_CACHE_TTL_SEC:
            cached = int(hit[1] or 0)
            if cached > 0:
                return cached
    live = 0
    try:
        from app.scrap_library.embed import region_library_totals_fast

        live = int(region_library_totals_fast(region=rid).get("total") or 0)
    except Exception:  # noqa: BLE001
        live = 0
    if live > 0:
        prev_inc = 0
        hit = _incomplete_cache.get(rid)
        if hit:
            prev_inc = int(hit[2] or 0)
        _incomplete_cache[rid] = (now, live, prev_inc)
        # 同步 tip.total，避免后续路径继续用旧目录量级
        _enrich._ensure_local_status_totals_loaded()
        tip = _enrich._LOCAL_STATUS_TOTALS.get(rid) or {}
        if int(tip.get("total") or 0) != live:
            _enrich._set_local_status_totals(
                rid,
                done=int(tip.get("done") or 0),
                soft=int(tip.get("soft") or 0),
                fail=int(tip.get("fail") or 0),
                total=live,
            )
    return max(0, live)


_classified_skip_cache: dict[str, tuple[float, set[str], set[str]]] = {}


_CLASSIFIED_SKIP_TTL_SEC = 120.0


_pending_backfill_done: set[str] = set()


_local_nfo_maps_cache: dict[str, tuple[float, set[str], set[str], int, int, int]] = {}


_LOCAL_NFO_MAPS_TTL_SEC = 900.0


_LOCAL_NFO_MAPS_CACHE_MAX = 2


def _invalidate_classified_skip_cache(region: str = "") -> None:
    rid = _enrich._queue_log_region(region) if str(region or "").strip() else ""
    if rid:
        _classified_skip_cache.pop(rid, None)
    else:
        _classified_skip_cache.clear()


_DONE_LOG_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9\-_]{1,24})\s*·\s*完成"
)


_folder_gaps_cache: dict[str, tuple[tuple[Any, ...], tuple[str, list[str]]]] = {}


_FOLDER_GAPS_CACHE_CAP = 160_000


_folder_gaps_cache_lock = threading.Lock()


_lib_progress_counts_cache: dict[str, tuple[float, dict[str, int]]] = {}


_LIB_PROGRESS_COUNTS_TTL_SEC = 3.0


_GAP_FAIL_LABEL = {
    "no_local": "封面",
    "no_media": "外链",
    "no_actress": "女优",
    "no_studio": "片商",
    "no_plot": "剧情",
    "thin_title": "标题",
    "no_zh_title": "中文标题",
}


_COVER_FAIL_LABEL = {
    "slot_blocked": "封面队列繁忙",
    "timeout": "封面超时",
    "download": "封面下载失败",
    "host_blocked": "图床暂时不可用",
    "blank": "封面空图",
    "too_small": "封面尺寸过小",
    "write_fail": "封面写入失败",
    "all_failed": "封面全部候选失败",
    "no_candidates": "无封面候选",
    "kept_old": "保留旧封面",
}


_SUCCESS_BLOCK_GAPS = frozenset({"no_local"})


_SOFT_SUCCESS_GAPS = frozenset({"thin_title"})


_SOFT_GAP_LABELS = frozenset(
    {_GAP_FAIL_LABEL[g] for g in _SOFT_SUCCESS_GAPS if g in _GAP_FAIL_LABEL}
)


_promoted_actress_soft: dict[str, int] = {}


_demoted_false_dones: set[str] = set()


_soft_correction_last: dict[str, float] = {}


_COVER_ONLY_GAPS = frozenset({"no_local", "no_media"})


_retry_hint_cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}


_retry_hint_known: dict[tuple[str, str], set[str]] = {}


_retry_hint_primed: set[tuple[str, str]] = set()


_SOURCE_DOWN_STREAK: dict[str, int] = {}


_SOURCE_COOLDOWN_UNTIL: dict[str, float] = {}


_SOURCE_COOLDOWN_LOCK = threading.Lock()


