# -*- coding: utf-8 -*-
"""embed_actress_opt —— 自 scrap_library/embed.py 拆出（机械搬移，行为不变）。"""

from __future__ import annotations
import json
import logging
import os
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
import app.core.settings_store as settings_store
from app.ai.config import resolve_embed_config
from app.ai.embed import encode_texts_sync
from app.core.db import data_dir, media_dir, get_meta_pool, init_db, meta_dsn_label
from app.scrap_library.nfo import (
    build_nfo_embed_text,
    content_sha,
    item_id_from_rel,
    normalize_source_text_for_diff,
    parse_nfo,
    polish_source_text_actresses,
    preserve_actress_line,
)
from app.core.ttl_cache import enforce_max, prune_by_age

import app.scrap_library.embed as _embed
import app.scrap_library.embed_catalog as _embed_catalog
import app.scrap_library.embed_facets as _embed_facets
from app.scrap_library.embed import (_ACTRESS_OPT_LOCK, _FACETS_CACHE, _actress_opt_job, _hydrate_actress_opt_job, _split_tokens, _vec_literal, get_job_status, log)


def _append_actress_clause(
    clauses: list[str], params: list[Any], actress: str
) -> None:
    actress_q = str(actress or "").strip()
    if not actress_q:
        return
    if actress_q in {"未标注女优", "未标注", "(unknown)"}:
        clauses.append(f"({_embed_facets._ACTRESS_LINE_SQL} IS NULL)")
        return
    # 女优行可多名：整行分词后精确命中
    clauses.append(
        f"""EXISTS (
          SELECT 1
          FROM unnest(
            regexp_split_to_array(trim({_embed_facets._ACTRESS_LINE_SQL}), '{_embed_facets._TOKEN_SPLIT_SQL}')
          ) AS tok
          WHERE trim(tok) = %s
        )"""
    )
    params.append(actress_q)


def _split_actress_tokens(raw: str) -> list[str]:
    from app.scrap_library.enrich import _clean_actors

    return _clean_actors(_split_tokens(raw))


def _persist_actress_opt_job(**extra: Any) -> None:
    try:
        from app.core import job_persist

        with _ACTRESS_OPT_LOCK:
            payload = {
                "status": (
                    "running"
                    if _actress_opt_job.get("running")
                    else str(extra.get("status") or _actress_opt_job.get("phase") or "idle")
                ),
                "phase": str(_actress_opt_job.get("phase") or ""),
                "progress": dict(_actress_opt_job.get("progress") or {}) or None,
                "log": list(_actress_opt_job.get("log") or [])[-40:],
                "result": _actress_opt_job.get("result"),
                "error": _actress_opt_job.get("error"),
                "running": bool(_actress_opt_job.get("running")),
            }
        for k, v in extra.items():
            payload[k] = v
        if payload.get("running"):
            payload["status"] = "running"
        job_persist.save_job(job_persist.ACTRESS_OPTIMIZE_JOB_KEY, payload)
    except Exception as e:  # noqa: BLE001
        log.warning("persist actress optimize job failed: %s", e)


def get_actress_optimize_status() -> dict[str, Any]:
    _hydrate_actress_opt_job()
    with _ACTRESS_OPT_LOCK:
        return {
            "running": bool(_actress_opt_job["running"]),
            "phase": _actress_opt_job.get("phase") or "",
            "progress": _actress_opt_job.get("progress"),
            "log": list(_actress_opt_job.get("log") or [])[-40:],
            "result": _actress_opt_job.get("result"),
            "error": _actress_opt_job.get("error"),
        }


def _actress_opt_log(msg: str) -> None:
    with _ACTRESS_OPT_LOCK:
        log_list = list(_actress_opt_job.get("log") or [])
        log_list.append(str(msg))
        _actress_opt_job["log"] = log_list[-40:]


def _actress_opt_progress(**kw: Any) -> None:
    with _ACTRESS_OPT_LOCK:
        cur = dict(_actress_opt_job.get("progress") or {})
        cur.update(kw)
        _actress_opt_job["progress"] = cur
        if kw.get("label"):
            _actress_opt_job["phase"] = str(kw["label"])


def optimize_actress_metadata(
    *,
    reembed: bool = True,
    force: bool = False,
    limit: int | None = None,
    batch_size: int = 32,
    read_nfo_directors: bool = False,
    resume_done_ids: set[str] | None = None,
) -> dict[str, Any]:
    """批量优化向量库女优行：映射中文标准名 + 排除导演/男优（不改 NFO）。

    force=True：即使女优行未变也重嵌（全量同步）。
    resume_done_ids：断点续跑已写入 item_id。
    """
    from app.ai.embed import encode_texts_sync
    from app.scrap_library.nfo import content_sha, parse_nfo
    from app.scrape.metadata_optimize import (
        actor_maps_loaded,
        polish_actress_names,
    )

    _embed.ensure_schema()
    maps_info = actor_maps_loaded()
    done_ids = set(resume_done_ids or ())
    _actress_opt_log(
        f"映射表 {maps_info.get('lang')} · {maps_info.get('count') or 0} 条"
        + (" · 全量" if force else " · 增量")
        + (f" · 续跑跳过 {len(done_ids):,}" if done_ids else "")
    )
    root = _embed.resolve_root(_embed.get_settings().get("root"))
    pool = get_meta_pool()
    like = "%女优：%"
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*)::int AS n FROM {_embed.TABLE} WHERE source_text LIKE %s",
            (like,),
        )
        counted = cur.fetchone() or {}
        total_all = int(
            (counted.get("n") if isinstance(counted, dict) else counted[0]) or 0
        )
    cap = int(limit) if limit is not None and int(limit) > 0 else 0
    total = min(total_all, cap) if cap else total_all
    _actress_opt_log(f"待检查 {total:,} 条含女优行")
    _actress_opt_progress(
        stage="scan", percent=2, label=f"检查 {total}", done=0, total=total
    )

    cfg = resolve_embed_config()
    if not cfg.get("enabled"):
        reembed = False
        _actress_opt_log("嵌入未启用 · 仅更新文本")
    bs = max(8, min(64, int(batch_size or 32)))
    written = 0
    reembedded = 0
    samples: list[dict[str, Any]] = []

    def _flush_actress(chunk: list[dict[str, Any]]) -> None:
        nonlocal written, reembedded
        if not chunk:
            return
        with pool.connection() as conn, conn.cursor() as cur:
            if reembed:
                texts = [p["source_text"] for p in chunk]
                vecs = encode_texts_sync(texts, query=False)
                if not vecs or len(vecs) != len(chunk):
                    raise RuntimeError("向量编码失败")
                for p, vec in zip(chunk, vecs):
                    if len(vec) != int(p["dim"]):
                        raise RuntimeError("向量维度不匹配")
                    cur.execute(
                        f"""
                        UPDATE {_embed.TABLE}
                        SET source_text = %s,
                            content_sha = %s,
                            embedding = %s::vector,
                            updated_at = now()
                        WHERE item_id = %s
                        """,
                        (
                            p["source_text"],
                            p["content_sha"],
                            _vec_literal(vec),
                            p["item_id"],
                        ),
                    )
                    reembedded += 1
                    written += 1
            else:
                for p in chunk:
                    cur.execute(
                        f"""
                        UPDATE {_embed.TABLE}
                        SET source_text = %s,
                            content_sha = %s,
                            updated_at = now()
                        WHERE item_id = %s
                        """,
                        (p["source_text"], p["content_sha"], p["item_id"]),
                    )
                    written += 1
            conn.commit()
        for p in chunk:
            iid = str(p.get("item_id") or "")
            if iid:
                done_ids.add(iid)
        _actress_opt_progress(
            stage="embed" if reembed else "patch",
            percent=min(94, 45 + int(50 * written / max(1, total))),
            label=f"写入 {written}",
            done=written,
            total=total,
        )
        _persist_actress_opt_job(
            status="running",
            params={
                "reembed": bool(reembed),
                "force": bool(force),
                "limit": limit,
            },
            doneIds=sorted(done_ids)[-8000:],
        )

    def _actress_rows():
        seen = 0
        sql = f"""
            SELECT item_id, code, rel_path, source_text, model, dim, title
            FROM {_embed.TABLE}
            WHERE source_text LIKE %s
            ORDER BY item_id
        """
        for batch in _embed_catalog._meta_iter_batches(
            sql, (like,), batch_size=200, cursor_name="actress_opt_scan"
        ):
            for raw in batch:
                if cap and seen >= cap:
                    return
                seen += 1
                if isinstance(raw, dict):
                    yield raw
                else:
                    yield {
                        "item_id": raw[0],
                        "code": raw[1],
                        "rel_path": raw[2],
                        "source_text": raw[3],
                        "model": raw[4],
                        "dim": raw[5],
                        "title": raw[6],
                    }

    actress_re = re.compile(r"^(女优：)(.+)$", re.M)
    pending: list[dict[str, Any]] = []
    unchanged = 0
    for i, row in enumerate(_actress_rows(), 1):
        iid = str(row.get("item_id") or "")
        if iid and iid in done_ids:
            unchanged += 1
            continue
        src = str(row.get("source_text") or "")
        m = actress_re.search(src)
        if not m:
            unchanged += 1
            continue
        raw_parts = [
            p for p in re.split(r"[\s、,/|]+", m.group(2).strip()) if p.strip()
        ]
        directors: list[str] = []
        # 批量任务默认不扫 NFO（极慢）；男优/导演以映射表 drop 为主。
        # 单条/小批量可传 read_nfo_directors=True。
        if read_nfo_directors:
            rel = str(row.get("rel_path") or "").replace("\\", "/").strip("/")
            if rel:
                folder = root / rel
                nfo = None
                if folder.is_dir():
                    for cand in (
                        folder / f"{folder.name}.nfo",
                        folder / f"{row.get('code')}.nfo",
                        *sorted(folder.glob("*.nfo")),
                    ):
                        if cand.is_file():
                            nfo = cand
                            break
                if nfo:
                    try:
                        meta = parse_nfo(nfo)
                        d = str(meta.get("director") or "").strip()
                        if d:
                            directors.append(d)
                    except Exception:  # noqa: BLE001
                        pass
        try:
            from app.scrap_library.enrich import _clean_actors

            cleaned = _clean_actors(raw_parts)
        except Exception:  # noqa: BLE001
            cleaned = raw_parts
        polished = polish_actress_names(cleaned, exclude=directors)
        old_line = m.group(0)
        if polished:
            new_line = f"女优：{' '.join(polished[:12])}"
        else:
            new_line = ""
        if new_line == old_line and not force:
            unchanged += 1
            continue
        if new_line == old_line and force:
            # 全量：文本未变也重嵌
            new_src = src
        elif new_line:
            new_src = src[: m.start()] + new_line + src[m.end() :]
        else:
            before = src[: m.start()].rstrip("\n")
            after = src[m.end() :].lstrip("\n")
            new_src = f"{before}\n{after}" if before and after else (before or after)
        new_src = re.sub(r"\n{2,}", "\n", new_src).strip()
        model = str(row.get("model") or "")
        dim = int(row.get("dim") or 0) or int(resolve_embed_config()["dim"])
        if not model:
            model = str(resolve_embed_config()["model"])
        pending.append(
            {
                "item_id": row["item_id"],
                "code": row.get("code"),
                "source_text": new_src,
                "content_sha": content_sha(new_src, model=model, dim=dim),
                "model": model,
                "dim": dim,
                "old": m.group(2).strip()[:80],
                "new": " ".join(polished[:8]) if polished else "(removed)",
            }
        )
        if len(samples) < 5:
            samples.append(pending[-1])
        if len(pending) >= bs:
            _flush_actress(pending)
            pending.clear()
        if i == 1 or i % 2000 == 0 or i == total:
            _actress_opt_progress(
                stage="diff",
                percent=2 + int(40 * i / max(1, total)),
                label=f"比对 {i}/{total}",
                done=i,
                total=total,
            )

    if pending:
        _flush_actress(pending)
        pending.clear()
    _actress_opt_log(f"需更新 {written:,} · 未变 {unchanged:,}")
    for s in samples:
        _actress_opt_log(f"例 {s.get('code')} · {s['old']} → {s['new']}")

    if written == 0:
        _actress_opt_progress(
            stage="done", percent=100, label="无需更新", done=0, total=total
        )
        return {
            "ok": True,
            "total": total,
            "unchanged": unchanged,
            "updated": 0,
            "reembedded": 0,
            "maps": maps_info,
        }

    try:
        _FACETS_CACHE.clear()
    except Exception:  # noqa: BLE001
        pass
    _actress_opt_progress(
        stage="done",
        percent=100,
        label="完成",
        done=written,
        total=len(pending),
    )
    _actress_opt_log(
        f"完成 · 更新 {written:,} · 重嵌 {reembedded:,} · 未变 {unchanged:,}"
    )
    _persist_actress_opt_job(
        status="done",
        params={"reembed": bool(reembed), "force": bool(force), "limit": limit},
        doneIds=[],
    )
    return {
        "ok": True,
        "total": total,
        "unchanged": unchanged,
        "updated": written,
        "reembedded": reembedded,
        "maps": maps_info,
    }


def start_actress_optimize_job(
    *, reembed: bool = True, force: bool = False, limit: int | None = None
) -> dict[str, Any]:
    import app.scrap_library.actress_avatar as av

    prev = _hydrate_actress_opt_job()
    resume_done: set[str] = set()
    resumed = False
    prev_params = prev.get("params") if isinstance(prev.get("params"), dict) else {}
    prev_status = str(prev.get("status") or "")
    same = (
        bool(prev_params.get("force")) == bool(force)
        and bool(prev_params.get("reembed", True)) == bool(reembed)
        and (prev_params.get("limit") in (None, limit) or limit is None)
    )
    if (
        prev_status in {"interrupted", "running", "paused"}
        and same
        and isinstance(prev.get("doneIds"), list)
    ):
        resume_done = {str(x) for x in prev["doneIds"] if str(x).strip()}
        resumed = bool(resume_done)

    with _ACTRESS_OPT_LOCK:
        if _actress_opt_job["running"]:
            raise RuntimeError("女优元数据优化已在运行")
        if get_job_status().get("running"):
            raise RuntimeError("刮削库向量同步进行中，请稍后再试")
        if av.get_job_status().get("running"):
            raise RuntimeError("女优刮削进行中，请稍后再试")
        try:
            from app.scrap_library import nfo_optimize as nfo_opt

            if nfo_opt.get_job_status().get("running"):
                raise RuntimeError("NFO 优化进行中，请稍后再试")
        except RuntimeError:
            raise
        except Exception:  # noqa: BLE001
            pass
        _actress_opt_job.update(
            {
                "running": True,
                "phase": "继续" if resumed else "starting",
                "progress": {
                    "stage": "prepare",
                    "percent": 0,
                    "label": "继续" if resumed else "starting",
                    "done": len(resume_done) if resumed else 0,
                    "total": None,
                },
                "log": (
                    list(_actress_opt_job.get("log") or [])[-20:] if resumed else []
                ),
                "result": None,
                "error": None,
            }
        )
    _persist_actress_opt_job(
        status="running",
        params={"reembed": bool(reembed), "force": bool(force), "limit": limit},
        doneIds=sorted(resume_done)[-8000:],
    )

    def run() -> None:
        try:
            if resumed:
                _actress_opt_log(f"续跑 · 已跳过 {len(resume_done):,} 条")
            result = optimize_actress_metadata(
                reembed=reembed,
                force=bool(force),
                limit=limit,
                resume_done_ids=resume_done or None,
            )
            with _ACTRESS_OPT_LOCK:
                _actress_opt_job["result"] = result
                _actress_opt_job["phase"] = "done"
            _persist_actress_opt_job(status="done", doneIds=[])
        except Exception as e:  # noqa: BLE001
            log.exception("actress optimize failed")
            with _ACTRESS_OPT_LOCK:
                _actress_opt_job["error"] = str(e)
                _actress_opt_job["phase"] = "error"
                log_list = list(_actress_opt_job.get("log") or [])
                log_list.append(f"失败: {e}")
                _actress_opt_job["log"] = log_list[-40:]
            _persist_actress_opt_job(
                status="error",
                doneIds=sorted(resume_done)[-8000:],
            )
        finally:
            with _ACTRESS_OPT_LOCK:
                _actress_opt_job["running"] = False
            _persist_actress_opt_job()

    threading.Thread(
        target=run, name="scrap-actress-optimize", daemon=True
    ).start()
    return {"started": True, "resumed": resumed}
