# -*- coding: utf-8 -*-
"""enrich_status —— 自 scrap_library/enrich.py 拆出（机械搬移，行为不变）。"""

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
import app.scrap_library.enrich_history as _enrich_history
import app.scrap_library.enrich_queue as _enrich_queue
from app.scrap_library.enrich import (_ENRICH_KINDS, _LIB_PROGRESS_COUNTS_TTL_SEC, _LOCAL_STATUS_TOTALS, _STATUS_QUEUE_HEAVY_KEYS, _checkpoint_summaries, _counts_cache, _counts_ok_cache, _enrich_job, _enrich_lock, _enrich_percent, _ensure_local_status_totals_loaded, _hydrate_enrich_runtime, _incomplete_cache, _lib_progress_counts_cache, _sample_queue_for_status, log)


def _persist_local_status_totals() -> None:
    try:
        from app.core.atomic_io import atomic_write_bytes

        payload = {
            "v": 1,
            "regions": {
                rid: {
                    "done": int(v.get("done") or 0),
                    "soft": int(v.get("soft") or 0),
                    "fail": int(v.get("fail") or 0),
                    **(
                        {"total": int(v.get("total") or 0)}
                        if int(v.get("total") or 0) > 0
                        else {}
                    ),
                }
                for rid, v in _LOCAL_STATUS_TOTALS.items()
                if rid and isinstance(v, dict)
            },
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        atomic_write_bytes(_enrich._local_status_totals_path(), raw)
    except Exception as e:  # noqa: BLE001
        log.debug("persist local status totals failed: %s", e)


def _set_local_status_totals(
    region: str,
    *,
    done: int | None = None,
    soft: int | None = None,
    fail: int | None = None,
    total: int | None = None,
) -> None:
    """写入扫描角标 tip。**未传的字段保持原值**（None 语义），不要默认 0。

    ⚠️ 旧实现 done/soft/fail 默认 0：任何只传 total 的调用都会把角标静默清零，
    是「成功 / 软成功 / 失败 计数失真」的一类来源。所有调用点都应显式传值。
    """
    rid = _enrich._queue_log_region(region)
    if not rid:
        return
    _ensure_local_status_totals_loaded()
    prev = _LOCAL_STATUS_TOTALS.get(rid) or {}
    row: dict[str, int] = {
        "done": max(
            0, int(prev.get("done") or 0) if done is None else int(done or 0)
        ),
        "soft": max(
            0, int(prev.get("soft") or 0) if soft is None else int(soft or 0)
        ),
        "fail": max(
            0, int(prev.get("fail") or 0) if fail is None else int(fail or 0)
        ),
    }
    tot = int(prev.get("total") or 0) if total is None else max(0, int(total or 0))
    if tot > 0:
        row["total"] = tot
    _LOCAL_STATUS_TOTALS[rid] = row
    _counts_cache.pop(rid, None)
    _persist_local_status_totals()


def _clear_local_status_totals(region: str = "") -> None:
    _ensure_local_status_totals_loaded()
    rid = _enrich._queue_log_region(region) if str(region or "").strip() else ""
    if rid:
        _LOCAL_STATUS_TOTALS.pop(rid, None)
        _counts_cache.pop(rid, None)
    else:
        _LOCAL_STATUS_TOTALS.clear()
        _counts_cache.clear()
    _persist_local_status_totals()


def _apply_local_status_totals(counts: dict[str, int], region: str) -> dict[str, int]:
    """队列表为唯一真相；tip 仅在库全空时兜底（扫描写入前）。"""
    rid = _enrich._queue_log_region(region)
    out = dict(counts)
    db_d = int(counts.get("done") or 0)
    db_s = int(counts.get("soft") or 0)
    db_f = int(counts.get("fail") or 0)
    db_p = int(counts.get("pending") or 0)
    db_sum = db_d + db_s + db_f + db_p
    if db_sum > 0:
        if rid:
            _set_local_status_totals(
                rid, done=db_d, soft=db_s, fail=db_f, total=None
            )
        return out
    _ensure_local_status_totals_loaded()
    tip = _LOCAL_STATUS_TOTALS.get(rid) if rid else None
    if not tip:
        return out
    out["done"] = int(tip.get("done") or 0)
    out["soft"] = int(tip.get("soft") or 0)
    out["fail"] = int(tip.get("fail") or 0)
    return out


def _region_counts_ok(region: str) -> bool:
    """上一次读库计数是否成功。未知时按 True（不要因为没记录就冻住角标）。"""
    rid = _enrich._queue_log_region(region)
    hit = _counts_ok_cache.get(rid)
    return bool(hit[1]) if hit else True


def _slim_one_result_mem(one: dict[str, Any]) -> dict[str, Any]:
    """内存 results 只留摘要，防止万级刮削占满堆。"""
    if not isinstance(one, dict):
        return {"ok": False}
    return {
        "code": one.get("code"),
        "ok": bool(one.get("ok")),
        "error": str(one.get("error") or "")[:160],
        "partialOk": bool(one.get("partialOk")),
        "posterDownloaded": bool(one.get("posterDownloaded")),
        "fetchMs": one.get("fetchMs"),
        "coverMs": one.get("coverMs"),
        "totalMs": one.get("totalMs"),
    }


def _pending_total_estimate(
    region: str, *, classified: dict[str, int] | None = None
) -> int:
    """未处理角标：向量总数 − 成功/软成功/失败。

    向量总数走轻量 COUNT（可缓存）；tip 仅作 COUNT 失败时回退。
    """
    rid = _enrich._queue_log_region(region)
    if not rid:
        return 0
    _ensure_local_status_totals_loaded()
    tip = _LOCAL_STATUS_TOTALS.get(rid) if rid else None
    vector_total = _enrich._fresh_vector_library_total(rid)
    if vector_total <= 0:
        vector_total = int((tip or {}).get("total") or 0)
    if classified is not None:
        done_n = int(classified.get("done") or 0)
        soft_n = int(classified.get("soft") or 0)
        fail_n = int(classified.get("fail") or 0)
    else:
        raw = _enrich_queue._queue_log_status_counts_db(rid)
        done_n = max(int(raw.get("done") or 0), int((tip or {}).get("done") or 0))
        soft_n = max(int(raw.get("soft") or 0), int((tip or {}).get("soft") or 0))
        fail_n = max(int(raw.get("fail") or 0), int((tip or {}).get("fail") or 0))
    return max(0, vector_total - done_n - soft_n - fail_n)


def _clamp_pending_badge(counts: dict[str, int], region: str) -> dict[str, int]:
    """未处理角标 = 队列表 pending 行数（不再用向量估算覆盖）。"""
    return dict(counts)


def _pending_page_from_vector(
    region: str, *, offset: int = 0, limit: int = 100
) -> list[dict[str, Any]]:
    """未处理翻页：队列表 pending 为唯一真相（扫描已整表写入）。"""
    from app.core.db import connect, init_db
    from app.scrap_library import embed as embed_svc

    rid = _enrich._queue_log_region(region)
    if not rid:
        return []
    off = max(0, int(offset or 0))
    lim = max(1, min(int(limit or 100), 500))
    out: list[dict[str, Any]] = []

    try:
        init_db()
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT id, item_id, code, status, gaps_json, error, source,
                       fetch_ms, detail_title, payload_json
                FROM enrich_queue_log
                WHERE region=? AND status='pending'
                ORDER BY updated_at DESC NULLS LAST, id DESC
                LIMIT ? OFFSET ?
                """,
                (rid, lim, off),
            ).fetchall()
        for raw in rows or []:
            if isinstance(raw, dict):
                it = _enrich_queue._queue_log_row_to_item(raw)
            else:
                it = _enrich_queue._queue_log_row_to_item(
                    {
                        "id": raw[0],
                        "item_id": raw[1],
                        "code": raw[2],
                        "status": raw[3],
                        "gaps_json": raw[4],
                        "error": raw[5],
                        "source": raw[6],
                        "fetch_ms": raw[7],
                        "detail_title": raw[8],
                        "payload_json": raw[9],
                    }
                )
            it["status"] = "pending"
            it["region"] = rid
            if not it.get("gaps"):
                it["gaps"] = list(_ENRICH_KINDS)
            out.append(it)
        if out or off == 0:
            return out
    except Exception as e:  # noqa: BLE001
        log.warning("pending page from queue_log failed region=%s: %s", rid, e)

    # ⚠️ 历史坑：回退分支曾是 OFFSET 重扫，而 scrap_library_embed 没有
    # (region, updated_at) 索引 → 每次全表排序 22.6 万行，实测 400→1.5s、
    # 2000→7.8s、8000→15s、20000→33s，只能靠 off>4000 直接返回空来保命，
    # 后果是未处理列表第 1 页有数、第 42 页起空白（而分页器仍显示 205 页）。
    # 根因已修：ensure_schema() 建了 {TABLE}_region_updated
    #   ON (region, updated_at DESC NULLS LAST, code)
    # 实测同一 SQL offset=20000 → 62ms（↓约 500 倍）。
    # 这里只保留一个绝对上限，防异常/恶意翻页，不再按「慢」设限。
    if off > 200_000:
        log.info("pending fallback offset beyond cap region=%s off=%s", rid, off)
        return []

    # 回退：向量 updated DESC（与开刮取号同序）+ 排除已分类
    # ⚠️ 已分类集合走 _queue_log_classified_skip_keys 的 TTL 缓存。
    # 旧实现每次翻页都现查一遍 enrich_queue_log（本区 done+fail ≈ 10.9 万行），
    # 单次 1.5~2.9s 全耗在这一步；缓存后翻页只付一次。
    done_iids, done_codes = _enrich_queue._queue_log_classified_skip_keys(rid)

    skipped = 0
    batch_sz = 500
    vec_off = 0
    raw_walked = 0
    # ⚠️ 出批数必须自适应：深页里前几批可能几乎全是「已分类」被跳过
    # （本区已分类占比 ≈ 84%），写死 40 批（旧实现）会在 offset 较大时
    # 静默返回不足 lim 条。上界按「原始行走行数」而非批数，与 batch_sz 解耦。
    raw_walk_max = 300_000
    while len(out) < lim or skipped < off:
        if raw_walked >= raw_walk_max:
            log.info(
                "pending fallback raw walk capped region=%s walked=%s off=%s",
                rid,
                raw_walked,
                off,
            )
            break
        try:
            # ⚠️ 必须与「开刮取号」（iter_enrich_pending_items → order="updated"）
            # 同序，否则未处理列表首条 ≠ 下一个会被处理的番号。旧实现用
            # order="code"，列表顶显示 AARM-002 这类最小番号，与开刮顺序不符。
            batch = embed_svc.list_region_code_items(
                region=rid, limit=batch_sz, offset=vec_off, order="updated"
            )
        except Exception as e:  # noqa: BLE001
            log.warning("pending page vector fallback failed: %s", e)
            break
        if not batch:
            break
        vec_off += len(batch)
        raw_walked += len(batch)
        for r in batch:
            if not isinstance(r, dict):
                continue
            iid = str(r.get("itemId") or "").strip()
            rel = str(r.get("relPath") or r.get("rel_path") or iid).strip()
            code_u = str(r.get("code") or "").strip().upper()
            iid2 = iid or rel
            if (
                iid2 in done_iids
                or (rel and rel in done_iids)
                or (code_u and code_u in done_codes)
            ):
                continue
            if skipped < off:
                skipped += 1
                continue
            item = {
                "itemId": iid2,
                "code": code_u,
                "gaps": list(r.get("gaps") or []) or list(_ENRICH_KINDS),
                "status": "pending",
                "region": rid,
                "shell": bool(r.get("shell")),
            }
            if rel:
                item["rel_path"] = rel
                item["relPath"] = rel
            out.append(item)
            if len(out) >= lim:
                break
        if len(batch) < batch_sz:
            break
        # 本批不够（多为「已分类」被跳过）→ 出批翻倍：浅页只付 1 批 500 行，
        # 深页按 500→1000→2000…≤20000 收敛，约 11 次往返即可覆盖 30 万原始行。
        if len(out) < lim or skipped < off:
            batch_sz = min(batch_sz * 2, 20_000)
    return out


def _slim_queue_row_for_status(row: dict[str, Any]) -> dict[str, Any]:
    """SSE/status 热路径：只留列表行需要的摘要。

    实测未瘦身时 120 行带 sourceTimings/fields ≈ 150KB+/帧，
    设置页总览 SSE 每 0.2s 解析一次会把主线程卡死。
    """
    if not isinstance(row, dict):
        return {}
    out = {k: v for k, v in row.items() if k not in _STATUS_QUEUE_HEAVY_KEYS}
    title = str(row.get("detailTitle") or "")
    if title:
        out["detailTitle"] = title[:120]
    timings = row.get("sourceTimings")
    if isinstance(timings, list) and timings:
        out["sourceTimingCount"] = len(timings)
    fields = row.get("fields")
    if isinstance(fields, list) and fields:
        out["fieldCount"] = len(fields)
    return out


def _slim_queue_for_status(rows: list[Any]) -> list[dict[str, Any]]:
    return [
        _slim_queue_row_for_status(r) for r in rows if isinstance(r, dict)
    ]


def _slim_current_for_status(current: Any) -> Any:
    """current 里的 sourceTimings 保留精简版（监控条要用），去掉超大字段。"""
    if not isinstance(current, dict):
        return current
    out = dict(current)
    timings = out.get("sourceTimings")
    if isinstance(timings, list) and timings:
        slim_t: list[dict[str, Any]] = []
        for t in timings[:16]:
            if not isinstance(t, dict):
                continue
            slim_t.append(
                {
                    "id": t.get("id"),
                    "status": t.get("status"),
                    "ok": t.get("ok"),
                    "ms": t.get("ms"),
                    "waitMs": t.get("waitMs"),
                    "kind": t.get("kind"),
                    "error": str(t.get("error") or "")[:80],
                    "actors": t.get("actors"),
                    "poster": t.get("poster"),
                }
            )
        out["sourceTimings"] = slim_t
    return out


def _slim_result_for_status(result: Any) -> Any:
    """状态/落盘只保留汇总，丢掉 parts/items 明细（可达 100KB+，轮询会拖垮线程池）。"""
    if not isinstance(result, dict):
        return result
    # 批量 enrich：顶层带 parts/items
    if "parts" in result or "items" in result:
        slim_parts: list[dict[str, Any]] = []
        for p in list(result.get("parts") or []):
            if not isinstance(p, dict):
                continue
            items = p.get("items")
            slim_parts.append(
                {
                    "dryRun": bool(p.get("dryRun")),
                    "mode": str(p.get("mode") or ""),
                    "region": str(p.get("region") or ""),
                    "kinds": list(p.get("kinds") or []),
                    "queued": int(p.get("queued") or 0),
                    "ok": int(p.get("ok") or 0),
                    "failed": int(p.get("failed") or 0),
                    "cancelled": bool(p.get("cancelled")),
                    "paused": bool(p.get("paused")),
                    "remaining": int(p.get("remaining") or 0),
                    "itemCount": len(items) if isinstance(items, list) else 0,
                }
            )
        out = {
            k: v
            for k, v in result.items()
            if k not in {"parts", "items", "groups", "sources"}
        }
        out["parts"] = slim_parts
        out["items"] = []
        out["itemsTruncated"] = True
        return out
    # 单条 enrich：保留摘要，去掉嵌套超大字段明细
    nested = result.get("result")
    if isinstance(nested, dict):
        slim_nested = {
            k: v
            for k, v in nested.items()
            if k
            not in {
                "items",
                "parts",
                "groups",
                "sources",
                "sourceTimings",
                "fields",
            }
        }
        if "sourceTimings" in nested and isinstance(nested.get("sourceTimings"), list):
            slim_nested["sourceTimingCount"] = len(nested["sourceTimings"])
        if "fields" in nested and isinstance(nested.get("fields"), list):
            slim_nested["fieldCount"] = len(nested["fields"])
        out = dict(result)
        out["result"] = slim_nested
        # item 行本身不大，保留；若异常巨大则丢掉
        item = out.get("item")
        if isinstance(item, dict) and len(str(item)) > 8000:
            out["item"] = {
                "itemId": item.get("itemId") or item.get("id"),
                "code": item.get("code"),
            }
        return out
    return result


def _progress_from_queue_counts(
    counts: dict[str, int], *, base: dict[str, Any] | None = None
) -> dict[str, Any]:
    """进度只跟本轮队列计数对齐（成功+软成功+失败）/（成功+软成功+失败+未处理）。"""
    ok_n = int(counts.get("done") or 0) + int(counts.get("soft") or 0)
    fin = ok_n + int(counts.get("fail") or 0)
    rem = int(counts.get("pending") or 0) + int(counts.get("running") or 0)
    tot = fin + rem
    cur = dict(base or {})
    cur.update(
        {
            "done": fin,
            "total": tot,
            "ok": ok_n,
            "failed": int(counts.get("fail") or 0),
            "percent": _enrich_percent(fin, tot) if tot > 0 else 0,
        }
    )
    return cur


def _region_library_progress(region: str) -> dict[str, int]:
    """库内进度（状态热路径）：轻量 total + tip 已分类。

    未处理 = total − done − soft − fail（与扫描角标同源）。
    禁止调用 quality_stats（分项 COUNT 在有码区要数秒，会卡死设置页）。
    total 以向量库 COUNT 为准（缓存），不再钉死旧 tip.total。
    """
    rid = _enrich._queue_log_region(region)
    if not rid:
        return {"total": 0, "incomplete": 0, "complete": 0, "percent": 0}
    _ensure_local_status_totals_loaded()
    tip = _LOCAL_STATUS_TOTALS.get(rid) or {}
    total = _enrich._fresh_vector_library_total(rid)
    if total <= 0:
        total = int(tip.get("total") or 0)
    tip = _LOCAL_STATUS_TOTALS.get(rid) or tip
    done_n = int(tip.get("done") or 0)
    soft_n = int(tip.get("soft") or 0)
    fail_n = int(tip.get("fail") or 0)
    # ⚠️ tip 是缓存，可能被「先删后写」的扫描中断留在瞬时低值：实测 japan_censored
    # tip.done=2 而磁盘实际已分类 10.2 万 → 未处理被算成 129,250（虚高 6 倍），
    # 连带开刮时的「预估未处理」也失真。这里用**纯只读**的库内计数取大纠正。
    # 必须用 _queue_log_status_counts_db：另一条 _queue_log_status_counts 会经
    # _lift_local_status_totals_from_counts 写盘，属于状态热路径禁用的磁盘写。
    # 加 3s 备忘，避免每次状态轮询都做一次 GROUP BY。
    try:
        _memo = _lib_progress_counts_cache.get(rid)
        _now_m = time.monotonic()
        if not _memo or _now_m - float(_memo[0]) >= _LIB_PROGRESS_COUNTS_TTL_SEC:
            _memo = (_now_m, _enrich_queue._queue_log_status_counts_db(rid))
            _lib_progress_counts_cache[rid] = _memo
        dbc = _memo[1] or {}
        done_n = max(done_n, int(dbc.get("done") or 0))
        soft_n = max(soft_n, int(dbc.get("soft") or 0))
        fail_n = max(fail_n, int(dbc.get("fail") or 0))
    except Exception as e:  # noqa: BLE001
        log.debug("region library progress db merge failed region=%s: %s", rid, e)
    # 已刮完（含软成功）视为完成；未处理(+fail 仍算待办里的剩余用 pending 公式)
    complete = done_n + soft_n
    incomplete = max(0, total - done_n - soft_n - fail_n) if total > 0 else 0
    now = time.time()
    _incomplete_cache[rid] = (now, total, incomplete)
    pct = _enrich_percent(complete, total) if total > 0 else 0
    return {
        "total": total,
        "incomplete": incomplete,
        "complete": complete,
        "percent": int(pct),
    }


def get_enrich_status(*, lite: bool = False) -> dict[str, Any]:
    """刮削状态快照。

    lite=True：总览页 / 角标用，不含 queue 抽样与大段日志（SSE 高频友好）。
    lite=False：详情直播页用，带瘦身后的 queue 抽样。
    """
    _hydrate_enrich_runtime()
    with _enrich_lock:
        region_logs_raw = _enrich_job.get("regionLogs") or {}
        region_logs: dict[str, list[str]] = {}
        region_log_counts: dict[str, int] = {}
        log_tail = 8 if lite else _enrich_history._ENRICH_LOG_RETURN
        if isinstance(region_logs_raw, dict):
            for rid, lines in region_logs_raw.items():
                key = str(rid or "").strip()
                if not key:
                    continue
                full = list(lines or [])
                region_log_counts[key] = len(full)
                if not lite:
                    region_logs[key] = full[-log_tail:]
        checkpoints = _checkpoint_summaries()
        halt = _enrich_job.get("halt")
        current_region = str(_enrich_job.get("currentRegion") or "")
        running = bool(_enrich_job["running"])
        phase_now = str(_enrich_job.get("phase") or "")
        # 已暂停/停止：状态对外一律非 running（避免清空被「繁忙」误拦）
        if halt in {"pause", "stop"} or phase_now in {
            "paused",
            "stopping",
            "stopped",
        }:
            running = False
        # 热路径：队列可达 2 万+ 行。**不要**在这里 `list(...)` 拷贝——
        # 队列每次改动都是整体替换新 list 对象，直接持有引用即可得到一致快照，
        # 而拷贝会破坏 `_sample_queue_for_status` 的按身份缓存（导致每帧重扫）。
        raw_queue = _enrich_job.get("queue") or []
        if lite:
            queue: list[dict[str, Any]] = []
        else:
            queue = _slim_queue_for_status(_sample_queue_for_status(raw_queue))
        stored_counts = _enrich_job.get("queueCounts")
        if isinstance(stored_counts, dict) and any(
            int(stored_counts.get(k) or 0) > 0
            for k in ("pending", "running", "done", "soft", "fail")
        ):
            queue_counts = {
                k: int(stored_counts.get(k) or 0)
                for k in ("pending", "running", "done", "soft", "fail")
            }
        else:
            queue_counts = _enrich_queue._queue_counts_of(raw_queue)
        # 暂停后若运行时队列被置空，用检查点剩余队列回填展示（停止则无检查点）
        # 切勿物化 10万+ 行：只抽样 + 用长度/计数填角标
        if not running and not queue:
            raw_cps = dict(_enrich_job.get("checkpoints") or {})
            for rid, cp in raw_cps.items():
                if not isinstance(cp, dict):
                    continue
                remaining = cp.get("queue") or []
                sample_n = (
                    len(remaining) if isinstance(remaining, list) else 0
                )
                rem_n = max(int(cp.get("remainingCount") or 0), sample_n)
                if rem_n <= 0:
                    continue
                done = int(cp.get("done") or 0)
                ok_n = int(cp.get("ok") or 0)
                fail_n = int(cp.get("failed") or 0)
                sample = (
                    [
                        _slim_queue_row_for_status(r)
                        for r in remaining[:48]
                        if isinstance(r, dict)
                    ]
                    if isinstance(remaining, list)
                    else []
                )
                rebuilt: list[dict[str, Any]] = []
                for j, row in enumerate(sample):
                    rebuilt.append(
                        {
                            "index": done + j,
                            "itemId": str(row.get("itemId") or ""),
                            "code": str(row.get("code") or ""),
                            "gaps": list(row.get("gaps") or []),
                            "status": "pending",
                        }
                    )
                queue = rebuilt
                queue_counts = {
                    "pending": rem_n,
                    "running": 0,
                    "done": ok_n,
                    "fail": fail_n,
                }
                break
        progress = _progress_from_queue_counts(
            queue_counts, base=dict(_enrich_job.get("progress") or {})
        )
        if running:
            _enrich_job["progress"] = progress
            _enrich_job["queueCounts"] = queue_counts
        # 暂停/停止：内存队列禁止残留 running（一律视作 pending）
        # 旧实现为此遍历并拷贝整个队列（2 万+ 行）——状态热路径不允许。
        # 计数直接用 queue_counts 的 running 搬移到 pending（O(1)，两者同源），
        # 展示层只对抽样出的行（≤limit）改状态。
        if halt in {"pause", "stop"} or str(_enrich_job.get("phase") or "") in {
            "paused",
            "stopping",
            "stopped",
        }:
            stray = int(queue_counts.get("running") or 0)
            if stray:
                queue_counts = {
                    **queue_counts,
                    "pending": int(queue_counts.get("pending") or 0) + stray,
                    "running": 0,
                }
            queue = [
                (
                    {**r, "status": "pending"}
                    if _enrich_queue._queue_row_status(r) == "running"
                    else r
                )
                for r in queue
            ]
        pending_total = int(queue_counts.get("pending") or 0)
        monitor = enrich_mon.snapshot()
        # 展示队列被裁过时，把监控里正在刮的番号补进抽样，处理中列表才有行
        if not lite:
            seen_codes = {
                str(r.get("code") or "").strip().upper()
                for r in queue
                if isinstance(r, dict)
            }
            seen_ids = {
                str(r.get("itemId") or "").strip()
                for r in queue
                if isinstance(r, dict) and str(r.get("itemId") or "").strip()
            }
            extra_running: list[dict[str, Any]] = []
            for it in monitor.get("inflight") or []:
                if not isinstance(it, dict):
                    continue
                code_k = str(it.get("code") or "").strip().upper()
                iid_k = str(it.get("itemId") or "").strip()
                if code_k and code_k in seen_codes:
                    continue
                if iid_k and iid_k in seen_ids:
                    continue
                extra_running.append(
                    {
                        "code": code_k,
                        "itemId": iid_k,
                        "status": "running",
                        "region": str(it.get("region") or ""),
                    }
                )
                if code_k:
                    seen_codes.add(code_k)
            if extra_running:
                queue = extra_running + list(queue)
        stall_by_code: dict[str, str] = {}
        for it in monitor.get("inflight") or []:
            if not isinstance(it, dict):
                continue
            stall = it.get("stall")
            if not isinstance(stall, dict):
                continue
            lab = str(stall.get("label") or "").strip()
            code_k = str(it.get("code") or "").strip().upper()
            if lab and code_k:
                stall_by_code[code_k] = lab
        if stall_by_code:
            annotated: list[dict[str, Any]] = []
            for r in queue:
                if not isinstance(r, dict):
                    continue
                if str(r.get("status") or "") != "running":
                    annotated.append(r)
                    continue
                lab = stall_by_code.get(str(r.get("code") or "").strip().upper())
                annotated.append({**r, "stallLabel": lab} if lab else r)
            queue = annotated
        queue_total_n = sum(
            int(queue_counts.get(k) or 0)
            for k in ("pending", "running", "done", "fail")
        )
        status = {
            "running": running,
            "phase": _enrich_job.get("phase") or "",
            "progress": progress,
            "log": list(_enrich_job.get("log") or [])[-(8 if lite else 40) :],
            "regionLogs": region_logs,
            "regionLogCounts": region_log_counts,
            "currentRegion": current_region,
            "cancel": bool(_enrich_job.get("cancel")) or halt in {"pause", "stop"},
            "halt": halt,
            "paused": bool(checkpoints),
            "checkpoints": checkpoints,
            "queue": queue,
            "queueTotal": queue_total_n,
            "queueCounts": dict(queue_counts),
            # queueTotal 由计数求和得出，等价于旧 `len(queue_full)`（每行必归一类）
            "queueTruncated": pending_total > len(queue) or queue_total_n > len(queue),
            "current": None if lite else _slim_current_for_status(_enrich_job.get("current")),
            "result": _slim_result_for_status(_enrich_job.get("result")),
            "error": _enrich_job.get("error"),
            "monitor": monitor,
            "queueScan": None if lite else _enrich_queue._queue_scan_snapshot(),
            "lite": bool(lite),
        }

    # 角标成功/失败并入库计数（勿在 _enrich_lock 内打 DB）
    # 暂停时 currentRegion 常为空：按检查点分区回填，避免成功/失败仍停在本轮内存 15
    # 完成后检查点已清：仍要从 result.regions/parts 回填，否则角标卡在截断内存队列（如 80/80）
    count_regions: list[str] = []
    cur_rid = _enrich._queue_log_region(str(status.get("currentRegion") or ""))
    if cur_rid:
        count_regions.append(cur_rid)
    # 开刮瞬间 currentRegion 可能仍为空；用本轮 regionLogs 键补分区，避免角标区缺失
    if status.get("running") and not count_regions:
        for rid in (status.get("regionLogs") or {}):
            key = _enrich._queue_log_region(str(rid or ""))
            if key and key not in count_regions:
                count_regions.append(key)
    if not status.get("running"):
        for rid in (status.get("checkpoints") or {}):
            key = _enrich._queue_log_region(str(rid or ""))
            if key and key not in count_regions:
                count_regions.append(key)
        result_obj = status.get("result") if isinstance(status.get("result"), dict) else {}
        for rid in list(result_obj.get("regions") or []):
            key = _enrich._queue_log_region(str(rid or ""))
            if key and key not in count_regions:
                count_regions.append(key)
        for part in list(result_obj.get("parts") or []):
            if not isinstance(part, dict):
                continue
            key = _enrich._queue_log_region(str(part.get("region") or ""))
            if key and key not in count_regions:
                count_regions.append(key)
        # 空闲时把 tip 里已有分区也算上，避免详情页角标停在旧扫描数
        _ensure_local_status_totals_loaded()
        for rid in list(_LOCAL_STATUS_TOTALS.keys()):
            key = _enrich._queue_log_region(str(rid or ""))
            if key and key not in count_regions:
                count_regions.append(key)
    if count_regions:
        # 运行中（含详情 SSE）：只用内存 queueCounts / monitor，禁止每帧打库
        if status.get("running"):
            ui_counts = dict(status.get("queueCounts") or {})
            mon = (
                status.get("monitor")
                if isinstance(status.get("monitor"), dict)
                else {}
            )
            inflight_n = len(list(mon.get("inflight") or []))
            if inflight_n > 0:
                ui_counts["running"] = inflight_n
            status["queueCounts"] = ui_counts
            status["queueTotal"] = sum(
                int(ui_counts.get(k) or 0)
                for k in ("pending", "running", "done", "soft", "fail")
            )
            base_prog = dict(status.get("progress") or {})
            status["progress"] = _progress_from_queue_counts(
                ui_counts, base=base_prog
            )
            library: dict[str, Any] = {}
            region_queue_counts: dict[str, dict[str, int]] = {}
            cur_rid_mem = _enrich._queue_log_region(str(status.get("currentRegion") or ""))
            for rid_counts in count_regions:
                dbc = _enrich_queue._queue_log_status_counts(rid_counts)
                lib = _region_library_progress(rid_counts)
                total = int(lib.get("total") or 0)
                done_n = int(dbc.get("done") or 0)
                soft_n = int(dbc.get("soft") or 0)
                fail_n = int(dbc.get("fail") or 0)
                pending_n = int(dbc.get("pending") or 0)
                run_n = (
                    inflight_n
                    if rid_counts == cur_rid_mem
                    else int(dbc.get("running") or 0)
                )
                complete = done_n + soft_n
                incomplete = pending_n + run_n
                library[rid_counts] = {
                    "total": total,
                    "incomplete": incomplete,
                    "complete": complete,
                    "percent": int(round(100.0 * complete / max(total, 1)))
                    if total > 0
                    else 0,
                }
                region_queue_counts[rid_counts] = {
                    "pending": pending_n,
                    "running": run_n,
                    "done": done_n,
                    "soft": soft_n,
                    "fail": fail_n,
                }
            if library:
                status["library"] = library
            status["regionQueueCounts"] = region_queue_counts
            if cur_rid_mem and cur_rid_mem in region_queue_counts:
                status["queueCounts"] = dict(region_queue_counts[cur_rid_mem])
                status["queueCountsRegion"] = cur_rid_mem
            elif count_regions:
                status["queueCountsRegion"] = count_regions[0]
        else:
            ui_counts = dict(status.get("queueCounts") or {})
            cps_ui = dict(status.get("checkpoints") or {})
            for rid_counts in count_regions:
                dbc = _enrich_queue._queue_log_status_counts(rid_counts)
                # 空闲时清掉库残留 running，避免「处理中」假数据
                if not status.get("running") and int(dbc.get("running") or 0) > 0:
                    _enrich_queue._queue_log_reopen_running(region=rid_counts)
                    dbc = _enrich_queue._queue_log_status_counts(rid_counts)
                if status.get("running"):
                    # 运行中：本轮内存与库取大（避免轮询漏计）
                    ui_counts["done"] = max(
                        int(ui_counts.get("done") or 0), int(dbc.get("done") or 0)
                    )
                    ui_counts["soft"] = max(
                        int(ui_counts.get("soft") or 0), int(dbc.get("soft") or 0)
                    )
                    ui_counts["fail"] = max(
                        int(ui_counts.get("fail") or 0), int(dbc.get("fail") or 0)
                    )
                    ui_counts["pending"] = max(
                        int(ui_counts.get("pending") or 0),
                        int(dbc.get("pending") or 0),
                    )
                else:
                    # 暂停/空闲：队列表是唯一真相
                    ui_counts["done"] = int(dbc.get("done") or 0)
                    ui_counts["soft"] = int(dbc.get("soft") or 0)
                    ui_counts["fail"] = int(dbc.get("fail") or 0)
                    ui_counts["pending"] = int(dbc.get("pending") or 0)
                    ui_counts["running"] = 0
                    stray_run = int(dbc.get("running") or 0)
                    if stray_run > 0:
                        ui_counts["pending"] = int(ui_counts["pending"]) + stray_run
                cp = cps_ui.get(rid_counts)
                if isinstance(cp, dict):
                    cp = dict(cp)
                    ok_bucket = int(dbc.get("done") or 0) + int(dbc.get("soft") or 0)
                    if status.get("running"):
                        cp["ok"] = max(int(cp.get("ok") or 0), ok_bucket)
                        cp["failed"] = max(
                            int(cp.get("failed") or 0), int(dbc.get("fail") or 0)
                        )
                    else:
                        cp["ok"] = ok_bucket
                        cp["failed"] = int(dbc.get("fail") or 0)
                        cp["remaining"] = int(ui_counts.get("pending") or 0)
                        done_n = int(cp["ok"]) + int(cp["failed"])
                        rem_n = int(cp["remaining"])
                        cp["total"] = max(int(cp.get("total") or 0), done_n + rem_n)
                        cp["done"] = done_n
                    cps_ui[rid_counts] = cp
            # 「处理中」= 真实 inflight；暂停/停止归零
            halt_now = str(status.get("halt") or "")
            phase_now = str(status.get("phase") or "")
            if (
                not status.get("running")
                or halt_now in {"pause", "stop"}
                or phase_now in {"paused", "stopping", "stopped"}
            ):
                stray = int(ui_counts.get("running") or 0)
                if stray > 0:
                    ui_counts["pending"] = int(ui_counts.get("pending") or 0) + stray
                ui_counts["running"] = 0
            elif status.get("running"):
                mon = (
                    status.get("monitor")
                    if isinstance(status.get("monitor"), dict)
                    else {}
                )
                inflight = list(mon.get("inflight") or [])
                inflight_n = len(inflight)
                ui_counts["running"] = inflight_n
                keep_ids = {
                    str(it.get("itemId") or "").strip()
                    for it in inflight
                    if isinstance(it, dict) and str(it.get("itemId") or "").strip()
                }
                for rid_counts in count_regions:
                    stale = _enrich_queue._queue_log_reopen_stale_running(
                        rid_counts, keep_item_ids=keep_ids
                    )
                    if stale:
                        ui_counts["pending"] = int(ui_counts.get("pending") or 0) + stale
                with _enrich_lock:
                    qc_mem = dict(_enrich_job.get("queueCounts") or {})
                    qc_mem["running"] = inflight_n
                    _enrich_job["queueCounts"] = qc_mem
            status["checkpoints"] = cps_ui
            status["queueCounts"] = ui_counts
            status["queueTotal"] = sum(
                int(ui_counts.get(k) or 0)
                for k in ("pending", "running", "done", "fail")
            )
            base_prog = dict(status.get("progress") or {})
            status["progress"] = _progress_from_queue_counts(ui_counts, base=base_prog)

            # 未处理 = 向量库所有番号 − 成功 − 软成功 − 失败（按分区独立，禁止串区）
            library: dict[str, Any] = {}
            region_queue_counts: dict[str, dict[str, int]] = {}
            run_n_global = int(ui_counts.get("running") or 0)
            for rid_counts in count_regions:
                dbc = _enrich_queue._queue_log_status_counts(rid_counts)
                lib = _region_library_progress(rid_counts)
                pending_n = int(dbc.get("pending") or 0)
                run_n = int(dbc.get("running") or 0)
                done_n = int(dbc.get("done") or 0)
                soft_n = int(dbc.get("soft") or 0)
                fail_n = int(dbc.get("fail") or 0)
                if (
                    rid_counts
                    == _enrich._queue_log_region(str(status.get("currentRegion") or ""))
                    and status.get("running")
                ):
                    run_n = run_n_global
                region_queue_counts[rid_counts] = {
                    "pending": pending_n,
                    "running": run_n,
                    "done": done_n,
                    "soft": soft_n,
                    "fail": fail_n,
                }
                library[rid_counts] = {
                    "total": int(lib.get("total") or 0),
                    "incomplete": int(lib.get("incomplete") or 0),
                    "complete": int(lib.get("complete") or 0),
                    "percent": int(lib.get("percent") or 0),
                }
            if library:
                status["library"] = library
            status["regionQueueCounts"] = region_queue_counts
            cur_rid2 = _enrich._queue_log_region(str(status.get("currentRegion") or ""))
            if cur_rid2 and cur_rid2 in region_queue_counts:
                status["queueCounts"] = dict(region_queue_counts[cur_rid2])
                status["queueCountsRegion"] = cur_rid2
            elif len(region_queue_counts) == 1:
                only_rid = next(iter(region_queue_counts))
                status["queueCounts"] = dict(region_queue_counts[only_rid])
                status["queueCountsRegion"] = only_rid
            status["queueTotal"] = sum(
                int(status.get("queueCounts", {}).get(k) or 0)
                for k in ("pending", "running", "done", "soft", "fail")
            )
            status["progress"] = _progress_from_queue_counts(
                dict(status.get("queueCounts") or {}),
                base=dict(status.get("progress") or {}),
            )

    # 角标可信度 + 真实刮削产出。
    # 前端旧实现靠「server===500」这个魔数猜服务端值是否被截断，而 500 是合法值
    # （扫描写盘上限），会把真值 500 误判成哨兵 → 改用显式标记。
    # 运行中不查库（热路径禁 DB），此时 scrape 留空，前端沿用旧值。
    _counts_rid = str(
        status.get("queueCountsRegion") or status.get("currentRegion") or ""
    )
    status["queueCountsOk"] = (
        True
        if status.get("running")
        else (_region_counts_ok(_counts_rid) if _counts_rid else True)
    )
    if _counts_rid and not status.get("running"):
        status["queueCountsScrape"] = _enrich_queue._queue_log_scrape_counts_db(_counts_rid)
        status["queueCountsScrapeRegion"] = _counts_rid

    # 元库回填：仅空闲时合并历史；运行中只用本轮内存，避免角标被历史顶满
    try:
        from app.core.region_meta import REGION_ORDER

        if not status.get("running"):
            want_regions = set(region_logs.keys()) | set(REGION_ORDER)
            if current_region:
                want_regions.add(current_region)
            for rid in want_regions:
                key = _enrich_history._canonical_enrich_log_region(str(rid or "").strip())
                if not key or key == "_all":
                    continue
                loaded = _enrich_history._load_enrich_logs_cached(region=key, limit=_enrich_history._ENRICH_LOG_RETURN)
                mem = list(region_logs.get(key) or [])
                for alias in _enrich_history._enrich_log_region_keys(key):
                    if alias == key:
                        continue
                    for line in list(region_logs.get(alias) or []):
                        if not line:
                            continue
                        if mem and mem[-1] == line:
                            continue
                        mem.append(line)
                if loaded and mem:
                    merged = list(loaded)
                    for line in mem:
                        if merged and merged[-1] == line:
                            continue
                        merged.append(line)
                    region_logs[key] = merged[-_enrich_history._ENRICH_LOG_RETURN:]
                elif loaded:
                    region_logs[key] = loaded[-_enrich_history._ENRICH_LOG_RETURN:]
                elif mem:
                    region_logs[key] = mem[-_enrich_history._ENRICH_LOG_RETURN:]
                region_log_counts[key] = len(region_logs.get(key) or [])
            if not status["log"]:
                loaded_all = _enrich_history._load_enrich_logs_cached(region="_all", limit=80)
                if loaded_all:
                    status["log"] = loaded_all[-40:]
        status["regionLogs"] = region_logs
        status["regionLogCounts"] = region_log_counts
    except Exception:  # noqa: BLE001
        pass
    if lite:
        mon = status.get("monitor")
        if isinstance(mon, dict):
            status["monitor"] = {
                "enabled": mon.get("enabled"),
                "itemWorkers": mon.get("itemWorkers"),
                "perSourceTimeoutSec": mon.get("perSourceTimeoutSec"),
                "region": mon.get("region"),
                "summary": mon.get("summary"),
                "inflight": [
                    {
                        "code": x.get("code"),
                        "phase": x.get("phase"),
                        "elapsedMs": x.get("elapsedMs"),
                        "phaseElapsedMs": x.get("phaseElapsedMs"),
                        "stall": x.get("stall"),
                    }
                    for x in list(mon.get("inflight") or [])
                    if isinstance(x, dict)
                ],
                "recentStalls": [],
            }
        status["queue"] = []
        status["current"] = None
        status["queueScan"] = None
        status["regionLogs"] = {}
        status["lite"] = True
    return status


def _cap_status_queue(rows: list[Any], *, limit: int = 120) -> list[dict[str, Any]]:
    """展示队列上限。进行中的行优先保留，避免边扫裁窗口后占槽番号消失。"""
    running: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        if str(r.get("status") or "") == "running":
            running.append(r)
        else:
            others.append(r)
    if len(running) >= limit:
        return running[:limit]
    room = limit - len(running)
    if len(others) <= room:
        return running + others
    head = min(40, room // 3)
    tail = room - head
    return running + others[:head] + others[-tail:]


def _empty_queue_counts() -> dict[str, int]:
    return {"pending": 0, "running": 0, "done": 0, "soft": 0, "fail": 0}
