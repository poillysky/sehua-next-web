# -*- coding: utf-8 -*-
"""enrich_queue —— 自 scrap_library/enrich.py 拆出（机械搬移，行为不变）。"""

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
import app.scrap_library.enrich_cover as _enrich_cover
import app.scrap_library.enrich_detail as _enrich_detail
import app.scrap_library.enrich_history as _enrich_history
import app.scrap_library.enrich_retry as _enrich_retry
import app.scrap_library.enrich_scan as _enrich_scan
import app.scrap_library.enrich_status as _enrich_status
from app.scrap_library.enrich import (_CLASSIFIED_SKIP_TTL_SEC, _SOFT_SUCCESS_GAPS, _STALE_RUNNING_MIN_INTERVAL_SEC, _SUCCESS_BLOCK_GAPS, _classified_skip_cache, _demoted_false_dones, _stale_running_last, log)
from app.scrap_library.enrich_queue_io import (
    _COUNTS_CACHE_TTL_SEC,
    _LOCAL_STATUS_TOTALS,
    _counts_cache,
    _counts_ok_cache,
    _ensure_local_status_totals_loaded,
    _scrape_counts_cache,
)
from app.scrap_library.enrich_runtime import (_QUEUE_SCAN_LOCK, _QUEUE_SCAN_STATE, _enrich_job, _enrich_lock, _set_progress, _set_queue_scan_progress)


_QUEUE_LOG_DONE_KEEP = 4000


_QUEUE_LOG_PRUNE_EVERY = 40


_QUEUE_LOG_STATUSES = ("pending", "running", "done", "fail")


_QUEUE_LOG_FILTER_STATUSES = (*_QUEUE_LOG_STATUSES, "soft")


_QUEUE_LOG_PAYLOAD_KEYS = (
    "actors",
    "nfoChanged",
    "posterDownloaded",
    "vectorSynced",
    "vectorSkipped",
    "vectorError",
    "sourceTimings",
    "fields",
    "wouldFill",
    "rel_path",
    "relPath",
    "coverMs",
    "coverFail",
    "coverTried",
    "coverAttempts",
    "actressMs",
    "vectorMs",
    "totalMs",
    "partialOk",
    "gapsAfter",
    "softActressRetry",
)


_QUEUE_SCAN_SAMPLE_CAP = 80  # 边扫边看：每态最多推送样例条数


_QUEUE_SCAN_NOTIFY_GAP = 0.35


def _queue_scan_preview_item(
    *,
    rel: str,
    code: str,
    gaps: list[str],
    region: str,
    kind: str,
) -> dict[str, Any]:
    """扫描中预览行（轻量，不读 sidecar）。"""
    code_u = str(code or "").strip().upper()
    rid = str(region or "").strip()
    item: dict[str, Any] = {
        "itemId": rel,
        "code": code_u,
        "gaps": list(gaps or []),
        "gapsAfter": list(gaps or []),
        "rel_path": rel,
        "relPath": rel,
        "region": rid,
        "source": "scan",
    }
    if kind == "done":
        item["status"] = "done"
        item["partialOk"] = False
        item["error"] = ""
    elif kind == "soft":
        soft_gaps = [g for g in gaps if g in _enrich._SOFT_SUCCESS_GAPS]
        labels = _enrich_retry._gap_labels(soft_gaps)
        item["status"] = "done"
        item["partialOk"] = True
        item["error"] = _enrich_retry._format_soft_ok_error(labels or ["女优"])
        item["gapsAfter"] = soft_gaps
    else:
        block = [g for g in gaps if g in _enrich._SUCCESS_BLOCK_GAPS] or list(gaps or [])
        labels = _enrich_retry._gap_labels(block)
        item["status"] = "fail"
        item["partialOk"] = False
        item["error"] = f"仍缺:{' · '.join(labels)}" if labels else "仍缺:封面"
    return item


def _queue_scan_snapshot() -> dict[str, Any] | None:
    with _enrich._QUEUE_SCAN_LOCK:
        if not _enrich._QUEUE_SCAN_STATE.get("active"):
            return None
        return {
            "active": True,
            "region": str(_enrich._QUEUE_SCAN_STATE.get("region") or ""),
            "stage": str(_enrich._QUEUE_SCAN_STATE.get("stage") or ""),
            "label": str(_enrich._QUEUE_SCAN_STATE.get("label") or ""),
            "scanned": int(_enrich._QUEUE_SCAN_STATE.get("scanned") or 0),
            "total": int(_enrich._QUEUE_SCAN_STATE.get("total") or 0),
            "done": int(_enrich._QUEUE_SCAN_STATE.get("done") or 0),
            "soft": int(_enrich._QUEUE_SCAN_STATE.get("soft") or 0),
            "fail": int(_enrich._QUEUE_SCAN_STATE.get("fail") or 0),
            "pending": int(_enrich._QUEUE_SCAN_STATE.get("pending") or 0),
            "samplesDone": list(_enrich._QUEUE_SCAN_STATE.get("samplesDone") or []),
            "samplesSoft": list(_enrich._QUEUE_SCAN_STATE.get("samplesSoft") or []),
            "samplesFail": list(_enrich._QUEUE_SCAN_STATE.get("samplesFail") or []),
        }


def _queue_scan_add_sample(kind: str, item: dict[str, Any]) -> None:
    """边扫边把样例推入状态，供前端提前展示列表。"""
    key = {
        "done": "samplesDone",
        "soft": "samplesSoft",
        "fail": "samplesFail",
    }.get(str(kind or "").strip())
    if not key or not isinstance(item, dict):
        return
    with _enrich._QUEUE_SCAN_LOCK:
        if not _enrich._QUEUE_SCAN_STATE.get("active"):
            return
        bucket = _enrich._QUEUE_SCAN_STATE.get(key)
        if not isinstance(bucket, list):
            bucket = []
            _enrich._QUEUE_SCAN_STATE[key] = bucket
        if len(bucket) >= _QUEUE_SCAN_SAMPLE_CAP:
            return
        code_u = str(item.get("code") or "").strip().upper()
        iid = str(item.get("itemId") or "").strip()
        for old in bucket:
            if not isinstance(old, dict):
                continue
            if iid and str(old.get("itemId") or "") == iid:
                return
            if code_u and str(old.get("code") or "").strip().upper() == code_u:
                return
        bucket.append(item)


def _clear_queue_scan_progress() -> None:
    _enrich._set_queue_scan_progress(active=False, notify=True)


def _queue_log_status_counts_db_ex(region: str) -> tuple[dict[str, int], bool]:
    """队列表真实计数（不含本地全量 overlay）。

    返回 `(counts, ok)`。ok=False 表示库读失败（断连 / 超时 / 池耗尽），
    此时 counts 全是 0。调用方必须能区分「库里真的是 0」与「读失败」，
    否则库抖动会被当成「全部归零」写进角标。
    """
    rid = _enrich._queue_log_region(region)
    out = _enrich_status._empty_queue_counts()
    if not rid:
        return out, False
    ok = False
    try:
        from app.core.db import connect, init_db

        init_db()
        soft_pred = _enrich_retry._soft_done_sql_pred(error_col="error")
        with connect() as conn:
            for row in conn.execute(
                f"""
                SELECT
                  CASE
                    WHEN status='done' AND {soft_pred} THEN 'soft'
                    ELSE status
                  END AS bucket,
                  COUNT(*) AS n
                FROM enrich_queue_log
                WHERE region=?
                GROUP BY 1
                """,
                (rid,),
            ).fetchall():
                key = str(
                    (row.get("bucket") if isinstance(row, dict) else row[0]) or ""
                ).strip().lower()
                n = int((row.get("n") if isinstance(row, dict) else row[1]) or 0)
                if key in out:
                    out[key] = n
        ok = True
    except Exception as e:  # noqa: BLE001
        log.warning("queue log status counts db failed region=%s: %s", rid, e)
        return out, False
    return out, ok


def _queue_log_status_counts_db(region: str) -> dict[str, int]:
    """兼容旧调用点：只要计数，丢弃 ok 标记。"""
    return _queue_log_status_counts_db_ex(region)[0]


def _queue_log_scrape_counts_db(region: str) -> dict[str, int]:
    """只统计「真实刮削产出」的行：排除扫描判定行（source=scan/local_scan）。

    队列日志表把两类语义混在一张表里：
      - scan/local_scan：扫描判定「本地 NFO 已齐 / 缺字段」，十万级
      - 真实刮削：enrich 实际抓取并写盘的结果，百级
    """
    rid = _enrich._queue_log_region(region)
    out = {"done": 0, "soft": 0, "fail": 0, "total": 0}
    if not rid:
        return out
    now = time.monotonic()
    hit = _enrich._scrape_counts_cache.get(rid)
    if hit and (now - float(hit[0])) < _enrich._COUNTS_CACHE_TTL_SEC:
        return dict(hit[1])
    try:
        from app.core.db import connect, init_db

        init_db()
        soft_pred = _enrich_retry._soft_done_sql_pred(error_col="error")
        with connect() as conn:
            for row in conn.execute(
                f"""
                SELECT
                  CASE
                    WHEN status='done' AND {soft_pred} THEN 'soft'
                    ELSE status
                  END AS bucket,
                  COUNT(*) AS n
                FROM enrich_queue_log
                WHERE region=?
                  AND {_enrich_scan._SQL_NOT_SCAN_SOURCE}
                GROUP BY 1
                """,
                (rid,),
            ).fetchall():
                key = str(
                    (row.get("bucket") if isinstance(row, dict) else row[0]) or ""
                ).strip().lower()
                n = int((row.get("n") if isinstance(row, dict) else row[1]) or 0)
                if key in out:
                    out[key] = n
        out["total"] = int(out["done"]) + int(out["soft"]) + int(out["fail"])
    except Exception as e:  # noqa: BLE001
        log.debug("queue log scrape counts db failed region=%s: %s", rid, e)
        return dict(out)
    _enrich._scrape_counts_cache[rid] = (now, dict(out))
    if len(_enrich._scrape_counts_cache) > 64:
        _enrich._scrape_counts_cache.clear()
    return dict(out)


def _queue_log_status_counts(region: str, *, fresh: bool = False) -> dict[str, int]:
    """队列表按 status 计数（角标唯一真相；done 再拆完整成功 / 软成功）。

    默认走 ~1.2s 短缓存：状态接口/轮询高频重复查询同一个分区时，1 秒级的
    角标延迟不可见，但能把「每帧一次 DB」的固定开销摊掉。
    需要真实值（暂停/结束判定、写检查点）时传 fresh=True。
    tip 不再参与角标合并。
    """
    rid = _enrich._queue_log_region(region)
    out = _enrich_status._empty_queue_counts()
    if not rid:
        return out
    # 纠偏（假成功回滚 / 软成功提升）只在扫描·开刮时跑，绝不挂在状态读路径。
    if not fresh:
        hit = _enrich._counts_cache.get(rid)
        if hit and (time.monotonic() - float(hit[0])) < _enrich._COUNTS_CACHE_TTL_SEC:
            return dict(hit[1])
    raw, db_ok = _queue_log_status_counts_db_ex(rid)
    _enrich._counts_ok_cache[rid] = (time.monotonic(), bool(db_ok))
    if len(_enrich._counts_ok_cache) > 64:
        _enrich._counts_ok_cache.clear()
    out = _enrich_status._apply_local_status_totals(raw, rid)
    out = _enrich_status._clamp_pending_badge(out, rid)
    _enrich._counts_cache[rid] = (time.monotonic(), dict(out))
    if len(_enrich._counts_cache) > 64:
        _enrich._counts_cache.clear()
    return out


def _queue_log_int_id(row: dict[str, Any]) -> int:
    raw = row.get("logId")
    if raw is None:
        raw = row.get("log_id")
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _queue_log_payload(row: dict[str, Any], *, base: dict[str, Any] | None = None) -> str:
    extra: dict[str, Any] = {}
    if isinstance(base, dict):
        extra.update(base)

    def _keep_rich(key: str, new_v: Any, old_v: Any) -> Any:
        """空列表/空字段表不要覆盖已有刮削结果。"""
        if key in {"fields", "sourceTimings"}:
            if isinstance(new_v, list) and not new_v and old_v:
                return old_v
            if key == "fields" and isinstance(new_v, list) and isinstance(old_v, list):
                new_src = sum(
                    1
                    for f in new_v
                    if isinstance(f, dict) and str(f.get("source") or "").strip()
                )
                old_src = sum(
                    1
                    for f in old_v
                    if isinstance(f, dict) and str(f.get("source") or "").strip()
                )
                # NFO 回填无站点源时，保留带选用源的旧表
                if old_src > 0 and new_src == 0:
                    return old_v
            if key == "sourceTimings" and isinstance(new_v, list) and isinstance(old_v, list):
                if len(old_v) > len(new_v):
                    return old_v
        return new_v

    for k in _QUEUE_LOG_PAYLOAD_KEYS:
        if k in row and row.get(k) is not None:
            extra[k] = _keep_rich(k, row.get(k), extra.get(k))
    try:
        return json.dumps(extra, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        slim = {
            k: extra.get(k)
            for k in (
                "posterDownloaded",
                "nfoChanged",
                "vectorSynced",
                "vectorSkipped",
                "vectorError",
                "actors",
                "fields",
                "sourceTimings",
                "coverMs",
                "actressMs",
                "vectorMs",
                "totalMs",
            )
            if k in extra
        }
        return json.dumps(slim, ensure_ascii=False, default=str)


def _queue_log_read_payload(conn: Any, lid: int) -> dict[str, Any]:
    if lid <= 0:
        return {}
    try:
        got = conn.execute(
            "SELECT payload_json FROM enrich_queue_log WHERE id=?",
            (lid,),
        ).fetchone()
        if not got:
            return {}
        raw = got["payload_json"] if isinstance(got, dict) else got[0]
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return dict(parsed) if isinstance(parsed, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _queue_log_insert_params(
    region: str,
    row: dict[str, Any],
    *,
    payload_base: dict[str, Any] | None = None,
) -> list[Any]:
    st = str(row.get("status") or "pending").strip().lower()
    if st not in _QUEUE_LOG_STATUSES:
        st = "pending"
    fetch_ms = row.get("fetchMs")
    try:
        fetch_i = int(fetch_ms) if fetch_ms is not None else None
    except (TypeError, ValueError):
        fetch_i = None
    return [
        region,
        str(row.get("itemId") or ""),
        str(row.get("code") or "").strip().upper(),
        st,
        json.dumps(list(row.get("gaps") or []), ensure_ascii=False),
        str(row.get("error") or "")[:500],
        str(row.get("source") or ""),
        fetch_i,
        str(row.get("detailTitle") or "")[:300],
        _queue_log_payload(row, base=payload_base),
    ]


def _queue_log_row_to_item(row: dict[str, Any]) -> dict[str, Any]:
    gaps: list[Any] = []
    payload: dict[str, Any] = {}
    try:
        raw_g = row.get("gaps_json") or "[]"
        parsed = json.loads(raw_g) if isinstance(raw_g, str) else raw_g
        if isinstance(parsed, list):
            gaps = parsed
    except Exception:  # noqa: BLE001
        gaps = []
    try:
        raw_p = row.get("payload_json") or "{}"
        parsed_p = json.loads(raw_p) if isinstance(raw_p, str) else raw_p
        if isinstance(parsed_p, dict):
            payload = parsed_p
    except Exception:  # noqa: BLE001
        payload = {}
    st = str(row.get("status") or "pending").strip().lower()
    if st not in _QUEUE_LOG_STATUSES:
        st = "pending"
    fetch_ms = row.get("fetch_ms")
    try:
        fetch_i = int(fetch_ms) if fetch_ms is not None else None
    except (TypeError, ValueError):
        fetch_i = None
    item: dict[str, Any] = {
        "logId": int(row.get("id") or 0),
        "itemId": str(row.get("item_id") or ""),
        "code": str(row.get("code") or ""),
        "gaps": gaps,
        "status": st,
        "error": str(row.get("error") or ""),
        "source": str(row.get("source") or ""),
        "fetchMs": fetch_i,
        "detailTitle": str(row.get("detail_title") or ""),
    }
    for k, v in payload.items():
        if k not in item:
            item[k] = v
    # 完整成功但 gaps_json 未清（历史 bug）：展示层清空缺口，避免「成功还缺封面」
    if st == "done" and not bool(item.get("partialOk")):
        item["gaps"] = []
        if not item.get("gapsAfter"):
            item["gapsAfter"] = []
        # 字段表封面：已落盘则强制 ok，避免陈旧 fields 误报
        if item.get("posterDownloaded") and isinstance(item.get("fields"), list):
            for f in item["fields"]:
                if isinstance(f, dict) and str(f.get("id") or "") == "poster":
                    f["ok"] = True
                    if not str(f.get("value") or "").strip():
                        f["value"] = "已落盘"
    # 伪命中源不展示
    if str(item.get("source") or "").strip() in {"log_recover", "recover"}:
        item["source"] = ""
    return item


def _clear_queue_log(*, region: str = "") -> None:
    rid = _enrich._queue_log_region(region) if str(region or "").strip() else ""
    keys = _enrich_history._enrich_log_region_keys(region) if str(region or "").strip() else []
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            if rid or keys:
                want = list(dict.fromkeys([rid, *keys] if rid else keys))
                ph = ",".join(["?"] * len(want))
                conn.execute(
                    f"DELETE FROM enrich_queue_log WHERE region IN ({ph})",
                    want,
                )
            else:
                conn.execute("DELETE FROM enrich_queue_log")
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("clear enrich queue log failed region=%s: %s", rid or "*", e)


def _queue_log_mark_pending(ids: list[int]) -> None:
    want = [int(x) for x in ids if int(x or 0) > 0]
    if not want:
        return
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            ph = ",".join(["?"] * len(want))
            conn.execute(
                f"""
                UPDATE enrich_queue_log
                SET status='pending', error='', updated_at=NOW()
                WHERE id IN ({ph}) AND status IN ('pending', 'running')
                """,
                want,
            )
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("mark enrich queue log pending failed: %s", e)


def _queue_log_reopen_running(*, region: str = "") -> None:
    rid = _enrich._queue_log_region(region)
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            if rid:
                conn.execute(
                    """
                    UPDATE enrich_queue_log
                    SET status='pending', updated_at=NOW()
                    WHERE region=? AND status='running'
                    """,
                    (rid,),
                )
            else:
                conn.execute(
                    """
                    UPDATE enrich_queue_log
                    SET status='pending', updated_at=NOW()
                    WHERE status='running'
                    """
                )
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("reopen running enrich queue log failed: %s", e)


def _queue_log_reopen_stale_running(
    region: str, *, keep_item_ids: set[str] | None = None, force: bool = False
) -> int:
    """把库里卡住的 running 退回 pending；保留当前 inflight 的 itemId。

    队列截断 / 崩溃后常见：库里残留十几条 running，角标「处理中」虚高。
    限频：状态快照每秒会问好几次，这条 UPDATE 不必每帧都发（WAL/死元组代价）。
    """
    rid = _enrich._queue_log_region(region)
    if not rid:
        return 0
    if not force:
        now = time.monotonic()
        if (now - float(_enrich._stale_running_last.get(rid) or 0.0)) < _enrich._STALE_RUNNING_MIN_INTERVAL_SEC:
            return 0
        _enrich._stale_running_last[rid] = now
    keep = {str(x or "").strip() for x in (keep_item_ids or set()) if str(x or "").strip()}
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            if keep:
                ph = ",".join(["?"] * len(keep))
                cur = conn.execute(
                    f"""
                    UPDATE enrich_queue_log
                    SET status='pending', updated_at=NOW()
                    WHERE region=? AND status='running'
                      AND COALESCE(item_id,'') NOT IN ({ph})
                    """,
                    (rid, *keep),
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE enrich_queue_log
                    SET status='pending', updated_at=NOW()
                    WHERE region=? AND status='running'
                    """,
                    (rid,),
                )
            n = int(getattr(cur, "rowcount", 0) or 0)
            conn.commit()
            return max(0, n)
    except Exception as e:  # noqa: BLE001
        log.warning("reopen stale running enrich queue log failed: %s", e)
        return 0


def _queue_log_reopen_fails(region: str) -> list[dict[str, Any]]:
    """失败 → 未处理；同番号已有 pending/running 则跳过，避免重复。返回可投递行。"""
    rid = _enrich._queue_log_region(region)
    if not rid:
        return []
    out: list[dict[str, Any]] = []
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            # 先取出将要重开的失败行（排除已有开放行）
            rows = conn.execute(
                """
                SELECT id, item_id, code, status, gaps_json, error, source,
                       fetch_ms, detail_title, payload_json
                FROM enrich_queue_log r
                WHERE r.region=? AND r.status='fail'
                  AND NOT EXISTS (
                    SELECT 1 FROM enrich_queue_log o
                    WHERE o.region=r.region
                      AND o.status IN ('pending', 'running')
                      AND (
                        (NULLIF(r.code, '') <> '' AND o.code=r.code)
                        OR (NULLIF(r.item_id, '') <> '' AND o.item_id=r.item_id)
                      )
                  )
                ORDER BY id ASC
                """,
                (rid,),
            ).fetchall()
            ids: list[int] = []
            for raw in rows or []:
                if isinstance(raw, dict):
                    it = _queue_log_row_to_item(raw)
                    lid = int(raw.get("id") or 0)
                else:
                    it = _queue_log_row_to_item(
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
                    lid = int(raw[0] or 0)
                if lid <= 0:
                    continue
                ids.append(lid)
                work = {
                    "itemId": str(it.get("itemId") or ""),
                    "code": str(it.get("code") or "").strip().upper(),
                    "gaps": list(it.get("gaps") or []),
                    "logId": lid,
                    "region": rid,
                    "status": "pending",
                    "error": "",
                }
                rel = str(it.get("rel_path") or it.get("relPath") or "")
                if rel:
                    work["rel_path"] = rel
                    work["relPath"] = rel
                out.append(work)
            if ids:
                # 分批更新
                for i in range(0, len(ids), 500):
                    chunk = ids[i : i + 500]
                    ph = ",".join(["?"] * len(chunk))
                    conn.execute(
                        f"""
                        UPDATE enrich_queue_log
                        SET status='pending', error='', updated_at=NOW()
                        WHERE id IN ({ph}) AND status='fail'
                        """,
                        chunk,
                    )
                conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("reopen fail enrich queue log failed region=%s: %s", rid, e)
        return []
    return out


def _queue_log_reopen_softs(region: str) -> list[dict[str, Any]]:
    """软成功批量重开为 pending（排除已有开放行）。"""
    rid = _enrich._queue_log_region(region)
    if not rid:
        return []
    soft_pred = _enrich_retry._soft_done_sql_pred(error_col="r.error")
    out: list[dict[str, Any]] = []
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, item_id, code, status, gaps_json, error, source,
                       fetch_ms, detail_title, payload_json
                FROM enrich_queue_log r
                WHERE r.region=? AND r.status='done' AND {soft_pred}
                  AND NOT EXISTS (
                    SELECT 1 FROM enrich_queue_log o
                    WHERE o.region=r.region
                      AND o.status IN ('pending', 'running')
                      AND (
                        (NULLIF(r.code, '') <> '' AND o.code=r.code)
                        OR (NULLIF(r.item_id, '') <> '' AND o.item_id=r.item_id)
                      )
                  )
                ORDER BY id ASC
                """,
                (rid,),
            ).fetchall()
            ids: list[int] = []
            for raw in rows or []:
                if isinstance(raw, dict):
                    it = _queue_log_row_to_item(raw)
                    lid = int(raw.get("id") or 0)
                else:
                    it = _queue_log_row_to_item(
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
                    lid = int(raw[0] or 0)
                if lid <= 0:
                    continue
                ids.append(lid)
                work = {
                    "itemId": str(it.get("itemId") or ""),
                    "code": str(it.get("code") or "").strip().upper(),
                    "gaps": list(it.get("gaps") or it.get("gapsAfter") or []),
                    "logId": lid,
                    "region": rid,
                    "status": "pending",
                    "error": "",
                }
                rel = str(it.get("rel_path") or it.get("relPath") or "")
                if rel:
                    work["rel_path"] = rel
                    work["relPath"] = rel
                out.append(work)
            if ids:
                soft_upd = _enrich_retry._soft_done_sql_pred(error_col="error")
                for i in range(0, len(ids), 500):
                    chunk = ids[i : i + 500]
                    ph = ",".join(["?"] * len(chunk))
                    conn.execute(
                        f"""
                        UPDATE enrich_queue_log
                        SET status='pending', error='', updated_at=NOW()
                        WHERE id IN ({ph}) AND status='done' AND {soft_upd}
                        """,
                        chunk,
                    )
                conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("reopen soft enrich queue log failed region=%s: %s", rid, e)
        return []
    return out


def _queue_log_find_open(
    region: str, *, item_id: str = "", code: str = ""
) -> int:
    rid = _enrich._queue_log_region(region)
    iid = str(item_id or "").strip()
    code_u = str(code or "").strip().upper()
    if not rid or (not iid and not code_u):
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            if iid:
                row = conn.execute(
                    """
                    SELECT id FROM enrich_queue_log
                    WHERE region=? AND status IN ('pending', 'running')
                      AND item_id=?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (rid, iid),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT id FROM enrich_queue_log
                    WHERE region=? AND status IN ('pending', 'running')
                      AND code=?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (rid, code_u),
                ).fetchone()
            if not row:
                return 0
            return int(row["id"] if isinstance(row, dict) else row[0])
    except Exception as e:  # noqa: BLE001
        log.warning("find open enrich queue log failed: %s", e)
        return 0


def _queue_log_done_keys(region: str) -> tuple[set[str], set[str]]:
    """本分区已成功刮削的 itemId / code（再启动增量时跳过，避免刮过又刮）。"""
    rid = _enrich._queue_log_region(region)
    iids: set[str] = set()
    codes: set[str] = set()
    if not rid:
        return iids, codes
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            for raw in conn.execute(
                """
                SELECT item_id, code
                FROM enrich_queue_log
                WHERE region=? AND status='done'
                """,
                (rid,),
            ).fetchall() or []:
                if isinstance(raw, dict):
                    iid = str(raw.get("item_id") or "").strip()
                    code_u = str(raw.get("code") or "").strip().upper()
                else:
                    iid = str(raw[0] or "").strip()
                    code_u = str(raw[1] or "").strip().upper()
                if iid:
                    iids.add(iid)
                if code_u:
                    codes.add(code_u)
    except Exception as e:  # noqa: BLE001
        log.warning("load enrich done keys failed region=%s: %s", rid, e)
    return iids, codes


def _ensure_queue_log_ids(
    region: str, rows: list[dict[str, Any]], *, persist: bool = True
) -> list[dict[str, Any]]:
    """给本轮队列补 logId：批量复用未完成行，再批量插入。

    旧实现逐条 find_open + update，有码区上万条时会卡在「筛选」数分钟。
    persist=False：预览模式，只查不写。
    """
    if not rows:
        return []
    rid = _enrich._queue_log_region(region)
    out: list[dict[str, Any]] = [dict(r) for r in rows if isinstance(r, dict)]
    if not out:
        return []
    if not rid:
        return out

    need_idx = [i for i, r in enumerate(out) if _queue_log_int_id(r) <= 0]
    if not need_idx:
        return out

    open_by_iid: dict[str, int] = {}
    open_by_code: dict[str, int] = {}
    # 只查本批 item_id/code，禁止全表扫 pending（边扫边刮时会越扫越卡直至卡死清空）
    batch_iids: list[str] = []
    batch_codes: list[str] = []
    seen_i: set[str] = set()
    seen_c: set[str] = set()
    for i in need_idx:
        row = out[i]
        iid = str(row.get("itemId") or "").strip()
        code_u = str(row.get("code") or "").strip().upper()
        if iid and iid not in seen_i:
            seen_i.add(iid)
            batch_iids.append(iid)
        if code_u and code_u not in seen_c:
            seen_c.add(code_u)
            batch_codes.append(code_u)
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            # 分片 IN，避免单次参数过多
            def _load_chunk(iids: list[str], codes: list[str]) -> None:
                if not iids and not codes:
                    return
                clauses: list[str] = []
                params: list[Any] = [rid]
                if iids:
                    ph = ",".join(["?"] * len(iids))
                    clauses.append(f"item_id IN ({ph})")
                    params.extend(iids)
                if codes:
                    ph = ",".join(["?"] * len(codes))
                    clauses.append(f"code IN ({ph})")
                    params.extend(codes)
                sql = f"""
                    SELECT id, item_id, code
                    FROM enrich_queue_log
                    WHERE region=? AND status IN ('pending', 'running')
                      AND ({' OR '.join(clauses)})
                    ORDER BY id DESC
                    """
                for raw in conn.execute(sql, params).fetchall() or []:
                    if isinstance(raw, dict):
                        lid = int(raw.get("id") or 0)
                        iid = str(raw.get("item_id") or "").strip()
                        code_u = str(raw.get("code") or "").strip().upper()
                    else:
                        lid = int(raw[0] or 0)
                        iid = str(raw[1] or "").strip()
                        code_u = str(raw[2] or "").strip().upper()
                    if lid <= 0:
                        continue
                    if iid and iid not in open_by_iid:
                        open_by_iid[iid] = lid
                    if code_u and code_u not in open_by_code:
                        open_by_code[code_u] = lid

            step = 80
            max_n = max(len(batch_iids), len(batch_codes))
            if max_n <= 0:
                pass
            else:
                for start in range(0, max_n, step):
                    _load_chunk(
                        batch_iids[start : start + step],
                        batch_codes[start : start + step],
                    )
    except Exception as e:  # noqa: BLE001
        log.warning("batch load open enrich queue log failed region=%s: %s", rid, e)

    reuse_ids: list[int] = []
    to_insert: list[dict[str, Any]] = []
    insert_at: list[int] = []
    used_lids: set[int] = set()

    for i in need_idx:
        row = out[i]
        iid = str(row.get("itemId") or "").strip()
        code_u = str(row.get("code") or "").strip().upper()
        lid = 0
        if iid and iid in open_by_iid:
            lid = int(open_by_iid.pop(iid) or 0)
            if code_u and open_by_code.get(code_u) == lid:
                open_by_code.pop(code_u, None)
        elif code_u and code_u in open_by_code:
            lid = int(open_by_code.pop(code_u) or 0)
            # 同步清掉同 id 的 item 映射，避免二次复用
            drop_iid = next(
                (k for k, v in open_by_iid.items() if v == lid),
                "",
            )
            if drop_iid:
                open_by_iid.pop(drop_iid, None)
        if lid > 0 and lid not in used_lids:
            used_lids.add(lid)
            row["logId"] = lid
            row["status"] = "pending"
            reuse_ids.append(lid)
            continue
        insert_at.append(i)
        to_insert.append(row)

    if not persist:
        # 预览（dryRun）：只保留「查已有 pending 行」的复用匹配，不做任何写。
        # 否则预览会凭空插入 pending 行，污染真实队列。
        return out

    # 复用行：只把 running 拨回 pending，不重写 payload（快）
    if reuse_ids:
        try:
            from app.core.db import connect, init_db

            init_db()
            with connect() as conn:
                for start in range(0, len(reuse_ids), 200):
                    chunk = reuse_ids[start : start + 200]
                    ph = ",".join(["?"] * len(chunk))
                    conn.execute(
                        f"""
                        UPDATE enrich_queue_log
                        SET status='pending', updated_at=NOW()
                        WHERE id IN ({ph}) AND status='running'
                        """,
                        chunk,
                    )
                conn.commit()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "batch reset enrich queue pending failed region=%s: %s", rid, e
            )

    if to_insert:
        n = len(to_insert)
        running = False
        with _enrich._enrich_lock:
            running = bool(_enrich._enrich_job.get("running"))
        if running:
            _enrich._set_progress(
                stage="queue",
                label=f"写入队列日志 0/{n}",
                done=0,
                total=n,
            )
        # 分块插入并刷新进度，避免 UI 一直停在「筛选」
        ids: list[int] = []
        chunk_size = 80
        for start in range(0, n, chunk_size):
            chunk = to_insert[start : start + chunk_size]
            got = _enrich._queue_log_insert_many(region, chunk)
            ids.extend(got)
            if running:
                _enrich._set_progress(
                    stage="queue",
                    label=f"写入队列日志 {min(start + len(chunk), n)}/{n}",
                    done=min(start + len(chunk), n),
                    total=n,
                )
        for pos, new_id in zip(insert_at, ids):
            if new_id:
                out[pos]["logId"] = int(new_id)
    return out


def _queue_log_prune_pending_not_in(region: str, keep_item_ids: set[str]) -> int:
    """扫描后：删除已不在缺口集合里的 pending（保留成功/失败/处理中）。"""
    rid = _enrich._queue_log_region(region)
    if not rid:
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            if not keep_item_ids:
                cur = conn.execute(
                    """
                    DELETE FROM enrich_queue_log
                    WHERE region=? AND status='pending'
                    """,
                    (rid,),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT id, item_id FROM enrich_queue_log
                    WHERE region=? AND status='pending'
                    """,
                    (rid,),
                )
                drop: list[int] = []
                keep = set(keep_item_ids)
                for row in cur.fetchall() or []:
                    iid = str(
                        (row.get("item_id") if isinstance(row, dict) else row[1])
                        or ""
                    )
                    lid = int(
                        (row.get("id") if isinstance(row, dict) else row[0]) or 0
                    )
                    if lid and iid not in keep:
                        drop.append(lid)
                if not drop:
                    conn.commit()
                    return 0
                ph = ",".join(["?"] * len(drop))
                cur = conn.execute(
                    f"DELETE FROM enrich_queue_log WHERE id IN ({ph})",
                    drop,
                )
            n = int(cur.rowcount or 0)
            conn.commit()
            return n
    except Exception as e:  # noqa: BLE001
        log.warning("prune enrich queue pending failed region=%s: %s", rid, e)
        return 0


def _queue_log_prune_open_if_done(
    region: str, *, code: str = "", item_id: str = ""
) -> int:
    """已有成功行时，删掉同番号/同条目的 pending·running，避免成功还出现在未处理。

    热路径（刚写完 done）只按 code/item_id 定点删，禁止 EXISTS 全表相关子查询：
    后者在 8 万+ done 行上会扫锁数分钟，卡住其它番号的 UPDATE → 监控假死在封面阶段。
    """
    rid = _enrich._queue_log_region(region)
    if not rid:
        return 0
    code_u = str(code or "").strip().upper()
    iid = str(item_id or "").strip()
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            # 短超时：prune 失败可下次再清，绝不能堵 worker
            try:
                conn.execute("SET LOCAL statement_timeout = '4s'")
                conn.execute("SET LOCAL lock_timeout = '2s'")
            except Exception:  # noqa: BLE001
                pass
            if code_u or iid:
                # 调用方刚写入 done：无需再 EXISTS 证明「已有成功」
                clauses: list[str] = []
                params: list[Any] = [rid]
                if code_u:
                    clauses.append("code=?")
                    params.append(code_u)
                if iid:
                    clauses.append("item_id=?")
                    params.append(iid)
                cur = conn.execute(
                    f"""
                    DELETE FROM enrich_queue_log
                    WHERE region=?
                      AND status IN ('pending', 'running')
                      AND ({" OR ".join(clauses)})
                    """,
                    params,
                )
                n = int(getattr(cur, "rowcount", 0) or 0)
                conn.commit()
                return max(0, n)

            # 全分区后台清理：分批 + 用 code/item_id 半连接，避免相关 EXISTS 长锁
            total = 0
            for _ in range(40):
                cur = conn.execute(
                    """
                    WITH doomed AS (
                      SELECT o.id
                      FROM enrich_queue_log AS o
                      WHERE o.region=?
                        AND o.status IN ('pending', 'running')
                        AND (
                          (
                            NULLIF(o.code, '') IS NOT NULL
                            AND EXISTS (
                              SELECT 1 FROM enrich_queue_log d
                              WHERE d.region=o.region
                                AND d.status='done'
                                AND d.code=o.code
                              LIMIT 1
                            )
                          )
                          OR (
                            NULLIF(o.item_id, '') IS NOT NULL
                            AND EXISTS (
                              SELECT 1 FROM enrich_queue_log d
                              WHERE d.region=o.region
                                AND d.status='done'
                                AND d.item_id=o.item_id
                              LIMIT 1
                            )
                          )
                        )
                      LIMIT 200
                    )
                    DELETE FROM enrich_queue_log
                    WHERE id IN (SELECT id FROM doomed)
                    """,
                    (rid,),
                )
                n = int(getattr(cur, "rowcount", 0) or 0)
                conn.commit()
                total += max(0, n)
                if n < 200:
                    break
                try:
                    conn.execute("SET LOCAL statement_timeout = '4s'")
                    conn.execute("SET LOCAL lock_timeout = '2s'")
                except Exception:  # noqa: BLE001
                    pass
            return total
    except Exception as e:  # noqa: BLE001
        log.warning(
            "prune open enrich queue if done failed region=%s: %s", rid, e
        )
    return 0


def _queue_log_prune_done_keep(region: str, keep: int = _QUEUE_LOG_DONE_KEEP) -> int:
    """只保留最近 keep 条「刮削完成」done，不删扫描分类行（scan/local_scan）。"""
    rid = _enrich._queue_log_region(region)
    keep_n = max(500, int(keep or _QUEUE_LOG_DONE_KEEP))
    if not rid:
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            # 仅裁剪非扫描写入的 done（刮削实时结果）
            row_n = conn.execute(
                f"""
                SELECT COUNT(*) AS n FROM enrich_queue_log
                WHERE region=? AND status='done'
                  AND {_enrich_scan._SQL_NOT_SCAN_SOURCE}
                """,
                (rid,),
            ).fetchone()
            if isinstance(row_n, dict):
                total = int(row_n.get("n") or 0)
            else:
                total = int((row_n[0] if row_n else 0) or 0)
            if total <= keep_n:
                return 0
            keep_rows = conn.execute(
                f"""
                SELECT id FROM enrich_queue_log
                WHERE region=? AND status='done'
                  AND {_enrich_scan._SQL_NOT_SCAN_SOURCE}
                ORDER BY updated_at DESC NULLS LAST, id DESC
                LIMIT ?
                """,
                (rid, keep_n),
            ).fetchall()
            keep_ids = [
                int((r.get("id") if isinstance(r, dict) else r[0]) or 0)
                for r in (keep_rows or [])
            ]
            keep_ids = [i for i in keep_ids if i > 0]
            if not keep_ids:
                return 0
            ph = ",".join("?" for _ in keep_ids)
            cur = conn.execute(
                f"""
                DELETE FROM enrich_queue_log
                WHERE region=? AND status='done'
                  AND {_enrich_scan._SQL_NOT_SCAN_SOURCE}
                  AND id NOT IN ({ph})
                """,
                (rid, *keep_ids),
            )
            dropped = int(getattr(cur, "rowcount", 0) or 0)
            try:
                conn.commit()
            except Exception:  # noqa: BLE001
                pass
            return max(0, dropped)
    except Exception as e:  # noqa: BLE001
        log.debug("prune done enrich queue failed region=%s: %s", rid, e)
    return 0


def _queue_log_prune_pending_if_running(
    region: str,
    *,
    code: str = "",
    item_id: str = "",
    keep_id: int = 0,
) -> int:
    """进入处理中后：删掉同番号其它 pending，避免处理中还挂在未处理。"""
    rid = _enrich._queue_log_region(region)
    if not rid:
        return 0
    code_u = str(code or "").strip().upper()
    iid = str(item_id or "").strip()
    kid = int(keep_id or 0)
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            try:
                conn.execute("SET LOCAL statement_timeout = '4s'")
                conn.execute("SET LOCAL lock_timeout = '2s'")
            except Exception:  # noqa: BLE001
                pass
            if kid > 0 and (code_u or iid):
                clauses: list[str] = []
                params: list[Any] = [rid]
                if code_u:
                    clauses.append("code=?")
                    params.append(code_u)
                if iid:
                    clauses.append("item_id=?")
                    params.append(iid)
                params.append(kid)
                cur = conn.execute(
                    f"""
                    DELETE FROM enrich_queue_log
                    WHERE region=?
                      AND status='pending'
                      AND ({" OR ".join(clauses)})
                      AND id<>?
                    """,
                    params,
                )
            elif code_u or iid:
                # 定点删：有 running 时由调用方保证；勿用全表相关 EXISTS
                clauses = []
                params = [rid]
                if code_u:
                    clauses.append("code=?")
                    params.append(code_u)
                if iid:
                    clauses.append("item_id=?")
                    params.append(iid)
                cur = conn.execute(
                    f"""
                    DELETE FROM enrich_queue_log
                    WHERE region=?
                      AND status='pending'
                      AND ({" OR ".join(clauses)})
                    """,
                    params,
                )
            else:
                # 后台全分区：分批，避免长事务锁死 UPDATE
                total = 0
                for _ in range(40):
                    cur = conn.execute(
                        """
                        WITH doomed AS (
                          SELECT o.id
                          FROM enrich_queue_log AS o
                          WHERE o.region=?
                            AND o.status='pending'
                            AND (
                              (
                                NULLIF(o.code, '') IS NOT NULL
                                AND EXISTS (
                                  SELECT 1 FROM enrich_queue_log r
                                  WHERE r.region=o.region
                                    AND r.status='running'
                                    AND r.code=o.code
                                  LIMIT 1
                                )
                              )
                              OR (
                                NULLIF(o.item_id, '') IS NOT NULL
                                AND EXISTS (
                                  SELECT 1 FROM enrich_queue_log r
                                  WHERE r.region=o.region
                                    AND r.status='running'
                                    AND r.item_id=o.item_id
                                  LIMIT 1
                                )
                              )
                            )
                          LIMIT 200
                        )
                        DELETE FROM enrich_queue_log
                        WHERE id IN (SELECT id FROM doomed)
                        """,
                        (rid,),
                    )
                    n = int(getattr(cur, "rowcount", 0) or 0)
                    conn.commit()
                    total += max(0, n)
                    if n < 200:
                        return total
                    try:
                        conn.execute("SET LOCAL statement_timeout = '4s'")
                        conn.execute("SET LOCAL lock_timeout = '2s'")
                    except Exception:  # noqa: BLE001
                        pass
                return total
            n = int(getattr(cur, "rowcount", 0) or 0)
            conn.commit()
            return max(0, n)
    except Exception as e:  # noqa: BLE001
        log.warning(
            "prune pending if running failed region=%s: %s", rid, e
        )
        return 0


def _queue_log_clear_pending(region: str) -> int:
    """清空该区 pending（保留成功/失败/处理中）。"""
    return _queue_log_prune_pending_not_in(region, set())


def _queue_log_classified_skip_keys(
    region: str, *, fresh: bool = False
) -> tuple[set[str], set[str]]:
    """队列表已分类（done/fail，含软成功）+ running 的 itemId/code。"""
    rid = _enrich._queue_log_region(region)
    empty: tuple[set[str], set[str]] = (set(), set())
    if not rid:
        return empty
    now = time.time()
    if not fresh:
        hit = _enrich._classified_skip_cache.get(rid)
        if hit and now - float(hit[0]) < _enrich._CLASSIFIED_SKIP_TTL_SEC:
            return hit[1], hit[2]
    iids: set[str] = set()
    codes: set[str] = set()
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            for raw in (
                conn.execute(
                    """
                    SELECT item_id, code FROM enrich_queue_log
                    WHERE region=? AND status IN ('done', 'fail', 'running')
                    """,
                    (rid,),
                ).fetchall()
                or []
            ):
                if isinstance(raw, dict):
                    iid = str(raw.get("item_id") or "").strip()
                    code_u = str(raw.get("code") or "").strip().upper()
                else:
                    iid = str(raw[0] or "").strip()
                    code_u = str(raw[1] or "").strip().upper()
                if iid:
                    iids.add(iid)
                if code_u:
                    codes.add(code_u)
    except Exception as e:  # noqa: BLE001
        log.warning("load classified skip keys failed region=%s: %s", rid, e)
        return empty
    _enrich._classified_skip_cache[rid] = (now, iids, codes)
    return iids, codes


def _queue_log_trim_inflated_pending(region: str) -> int:
    """已废弃：队列表 pending 为唯一真相，禁止按估算清库。

    旧逻辑在 db_pending > estimate*1.15 时清空 pending，会把扫描刚写入的
    真实未处理（如 24708）误判为虚高删光 → 界面「暂无未处理项」。
    """
    return 0


def _queue_log_clear_local_scan_status(region: str) -> int:
    """删掉扫描写入的成功/失败行，便于全量重写分类列表。"""
    rid = _enrich._queue_log_region(region)
    if not rid:
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            cur = conn.execute(
                f"""
                DELETE FROM enrich_queue_log
                WHERE region=? AND {_enrich_scan._SQL_IS_SCAN_SOURCE}
                  AND status IN ('done', 'fail')
                """,
                (rid,),
            )
            n = int(getattr(cur, "rowcount", 0) or 0)
            try:
                conn.commit()
            except Exception:  # noqa: BLE001
                pass
            _enrich._counts_cache.pop(rid, None)
            return max(0, n)
    except Exception as e:  # noqa: BLE001
        log.warning("clear local_scan status failed region=%s: %s", rid, e)
        return 0


_QUEUE_LOG_INSERT_CHUNK = 500


def _queue_log_insert_local_status_samples(
    region: str,
    maps: _enrich_scan._LocalNfoMaps,
    *,
    write_cap: int = 0,
    root: Path | None = None,
) -> dict[str, int]:
    """本地分类全量写入队列表（轻量行，可翻页）；返回全量 done/soft/fail 计数。

    write_cap>0 时仅写入每态前 N 条（兼容旧样例模式）；<=0 写全量。
    """
    rid = _enrich._queue_log_region(region)
    empty = {"done": 0, "soft": 0, "fail": 0}
    if not rid or not isinstance(maps, _enrich_scan._LocalNfoMaps):
        return empty
    cap = max(0, int(write_cap or 0))

    def _take(
        cands: list[tuple[str, str, list[str]]],
        samples: list[dict[str, Any]],
    ) -> list[tuple[str, str, list[str]]] | list[dict[str, Any]]:
        if cands:
            return cands if cap <= 0 else cands[:cap]
        if samples:
            return samples if cap <= 0 else samples[:cap]
        return []

    jobs: list[tuple[str, list[Any]]] = [
        ("done", _take(list(maps.done_cands or []), list(maps.done_samples or []))),
        ("soft", _take(list(maps.soft_cands or []), list(maps.soft_samples or []))),
        ("fail", _take(list(maps.fail_cands or []), list(maps.fail_samples or []))),
    ]
    total_rows = sum(len(xs) for _, xs in jobs)
    written = 0
    batch = 2000
    last_progress_at = 0.0

    def _as_item(kind: str, raw: Any) -> dict[str, Any] | None:
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, (tuple, list)) or len(raw) < 2:
            return None
        rel = str(raw[0] or "")
        code_u = str(raw[1] or "")
        gaps = list(raw[2] if len(raw) > 2 else [])
        # 全量扫描写入禁止读盘：否则 10 万行会卡在进度条不动
        return _enrich_scan._local_status_item(
            rel=rel,
            code=code_u,
            gaps=gaps,
            region=rid,
            kind=kind,
            root=None,
            merge_sidecar=False,
            enrich_detail=False,
        )

    try:
        for kind, xs in jobs:
            for start in range(0, len(xs), batch):
                chunk_raw = xs[start : start + batch]
                rows: list[dict[str, Any]] = []
                for raw in chunk_raw:
                    item = _as_item(kind, raw)
                    if item:
                        rows.append(item)
                if rows:
                    _enrich._queue_log_insert_many(rid, rows)
                written += len(rows)
                now = time.monotonic()
                if total_rows > 0 and (
                    written <= batch
                    or written >= total_rows
                    or now - last_progress_at >= 0.4
                ):
                    last_progress_at = now
                    _enrich._set_queue_scan_progress(
                        region=rid,
                        stage="write",
                        label=(
                            f"写入分类队列 · {written:,}/{total_rows:,}"
                            f" · 成功 {maps.done_n:,} · 软成功 {maps.soft_n:,}"
                            f" · 失败 {maps.fail_n:,}"
                        ),
                        scanned=written,
                        total=total_rows,
                        done=int(maps.done_n or 0),
                        soft=int(maps.soft_n or 0),
                        fail=int(maps.fail_n or 0),
                        notify=True,
                    )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "insert local status rows failed region=%s: %s", rid, e
        )
    _enrich._counts_cache.pop(rid, None)
    return {
        "done": int(maps.done_n or 0),
        "soft": int(maps.soft_n or 0),
        "fail": int(maps.fail_n or 0),
    }


def _queue_row_status(row: Any) -> str:
    """内存队列行的状态串（规范化后）。

    **唯一真相源**：`_queue_counts_of` 与暂停态改写的展示层都走这里，
    避免两处对 status 的读法漂移（曾出现大小写/空白不一致导致计数与展示打架）。

    注意：这里的行是内存队列 dict，不是 DB 行——形态为
    `{"status": "running"|"pending"|"done"|"fail", "code": ..., "itemId": ...}`。
    """
    if not isinstance(row, dict):
        return ""
    return str(row.get("status") or "").strip().lower()


def _queue_counts_of(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = _enrich_status._empty_queue_counts()
    for row in rows:
        if not isinstance(row, dict):
            continue
        st = _queue_row_status(row) or "pending"
        if st == "done":
            if bool(row.get("partialOk")) or _enrich_retry._is_soft_ok_error(
                str(row.get("error") or "")
            ):
                counts["soft"] += 1
            else:
                counts["done"] += 1
            continue
        if st not in counts:
            st = "pending"
        counts[st] += 1
    return counts


def _sample_queue_uncached(
    raw_queue: list[Any], *, limit: int
) -> list[dict[str, Any]]:
    """单趟抽样的**实现体**（4 次 C 层推导，常数最小）。

    注意别改成"单次 Python 循环"：实测 2 万行时 1 次 Python 循环反而比
    4 次列表推导慢（4.6ms vs 3.1ms），因为推导的循环体在 C 层跑。
    """
    running = [r for r in raw_queue if isinstance(r, dict) and r.get("status") == "running"]
    pending = [
        r
        for r in raw_queue
        if isinstance(r, dict) and (r.get("status") or "pending") in {"pending", ""}
    ]
    fail = [r for r in raw_queue if isinstance(r, dict) and r.get("status") == "fail"]
    done = [r for r in raw_queue if isinstance(r, dict) and r.get("status") == "done"]
    # 当前 + 未处理头 + 最近失败/成功（新完成的在前）
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in (
        *running[:8],
        *pending[:48],
        *reversed(fail[-32:]),
        *reversed(done[-32:]),
    ):
        key = str(row.get("itemId") or row.get("code") or id(row))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _queue_row_match_index(
    queue: list[Any],
    *,
    index: int = -1,
    match: dict[str, Any] | None = None,
) -> int:
    """定位内存队列行：边扫截断后 worker 下标会错位，必须按 logId/itemId/code 对齐。"""
    m = match if isinstance(match, dict) else {}
    lid = _queue_log_int_id(m)
    iid = str(m.get("itemId") or m.get("item_id") or "").strip()
    code_u = str(m.get("code") or "").strip().upper()

    def _at(i: int) -> dict[str, Any] | None:
        if 0 <= i < len(queue) and isinstance(queue[i], dict):
            return queue[i]
        return None

    if lid > 0:
        for i, r in enumerate(queue):
            if isinstance(r, dict) and _queue_log_int_id(r) == lid:
                return i
    if iid:
        for i, r in enumerate(queue):
            if isinstance(r, dict) and str(r.get("itemId") or "").strip() == iid:
                return i
    if code_u:
        # 优先命中处理中/未处理，避免改到已完成的同番号旧行
        prefer = ("running", "pending", "fail", "done")
        best_i, best_rank = -1, 99
        for i, r in enumerate(queue):
            if not isinstance(r, dict):
                continue
            if str(r.get("code") or "").strip().upper() != code_u:
                continue
            st = str(r.get("status") or "pending").strip().lower()
            try:
                rank = prefer.index(st)
            except ValueError:
                rank = 50
            if rank < best_rank:
                best_i, best_rank = i, rank
        if best_i >= 0:
            return best_i
    # 下标仅作兜底：且必须番号一致，防止截断队列串写
    hit = _at(index)
    if hit is not None:
        if not code_u or str(hit.get("code") or "").strip().upper() == code_u:
            return index
    return -1


def _payload_field_code(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    fields = payload.get("fields")
    if not isinstance(fields, list):
        return ""
    for f in fields:
        if not isinstance(f, dict):
            continue
        if str(f.get("id") or "") != "code":
            continue
        return str(f.get("value") or "").strip().upper()
    return ""


def _queue_log_demote_false_dones(region: str) -> int:
    """成功/软成功/失败但无本地目录或字段番号串号 → 退回 pending 重刮。

    磁盘校验在连接外做：持连接扫 10 万行会锁死其它状态接口。
    """
    rid = _enrich._queue_log_region(region)
    if not rid:
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            rows = list(
                conn.execute(
                    """
                    SELECT id, code, item_id, error, gaps_json, payload_json, status
                    FROM enrich_queue_log
                    WHERE region=? AND status IN ('done', 'fail')
                    """,
                    (rid,),
                ).fetchall()
                or []
            )
        # 连接已释放；下面只做磁盘判定
        updates: list[tuple[str, str, str, int]] = []
        for raw in rows:
            if isinstance(raw, dict):
                lid = int(raw.get("id") or 0)
                code = str(raw.get("code") or "").strip().upper()
                iid = str(raw.get("item_id") or "").strip()
                payload_raw = raw.get("payload_json")
                st = str(raw.get("status") or "").strip().lower()
            else:
                lid = int(raw[0] or 0)
                code = str(raw[1] or "").strip().upper()
                iid = str(raw[2] or "").strip()
                payload_raw = raw[5]
                st = str(raw[6] if len(raw) > 6 else "").strip().lower()
            if lid <= 0:
                continue
            try:
                payload = (
                    json.loads(payload_raw)
                    if isinstance(payload_raw, str)
                    else (payload_raw if isinstance(payload_raw, dict) else {})
                )
            except Exception:  # noqa: BLE001
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            field_code = _payload_field_code(payload)
            code_mismatch = bool(field_code and code and field_code != code)
            folder = _enrich_detail._resolve_enrich_folder(
                region=rid, code=code, item_id=iid
            )
            missing_disk = folder is None or not _enrich_cover._local_poster_ok(folder)
            # fail：仅本地已删才回 pending（仍缺封面的 fail 保持失败）
            if st == "fail" and not missing_disk and not code_mismatch:
                continue
            if not code_mismatch and not missing_disk:
                continue
            reason = (
                f"串号回滚:{field_code}"
                if code_mismatch
                else "仍缺:封面 · 无本地目录"
            )
            gaps = [
                "no_local",
                "no_media",
                "no_actress",
                "no_studio",
                "no_plot",
                "thin_title",
            ]
            if folder is not None and folder.is_dir():
                try:
                    _, gaps = _enrich_scan._local_folder_gaps(folder)
                except Exception:  # noqa: BLE001
                    gaps = ["no_local"]
            payload["partialOk"] = False
            payload["gapsAfter"] = gaps
            payload.pop("ok", None)
            updates.append(
                (
                    reason[:500],
                    json.dumps(gaps, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False, default=str),
                    lid,
                )
            )
        if not updates:
            return 0
        n = 0
        with connect() as conn:
            for i in range(0, len(updates), 200):
                chunk = updates[i : i + 200]
                for params in chunk:
                    conn.execute(
                        """
                        UPDATE enrich_queue_log
                        SET status='pending', error=?, gaps_json=?, payload_json=?,
                            updated_at=NOW()
                        WHERE id=? AND status IN ('done', 'fail')
                        """,
                        params,
                    )
                    n += 1
                conn.commit()
        return n
    except Exception as e:  # noqa: BLE001
        log.warning("demote false enrich dones failed region=%s: %s", rid, e)
        return 0


def _queue_log_demote_false_dones_budgeted(
    region: str, *, time_budget_sec: float = 8.0
) -> int:
    """后台有限预算 demote：不挡开刮；扫完或超时即停。"""
    rid = _enrich._queue_log_region(region)
    if not rid:
        return 0
    # 标记已调度，避免同一进程反复开线程；未扫完也不再强制全量挡启动
    if rid in _enrich._demoted_false_dones:
        return 0
    _enrich._demoted_false_dones.add(rid)
    t0 = time.monotonic()
    budget = max(1.0, float(time_budget_sec or 8.0))
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            rows = list(
                conn.execute(
                    """
                    SELECT id, code, item_id, error, gaps_json, payload_json, status
                    FROM enrich_queue_log
                    WHERE region=? AND status IN ('done', 'fail')
                    ORDER BY updated_at ASC NULLS FIRST, id ASC
                    LIMIT 4000
                    """,
                    (rid,),
                ).fetchall()
                or []
            )
        updates: list[tuple[str, str, str, int]] = []
        for raw in rows:
            if (time.monotonic() - t0) >= budget:
                break
            if isinstance(raw, dict):
                lid = int(raw.get("id") or 0)
                code = str(raw.get("code") or "").strip().upper()
                iid = str(raw.get("item_id") or "").strip()
                payload_raw = raw.get("payload_json")
                st = str(raw.get("status") or "").strip().lower()
            else:
                lid = int(raw[0] or 0)
                code = str(raw[1] or "").strip().upper()
                iid = str(raw[2] or "").strip()
                payload_raw = raw[5]
                st = str(raw[6] if len(raw) > 6 else "").strip().lower()
            if lid <= 0:
                continue
            try:
                payload = (
                    json.loads(payload_raw)
                    if isinstance(payload_raw, str)
                    else (payload_raw if isinstance(payload_raw, dict) else {})
                )
            except Exception:  # noqa: BLE001
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            field_code = _payload_field_code(payload)
            code_mismatch = bool(field_code and code and field_code != code)
            folder = _enrich_detail._resolve_enrich_folder(region=rid, code=code, item_id=iid)
            missing_disk = folder is None or not _enrich_cover._local_poster_ok(folder)
            if st == "fail" and not missing_disk and not code_mismatch:
                continue
            if not code_mismatch and not missing_disk:
                continue
            reason = (
                f"串号回滚:{field_code}"
                if code_mismatch
                else "仍缺:封面 · 无本地目录"
            )
            gaps = [
                "no_local",
                "no_media",
                "no_actress",
                "no_studio",
                "no_plot",
                "thin_title",
            ]
            if folder is not None and folder.is_dir():
                try:
                    _, gaps = _enrich_scan._local_folder_gaps(folder)
                except Exception:  # noqa: BLE001
                    gaps = ["no_local"]
            payload["partialOk"] = False
            payload["gapsAfter"] = gaps
            payload.pop("ok", None)
            updates.append(
                (
                    reason[:500],
                    json.dumps(gaps, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False, default=str),
                    lid,
                )
            )
        if not updates:
            return 0
        n = 0
        with connect() as conn:
            for i in range(0, len(updates), 200):
                chunk = updates[i : i + 200]
                for params in chunk:
                    conn.execute(
                        """
                        UPDATE enrich_queue_log
                        SET status='pending', error=?, gaps_json=?, payload_json=?,
                            updated_at=NOW()
                        WHERE id=? AND status IN ('done', 'fail')
                        """,
                        params,
                    )
                    n += 1
                conn.commit()
        if n:
            log.info(
                "budget demote region=%s n=%s spent=%.1fs",
                rid,
                n,
                time.monotonic() - t0,
            )
        return n
    except Exception as e:  # noqa: BLE001
        log.warning("budget demote failed region=%s: %s", rid, e)
        return 0


def _queue_log_promote_actress_soft_fails(region: str) -> int:
    """历史软缺口失败（不缺封面/标题）→ 软成功（done）。须本地封面已落盘。"""
    rid = _enrich._queue_log_region(region)
    if not rid:
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT id, code, item_id, error, gaps_json, payload_json
                FROM enrich_queue_log
                WHERE region=? AND status='fail'
                """,
                (rid,),
            ).fetchall()
            ids: list[int] = []
            for raw in rows or []:
                if isinstance(raw, dict):
                    lid = int(raw.get("id") or 0)
                    code = str(raw.get("code") or "").strip().upper()
                    iid = str(raw.get("item_id") or "").strip()
                    err = str(raw.get("error") or "")
                    gaps_raw = raw.get("gaps_json")
                    payload_raw = raw.get("payload_json")
                else:
                    lid = int(raw[0] or 0)
                    code = str(raw[1] or "").strip().upper()
                    iid = str(raw[2] or "").strip()
                    err = str(raw[3] or "")
                    gaps_raw = raw[4]
                    payload_raw = raw[5]
                if lid <= 0:
                    continue
                # 文案已是软缺口，或 gaps_json 不含硬缺口
                gaps_hint: list[str] = []
                try:
                    parsed = (
                        json.loads(gaps_raw)
                        if isinstance(gaps_raw, str)
                        else (gaps_raw if isinstance(gaps_raw, list) else [])
                    )
                    if isinstance(parsed, list):
                        gaps_hint = [str(g) for g in parsed if str(g).strip()]
                except Exception:  # noqa: BLE001
                    gaps_hint = []
                soft_by_err = _enrich_retry._is_soft_remain_error(err)
                soft_hint = [g for g in gaps_hint if g in _enrich._SOFT_SUCCESS_GAPS]
                # 仅女优/片商软缺口，或「无硬缺口」的历史 fail（可能升完整成功）
                soft_by_gaps = bool(soft_hint) or (
                    bool(gaps_hint)
                    and not any(g in _enrich._SUCCESS_BLOCK_GAPS for g in gaps_hint)
                )
                if not soft_by_err and not soft_by_gaps:
                    continue
                folder = _enrich_detail._resolve_enrich_folder(
                    region=rid, code=code, item_id=iid
                )
                if folder is None or not _enrich_cover._local_poster_ok(folder):
                    continue
                # 再以磁盘为准，避免文案软缺口但实际仍缺硬字段
                try:
                    _, disk_gaps = _enrich_scan._local_folder_gaps(folder)
                except Exception:  # noqa: BLE001
                    continue
                if any(g in _enrich._SUCCESS_BLOCK_GAPS for g in disk_gaps):
                    continue
                soft_only = [
                    g for g in disk_gaps if g in _enrich._SOFT_SUCCESS_GAPS
                ]
                ids.append(lid)
                # 磁盘无女优/片商缺口 → 完整成功（剧情/外链不算软成功）
                soft_gaps = (
                    soft_only
                    or _enrich_retry._soft_gaps_from_remain_error(err)
                    or soft_hint
                )
                try:
                    payload = (
                        json.loads(payload_raw)
                        if isinstance(payload_raw, str)
                        else (payload_raw if isinstance(payload_raw, dict) else {})
                    )
                except Exception:  # noqa: BLE001
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                if soft_gaps:
                    payload["partialOk"] = True
                    payload["gapsAfter"] = soft_gaps
                    labels = _enrich_retry._gap_labels(soft_gaps)
                    new_err = _enrich_retry._format_soft_ok_error(labels)
                    gaps_js = json.dumps(soft_gaps, ensure_ascii=False)
                else:
                    payload["partialOk"] = False
                    payload["gapsAfter"] = []
                    new_err = ""
                    gaps_js = "[]"
                conn.execute(
                    """
                    UPDATE enrich_queue_log
                    SET status='done', error=?, gaps_json=?, payload_json=?,
                        updated_at=NOW()
                    WHERE id=? AND status='fail'
                    """,
                    (
                        new_err[:500],
                        gaps_js,
                        json.dumps(payload, ensure_ascii=False, default=str),
                        lid,
                    ),
                )
            if ids:
                conn.commit()
            return len(ids)
    except Exception as e:  # noqa: BLE001
        log.warning(
            "promote actress soft fails failed region=%s: %s", rid, e
        )
        return 0


def _queue_log_normalize_soft_to_full_success(region: str) -> int:
    """旧规则把「缺剧情/外链」也标成软成功 → 升为完整成功。

    仅保留缺女优/片商为 soft；其余 done+partialOk 清掉 soft 标记。
    """
    rid = _enrich._queue_log_region(region)
    if not rid:
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            soft_pred = _enrich_retry._soft_done_sql_pred(error_col="error")
            rows = conn.execute(
                f"""
                SELECT id, error, gaps_json, payload_json
                FROM enrich_queue_log
                WHERE region=? AND status='done' AND {soft_pred}
                """,
                (rid,),
            ).fetchall()
            n = 0
            for raw in rows or []:
                if isinstance(raw, dict):
                    lid = int(raw.get("id") or 0)
                    err = str(raw.get("error") or "")
                    gaps_raw = raw.get("gaps_json")
                    payload_raw = raw.get("payload_json")
                else:
                    lid = int(raw[0] or 0)
                    err = str(raw[1] or "")
                    gaps_raw = raw[2]
                    payload_raw = raw[3]
                if lid <= 0:
                    continue
                try:
                    gaps = (
                        json.loads(gaps_raw)
                        if isinstance(gaps_raw, str)
                        else (gaps_raw if isinstance(gaps_raw, list) else [])
                    )
                except Exception:  # noqa: BLE001
                    gaps = []
                try:
                    payload = (
                        json.loads(payload_raw)
                        if isinstance(payload_raw, str)
                        else (payload_raw if isinstance(payload_raw, dict) else {})
                    )
                except Exception:  # noqa: BLE001
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                after = list(payload.get("gapsAfter") or gaps or [])
                soft_gaps = [g for g in after if str(g) in _enrich._SOFT_SUCCESS_GAPS]
                # 仍缺女优/片商 → 保留软成功，只规范化文案/gaps
                if soft_gaps or _enrich_retry._is_soft_remain_error(err):
                    if soft_gaps and (
                        list(payload.get("gapsAfter") or []) != soft_gaps
                        or not _enrich_retry._is_soft_remain_error(err)
                    ):
                        payload["partialOk"] = True
                        payload["gapsAfter"] = soft_gaps
                        conn.execute(
                            """
                            UPDATE enrich_queue_log
                            SET error=?, gaps_json=?, payload_json=?, updated_at=NOW()
                            WHERE id=?
                            """,
                            (
                                _enrich_retry._format_soft_ok_error(_enrich_retry._gap_labels(soft_gaps)),
                                json.dumps(soft_gaps, ensure_ascii=False),
                                json.dumps(payload, ensure_ascii=False, default=str),
                                lid,
                            ),
                        )
                        n += 1
                    continue
                # 仅缺剧情/外链等 → 升完整成功
                payload["partialOk"] = False
                payload["gapsAfter"] = []
                conn.execute(
                    """
                    UPDATE enrich_queue_log
                    SET error='', gaps_json='[]', payload_json=?, updated_at=NOW()
                    WHERE id=?
                    """,
                    (
                        json.dumps(payload, ensure_ascii=False, default=str),
                        lid,
                    ),
                )
                n += 1
            if n:
                conn.commit()
            # 角标 tip 与库对齐（软成功降档必须立刻反映到 UI）
            try:
                dbc = _queue_log_status_counts_db(rid)
                tip_prev = (_enrich._LOCAL_STATUS_TOTALS.get(rid) or {}) if rid else {}
                _enrich._ensure_local_status_totals_loaded()
                _enrich_status._set_local_status_totals(
                    rid,
                    done=int(dbc.get("done") or 0),
                    soft=int(dbc.get("soft") or 0),
                    fail=int(dbc.get("fail") or 0),
                    total=int(tip_prev.get("total") or 0) or None,
                )
            except Exception:  # noqa: BLE001
                pass
            return n
    except Exception as e:  # noqa: BLE001
        log.warning(
            "normalize soft→full success failed region=%s: %s", rid, e
        )
        return 0
