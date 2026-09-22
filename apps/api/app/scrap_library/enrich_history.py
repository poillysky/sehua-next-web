# -*- coding: utf-8 -*-
"""enrich_history —— 自 scrap_library/enrich.py 拆出（机械搬移，行为不变）。"""

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
import app.scrap_library.enrich_queue as _enrich_queue
import app.scrap_library.enrich_status as _enrich_status
from app.scrap_library.enrich import (_DONE_LOG_RE, _enrich_job, _enrich_lock, _enrich_log_sink, _hist_log_cache, _hydrate_queue_item_from_library, _invalidate_classified_skip_cache, _pending_backfill_done, _persist_enrich_runtime, log, notify_enrich_watchers)


_ENRICH_LOG_KEEP = 2000


_ENRICH_LOG_RETURN = 40


_ENRICH_LOG_MEMORY = 500


def _enrich_log_region_keys(region: str) -> list[str]:
    """分区日志可能的键：稳定 id + 中文目录名 + 短标签。"""
    raw = str(region or "").strip()
    if not raw:
        return ["_all"]
    from app.core.region_meta import REGION_META, REGION_ORDER

    keys: list[str] = []
    seen: set[str] = set()

    def add(v: str) -> None:
        s = str(v or "").strip()
        if not s or s in seen:
            return
        seen.add(s)
        keys.append(s)

    add(raw)
    # id → label
    meta = REGION_META.get(raw)
    if meta:
        add(str(meta.get("label") or ""))
        add(str(meta.get("id") or ""))
    # label / 目录名 → id
    for rid, m in REGION_META.items():
        label = str(m.get("label") or "").strip()
        if raw == label or raw == rid:
            add(rid)
            add(label)
    # 短标签「有码」等
    for rid in REGION_ORDER:
        m = REGION_META.get(rid) or {}
        label = str(m.get("label") or "")
        if raw in label or label.endswith(raw):
            add(rid)
            add(label)
    return keys or [raw]


def _canonical_enrich_log_region(region: str | None = None) -> str:
    """落库/内存统一用稳定 id，避免 日本有码 / japan_censored 分裂。

    注意：禁止在已持有 _enrich_lock 时再 acquire（旧 Lock 会死锁）。
    空 region 时无锁读 currentRegion（可接受极短竞态）。
    """
    raw = str(region or "").strip()
    if not raw:
        raw = str(_enrich_job.get("currentRegion") or "").strip()
    if not raw:
        return "_all"
    from app.core.region_meta import REGION_META

    # 旧逻辑区 fc2_ppv 并回物理 FC2（设置页已合并为一类）
    if raw in {"fc2_ppv", "FC2-PPV 番号", "FC2PPV"}:
        return "fc2"
    if raw in REGION_META:
        return raw
    for rid, m in REGION_META.items():
        if raw == str(m.get("label") or "").strip():
            return rid
    # 短名：有码 → 日本有码
    for rid, m in REGION_META.items():
        label = str(m.get("label") or "")
        if label.endswith(raw) or raw in label:
            return rid
    return raw


def _persist_enrich_log(region: str, text: str) -> None:
    """刮削日志落元库（**异步攒批**），重启后仍可查。

    ⚠️ 语义变化（第九轮）：返回时只保证「已入缓冲」，不保证已落库。
    需要读回刚写的内容（探针/收尾）请先 `flush_enrich_logs()`。
    """
    rid = _canonical_enrich_log_region(region)
    line = str(text or "").strip()
    if not line:
        return
    _enrich_log_sink.push(rid, line)


def flush_enrich_logs() -> None:
    """把缓冲里的日志立刻写库（任务收尾 / 探针 / 清空日志前用）。"""
    _enrich_log_sink.flush()


def enrich_log_sink_stats() -> dict[str, int]:
    """缓冲状态（诊断用）：pending / written / dropped。"""
    return _enrich_log_sink.stats()


def load_enrich_logs(*, region: str = "", limit: int = 200) -> list[str]:
    rid = str(region or "").strip()
    lim = max(1, min(int(limit or 200), 500))
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            if rid:
                keys = _enrich_log_region_keys(rid)
                # 多键合并后按 id 排序取尾
                placeholders = ",".join(["?"] * len(keys))
                rows = conn.execute(
                    f"""
                    SELECT line FROM enrich_logs
                    WHERE region IN ({placeholders})
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (*keys, lim),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT line FROM enrich_logs
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (lim,),
                ).fetchall()
        out = [
            str((r.get("line") if isinstance(r, dict) else r[0]) or "")
            for r in (rows or [])
        ]
        out.reverse()
        return [x for x in out if x]
    except Exception as e:  # noqa: BLE001
        log.warning("load enrich logs failed: %s", e)
        return []


_HIST_LOG_TTL_SEC = 3.0


def _load_enrich_logs_cached(region: str, limit: int) -> list[str]:
    key = (str(region or ""), int(limit))
    hit = _hist_log_cache.get(key)
    if hit and (time.monotonic() - float(hit[0])) < _HIST_LOG_TTL_SEC:
        return list(hit[1])
    rows = load_enrich_logs(region=region, limit=limit)
    if len(_hist_log_cache) > 64:
        _hist_log_cache.clear()
    _hist_log_cache[key] = (time.monotonic(), list(rows))
    return rows


def _clear_enrich_logs(*, region: str = "", wipe_all_tail: bool = True) -> None:
    """清分区运行日志（内存 + 元库）；暂停绝不能调用。"""
    rid = str(region or "").strip()
    keys = _enrich_log_region_keys(rid) if rid else []
    with _enrich_lock:
        if rid:
            region_logs = dict(_enrich_job.get("regionLogs") or {})
            for k in keys:
                region_logs.pop(k, None)
            # 当前分区停止时顺带清空全局尾日志，避免 UI 回退到 st.log
            cur = str(_enrich_job.get("currentRegion") or "").strip()
            if not cur or cur == rid or cur in keys or _canonical_enrich_log_region(cur) == _canonical_enrich_log_region(rid):
                _enrich_job["log"] = []
            _enrich_job["regionLogs"] = region_logs
        else:
            _enrich_job["regionLogs"] = {}
            _enrich_job["log"] = []
    try:
        from app.core.db import connect, init_db

        # ⚠️ 必须先丢掉**未落库**的缓冲行：否则 DELETE 之后后台线程再 flush，
        # 刚清掉的日志又被写回来（`discard` 与写库共用 `_io_lock`，不会交错）。
        if not rid:
            _enrich_log_sink.discard(None)
        else:
            drop_keys = set(keys) | {_canonical_enrich_log_region(rid)}
            if wipe_all_tail:
                drop_keys.add("_all")
            for k in drop_keys:
                _enrich_log_sink.discard(k)
        init_db()
        with connect() as conn:
            if rid:
                for k in keys:
                    conn.execute("DELETE FROM enrich_logs WHERE region = ?", (k,))
                # 兼容历史脏键 + 无分区时落到 _all 的尾日志
                canon = _canonical_enrich_log_region(rid)
                conn.execute("DELETE FROM enrich_logs WHERE region = ?", (canon,))
                if wipe_all_tail:
                    conn.execute("DELETE FROM enrich_logs WHERE region = ?", ("_all",))
            else:
                conn.execute("DELETE FROM enrich_logs")
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("clear enrich logs failed region=%s: %s", rid or "*", e)


def clear_enrich_logs(*, region: str = "") -> dict[str, Any]:
    """清空刮削日志表（文本日志 + 队列记录）并丢掉该区旧检查点。

    清空·扫描后必须以队列表/新扫描为准，不能再让历史 checkpoint
    （如 fail=622）顶掉真实角标。
    已暂停/停止（halt）时允许清空，即使 worker 尚未把 running 置 False。
    """
    rid = _enrich._queue_log_region(region) or str(region or "").strip()

    running = False
    cur = ""
    halt = None
    phase = ""
    if not _enrich_lock.acquire(timeout=2.0):
        # 锁被卡：仍允许清库（用户已点暂停），内存态尽量事后对齐
        log.warning("clear_enrich_logs lock busy region=%s — force clear db", rid)
        running = bool(_enrich_job.get("running"))
        cur = _enrich._queue_log_region(str(_enrich_job.get("currentRegion") or ""))
        halt = _enrich_job.get("halt")
        phase = str(_enrich_job.get("phase") or "")
        locked = False
    else:
        locked = True
        try:
            running = bool(_enrich_job.get("running"))
            cur = _enrich._queue_log_region(str(_enrich_job.get("currentRegion") or ""))
            halt = _enrich_job.get("halt")
            phase = str(_enrich_job.get("phase") or "")
            # 真正在跑且未暂停/停止：拒绝硬清
            paused_like = halt in {"pause", "stop"} or phase in {
                "paused",
                "stopping",
                "stopped",
            }
            if running and rid and cur == rid and not paused_like:
                return {
                    "ok": False,
                    "cleared": False,
                    "busy": True,
                    "error": "刮削进行中，请先暂停再清空·扫描",
                    "region": rid or None,
                }
            # 暂停收尾中：打断残留 running，避免 UI/清空一直以为在刮
            if paused_like and running and rid and cur == rid:
                _enrich_job["running"] = False
                _enrich_job["halt"] = "stop"
                _enrich_job["phase"] = "stopped"
                running = False
        finally:
            if locked:
                _enrich_lock.release()

    _clear_enrich_logs(region=rid, wipe_all_tail=False)
    _enrich_queue._clear_queue_log(region=rid)
    _enrich_status._clear_local_status_totals(rid)
    _invalidate_classified_skip_cache(rid)
    if rid:
        _pending_backfill_done.discard(rid)
    else:
        _pending_backfill_done.clear()
    cleared_cp = False
    got_lock = _enrich_lock.acquire(timeout=2.0)
    try:
        if got_lock:
            running = bool(_enrich_job.get("running"))
            cur = _enrich._queue_log_region(str(_enrich_job.get("currentRegion") or ""))
            halt = _enrich_job.get("halt")
            phase = str(_enrich_job.get("phase") or "")
            paused_like = halt in {"pause", "stop"} or phase in {
                "paused",
                "stopping",
                "stopped",
            }
            if paused_like:
                _enrich_job["running"] = False
                running = False
            # 非本区运行中才清检查点；本区已暂停/空闲都清
            if rid and (not running or cur != rid or paused_like):
                cps = dict(_enrich_job.get("checkpoints") or {})
                if rid in cps or any(
                    _enrich._queue_log_region(str(k)) == rid for k in list(cps.keys())
                ):
                    for k in list(cps.keys()):
                        if _enrich._queue_log_region(str(k)) == rid or str(k) == rid:
                            cps.pop(k, None)
                            cleared_cp = True
                    _enrich_job["checkpoints"] = cps
                prog = dict(_enrich_job.get("progress") or {})
                if prog:
                    prog.update(
                        {
                            "done": 0,
                            "ok": 0,
                            "failed": 0,
                            "percent": 0,
                            "label": "已清空",
                            "stage": "idle",
                        }
                    )
                    _enrich_job["progress"] = prog
                result = _enrich_job.get("result")
                if isinstance(result, dict):
                    _enrich_job["result"] = {
                        **result,
                        "ok": 0,
                        "failed": 0,
                        "queued": 0,
                    }
                _enrich_job["queue"] = []
                _enrich_job["queueCounts"] = {
                    "pending": 0,
                    "running": 0,
                    "done": 0,
                    "fail": 0,
                }
                _enrich_job["phase"] = ""
                _enrich_job["halt"] = None
                _enrich_job["paused"] = False
                _enrich_job["cancel"] = False
                if cur == rid:
                    _enrich_job["currentRegion"] = ""
                    _enrich_job["current"] = None
    finally:
        if got_lock:
            _enrich_lock.release()
    if cleared_cp or rid:
        try:
            _persist_enrich_runtime()
        except Exception as e:  # noqa: BLE001
            log.warning("persist after clear enrich logs failed: %s", e)
    try:
        notify_enrich_watchers(force=True)
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "cleared": True,
        "checkpointCleared": bool(cleared_cp),
        "region": rid or None,
    }


def _recover_done_from_enrich_logs(region: str) -> int:
    """从文本日志里的「番号 · 完成…」回填成功队列（暂停/清检查点后成功 tab 会空）。"""
    rid = _enrich._queue_log_region(region)
    if not rid:
        return 0
    codes: list[str] = []
    seen: set[str] = set()
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT line FROM enrich_logs
                WHERE region = ?
                ORDER BY id ASC
                """,
                (rid,),
            ).fetchall()
            for raw in rows or []:
                line = str(
                    (raw.get("line") if isinstance(raw, dict) else raw[0]) or ""
                ).strip()
                m = _DONE_LOG_RE.match(line)
                if not m:
                    continue
                code = m.group(1).strip().upper()
                if not code or code in seen:
                    continue
                seen.add(code)
                codes.append(code)
    except Exception as e:  # noqa: BLE001
        log.warning("recover done from enrich logs failed region=%s: %s", rid, e)
        return 0
    if not codes:
        return 0

    recovered = 0
    for code in codes:
        try:
            # 本地已删 → 不回填 done（否则重扫 demote 后又被日志捞回）
            folder = _enrich_detail._resolve_enrich_folder(region=rid, code=code, item_id="")
            if folder is None or not _enrich_cover._local_poster_ok(folder):
                continue
            # 已有 pending/running → 改 done；已有 done 跳过；没有则插入
            from app.core.db import connect, init_db

            init_db()
            with connect() as conn:
                row = conn.execute(
                    """
                    SELECT id, status, payload_json, detail_title, source, item_id
                    FROM enrich_queue_log
                    WHERE region=? AND code=?
                    ORDER BY
                      CASE status
                        WHEN 'done' THEN 0
                        WHEN 'fail' THEN 1
                        WHEN 'running' THEN 2
                        ELSE 3
                      END,
                      id DESC
                    LIMIT 1
                    """,
                    (rid, code),
                ).fetchone()
                if row:
                    lid = int(
                        (row.get("id") if isinstance(row, dict) else row[0]) or 0
                    )
                    st = str(
                        (row.get("status") if isinstance(row, dict) else row[1])
                        or ""
                    ).strip().lower()
                    if st == "fail":
                        continue
                    payload_raw = (
                        row.get("payload_json")
                        if isinstance(row, dict)
                        else (row[2] if len(row) > 2 else "{}")
                    )
                    detail_title = str(
                        (
                            row.get("detail_title")
                            if isinstance(row, dict)
                            else (row[3] if len(row) > 3 else "")
                        )
                        or ""
                    ).strip()
                    item_id = str(
                        (
                            row.get("item_id")
                            if isinstance(row, dict)
                            else (row[5] if len(row) > 5 else "")
                        )
                        or ""
                    ).strip()
                    try:
                        payload = (
                            json.loads(payload_raw)
                            if isinstance(payload_raw, str)
                            else (payload_raw or {})
                        )
                    except Exception:  # noqa: BLE001
                        payload = {}
                    if not isinstance(payload, dict):
                        payload = {}
                    has_fields = bool(payload.get("fields"))
                    if st == "done" and has_fields and detail_title:
                        continue
                    # done 但空壳 / pending→done：用本地库补全
                    hydrated = _hydrate_queue_item_from_library(
                        code=code, region=rid, item_id=item_id
                    )
                    if lid > 0:
                        merged = {
                            "itemId": hydrated.get("itemId") or item_id,
                            "code": code,
                            "status": "done",
                            "gaps": [],
                            "error": "",
                            "source": str(
                                hydrated.get("source")
                                or (
                                    row.get("source")
                                    if isinstance(row, dict)
                                    else ""
                                )
                                or ""
                            ).strip(),
                            "detailTitle": hydrated.get("detailTitle")
                            or detail_title,
                            "posterDownloaded": hydrated.get("posterDownloaded"),
                            "vectorSynced": hydrated.get("vectorSynced"),
                            "fields": hydrated.get("fields") or payload.get("fields"),
                            "sourceTimings": payload.get("sourceTimings") or [],
                        }
                        # 去掉伪命中源
                        if merged["source"] in {"log_recover", "recover"}:
                            merged["source"] = ""
                        params = _enrich_queue._queue_log_insert_params(rid, merged)
                        conn.execute(
                            """
                            UPDATE enrich_queue_log
                            SET item_id=?, code=?, status=?, gaps_json=?, error=?,
                                source=?, fetch_ms=?, detail_title=?, payload_json=?,
                                updated_at=NOW()
                            WHERE id=?
                            """,
                            (*params[1:], lid),
                        )
                        conn.commit()
                        recovered += 1
                        continue
                # 无行：插入并尽量补全
                hydrated = _hydrate_queue_item_from_library(code=code, region=rid)
                merged = {
                    "itemId": hydrated.get("itemId") or "",
                    "code": code,
                    "status": "done",
                    "gaps": [],
                    "error": "",
                    "source": "",
                    "detailTitle": hydrated.get("detailTitle") or "",
                    "posterDownloaded": hydrated.get("posterDownloaded"),
                    "vectorSynced": hydrated.get("vectorSynced"),
                    "fields": hydrated.get("fields") or [],
                    "sourceTimings": [],
                }
                params = _enrich_queue._queue_log_insert_params(rid, merged)
                conn.execute(
                    """
                    INSERT INTO enrich_queue_log (
                      region, item_id, code, status, gaps_json, error, source,
                      fetch_ms, detail_title, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )
                conn.commit()
                recovered += 1
        except Exception as e:  # noqa: BLE001
            log.debug("recover done row failed %s %s: %s", rid, code, e)
    if recovered:
        log.info(
            "recover enrich done from logs region=%s n=%s", rid, recovered
        )
    return recovered
