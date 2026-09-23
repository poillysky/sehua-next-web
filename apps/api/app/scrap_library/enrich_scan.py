# -*- coding: utf-8 -*-
"""enrich_scan —— 自 scrap_library/enrich.py 拆出（机械搬移，行为不变）。"""

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
import app.scrap_library.enrich_detail as _enrich_detail
import app.scrap_library.enrich_history as _enrich_history
import app.scrap_library.enrich_merge as _enrich_merge
import app.scrap_library.enrich_queue as _enrich_queue
import app.scrap_library.enrich_retry as _enrich_retry
import app.scrap_library.enrich_sidecar as _enrich_sidecar
import app.scrap_library.enrich_status as _enrich_status
import app.scrap_library.enrich_text as _enrich_text
from app.scrap_library.enrich import (_ENRICH_KINDS, _LOCAL_NFO_MAPS_CACHE_MAX, _LOCAL_NFO_MAPS_TTL_SEC, _SOFT_SUCCESS_GAPS, _SUCCESS_BLOCK_GAPS, _demoted_false_dones, _folder_gaps_cache, _folder_gaps_cache_lock, _invalidate_classified_skip_cache, _local_nfo_maps_cache, _pending_backfill_done, log)
from app.scrap_library.enrich_queue_io import _counts_cache, load_queue_log
from app.scrap_library.enrich_runtime import (_QUEUE_SCAN_LOCK, _QUEUE_SCAN_STATE, _enrich_job, _enrich_lock, _set_queue_scan_progress)


_SQL_NOT_SCAN_SOURCE = "COALESCE(source, '') NOT IN ('local_scan', 'scan')"


_SQL_IS_SCAN_SOURCE = "COALESCE(source, '') IN ('local_scan', 'scan')"


class _CachedLocalMapsMarker:
    """本地 NFO 分类缓存命中时的轻量载体。

    ⚠️ 不能复用 _LocalNfoMaps：它的 skip_rels / classified_codes 是**只读
    property**（由 complete_rels/soft_rels/hard 推导），__slots__ 里也没有这两个
    名字，直接赋值会 AttributeError。缓存里存的本来就是推导后的集合，用这个
    载体直接带出来即可。
    """

    __slots__ = ("skip_rels", "classified_codes", "done_n", "soft_n", "fail_n")

    def __init__(
        self,
        skip_rels: set[str],
        classified_codes: set[str],
        done_n: int,
        soft_n: int,
        fail_n: int,
    ) -> None:
        self.skip_rels = skip_rels
        self.classified_codes = classified_codes
        self.done_n = done_n
        self.soft_n = soft_n
        self.fail_n = fail_n


def _local_nfo_maps_cache_get(
    region: str,
) -> tuple[set[str], set[str], int, int, int] | None:
    hit = _enrich._local_nfo_maps_cache.get(region)
    if not hit:
        return None
    if time.monotonic() - float(hit[0]) >= _enrich._LOCAL_NFO_MAPS_TTL_SEC:
        _enrich._local_nfo_maps_cache.pop(region, None)
        return None
    return set(hit[1]), set(hit[2]), int(hit[3]), int(hit[4]), int(hit[5])


def _local_nfo_maps_cache_put(region: str, maps: Any) -> None:
    try:
        if len(_enrich._local_nfo_maps_cache) >= _enrich._LOCAL_NFO_MAPS_CACHE_MAX:
            oldest = min(_enrich._local_nfo_maps_cache.items(), key=lambda kv: kv[1][0])[0]
            _enrich._local_nfo_maps_cache.pop(oldest, None)
        _enrich._local_nfo_maps_cache[region] = (
            time.monotonic(),
            set(getattr(maps, "skip_rels", ()) or ()),
            set(getattr(maps, "classified_codes", ()) or ()),
            int(getattr(maps, "done_n", 0) or 0),
            int(getattr(maps, "soft_n", 0) or 0),
            int(getattr(maps, "fail_n", 0) or 0),
        )
    except Exception:  # noqa: BLE001
        pass


def _region_local_dirs(root: Path, region: str) -> list[Path]:
    """刮削库根下该分区的本地目录（日本有码 / japan_censored …）。

    FC2 区一次扫整区：其下旧 FC2 / FC2-PPV 前缀夹均进队；新落盘一律 FC2/FC2/FC2-*。
    """
    from app.scrap_library.embed import _region_match_values

    out: list[Path] = []
    seen: set[str] = set()
    for name in _region_match_values(region):
        key = str(name or "").strip()
        if not key or key.casefold() in seen:
            continue
        seen.add(key.casefold())
        p = (root / key).resolve()
        try:
            p.relative_to(root.resolve())
        except ValueError:
            continue
        if p.is_dir():
            out.append(p)
    return out


def _local_scan_workers() -> int:
    """清空·扫描分类线程。1G 容器不要按宿主机核数开到 24。"""
    from app.core.container_budget import io_threads, memory_class

    if memory_class() == "host":
        return max(4, min(24, (os.cpu_count() or 8) * 2))
    return io_threads(floor=2, host_max=4)


def _folder_gaps_cache_cap() -> int:
    from app.core.container_budget import memory_class

    kind = memory_class()
    if kind == "tight":
        return 4_000
    if kind == "small":
        return 20_000
    return _enrich._FOLDER_GAPS_CACHE_CAP


_SCAN_STREAM_FLUSH = 800


def _folder_gaps_stamp(
    folder: "Path", nfo: "Path | None", posters: list
) -> tuple[Any, ...]:
    """失效指纹：目录 mtime（覆盖目录内增删文件）+ NFO/海报的 mtime/size。

    海报被"覆盖写"不改目录 mtime，但会改海报自身 mtime/size → 仍能失效。
    """
    try:
        dm = int(folder.stat().st_mtime_ns or 0)
    except OSError:
        dm = 0
    parts: list[Any] = [dm, *_enrich_sidecar._file_stamp(nfo)]
    for p in posters:
        parts.extend(_enrich_sidecar._file_stamp(p))
    return tuple(parts)


def _local_folder_gaps(folder: Path) -> tuple[str, list[str]]:
    """只读本地 NFO + poster，算出与增量 kinds 对齐的缺口（不看向量库）。

    ⚠️ 这是启动/续跑路径上的固定开销大头：`_local_nfo_gap_maps` 要对整个分区
    逐目录跑，每目录一次 _enrich.parse_nfo（读解析 XML）+ 一次空白封面判定（读图），
    实测 1.1ms/目录（冷缓存 9.4ms/目录），有码区 1349 个目录 ≈ 1.5s。
    按 (目录 mtime, NFO/海报 mtime+size) 缓存结果 → 命中只需几次 stat。
    """
    from app.scrap_library import embed as embed_svc

    code_name = str(folder.name or "").strip().upper()
    nfo = _enrich_detail._find_nfo(folder)
    posters: list[Path] = []
    if nfo and nfo.is_file():
        for name in ("poster.jpg", "poster.jpeg", "poster.png", "poster.webp"):
            p = folder / name
            if p.is_file():
                posters.append(p)
    ckey = str(folder)
    stamp = _folder_gaps_stamp(folder, nfo, posters)
    with _enrich._folder_gaps_cache_lock:
        hit = _enrich._folder_gaps_cache.get(ckey)
        if hit is not None and hit[0] == stamp:
            return hit[1][0], list(hit[1][1])

    def _remember(code_u: str, gaps: list[str]) -> tuple[str, list[str]]:
        with _enrich._folder_gaps_cache_lock:
            if len(_enrich._folder_gaps_cache) > _folder_gaps_cache_cap():
                _enrich._folder_gaps_cache.clear()
            _enrich._folder_gaps_cache[ckey] = (stamp, (code_u, list(gaps)))
        return code_u, gaps

    if not nfo or not nfo.is_file():
        return _remember(
            code_name,
            ["no_local", "no_media", "no_actress", "no_studio", "no_plot", "thin_title"],
        )
    meta = _enrich.parse_nfo(nfo) or {}
    code_u = str(meta.get("num") or code_name).strip().upper() or code_name
    title = str(meta.get("title") or "").strip()
    plot = str(meta.get("plot") or meta.get("overview") or "").strip()
    actors = [
        str(a).strip()
        for a in (meta.get("actors") or [])
        if str(a or "").strip()
    ]
    studio = str(meta.get("studio") or meta.get("maker") or "").strip()
    cover_url = str(meta.get("cover_url") or "").strip()

    poster_ok = False
    for p in posters:
        try:
            if not embed_svc._is_blank_cover_file(p):  # noqa: SLF001
                poster_ok = True
                break
        except Exception:  # noqa: BLE001
            poster_ok = True
            break

    gaps: list[str] = []
    if not poster_ok:
        gaps.append("no_local")
    if not cover_url:
        gaps.append("no_media")
    if not actors:
        gaps.append("no_actress")
    if not studio:
        gaps.append("no_studio")
    if len(plot) < 12:
        gaps.append("no_plot")
    if (not title) or len(title) < 4 or title.casefold() == code_u.casefold():
        gaps.append("thin_title")
    elif _enrich_text._title_lacks_zh(title, code_u):
        gaps.append("no_zh_title")
    return _remember(code_u, gaps)


def iter_local_incomplete_items(
    *,
    region: str,
    limit: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """扫描本地分区 NFO：返回 (缺口样例列表, 缺口总数)。limit<=0 表示样例不截断。"""
    from app.scrap_library import embed as embed_svc

    rid = _enrich._queue_log_region(region)
    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root")).resolve()
    dirs = _region_local_dirs(root, rid or region)
    if not dirs:
        return [], 0

    lim = int(limit or 0)
    samples: list[dict[str, Any]] = []
    total = 0
    seen: set[str] = set()

    for base in dirs:
        # PREFIX/CODE/*.nfo → nfo.parent 即番号目录
        try:
            nfo_iter = base.rglob("*.nfo")
        except Exception:  # noqa: BLE001
            continue
        for nfo in nfo_iter:
            folder = nfo.parent
            try:
                rel = folder.relative_to(root).as_posix()
            except ValueError:
                continue
            if rel in seen:
                continue
            seen.add(rel)
            code_u, gaps = _local_folder_gaps(folder)
            if not gaps:
                continue
            total += 1
            if lim > 0 and len(samples) >= lim:
                continue
            samples.append(
                {
                    "itemId": rel,
                    "code": code_u,
                    "gaps": gaps,
                    "rel_path": rel,
                    "relPath": rel,
                    "region": rid or region,
                    "status": "pending",
                }
            )
    return samples, total


def _local_status_item(
    *,
    rel: str,
    code: str,
    gaps: list[str],
    region: str,
    kind: str,
    root: Path | None = None,
    merge_sidecar: bool = True,
    enrich_detail: bool = True,
) -> dict[str, Any]:
    """本地分类 → 可入库队列行。

    enrich_detail=False：扫描全量写入用，只写状态/番号，不读盘 NFO
    （10 万+ 行时读盘会卡在「写入分类队列 · 4,000/109,xxx」数十分钟）。
    详情页仍走 _enrich._backfill_queue_item_detail 按需补全。
    """
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
        item["error"] = _enrich_retry._format_soft_ok_error(labels or ["标题"])
        item["gapsAfter"] = soft_gaps
    else:
        block = [g for g in gaps if g in _enrich._SUCCESS_BLOCK_GAPS] or list(gaps or [])
        labels = _enrich_retry._gap_labels(block)
        item["status"] = "fail"
        item["partialOk"] = False
        item["error"] = f"仍缺:{' · '.join(labels)}" if labels else "仍缺:封面"
    if not enrich_detail:
        return item
    if not merge_sidecar:
        # 仍附上本地 NFO 字段，避免详情「标题/封面 · 无」
        try:
            from app.scrap_library import embed as embed_svc

            base = root
            if base is None:
                settings = embed_svc.get_settings()
                base = embed_svc.resolve_root(settings.get("root")).resolve()
            fol = (base / rel).resolve()
            fol.relative_to(base)
            if fol.is_dir():
                local_detail, fields, local_ok = _enrich_detail._detail_from_local_folder(
                    fol, code=code_u
                )
                item["fields"] = fields
                if local_detail.get("detailTitle"):
                    item["detailTitle"] = local_detail["detailTitle"]
                item["posterDownloaded"] = bool(local_ok)
        except Exception:  # noqa: BLE001
            pass
        return item
    # 若番号目录已有 enrich.log，合并源耗时/字段（清空扫描后仍可展示）
    try:
        from app.scrap_library import embed as embed_svc

        base = root
        if base is None:
            settings = embed_svc.get_settings()
            base = embed_svc.resolve_root(settings.get("root")).resolve()
        fol = (base / rel).resolve()
        try:
            fol.relative_to(base)
        except ValueError:
            fol = None  # type: ignore[assignment]
        if fol is not None and fol.is_dir():
            item = _enrich_merge._merge_enrich_sidecar_into_item(item, folder=fol, region=rid)
            # 无刮削 sidecar 时，用本地 NFO 填字段表（转移入库）
            has_src_fields = isinstance(item.get("fields"), list) and any(
                isinstance(f, dict) and str(f.get("source") or "").strip()
                for f in (item.get("fields") or [])
            )
            if not has_src_fields:
                local_detail, fields, local_ok = _enrich_detail._detail_from_local_folder(
                    fol, code=code_u
                )
                item["fields"] = fields
                if local_detail.get("detailTitle") and not str(
                    item.get("detailTitle") or ""
                ).strip():
                    item["detailTitle"] = local_detail["detailTitle"]
                if local_ok:
                    item["posterDownloaded"] = True
    except Exception:  # noqa: BLE001
        pass
    return item


class _LocalNfoMaps:
    """一次磁盘扫描分类结果（全量候选 + 预览样例）。"""

    __slots__ = (
        "complete_rels",
        "soft_rels",
        "hard",
        "done_cands",
        "soft_cands",
        "fail_cands",
        "done_samples",
        "soft_samples",
        "fail_samples",
        "done_n",
        "soft_n",
        "fail_n",
        "stream_written",
    )

    def __init__(self) -> None:
        self.complete_rels: set[str] = set()
        self.soft_rels: set[str] = set()
        self.hard: dict[str, dict[str, Any]] = {}
        # 全量轻量候选 (rel, code, gaps) — 供队列表翻页写入
        self.done_cands: list[tuple[str, str, list[str]]] = []
        self.soft_cands: list[tuple[str, str, list[str]]] = []
        self.fail_cands: list[tuple[str, str, list[str]]] = []
        # 带 sidecar 的预览样例（条数受 sample_cap 限制）
        self.done_samples: list[dict[str, Any]] = []
        self.soft_samples: list[dict[str, Any]] = []
        self.fail_samples: list[dict[str, Any]] = []
        self.done_n = 0
        self.soft_n = 0
        self.fail_n = 0
        self.stream_written = False

    @property
    def skip_rels(self) -> set[str]:
        """本地已分类（成功/软成功/失败）：向量骨架入未处理时应排除。"""
        return self.complete_rels | self.soft_rels | set(self.hard.keys())

    @property
    def classified_codes(self) -> set[str]:
        """本地已分类番号（大写），供与向量骨架 code 对齐排除。"""
        out: set[str] = set()
        for rel in self.skip_rels:
            base = str(rel or "").replace("\\", "/").rstrip("/").split("/")[-1]
            cu = base.strip().upper()
            if cu:
                out.add(cu)
        for item in self.hard.values():
            if not isinstance(item, dict):
                continue
            cu = str(item.get("code") or "").strip().upper()
            if cu:
                out.add(cu)
        return out


def _local_nfo_gap_maps(
    *,
    region: str,
    sample_cap: int = 500,
    report_progress: bool = False,
    workers: int | None = None,
    stream_write_region: str = "",
) -> _LocalNfoMaps:
    """一次扫本地分区：已齐 / 软成功 / 硬缺口（多线程分类）。

    全量候选写入 maps.*_cands；*_samples 仅保留 sample_cap 条富样例供预览。
    sample_cap<=0 时富样例默认取边扫预览上限。
    stream_write_region：边分类边写入该区队列表（与扫盘并行，仍为全量）。
    """
    import queue as queue_mod

    from app.scrap_library import embed as embed_svc

    rid = _enrich._queue_log_region(region)
    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root")).resolve()
    dirs = _region_local_dirs(root, rid or region)
    out = _LocalNfoMaps()
    if not dirs:
        return out

    scan_cap = _local_scan_workers()
    n_workers = max(1, min(scan_cap, int(workers or scan_cap)))
    total_est = 0
    if report_progress:
        try:
            total_est = _enrich._fresh_vector_library_total(rid or region, force=True)
        except Exception:  # noqa: BLE001
            total_est = 0
        _enrich._set_queue_scan_progress(
            region=rid or region,
            stage="disk",
            label=f"扫描本地 NFO…（{n_workers} 线程）",
            scanned=0,
            total=total_est,
            done=0,
            soft=0,
            fail=0,
            pending=total_est,
            notify=True,
        )

    rich_cap = (
        max(1, int(sample_cap))
        if int(sample_cap or 0) > 0
        else _enrich_queue._QUEUE_SCAN_SAMPLE_CAP
    )
    done_cands = out.done_cands
    soft_cands = out.soft_cands
    fail_cands = out.fail_cands
    last_report = 0
    from app.core.container_budget import memory_class as _mem_class

    inflight_limit = n_workers * 4
    if _mem_class() == "host":
        inflight_limit = max(inflight_limit, 64)

    stream_rid = _enrich._queue_log_region(stream_write_region) if stream_write_region else ""
    stream_q: queue_mod.Queue | None = None
    stream_thread: threading.Thread | None = None
    stream_err: list[BaseException] = []
    stream_written_n = [0]
    flush_n = max(200, int(_SCAN_STREAM_FLUSH or 800))

    def _flush_stream_batch(
        batch: list[tuple[str, tuple[str, str, list[str]]]],
    ) -> None:
        if not batch or not stream_rid:
            return
        rows: list[dict[str, Any]] = []
        for kind, trip in batch:
            rel, code_u, gaps = trip
            rows.append(
                _local_status_item(
                    rel=rel,
                    code=code_u,
                    gaps=gaps,
                    region=stream_rid,
                    kind=kind,
                    root=root,
                    merge_sidecar=False,
                    enrich_detail=False,
                )
            )
        if rows:
            _enrich._queue_log_insert_many(stream_rid, rows)
            stream_written_n[0] += len(rows)
            if report_progress and (
                stream_written_n[0] < len(rows) + 5
                or stream_written_n[0] % 2000 < len(rows)
            ):
                _enrich._set_queue_scan_progress(
                    region=rid or region,
                    stage="disk",
                    label=(
                        f"扫描并写入 · 已分类 {out.done_n + out.soft_n + out.fail_n:,}"
                        f" · 已入库 {stream_written_n[0]:,}"
                        f" · 成功 {out.done_n:,} · 软成功 {out.soft_n:,}"
                        f" · 失败 {out.fail_n:,}"
                    ),
                    scanned=out.done_n + out.soft_n + out.fail_n,
                    total=max(total_est, out.done_n + out.soft_n + out.fail_n),
                    done=out.done_n,
                    soft=out.soft_n,
                    fail=out.fail_n,
                    pending=max(
                        0,
                        int(total_est or 0)
                        - int(out.done_n or 0)
                        - int(out.soft_n or 0)
                        - int(out.fail_n or 0),
                    ),
                    notify=True,
                )

    if stream_rid:
        stream_q = queue_mod.Queue(maxsize=max(flush_n * 4, 4000))

        def _stream_writer() -> None:
            buf: list[tuple[str, tuple[str, str, list[str]]]] = []
            try:
                while True:
                    try:
                        item = stream_q.get(timeout=0.25)
                    except queue_mod.Empty:
                        if buf:
                            _flush_stream_batch(buf)
                            buf = []
                        continue
                    if item is None:
                        if buf:
                            _flush_stream_batch(buf)
                        break
                    buf.append(item)
                    if len(buf) >= flush_n:
                        _flush_stream_batch(buf)
                        buf = []
            except BaseException as e:  # noqa: BLE001
                stream_err.append(e)
                log.warning(
                    "stream write enrich queue failed region=%s: %s",
                    stream_rid,
                    e,
                )

        stream_thread = threading.Thread(
            target=_stream_writer,
            name="enrich-scan-stream-write",
            daemon=True,
        )
        stream_thread.start()

    def _work(rel: str, folder: Path) -> tuple[str, str, list[str]]:
        code_u, gaps = _local_folder_gaps(folder)
        return rel, code_u, list(gaps)

    def _absorb(rel: str, code_u: str, gaps: list[str]) -> None:
        nonlocal last_report
        kind = _enrich_detail._classify_disk_gaps(gaps)
        gaps_l = list(gaps or [])
        if kind == "done":
            out.complete_rels.add(rel)
            out.done_n += 1
            trip = (rel, code_u, [])
            done_cands.append(trip)
            if report_progress and out.done_n <= _enrich_queue._QUEUE_SCAN_SAMPLE_CAP:
                _enrich_queue._queue_scan_add_sample(
                    "done",
                    _enrich_queue._queue_scan_preview_item(
                        rel=rel,
                        code=code_u,
                        gaps=[],
                        region=rid or region,
                        kind="done",
                    ),
                )
        elif kind == "soft":
            out.soft_rels.add(rel)
            out.soft_n += 1
            trip = (rel, code_u, gaps_l)
            soft_cands.append(trip)
            if report_progress and out.soft_n <= _enrich_queue._QUEUE_SCAN_SAMPLE_CAP:
                _enrich_queue._queue_scan_add_sample(
                    "soft",
                    _enrich_queue._queue_scan_preview_item(
                        rel=rel,
                        code=code_u,
                        gaps=gaps_l,
                        region=rid or region,
                        kind="soft",
                    ),
                )
        else:
            out.fail_n += 1
            out.hard[rel] = {
                "itemId": rel,
                "code": code_u,
                "gaps": gaps_l,
                "rel_path": rel,
                "relPath": rel,
                "region": rid or region,
                "status": "pending",
            }
            trip = (rel, code_u, gaps_l)
            fail_cands.append(trip)
            if report_progress and out.fail_n <= _enrich_queue._QUEUE_SCAN_SAMPLE_CAP:
                _enrich_queue._queue_scan_add_sample(
                    "fail",
                    _enrich_queue._queue_scan_preview_item(
                        rel=rel,
                        code=code_u,
                        gaps=gaps_l,
                        region=rid or region,
                        kind="fail",
                    ),
                )
        if stream_q is not None:
            try:
                stream_q.put((kind, trip), timeout=30)
            except Exception:  # noqa: BLE001
                pass
        n = out.done_n + out.soft_n + out.fail_n
        if report_progress and (n - last_report >= 400 or n == 1):
            last_report = n
            tot = max(total_est, n)
            written_tip = (
                f" · 已入库 {stream_written_n[0]:,}" if stream_q is not None else ""
            )
            _enrich._set_queue_scan_progress(
                region=rid or region,
                stage="disk",
                label=(
                    f"扫描本地 · {n:,}"
                    + (f"/{tot:,}" if tot > n else "")
                    + written_tip
                    + f" · 成功 {out.done_n:,} · 软成功 {out.soft_n:,} · 失败 {out.fail_n:,}"
                ),
                scanned=n,
                total=tot,
                done=out.done_n,
                soft=out.soft_n,
                fail=out.fail_n,
                notify=True,
            )

    if report_progress:
        _enrich._set_queue_scan_progress(
            region=rid or region,
            stage="disk",
            label=f"枚举番号目录…（{n_workers} 线程）",
            notify=True,
        )
    folder_jobs = _enrich_detail._collect_nfo_folders_parallel(
        list(dirs), root, workers=min(16, n_workers)
    )
    if report_progress and folder_jobs:
        total_est = max(total_est, len(folder_jobs))
        _enrich._set_queue_scan_progress(
            region=rid or region,
            stage="disk",
            label=f"分类本地 NFO… {len(folder_jobs):,} 个（{n_workers} 线程）",
            scanned=0,
            total=total_est,
            notify=True,
        )

    pending: set[Any] = set()
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        for rel, folder in folder_jobs:
            while len(pending) >= inflight_limit:
                done_set, pending = wait(pending, return_when=FIRST_COMPLETED)
                for fut in done_set:
                    try:
                        rel_r, code_u, gaps = fut.result()
                    except Exception:  # noqa: BLE001
                        continue
                    _absorb(rel_r, code_u, gaps)
            pending.add(pool.submit(_work, rel, folder))
        while pending:
            done_set, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done_set:
                try:
                    rel_r, code_u, gaps = fut.result()
                except Exception:  # noqa: BLE001
                    continue
                _absorb(rel_r, code_u, gaps)

    if stream_q is not None and stream_thread is not None:
        try:
            stream_q.put(None, timeout=60)
        except Exception:  # noqa: BLE001
            pass
        stream_thread.join(timeout=900)
        if not stream_err and stream_written_n[0] > 0:
            out.stream_written = True
        elif stream_err:
            log.warning(
                "stream write incomplete region=%s written=%s err=%s",
                stream_rid,
                stream_written_n[0],
                stream_err[0],
            )

    def _mk_sample(
        trip: tuple[str, str, list[str]], kind: str
    ) -> dict[str, Any]:
        rel, code_u, gaps = trip
        return _local_status_item(
            rel=rel,
            code=code_u,
            gaps=gaps,
            region=rid or region,
            kind=kind,
            root=root,
            merge_sidecar=True,
        )

    sample_jobs: list[tuple[str, tuple[str, str, list[str]]]] = []
    for t in done_cands[:rich_cap]:
        sample_jobs.append(("done", t))
    for t in soft_cands[:rich_cap]:
        sample_jobs.append(("soft", t))
    for t in fail_cands[:rich_cap]:
        sample_jobs.append(("fail", t))
    if sample_jobs:
        sw = max(2, min(n_workers, 12))
        with ThreadPoolExecutor(max_workers=sw) as pool:
            futs = [pool.submit(_mk_sample, trip, kind) for kind, trip in sample_jobs]
            for i, fut in enumerate(futs):
                try:
                    item = fut.result()
                except Exception:  # noqa: BLE001
                    kind, trip = sample_jobs[i]
                    item = _local_status_item(
                        rel=trip[0],
                        code=trip[1],
                        gaps=trip[2],
                        region=rid or region,
                        kind=kind,
                        root=root,
                        merge_sidecar=False,
                    )
                kind = sample_jobs[i][0]
                if kind == "done":
                    out.done_samples.append(item)
                elif kind == "soft":
                    out.soft_samples.append(item)
                else:
                    out.fail_samples.append(item)

    if report_progress:
        n = out.done_n + out.soft_n + out.fail_n
        written_tip = (
            f" · 已入库 {stream_written_n[0]:,}" if stream_written_n[0] else ""
        )
        _enrich._set_queue_scan_progress(
            region=rid or region,
            stage="disk",
            label=(
                f"本地分类完成 · {n:,}{written_tip}"
                f" · 成功 {out.done_n:,} · 软成功 {out.soft_n:,} · 失败 {out.fail_n:,}"
            ),
            scanned=n,
            total=max(total_est, n),
            done=out.done_n,
            soft=out.soft_n,
            fail=out.fail_n,
            notify=True,
        )
    return out


def _rebuild_region_queue_from_scan(
    *,
    region: str,
    local_maps: _LocalNfoMaps,
    vector_total: int,
) -> dict[str, int]:
    """扫描完成后原子重建本区队列表：清空 → 本地分类 → 向量差集 pending。"""
    rid = _enrich._queue_log_region(region)
    empty = {"pending": 0, "running": 0, "done": 0, "soft": 0, "fail": 0}
    if not rid:
        return empty
    _enrich_queue._clear_queue_log(region=rid)
    _enrich._invalidate_classified_skip_cache(rid)
    _enrich._counts_cache.pop(rid, None)
    _enrich._demoted_false_dones.discard(rid)
    _enrich._pending_backfill_done.discard(rid)

    _enrich._set_queue_scan_progress(
        region=rid,
        stage="write",
        label="写入成功 / 软成功 / 失败…",
        done=int(local_maps.done_n or 0),
        soft=int(local_maps.soft_n or 0),
        fail=int(local_maps.fail_n or 0),
        scanned=0,
        total=max(
            int(local_maps.done_n or 0)
            + int(local_maps.soft_n or 0)
            + int(local_maps.fail_n or 0),
            1,
        ),
        notify=True,
    )
    _enrich_queue._queue_log_insert_local_status_samples(rid, local_maps, write_cap=0)
    _replace_pending_from_vector(
        region=rid,
        local_maps=local_maps,
        vector_total=vector_total,
        clear_pending=False,
    )
    _enrich_history._recover_done_from_enrich_logs(rid)
    db_counts, db_ok = _enrich_queue._queue_log_status_counts_db_ex(rid)
    _enrich._invalidate_classified_skip_cache(rid)
    if db_ok:
        _enrich_status._set_local_status_totals(
            rid,
            done=int(db_counts.get("done") or 0),
            soft=int(db_counts.get("soft") or 0),
            fail=int(db_counts.get("fail") or 0),
            total=int(vector_total or 0) or None,
        )
        return dict(db_counts)
    return {
        "pending": 0,
        "running": 0,
        "done": int(local_maps.done_n or 0),
        "soft": int(local_maps.soft_n or 0),
        "fail": int(local_maps.fail_n or 0),
    }


def _replace_pending_from_vector(
    *,
    region: str,
    local_maps: _LocalNfoMaps,
    vector_total: int,
    preview_cap: int = 500,
    clear_pending: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """用最新向量库差集整表重写未处理队列（不只留样例）。

    未处理 = 向量库有番号且本地未归入成功/软成功/失败。
    一次轻量 SELECT（不含 source_text）+ 内存差集，避免 OFFSET 分页拖到数分钟。
    """
    from app.scrap_library import embed as embed_svc
    from app.scrap_library.embed_catalog import SKELETON_SHA_PREFIX

    rid = _enrich._queue_log_region(region)
    if not rid:
        return [], 0
    skip_rels = set(local_maps.skip_rels)
    skip_codes = {str(c or "").strip().upper() for c in local_maps.classified_codes if c}
    classified_n = (
        int(local_maps.done_n or 0)
        + int(local_maps.soft_n or 0)
        + int(local_maps.fail_n or 0)
    )
    est = max(0, int(vector_total or 0) - classified_n)
    t0 = time.monotonic()
    _enrich._set_queue_scan_progress(
        region=rid,
        stage="pending",
        label="对照最新向量库生成未处理…",
        done=int(local_maps.done_n or 0),
        soft=int(local_maps.soft_n or 0),
        fail=int(local_maps.fail_n or 0),
        pending=est,
        scanned=0,
        total=max(int(vector_total or 0), 1),
        notify=True,
    )

    pending_rows: list[dict[str, Any]] = []
    scanned_vec = 0
    try:
        region_sql, region_params = embed_svc._quality_region_sql(rid)
        pool = get_meta_pool()
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT item_id, code, rel_path, content_sha
                  FROM {embed_svc.TABLE}
                 WHERE coalesce(trim(code), '') <> ''
                   {region_sql}
                """,
                region_params,
            )
            raw_rows = cur.fetchall() or []
        scanned_vec = len(raw_rows)
        seen: set[str] = set()
        for raw in raw_rows:
            if isinstance(raw, dict):
                iid = str(raw.get("item_id") or "").strip()
                code_u = str(raw.get("code") or "").strip().upper()
                rel = str(raw.get("rel_path") or "").strip().replace("\\", "/")
                sha = str(raw.get("content_sha") or "")
            else:
                iid = str(raw[0] or "").strip()
                code_u = str(raw[1] or "").strip().upper()
                rel = str(raw[2] or "").strip().replace("\\", "/")
                sha = str(raw[3] or "")
            rel = rel or iid
            key = iid or rel or code_u
            if not key or key in seen:
                continue
            if (rel and rel in skip_rels) or (iid and iid in skip_rels):
                continue
            if code_u and code_u in skip_codes:
                continue
            seen.add(key)
            shell = sha.startswith(f"{SKELETON_SHA_PREFIX}:")
            gaps = (
                list(embed_svc._SHELL_GAPS)
                if shell
                else list(_enrich._ENRICH_KINDS)
            )
            pending_rows.append(
                {
                    "itemId": iid or rel or code_u,
                    "code": code_u,
                    "gaps": gaps,
                    "rel_path": rel or iid,
                    "relPath": rel or iid,
                    "region": rid,
                    "status": "pending",
                    "shell": shell,
                }
            )
        _enrich._set_queue_scan_progress(
            region=rid,
            stage="pending",
            label=(
                f"对照向量库 · 差集 {len(pending_rows):,}"
                f" · {int((time.monotonic() - t0) * 1000)}ms"
            ),
            done=int(local_maps.done_n or 0),
            soft=int(local_maps.soft_n or 0),
            fail=int(local_maps.fail_n or 0),
            pending=len(pending_rows) or est,
            scanned=scanned_vec,
            total=max(int(vector_total or 0), scanned_vec, 1),
            notify=True,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("pending vector light-diff failed region=%s: %s", rid, e)

    if clear_pending:
        _enrich_queue._queue_log_clear_pending(rid)
    if pending_rows:
        _enrich._queue_log_insert_many(rid, pending_rows)
    _enrich._counts_cache.pop(rid, None)
    n = len(pending_rows)
    _enrich._set_queue_scan_progress(
        region=rid,
        stage="pending",
        label=f"未处理已按最新向量库写入 {n:,}",
        done=int(local_maps.done_n or 0),
        soft=int(local_maps.soft_n or 0),
        fail=int(local_maps.fail_n or 0),
        pending=n,
        scanned=scanned_vec,
        total=max(int(vector_total or 0), scanned_vec, 1),
        notify=True,
    )
    cap = max(0, int(preview_cap or 0))
    preview = pending_rows[:cap] if cap else pending_rows[:500]
    return preview, n


def _hot_prefixes_for_region(region: str, *, max_n: int = 80) -> list[str]:
    """空壳降权用：本地已有前缀目录 + 近期成功前缀（高优切片）。"""
    from app.scrap_library import embed as embed_svc

    rid = _enrich._queue_log_region(region)
    out: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        p = str(raw or "").strip().upper()
        if not p or p in seen:
            return
        seen.add(p)
        out.append(p)

    try:
        settings = embed_svc.get_settings()
        root = embed_svc.resolve_root(settings.get("root")).resolve()
        for base in _region_local_dirs(root, rid or region):
            try:
                for child in base.iterdir():
                    if child.is_dir() and not child.name.startswith("_"):
                        _add(child.name)
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        pass

    # 近期成功前缀（队列表）
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT code FROM enrich_queue_log
                WHERE region=? AND status='done'
                ORDER BY id DESC
                LIMIT 200
                """,
                (rid,),
            ).fetchall()
        for r in rows or []:
            d = dict(r) if isinstance(r, dict) else {}
            code = str(d.get("code") or "").strip().upper()
            if "-" in code:
                _add(code.split("-", 1)[0])
            elif code:
                # FC2 等无横杠：取字母前缀
                m = re.match(r"^([A-Z]+)", code)
                if m:
                    _add(m.group(1))
    except Exception:  # noqa: BLE001
        pass

    return out[: max(1, int(max_n or 80))]


def scan_enrich_queue(
    *,
    region: str,
    limit: int = 0,
) -> dict[str, Any]:
    """打开日志页：重建队列（不启动刮削）。

    增量：向量全部番号 − 本地成功/软成功/失败 → 未处理（含本地已删回填）；
    覆盖：本地分区全部 NFO 进未处理。
    每次扫描强制把「成功/失败但本地已删」回滚为 pending。
    """
    rid = _enrich._queue_log_region(region)
    empty = {
        "ok": False,
        "scanned": False,
        "region": rid or None,
        "counts": {"pending": 0, "running": 0, "done": 0, "soft": 0, "fail": 0},
        "items": [],
        "scannedN": 0,
        "listedN": 0,
        "pendingTotal": 0,
        "prunedN": 0,
    }
    if not rid:
        empty["error"] = "region required"
        return empty

    with _enrich._enrich_lock:
        running = bool(_enrich._enrich_job.get("running"))
        cur_reg = str(_enrich._enrich_job.get("currentRegion") or "").strip()
    if running and _enrich_history._canonical_enrich_log_region(cur_reg) == rid:
        out = _enrich.load_queue_log(region=rid, status="pending", limit=200)
        out["ok"] = True
        out["scanned"] = False
        out["reason"] = "running"
        out["scannedN"] = int((out.get("counts") or {}).get("pending") or 0)
        out["listedN"] = len(out.get("items") or [])
        out["pendingTotal"] = out["scannedN"]
        out["prunedN"] = 0
        return out

    from app.scrap_library.enrich_strategy import get_strategy

    # 扫描只落盘队首样例；未处理列表用虚拟翻页（向量 − 已分类），打开不卡
    _SCAN_WRITE = 500
    strat = get_strategy()
    mode = str(strat.get("fillMode") or "incremental").lower()
    overwrite = mode in {"overwrite", "cover", "force", "replace", "full"}
    fetch_lim = int(limit or 0)
    if fetch_lim <= 0:
        fetch_lim = 0
    else:
        fetch_lim = max(1, min(_SCAN_WRITE, fetch_lim))

    # 每次重扫强制回滚：本地已删的 done/fail → pending（不限频）
    try:
        _enrich._demoted_false_dones.discard(rid)
        demoted_scan = _enrich_queue._queue_log_demote_false_dones(rid)
        _enrich._demoted_false_dones.add(rid)
        if demoted_scan:
            log.info(
                "scan demote missing-local region=%s n=%s", rid, demoted_scan
            )
    except Exception as e:  # noqa: BLE001
        log.warning("scan demote failed region=%s: %s", rid, e)
        demoted_scan = 0

    skip_done_iids, skip_done_codes = (
        (set(), set()) if overwrite else _enrich_queue._queue_log_done_keys(rid)
    )

    _enrich._pending_backfill_done.discard(rid)
    _enrich._invalidate_classified_skip_cache(rid)

    _enrich._set_queue_scan_progress(
        region=rid,
        stage="start",
        label="开始扫描队列…",
        scanned=0,
        total=0,
        done=0,
        soft=0,
        fail=0,
        notify=True,
    )

    local_maps: _LocalNfoMaps | None = None
    try:
        if overwrite:
            # 覆盖模式：本地全部 NFO 进队（样例写入 + 全量计数）
            # 覆盖 = 用户明确要求「重来一遍」→ 解除两类有界重试的 giveup（封面 / 源故障），
            # 否则已放弃的番号在全量重扫里依然被跳过，用户没有别的办法把它们捞回来。
            _enrich_retry._retry_hint_clear_region(rid)
            from app.scrap_library import embed as embed_svc

            settings = embed_svc.get_settings()
            root = embed_svc.resolve_root(settings.get("root")).resolve()
            dirs = _region_local_dirs(root, rid)
            samples: list[dict[str, Any]] = []
            seen: set[str] = set()
            write_cap = fetch_lim if fetch_lim > 0 else _SCAN_WRITE
            _enrich._set_queue_scan_progress(
                region=rid,
                stage="disk",
                label="覆盖模式 · 扫描本地 NFO…",
                notify=True,
            )
            last_report = 0
            for base in dirs:
                try:
                    nfo_iter = base.rglob("*.nfo")
                except Exception:  # noqa: BLE001
                    continue
                for nfo in nfo_iter:
                    folder = nfo.parent
                    try:
                        rel = folder.relative_to(root).as_posix()
                    except ValueError:
                        continue
                    if rel in seen:
                        continue
                    seen.add(rel)
                    if len(samples) < write_cap:
                        code_u, _gaps = _local_folder_gaps(folder)
                        samples.append(
                            {
                                "itemId": rel,
                                "code": code_u,
                                "gaps": list(_enrich._ENRICH_KINDS),
                                "rel_path": rel,
                                "relPath": rel,
                                "region": rid,
                                "status": "pending",
                            }
                        )
                    n = len(seen)
                    if n - last_report >= 200 or n == 1:
                        last_report = n
                        _enrich._set_queue_scan_progress(
                            region=rid,
                            stage="disk",
                            label=f"覆盖扫描 · 已发现 {n:,} 个番号",
                            scanned=n,
                            total=n,
                            notify=True,
                        )
            pending_total = len(seen)
            rows = samples
            source = "local_nfo_overwrite"
        else:
            write_cap = fetch_lim if fetch_lim > 0 else _SCAN_WRITE
            # ⚠️ 禁止在扫盘**前**清 local_scan 分类行（原实现如此 + 边扫边写）。
            # 扫盘要数分钟，期间任何中断（切页 / 暂停 / 进程重启）都会先把该区
            # 全部分类行删掉、只写回一小部分：实测 japan_censored 因此从 10.8 万
            # 行掉到 4,799 行，tip 被留在瞬时值 done=2，后果是
            #   ① 角标「未处理」虚高到 12.9 万（见 _enrich._region_library_progress）；
            #   ② 之后每次开刮都失去库侧分类，只能重跑全盘分类数分钟。
            # 改为「先扫盘、再原子替换」：扫盘阶段只读磁盘、不碰库；扫完统一
            # clear + 全量写入（见下方 stream_written 分支），中断窗口由分钟级
            # 缩到写入的十几秒。代价是失去「边扫边写」的并行度，但换来的是
            # 中断不再毁数据——这个取舍是刻意的。
            local_maps = _local_nfo_gap_maps(
                region=rid,
                sample_cap=write_cap,
                report_progress=True,
            )
            _local_nfo_maps_cache_put(rid, local_maps)
            # 双库对齐：目录有、向量无 → 先建空壳番号行，再算未处理差集
            try:
                from app.scrap_library.embed_catalog import (
                    ensure_region_catalog_skeletons,
                )

                def _skel_prog(p: dict[str, Any]) -> None:
                    label = str(p.get("label") or "同步目录骨架…")
                    _enrich._set_queue_scan_progress(
                        region=rid,
                        stage="skeleton",
                        label=label,
                        done=int(local_maps.done_n or 0),
                        soft=int(local_maps.soft_n or 0),
                        fail=int(local_maps.fail_n or 0),
                        pending=max(
                            0,
                            int(p.get("total") or 0) - int(p.get("done") or 0),
                        ),
                        scanned=int(p.get("done") or 0),
                        total=int(p.get("total") or 0) or None,
                        notify=True,
                    )

                sk = ensure_region_catalog_skeletons(
                    rid, on_progress=_skel_prog
                )
                if int(sk.get("inserted") or 0) or int(sk.get("deleted") or 0):
                    log.info(
                        "scan sync skeletons region=%s inserted=%s deleted=%s total=%s",
                        rid,
                        sk.get("inserted"),
                        sk.get("deleted"),
                        sk.get("total"),
                    )
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "scan ensure skeletons failed region=%s: %s", rid, e
                )
            vector_total = _enrich._fresh_vector_library_total(rid, force=True)
            db_counts = _rebuild_region_queue_from_scan(
                region=rid,
                local_maps=local_maps,
                vector_total=vector_total,
            )
            pending_total = int(db_counts.get("pending") or 0)
            rows = _enrich_status._pending_page_from_vector(rid, offset=0, limit=write_cap)
            source = "vector_all_minus_local"
            local_counts = {
                "done": int(db_counts.get("done") or 0),
                "soft": int(db_counts.get("soft") or 0),
                "fail": int(db_counts.get("fail") or 0),
            }

        seen_q: set[str] = set()
        queue_view: list[dict[str, Any]] = []
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            iid = str(r.get("itemId") or "").strip()
            if not iid or iid in seen_q:
                continue
            code_u = str(r.get("code") or "").strip().upper()
            seen_q.add(iid)
            item: dict[str, Any] = {
                "itemId": iid,
                "code": code_u,
                "gaps": list(r.get("gaps") or []),
                "status": "pending",
            }
            rel = str(r.get("rel_path") or r.get("relPath") or "").strip()
            if rel:
                item["rel_path"] = rel
                item["relPath"] = rel
            queue_view.append(item)

        if overwrite:
            pending_total = len(seen)

        if overwrite:
            _enrich_queue._clear_queue_log(region=rid)
            _enrich._invalidate_classified_skip_cache(rid)
            _enrich._counts_cache.pop(rid, None)
            pruned = 0
            queue_view = _enrich_queue._ensure_queue_log_ids(rid, queue_view)
            recovered = _enrich_history._recover_done_from_enrich_logs(rid)
            local_counts = {"done": 0, "soft": 0, "fail": 0}
            if queue_view:
                _enrich._queue_log_insert_many(rid, queue_view)
            try:
                vector_total = _enrich._fresh_vector_library_total(rid, force=True)
            except Exception:  # noqa: BLE001
                vector_total = 0
            _enrich_status._set_local_status_totals(
                rid,
                done=0,
                soft=0,
                fail=0,
                total=vector_total,
            )
        else:
            pruned = 0
            queue_view = _enrich_queue._ensure_queue_log_ids(rid, queue_view)
            recovered = 0

        out = _enrich.load_queue_log(region=rid, status="pending", limit=200)
        listed = len(queue_view)
        counts = dict(out.get("counts") or {})
        db_counts, db_ok = _enrich_queue._queue_log_status_counts_db_ex(rid)
        if db_ok:
            counts = dict(db_counts)
        elif local_counts.get("done") or local_counts.get("soft") or local_counts.get("fail"):
            counts["done"] = int(local_counts.get("done") or 0)
            counts["soft"] = int(local_counts.get("soft") or 0)
            counts["fail"] = int(local_counts.get("fail") or 0)
            counts["pending"] = int(pending_total)
        out["counts"] = counts
        out["ok"] = True
        out["scanned"] = True
        out["scannedN"] = int(pending_total)
        out["listedN"] = listed
        out["pendingTotal"] = int(pending_total)
        out["prunedN"] = int(pruned or 0)
        out["recoveredDone"] = int(recovered or 0)
        out["demotedN"] = int(demoted_scan or 0)
        # ⚠️ localDone/Soft/Fail 是历史字段名（意为「本地扫描得出的角标」），
        # 前端 `data.localDone ?? counts.done` 会**优先取它**，所以它的值必须
        # 与 counts 同源（库内行数）。若这里回磁盘分类数（109,368），
        # 前端就会拿它覆盖掉 counts.done（102,183），角标又和列表脱节。
        out["localDone"] = int(counts.get("done") or 0)
        out["localSoft"] = int(counts.get("soft") or 0)
        out["localFail"] = int(counts.get("fail") or 0)
        out["localDiskDone"] = int(local_counts.get("done") or 0)
        out["localDiskSoft"] = int(local_counts.get("soft") or 0)
        out["localDiskFail"] = int(local_counts.get("fail") or 0)
        out["mode"] = "overwrite" if overwrite else "incremental"
        out["source"] = source
        out["truncated"] = listed < int(pending_total)
        return out
    finally:
        _enrich_queue._clear_queue_scan_progress()


def _code_search_match(code: str, needle: str) -> bool:
    c = str(code or "").strip().upper().replace(" ", "").replace("　", "")
    n = str(needle or "").strip().upper().replace(" ", "").replace("　", "")
    if not c or not n:
        return False
    return c == n or (len(n) >= 2 and c.startswith(n))


def _lookup_code_from_scan_samples(
    *,
    region: str,
    code_q: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """扫描中内存样例（跨 done/soft/fail，未入库也能搜）。"""
    rid = _enrich._queue_log_region(region)
    needle = (
        str(code_q or "").strip().upper().replace(" ", "").replace("　", "")
    )
    if not rid or not needle:
        return []
    lim = max(1, min(int(limit or 20), 100))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        with _enrich._QUEUE_SCAN_LOCK:
            snap = {
                "done": list(_enrich._QUEUE_SCAN_STATE.get("samplesDone") or []),
                "soft": list(_enrich._QUEUE_SCAN_STATE.get("samplesSoft") or []),
                "fail": list(_enrich._QUEUE_SCAN_STATE.get("samplesFail") or []),
                "region": str(_enrich._QUEUE_SCAN_STATE.get("region") or ""),
                "active": bool(_enrich._QUEUE_SCAN_STATE.get("active")),
            }
        if snap["region"] and snap["region"] != rid:
            return []
        if not (snap["active"] or snap["done"] or snap["soft"] or snap["fail"]):
            return []
        for bucket, rows in (
            ("fail", snap["fail"]),
            ("soft", snap["soft"]),
            ("done", snap["done"]),
        ):
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                code_u = str(raw.get("code") or "").strip().upper()
                if not _code_search_match(code_u, needle):
                    continue
                key = (
                    str(
                        raw.get("itemId")
                        or raw.get("relPath")
                        or raw.get("rel_path")
                        or code_u
                    ).strip()
                )
                if not key or key in seen:
                    continue
                seen.add(key)
                item = dict(raw)
                if bucket == "soft":
                    item["status"] = "done"
                    item["partialOk"] = True
                elif bucket == "done":
                    item["status"] = "done"
                    item["partialOk"] = False
                else:
                    item["status"] = "fail"
                out.append(item)
                if len(out) >= lim:
                    return out
    except Exception:  # noqa: BLE001
        return out
    return out


def _lookup_code_outside_queue_log(
    *,
    region: str,
    code_q: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """队列表未命中时：扫描内存样例 + 本地目录/向量库，跨状态查找番号。"""
    rid = _enrich._queue_log_region(region)
    needle = (
        str(code_q or "").strip().upper().replace(" ", "").replace("　", "")
    )
    if not rid or not needle:
        return []
    lim = max(1, min(int(limit or 20), 100))
    out = _lookup_code_from_scan_samples(region=rid, code_q=needle, limit=lim)
    if out:
        return out
    seen = {
        str(it.get("itemId") or it.get("code") or "").strip() for it in out if it
    }

    # 精确：本地番号目录 → 按缺口归类
    try:
        folder = _enrich_detail._resolve_enrich_folder(region=rid, code=needle)
        if folder is not None:
            settings = embed_svc.get_settings()
            root = embed_svc.resolve_root(settings.get("root")).resolve()
            try:
                rel = folder.relative_to(root).as_posix()
            except ValueError:
                rel = folder.name
            code_u, gaps = _local_folder_gaps(folder)
            kind = _enrich_detail._classify_disk_gaps(gaps)
            item = _local_status_item(
                rel=rel,
                code=code_u or needle,
                gaps=list(gaps or []),
                region=rid,
                kind=kind,
                root=root,
                merge_sidecar=True,
            )
            key = str(item.get("itemId") or item.get("code") or "").strip()
            if key and key not in seen:
                out.append(item)
            if out:
                return out
    except Exception as e:  # noqa: BLE001
        log.debug(
            "code search disk lookup failed region=%s code=%s: %s",
            rid,
            needle,
            e,
        )

    # 向量库：未落盘分类 → 未处理
    try:
        embed_svc.ensure_schema()
        pool = _enrich.get_meta_pool()
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT item_id, region, prefix, code, title, rel_path
                FROM {embed_svc.TABLE}
                WHERE UPPER(code) = %s
                   OR (LENGTH(%s) >= 2 AND UPPER(code) LIKE %s)
                ORDER BY
                  CASE WHEN UPPER(code) = %s THEN 0 ELSE 1 END,
                  CASE WHEN region = %s THEN 0 ELSE 1 END,
                  updated_at DESC NULLS LAST
                LIMIT %s
                """,
                (needle, needle, f"{needle}%", needle, rid, lim),
            )
            rows = cur.fetchall() or []
        for row in rows:
            d = dict(row) if isinstance(row, dict) else {}
            code_u = str(d.get("code") or "").strip().upper()
            if not _code_search_match(code_u, needle):
                continue
            rel = (
                str(d.get("rel_path") or d.get("item_id") or "")
                .replace("\\", "/")
                .strip()
            )
            key = str(d.get("item_id") or rel or code_u).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "itemId": key,
                    "code": code_u,
                    "status": "pending",
                    "gaps": list(_enrich._ENRICH_KINDS),
                    "rel_path": rel,
                    "relPath": rel,
                    "region": rid,
                    "detailTitle": str(d.get("title") or "")[:300],
                    "source": "vector",
                    "error": "待处理",
                }
            )
            if len(out) >= lim:
                break
    except Exception as e:  # noqa: BLE001
        log.debug(
            "code search vector lookup failed region=%s code=%s: %s",
            rid,
            needle,
            e,
        )

    return out
