# -*- coding: utf-8 -*-
"""刮削批量任务卡顿监控（内存态，经 enrich status / SSE 推送）。

只观测、不改调度；番号并发 / 源并发由策略另行控制。
"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_RECENT_MAX = 5
_INFLIGHT_MAX = 16

# 阶段无进展 / 慢阶段阈值（秒）
# 封面常 8–18s（CDN 多候选），过严会把正常下载刷成一片红
_PENDING_ALL_SEC = 4.0
_SLOT_BLOCKED_SEC = 14.0
_COVER_SLOW_SEC = 22.0
_ACTRESS_SLOW_SEC = 18.0
_WRITE_SLOW_SEC = 10.0
_FETCH_TAIL_SEC = 12.0  # 源已齐但仍停在 fetch

# 软卡顿：仍在干活，UI 用黄/橙；硬卡顿才红
SOFT_STALL_KINDS = frozenset(
    {
        "slot_blocked",
        "cover_slow",
        "source_slow",
        "fetch_tail",
        "all_sources_pending",
        "actress_slow",
        "write_slow",
    }
)

_PHASE_LABEL = {
    "fetch": "拉详情",
    "cover": "封面",
    "actress": "女优",
    "write": "写回",
    "start": "启动",
    "done": "完成",
    "fail": "失败",
}

_state: dict[str, Any] = {
    "enabled": True,
    "jobStartedAt": 0.0,
    "region": "",
    "itemWorkers": 5,
    "perSourceTimeoutSec": 28,
    "inflight": {},  # key -> item dict
    "recentStalls": [],
    "stallKindCounts": {},
    "fetchMsSamples": [],
}


def reset_job(
    *,
    region: str = "",
    item_workers: int = 5,
    per_source_timeout_sec: int = 28,
) -> None:
    with _lock:
        _state["jobStartedAt"] = time.time()
        _state["region"] = str(region or "")
        _state["itemWorkers"] = max(1, min(16, int(item_workers or 5)))
        _state["perSourceTimeoutSec"] = max(
            5, min(180, int(per_source_timeout_sec or 28))
        )
        _state["inflight"] = {}
        _state["recentStalls"] = []
        _state["stallKindCounts"] = {}
        _state["fetchMsSamples"] = []


def clear_job() -> None:
    with _lock:
        _state["inflight"] = {}
        _state["jobStartedAt"] = 0.0


def _item_key(code: str = "", item_id: str = "") -> str:
    # 优先番号，保证 fetch 埋点与 item_start 能对上
    c = str(code or "").strip().upper()
    if c:
        return c
    return str(item_id or "").strip()


def _slim_sources(rows: list[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sid = str(r.get("id") or "").strip()
        if not sid:
            continue
        out.append(
            {
                "id": sid,
                "status": str(r.get("status") or ""),
                "ms": int(r.get("ms") or 0),
                "ok": bool(r.get("ok")),
                "error": str(r.get("error") or "")[:120],
            }
        )
    return out


def diagnose(
    item: dict[str, Any],
    *,
    per_source_timeout_sec: int | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    """根据 phase + sources 给出卡顿原因；无卡顿返回 None。"""
    t_now = float(now if now is not None else time.time())
    phase = str(item.get("phase") or "")
    phase_at = float(item.get("phaseStartedAt") or item.get("startedAt") or t_now)
    phase_elapsed = max(0.0, t_now - phase_at)
    started = float(item.get("startedAt") or t_now)
    total_elapsed = max(0.0, t_now - started)
    timeout = int(
        per_source_timeout_sec
        if per_source_timeout_sec is not None
        else _state.get("perSourceTimeoutSec")
        or 28
    )
    timeout = max(5, min(180, timeout))
    sources = list(item.get("sources") or [])

    # 只看「仍在跑」的源。已 fail 的 timeout:15s 不能永久钉死「卡顿」——
    # 否则 iqqtv 早停后封面/其它源还在跑，UI 一直红标，看起来像整槽卡死。
    slow_thr = timeout * 0.7
    for s in sources:
        if str(s.get("status") or "") != "running":
            continue
        err = str(s.get("error") or "")
        if "timeout" in err.lower():
            return {
                "kind": "source_timeout",
                "label": f"{s.get('id')} 超时",
                "detail": err[:120],
                "sinceMs": int(s.get("ms") or phase_elapsed * 1000),
            }
        ms = float(s.get("ms") or 0)
        run_sec = (ms / 1000.0) if ms > 0 else phase_elapsed
        if run_sec >= slow_thr:
            return {
                "kind": "source_slow",
                "label": f"{s.get('id')} 已跑 {int(run_sec)}s / 超时 {timeout}s",
                "detail": f"source={s.get('id')} phase=fetch",
                "sinceMs": int(run_sec * 1000),
            }

    if phase == "fetch":
        if sources and all(
            str(s.get("status") or "") in {"pending", ""} for s in sources
        ):
            if phase_elapsed >= _PENDING_ALL_SEC:
                return {
                    "kind": "all_sources_pending",
                    "label": "源尚未发出请求",
                    "detail": f"fetch idle {phase_elapsed:.1f}s",
                    "sinceMs": int(phase_elapsed * 1000),
                }
        # 源已齐但仍停在拉详情：多半是译文/合并收尾
        finished = [
            s
            for s in sources
            if str(s.get("status") or "") in {"done", "fail", "skipped"}
        ]
        running_src = [
            s for s in sources if str(s.get("status") or "") == "running"
        ]
        if (
            sources
            and finished
            and not running_src
            and phase_elapsed >= _FETCH_TAIL_SEC
        ):
            return {
                "kind": "fetch_tail",
                "label": "源已齐 · 收尾过久",
                "detail": f"fetch tail {phase_elapsed:.1f}s after sources",
                "sinceMs": int(phase_elapsed * 1000),
            }
    elif phase == "cover" and phase_elapsed >= _COVER_SLOW_SEC:
        return {
            "kind": "cover_slow",
            "label": "封面阶段过久",
            "detail": f"cover {phase_elapsed:.1f}s",
            "sinceMs": int(phase_elapsed * 1000),
        }
    elif phase == "actress" and phase_elapsed >= _ACTRESS_SLOW_SEC:
        return {
            "kind": "actress_slow",
            "label": "女优阶段过久",
            "detail": f"actress {phase_elapsed:.1f}s",
            "sinceMs": int(phase_elapsed * 1000),
        }
    elif phase == "write" and phase_elapsed >= _WRITE_SLOW_SEC:
        return {
            "kind": "write_slow",
            "label": "写 NFO/入库过久",
            "detail": f"write {phase_elapsed:.1f}s",
            "sinceMs": int(phase_elapsed * 1000),
        }

    # 封面阶段靠 cover_slow，不另报「无心跳」（下载本身很少 touch sources）
    if phase == "cover":
        return None

    last_beat = float(item.get("lastBeatAt") or phase_at)
    if (t_now - last_beat) >= _SLOT_BLOCKED_SEC and total_elapsed >= _SLOT_BLOCKED_SEC:
        return {
            "kind": "slot_blocked",
            "label": "步骤无心跳",
            "detail": f"phase={phase or '?'} quiet {t_now - last_beat:.1f}s",
            "sinceMs": int((t_now - last_beat) * 1000),
        }
    return None


def touch_beat(
    *,
    code: str = "",
    item_id: str = "",
    note: str = "",
) -> None:
    """轻量心跳：封面下载等无 sources 更新的阶段用，避免误报 slot_blocked。"""
    key = _item_key(code, item_id)
    if not key:
        return
    now = time.time()
    with _lock:
        inflight = dict(_state.get("inflight") or {})
        cur = inflight.get(key)
        if not isinstance(cur, dict):
            return
        nxt = dict(cur)
        nxt["lastBeatAt"] = now
        if note:
            nxt["beatNote"] = str(note)[:80]
        nxt["elapsedMs"] = int(
            max(0.0, now - float(nxt.get("startedAt") or now)) * 1000
        )
        nxt["phaseElapsedMs"] = int(
            max(0.0, now - float(nxt.get("phaseStartedAt") or now)) * 1000
        )
        nxt["stall"] = diagnose(
            nxt,
            per_source_timeout_sec=int(_state.get("perSourceTimeoutSec") or 28),
            now=now,
        )
        inflight[key] = nxt
        _state["inflight"] = inflight


def item_start(
    *,
    code: str = "",
    item_id: str = "",
    region: str = "",
) -> None:
    key = _item_key(code, item_id)
    if not key:
        return
    now = time.time()
    with _lock:
        inflight: dict[str, Any] = dict(_state.get("inflight") or {})
        while len(inflight) >= _INFLIGHT_MAX and key not in inflight:
            oldest = min(
                inflight.items(),
                key=lambda kv: float((kv[1] or {}).get("startedAt") or 0),
            )[0]
            inflight.pop(oldest, None)
        inflight[key] = {
            "code": str(code or "").strip().upper(),
            "itemId": str(item_id or "").strip(),
            "region": str(region or _state.get("region") or ""),
            "phase": "start",
            "phaseLabel": _PHASE_LABEL["start"],
            "startedAt": now,
            "phaseStartedAt": now,
            "lastBeatAt": now,
            "elapsedMs": 0,
            "phaseElapsedMs": 0,
            "sources": [],
            "stall": None,
        }
        _state["inflight"] = inflight


def set_phase(
    *,
    code: str = "",
    item_id: str = "",
    phase: str,
) -> None:
    key = _item_key(code, item_id)
    if not key:
        return
    now = time.time()
    ph = str(phase or "").strip().lower() or "fetch"
    with _lock:
        inflight = dict(_state.get("inflight") or {})
        cur = inflight.get(key)
        if not isinstance(cur, dict):
            return
        nxt = dict(cur)
        if str(nxt.get("phase") or "") != ph:
            nxt["phase"] = ph
            nxt["phaseLabel"] = _PHASE_LABEL.get(ph, ph)
            nxt["phaseStartedAt"] = now
        nxt["lastBeatAt"] = now
        nxt["elapsedMs"] = int(
            max(0.0, now - float(nxt.get("startedAt") or now)) * 1000
        )
        nxt["phaseElapsedMs"] = int(
            max(0.0, now - float(nxt.get("phaseStartedAt") or now)) * 1000
        )
        nxt["stall"] = diagnose(
            nxt,
            per_source_timeout_sec=int(_state.get("perSourceTimeoutSec") or 28),
            now=now,
        )
        inflight[key] = nxt
        _state["inflight"] = inflight


def touch_sources(
    *,
    code: str = "",
    item_id: str = "",
    sources: list[Any] | None = None,
) -> None:
    key = _item_key(code, item_id)
    if not key:
        return
    now = time.time()
    slim = _slim_sources(sources)
    with _lock:
        inflight = dict(_state.get("inflight") or {})
        cur = inflight.get(key)
        if not isinstance(cur, dict):
            return
        nxt = dict(cur)
        nxt["lastBeatAt"] = now
        if str(nxt.get("phase") or "") in {"", "start"}:
            nxt["phase"] = "fetch"
            nxt["phaseLabel"] = _PHASE_LABEL["fetch"]
            nxt["phaseStartedAt"] = float(nxt.get("phaseStartedAt") or now)
        nxt["elapsedMs"] = int(
            max(0.0, now - float(nxt.get("startedAt") or now)) * 1000
        )
        nxt["phaseElapsedMs"] = int(
            max(0.0, now - float(nxt.get("phaseStartedAt") or now)) * 1000
        )
        refreshed: list[dict[str, Any]] = []
        for s in slim:
            row = dict(s)
            if str(row.get("status") or "") == "running" and int(row.get("ms") or 0) <= 0:
                row["ms"] = int(nxt["phaseElapsedMs"])
            refreshed.append(row)
        nxt["sources"] = refreshed
        nxt["stall"] = diagnose(
            nxt,
            per_source_timeout_sec=int(_state.get("perSourceTimeoutSec") or 28),
            now=now,
        )
        inflight[key] = nxt
        _state["inflight"] = inflight


def item_end(
    *,
    code: str = "",
    item_id: str = "",
    ok: bool = True,
    fetch_ms: int | None = None,
    error: str = "",
) -> None:
    key = _item_key(code, item_id)
    if not key:
        return
    now = time.time()
    with _lock:
        inflight = dict(_state.get("inflight") or {})
        cur = inflight.pop(key, None)
        _state["inflight"] = inflight
        if not isinstance(cur, dict):
            return
        stall = cur.get("stall") or diagnose(
            cur,
            per_source_timeout_sec=int(_state.get("perSourceTimeoutSec") or 28),
            now=now,
        )
        elapsed = int(max(0.0, now - float(cur.get("startedAt") or now)) * 1000)
        if fetch_ms is not None and int(fetch_ms) > 0:
            samples = list(_state.get("fetchMsSamples") or [])
            samples.append(int(fetch_ms))
            _state["fetchMsSamples"] = samples[-80:]
        if stall and isinstance(stall, dict):
            kind = str(stall.get("kind") or "")
            counts = dict(_state.get("stallKindCounts") or {})
            if kind:
                counts[kind] = int(counts.get(kind) or 0) + 1
            _state["stallKindCounts"] = counts
            recent = list(_state.get("recentStalls") or [])
            recent.append(
                {
                    "code": cur.get("code"),
                    "itemId": cur.get("itemId"),
                    "ok": bool(ok),
                    "elapsedMs": elapsed,
                    "phase": cur.get("phase"),
                    "stall": stall,
                    "error": str(error or "")[:120],
                    "endedAt": now,
                }
            )
            _state["recentStalls"] = recent[-_RECENT_MAX:]


def snapshot() -> dict[str, Any]:
    """供 get_enrich_status / SSE 使用。"""
    now = time.time()
    with _lock:
        timeout = int(_state.get("perSourceTimeoutSec") or 28)
        inflight_raw = dict(_state.get("inflight") or {})
        items: list[dict[str, Any]] = []
        for key, cur in inflight_raw.items():
            if not isinstance(cur, dict):
                continue
            nxt = dict(cur)
            # 量化到 250ms：SSE 用 JSON 去重，毫秒级跳动会导致几乎每帧都推
            raw_elapsed = int(
                max(0.0, now - float(nxt.get("startedAt") or now)) * 1000
            )
            raw_phase = int(
                max(0.0, now - float(nxt.get("phaseStartedAt") or now)) * 1000
            )
            nxt["elapsedMs"] = (raw_elapsed // 250) * 250
            nxt["phaseElapsedMs"] = (raw_phase // 250) * 250
            srcs = []
            for s in list(nxt.get("sources") or []):
                if not isinstance(s, dict):
                    continue
                row = dict(s)
                if str(row.get("status") or "") == "running":
                    row["ms"] = max(
                        int(row.get("ms") or 0), int(nxt["phaseElapsedMs"])
                    )
                srcs.append(row)
            nxt["sources"] = srcs
            nxt["stall"] = diagnose(nxt, per_source_timeout_sec=timeout, now=now)
            items.append(
                {
                    "code": nxt.get("code"),
                    "itemId": nxt.get("itemId"),
                    "region": nxt.get("region"),
                    "phase": nxt.get("phase"),
                    "phaseLabel": nxt.get("phaseLabel")
                    or _PHASE_LABEL.get(str(nxt.get("phase") or ""), ""),
                    "elapsedMs": nxt["elapsedMs"],
                    "phaseElapsedMs": nxt["phaseElapsedMs"],
                    "sources": nxt.get("sources") or [],
                    "stall": nxt.get("stall"),
                }
            )
            inflight_raw[key] = {**cur, **nxt}
        _state["inflight"] = inflight_raw
        items.sort(key=lambda x: -int(x.get("elapsedMs") or 0))
        samples = [
            int(x) for x in (_state.get("fetchMsSamples") or []) if int(x) > 0
        ]
        avg_fetch = int(sum(samples) / len(samples)) if samples else 0
        recent_pub = []
        for r in list(_state.get("recentStalls") or [])[-_RECENT_MAX:]:
            if not isinstance(r, dict):
                continue
            recent_pub.append(
                {
                    "code": r.get("code"),
                    "itemId": r.get("itemId"),
                    "ok": bool(r.get("ok")),
                    "elapsedMs": int(r.get("elapsedMs") or 0),
                    "phase": r.get("phase"),
                    "stall": r.get("stall"),
                    "error": r.get("error") or "",
                }
            )
        return {
            "enabled": True,
            "itemWorkers": int(_state.get("itemWorkers") or 5),
            "perSourceTimeoutSec": timeout,
            "region": str(_state.get("region") or ""),
            "inflight": items,
            "recentStalls": recent_pub,
            "summary": {
                "inflightN": len(items),
                "stallKinds": dict(_state.get("stallKindCounts") or {}),
                "avgFetchMs": avg_fetch,
                "stallingN": sum(1 for x in items if x.get("stall")),
            },
        }


def stall_label_for(code: str = "", item_id: str = "") -> str:
    """队列行副文案：有卡顿则返回 label。"""
    key = _item_key(code, item_id)
    if not key:
        return ""
    with _lock:
        cur = (_state.get("inflight") or {}).get(key)
        if not isinstance(cur, dict):
            return ""
        stall = cur.get("stall")
        if isinstance(stall, dict) and stall.get("label"):
            return str(stall.get("label") or "")
    return ""
