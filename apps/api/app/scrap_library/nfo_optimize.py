# -*- coding: utf-8 -*-
"""本地 NFO 映射优化：用 code-titles / 演员表 / 标签表 / 片商表修正磁盘 NFO。"""

from __future__ import annotations

import logging
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "progress": None,
    "log": [],
    "result": None,
    "error": None,
}
_hydrated = False
_hydrate_lock = threading.Lock()


def _persist(**extra: Any) -> None:
    try:
        from app.core import job_persist

        with _LOCK:
            payload = {
                "status": (
                    "running"
                    if _job.get("running")
                    else str(extra.get("status") or _job.get("phase") or "idle")
                ),
                "phase": str(_job.get("phase") or ""),
                "progress": dict(_job.get("progress") or {}) or None,
                "log": list(_job.get("log") or [])[-40:],
                "result": _job.get("result"),
                "error": _job.get("error"),
                "running": bool(_job.get("running")),
            }
        for k, v in extra.items():
            payload[k] = v
        if payload.get("running"):
            payload["status"] = "running"
        job_persist.save_job(job_persist.NFO_OPTIMIZE_JOB_KEY, payload)
    except Exception as e:  # noqa: BLE001
        log.warning("persist nfo optimize job failed: %s", e)


def _hydrate(*, force: bool = False) -> dict[str, Any]:
    global _hydrated
    with _hydrate_lock:
        if _hydrated and not force:
            return {}
        _hydrated = True
    try:
        from app.core import job_persist

        raw = job_persist.load_job(job_persist.NFO_OPTIMIZE_JOB_KEY)
        if not raw:
            return {}
        with _LOCK:
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
            if str(raw.get("status") or "") == "running":
                _job["phase"] = "interrupted"
                prog = dict(_job.get("progress") or {})
                prog["label"] = "进程中断 · 可继续"
                _job["progress"] = prog
                raw = dict(raw)
                raw["status"] = "interrupted"
                raw["running"] = False
                job_persist.save_job(job_persist.NFO_OPTIMIZE_JOB_KEY, raw)
        return raw
    except Exception as e:  # noqa: BLE001
        log.warning("hydrate nfo optimize job failed: %s", e)
        return {}


def get_job_status() -> dict[str, Any]:
    _hydrate()
    with _LOCK:
        return {
            "running": bool(_job["running"]),
            "phase": _job.get("phase") or "",
            "progress": _job.get("progress"),
            "log": list(_job.get("log") or [])[-40:],
            "result": _job.get("result"),
            "error": _job.get("error"),
        }


def _log(msg: str) -> None:
    with _LOCK:
        log_list = list(_job.get("log") or [])
        log_list.append(str(msg))
        _job["log"] = log_list[-40:]


def _progress(**kw: Any) -> None:
    with _LOCK:
        cur = dict(_job.get("progress") or {})
        cur.update(kw)
        _job["progress"] = cur
        if kw.get("label"):
            _job["phase"] = str(kw["label"])


def _read_movie_root(nfo_path: Path) -> ET.Element | None:
    try:
        raw = nfo_path.read_bytes()
        root = ET.fromstring(raw.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return None
    if root.tag.lower() != "movie":
        movie = root.find("movie")
        root = movie if movie is not None else root
    if root is None or root.tag.lower() != "movie":
        return None
    return root


def optimize_one_nfo(
    nfo_path: Path,
    *,
    force: bool = False,
    strategy: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """用本地映射修正单个 NFO。返回 (是否写盘, 应用项)。"""
    from app.core.maps_paths import lookup_code_actors, lookup_code_title
    from app.scrap_library.enrich import (
        _align_llm_text_actors,
        _apply_mdcx_maps,
        _has_kana,
        _normalize_merged_title,
        _polish_studio_name,
        _strip_trailing_alt_code,
        merge_nfo_with_detail,
    )
    from app.scrap_library.enrich_extras import (
        strip_title_actor_suffix,
        strip_title_code_prefix,
    )
    from app.scrap_library.nfo import fields_from_movie_root
    from app.scrape.metadata_optimize import polish_actress_names

    old_bytes = b""
    try:
        old_bytes = nfo_path.read_bytes()
        root = ET.fromstring(old_bytes.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return False, []
    if root.tag.lower() != "movie":
        movie = root.find("movie")
        root = movie if movie is not None else root
    if root is None or root.tag.lower() != "movie":
        return False, []

    fields = fields_from_movie_root(root, code_fallback=nfo_path.stem)
    code = str(fields.get("num") or nfo_path.stem or "").strip().upper()
    if not code:
        return False, []

    title_raw = str(fields.get("title") or "").strip()
    title_bare = strip_title_code_prefix(title_raw, code)
    actors0 = [str(a).strip() for a in (fields.get("actors") or []) if str(a).strip()]
    genres0 = [str(g).strip() for g in (fields.get("genres") or []) if str(g).strip()]
    studio0 = str(fields.get("studio") or fields.get("maker") or "").strip()
    plot0 = str(fields.get("plot") or fields.get("outline") or "").strip()

    detail: dict[str, Any] = {
        "code": code,
        "title": title_bare,
        "actors": list(actors0),
        "tags": list(genres0),
        "studio": studio0,
        "maker": studio0,
        "overview": plot0,
        "director": str(fields.get("director") or "").strip(),
        "series": str(fields.get("series") or "").strip(),
        "publisher": str(fields.get("publisher") or "").strip(),
    }

    detail = _apply_mdcx_maps(detail, code=code) or detail
    applied = list(detail.get("mapsApplied") or [])

    # 全量：映射有则强制覆盖标题/女优
    if force and code:
        mapped = str(lookup_code_title(code) or "").strip()
        if mapped:
            cur = str(detail.get("title") or "").strip()
            if cur and "title" not in applied:
                if _has_kana(cur) and not str(detail.get("titleJa") or "").strip():
                    detail["titleJa"] = cur
            detail["title"] = _strip_trailing_alt_code(
                _normalize_merged_title(mapped), code
            )
            detail["titleMapApplied"] = True
            detail["titleMapForced"] = True
            if "title" not in applied:
                applied.append("title")
        local_a = polish_actress_names(
            list(lookup_code_actors(code) or []),
            enable_mapping=True,
        )
        if local_a:
            detail["actors"] = list(local_a)[:12]
            if "actors_code" not in applied and "actors" not in applied:
                applied.append("actors_code")

    studio_new = _polish_studio_name(str(detail.get("studio") or studio0))
    if studio_new and studio_new != studio0:
        detail["studio"] = studio_new
        detail["maker"] = studio_new
        if "studio" not in applied:
            applied.append("studio")

    acts = [str(a).strip() for a in (detail.get("actors") or []) if str(a).strip()]
    title = str(detail.get("title") or "").strip()
    if title:
        st = strategy if isinstance(strategy, dict) else {}
        if not st:
            try:
                from app.scrap_library.enrich_strategy import get_strategy

                st = get_strategy()
            except Exception:  # noqa: BLE001
                st = {}
        if bool(st.get("stripTitleActorSuffix")):
            title = strip_title_actor_suffix(title, acts)
        if bool(st.get("stripTitleCodePrefix")):
            title = strip_title_code_prefix(title, code)
        if acts:
            title = _align_llm_text_actors(title, acts)
        if title != title_bare and "title" not in applied:
            applied.append("title_strip")
        detail["title"] = title

    force_fields: set[str] = set()
    if any(str(x).startswith("title") for x in applied) or detail.get(
        "titleMapApplied"
    ):
        force_fields.add("title")
    if any("actor" in str(x) for x in applied):
        force_fields.add("actors")
    if "tags" in applied:
        force_fields.add("tags")
    if "outline_nl" in applied:
        force_fields.add("overview")
    if "studio" in applied:
        force_fields.add("studio")

    if force:
        force_fields |= {"title", "actors", "tags", "studio"}

    if not force_fields:
        return False, []

    changed = merge_nfo_with_detail(
        nfo_path,
        detail,
        overwrite=False,
        force_fields=force_fields,
        existing_fields=dict(fields),
        old_bytes=old_bytes,
    )
    return bool(changed), applied


_MP_FORCE = False
_MP_STRATEGY: dict[str, Any] | None = None


def _mp_init(force: bool, strategy: dict[str, Any] | None) -> None:
    """子进程预热映射表，避免每条 NFO 重复加载。"""
    global _MP_FORCE, _MP_STRATEGY
    _MP_FORCE = bool(force)
    _MP_STRATEGY = strategy or {}
    try:
        from app.core.maps_paths import load_code_actors, load_code_titles

        load_code_titles()
        load_code_actors()
        from app.scrape.metadata_optimize import actor_maps_loaded

        actor_maps_loaded()
    except Exception:  # noqa: BLE001
        pass


def _mp_optimize_one(
    item: tuple[str, str],
) -> tuple[str, bool, list[str], str | None]:
    rel, path_str = item
    try:
        changed, applied = optimize_one_nfo(
            Path(path_str), force=_MP_FORCE, strategy=_MP_STRATEGY
        )
        return rel, bool(changed), list(applied or []), None
    except Exception as e:  # noqa: BLE001
        return rel, False, [], str(e)


def optimize_library_nfos(
    *,
    force: bool = False,
    limit: int | None = None,
    resume_done: set[str] | None = None,
    resume_index: int = 0,
) -> dict[str, Any]:
    """扫描刮削库全部 NFO，按本地映射写回。"""
    import multiprocessing as mp
    import os
    from concurrent.futures import ProcessPoolExecutor, as_completed

    from app.core.maps_paths import load_code_actors, load_code_titles
    from app.scrap_library import embed as embed_svc
    from app.scrape.metadata_optimize import actor_maps_loaded

    done = set(resume_done or ())
    maps_info = actor_maps_loaded()
    try:
        load_code_titles()
        load_code_actors()
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.scrap_library.enrich_strategy import get_strategy

        strategy = get_strategy()
    except Exception:  # noqa: BLE001
        strategy = {}

    root = embed_svc.resolve_root(embed_svc.get_settings().get("root"))
    root_r = root.resolve()
    workers = min(8, max(4, os.cpu_count() or 4))
    _log(
        f"映射表 {maps_info.get('lang')} · {maps_info.get('count') or 0} 条"
        + (" · 全量" if force else " · 增量")
        + f" · {workers} 进程"
        + (f" · 续跑跳过 {len(done):,}" if done else "")
        + (f" · 下标 {resume_index:,}" if resume_index else "")
    )
    _progress(stage="scan", percent=1, label="扫描 NFO…", done=0, total=None)

    nfos: list[Path] = []
    try:
        for p in root_r.rglob("*.nfo"):
            if p.is_file():
                nfos.append(p)
    except OSError as e:
        raise RuntimeError(f"扫描失败: {e}") from e
    nfos.sort(key=lambda p: str(p).lower())
    if limit is not None and int(limit) > 0:
        nfos = nfos[: int(limit)]

    start_i = max(0, int(resume_index or 0))
    if start_i > len(nfos):
        start_i = 0
    total = len(nfos)
    _log(f"待检查 {total:,} 个 NFO")
    _progress(
        stage="scan",
        percent=3,
        label=f"检查 {total}",
        done=start_i,
        total=total,
    )

    updated = 0
    unchanged = 0
    errors = 0
    samples: list[str] = []
    processed = start_i

    def _rel(nfo: Path) -> str:
        try:
            return str(nfo.relative_to(root_r)).replace("\\", "/")
        except ValueError:
            return str(nfo)

    chunk = 512
    persist_every = 2000
    ui_every = 40
    ctx = mp.get_context("spawn")

    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=ctx,
        initializer=_mp_init,
        initargs=(bool(force), strategy),
    ) as ex:
        i = start_i
        while i < total:
            batch = nfos[i : i + chunk]
            items: list[tuple[str, str]] = []
            for p in batch:
                rel = _rel(p)
                if rel in done:
                    processed += 1
                    unchanged += 1
                    continue
                items.append((rel, str(p)))
            futs = [ex.submit(_mp_optimize_one, item) for item in items]
            for fut in as_completed(futs):
                rel, changed, applied, err = fut.result()
                processed += 1
                done.add(rel)
                if err:
                    errors += 1
                    if errors <= 5:
                        _log(f"失败 {rel}: {err}")
                    log.warning("nfo optimize failed %s: %s", rel, err)
                elif changed:
                    updated += 1
                    if len(samples) < 8:
                        samples.append(f"{rel} · {','.join(applied) or 'rewrite'}")
                else:
                    unchanged += 1

                if processed == 1 or processed % ui_every == 0 or processed == total:
                    _progress(
                        stage="write",
                        percent=3 + int(95 * processed / max(1, total)),
                        label=f"优化 {processed}/{total}",
                        done=processed,
                        total=total,
                    )
            i += len(batch)
            if i % persist_every == 0 or i == total:
                _persist(
                    status="running",
                    params={"force": bool(force), "limit": limit},
                    doneIndex=i,
                    donePaths=[],
                )
                _log(f"进度 {i}/{total} · 已改 {updated:,} · 未变 {unchanged:,}")

    if samples:
        for s in samples:
            _log(f"例 {s}")

    _progress(
        stage="done",
        percent=100,
        label="完成",
        done=updated,
        total=total,
    )
    _log(
        f"完成 · 更新 {updated:,} · 未变 {unchanged:,} · 失败 {errors:,} · 共 {total:,}"
    )
    _persist(status="done", params={"force": bool(force), "limit": limit}, donePaths=[], doneIndex=0)
    return {
        "ok": True,
        "total": total,
        "updated": updated,
        "unchanged": unchanged,
        "errors": errors,
        "maps": maps_info,
        "samples": samples,
    }


def start_nfo_optimize_job(
    *, force: bool = False, limit: int | None = None
) -> dict[str, Any]:
    import app.scrap_library.actress_avatar as av
    import app.scrap_library.embed as embed_svc
    import app.scrap_library.enrich as enrich_svc

    prev = _hydrate()
    resume_done: set[str] = set()
    resume_index = 0
    resumed = False
    prev_params = prev.get("params") if isinstance(prev.get("params"), dict) else {}
    prev_status = str(prev.get("status") or "")
    same = bool(prev_params.get("force")) == bool(force) and (
        prev_params.get("limit") in (None, limit) or limit is None
    )
    if prev_status in {"interrupted", "running", "paused"} and same:
        try:
            resume_index = max(0, int(prev.get("doneIndex") or 0))
        except (TypeError, ValueError):
            resume_index = 0
        if isinstance(prev.get("donePaths"), list):
            resume_done = {str(x) for x in prev["donePaths"] if str(x).strip()}
        resumed = bool(resume_index or resume_done)

    with _LOCK:
        if _job["running"]:
            raise RuntimeError("NFO 优化已在运行")
        if embed_svc.get_job_status().get("running"):
            raise RuntimeError("刮削库向量同步进行中，请稍后再试")
        if embed_svc.get_actress_optimize_status().get("running"):
            raise RuntimeError("女优元数据优化进行中，请稍后再试")
        if av.get_job_status().get("running"):
            raise RuntimeError("女优刮削进行中，请稍后再试")
        if enrich_svc.get_enrich_status().get("running"):
            raise RuntimeError("刮削补齐进行中，请稍后再试")
        _job.update(
            {
                "running": True,
                "phase": "继续" if resumed else "starting",
                "progress": {
                    "stage": "prepare",
                    "percent": 0,
                    "label": "继续" if resumed else "starting",
                    "done": resume_index if resumed else 0,
                    "total": None,
                },
                "log": list(_job.get("log") or [])[-20:] if resumed else [],
                "result": None,
                "error": None,
            }
        )
    _persist(
        status="running",
        params={"force": bool(force), "limit": limit},
        donePaths=[],
        doneIndex=resume_index,
    )

    def run() -> None:
        try:
            if resumed:
                _log(f"续跑 · 下标 {resume_index:,}")
            result = optimize_library_nfos(
                force=bool(force),
                limit=limit,
                resume_done=resume_done or None,
                resume_index=resume_index,
            )
            with _LOCK:
                _job["result"] = result
                _job["phase"] = "done"
            _persist(status="done", donePaths=[])
        except Exception as e:  # noqa: BLE001
            log.exception("nfo optimize failed")
            with _LOCK:
                _job["error"] = str(e)
                _job["phase"] = "error"
                log_list = list(_job.get("log") or [])
                log_list.append(f"失败: {e}")
                _job["log"] = log_list[-40:]
            _persist(
                status="error",
                donePaths=[],
                doneIndex=resume_index,
            )
        finally:
            with _LOCK:
                _job["running"] = False
            _persist()

    threading.Thread(target=run, name="scrap-nfo-optimize", daemon=True).start()
    return {"started": True, "resumed": resumed}
