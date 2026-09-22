# -*- coding: utf-8 -*-
"""Folder reingest / meta patch / queue-log persist helpers."""
from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

import app.scrap_library.embed as embed_svc
import app.scrap_library.enrich as _enrich
from app.core.db import get_meta_pool, media_dir
from app.scrap_library.nfo import (
    build_mdcx_nfo_root,
    fields_from_movie_root,
    parse_nfo,
    write_nfo,
)

log = logging.getLogger(__name__)

def reingest_folder(folder: Path) -> dict[str, Any] | None:
    """单目录 NFO 重扫并写回向量库（刮削后一步完成）。"""
    nfo = _enrich._find_nfo(folder)
    if not nfo:
        return {"ok": False, "embedded": False, "error": "missing_nfo"}
    cfg = _enrich.resolve_embed_config(include_secret=True)
    if not cfg.get("enabled"):
        meta = _enrich.parse_nfo(nfo)
        return {
            "ok": False,
            "embedded": False,
            "error": "embed_disabled",
            "title": meta.get("title"),
        }

    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root"))
    media_root = _enrich.media_dir()
    scrap_rel = ""
    try:
        scrap_rel = root.relative_to(media_root.resolve()).as_posix()
    except ValueError:
        scrap_rel = (
            str(settings.get("root") or "scrap-library").replace("\\", "/").strip("/")
        )

    model = str(cfg["model"])
    dim = int(cfg["dim"])
    item = embed_svc._scan_one_nfo(  # noqa: SLF001
        nfo,
        root=root,
        model=model,
        dim=dim,
        media_root=media_root,
        scrap_rel=scrap_rel,
    )
    if not item:
        return {"ok": False, "embedded": False, "error": "scan_nfo_failed"}
    vecs = _enrich.encode_texts_sync([item["source_text"]], query=False)
    if not vecs or len(vecs[0]) != dim:
        raise RuntimeError("向量编码失败")
    vec_lit = embed_svc._vec_literal(vecs[0])  # noqa: SLF001
    pool = _enrich.get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {embed_svc.TABLE}
              (item_id, region, prefix, code, rel_path, title,
               poster_path, thumb_path, fanart_path, cover_url,
               model, dim, content_sha, source_text, embedding, updated_at)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, now())
            ON CONFLICT (item_id) DO UPDATE SET
              region = EXCLUDED.region,
              prefix = EXCLUDED.prefix,
              code = EXCLUDED.code,
              rel_path = EXCLUDED.rel_path,
              title = EXCLUDED.title,
              poster_path = EXCLUDED.poster_path,
              thumb_path = EXCLUDED.thumb_path,
              fanart_path = EXCLUDED.fanart_path,
              cover_url = EXCLUDED.cover_url,
              model = EXCLUDED.model,
              dim = EXCLUDED.dim,
              content_sha = EXCLUDED.content_sha,
              source_text = EXCLUDED.source_text,
              embedding = EXCLUDED.embedding,
              updated_at = now()
            """,
            (
                item["item_id"],
                item["region"],
                item["prefix"],
                item["code"],
                item["rel_path"],
                item["title"],
                item["poster_path"],
                item["thumb_path"],
                item["fanart_path"],
                item["cover_url"],
                item["model"],
                item["dim"],
                item["content_sha"],
                item["source_text"],
                vec_lit,
            ),
        )
        conn.commit()
    return {
        "ok": True,
        "embedded": True,
        "itemId": item["item_id"],
        "code": item["code"],
        "title": item.get("title"),
    }


def patch_folder_meta_no_embed(folder: Path) -> dict[str, Any]:
    """本地刮削后：回写标题/source_text/封面路径，并覆盖旧 embedding。

    分区批量 sync_vector=False 时必须调用，否则缺口仍按旧向量行计算，
    再启动会把刚刮过的番号又排进队。二次刮削直接覆盖向量库已有行（embedding 置零待再同步）。
    """
    nfo = _enrich._find_nfo(folder)
    if not nfo:
        return {"ok": False, "patched": False, "error": "missing_nfo"}
    cfg = _enrich.resolve_embed_config(include_secret=False)
    model = str(cfg.get("model") or "text-embedding-3-small")
    try:
        dim = int(cfg.get("dim") or 1536)
    except (TypeError, ValueError):
        dim = 1536
    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root"))
    media_root = _enrich.media_dir()
    scrap_rel = ""
    try:
        scrap_rel = root.relative_to(media_root.resolve()).as_posix()
    except ValueError:
        scrap_rel = (
            str(settings.get("root") or "scrap-library").replace("\\", "/").strip("/")
        )
    item = embed_svc._scan_one_nfo(  # noqa: SLF001
        nfo,
        root=root,
        model=model,
        dim=dim,
        media_root=media_root,
        scrap_rel=scrap_rel,
    )
    if not item:
        return {"ok": False, "patched": False, "error": "scan_nfo_failed"}
    iid = str(item.get("item_id") or "").strip()
    if not iid:
        return {"ok": False, "patched": False, "error": "missing_item_id"}
    # 无行时占位零向量；二次刮削：已有行也覆盖 embedding（清旧向量，待再同步）
    zero_lit = embed_svc._vec_literal([0.0] * dim)  # noqa: SLF001
    pool = _enrich.get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {embed_svc.TABLE}
              (item_id, region, prefix, code, rel_path, title,
               poster_path, thumb_path, fanart_path, cover_url,
               model, dim, content_sha, source_text, embedding, updated_at)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, now())
            ON CONFLICT (item_id) DO UPDATE SET
              region = EXCLUDED.region,
              prefix = EXCLUDED.prefix,
              code = EXCLUDED.code,
              rel_path = EXCLUDED.rel_path,
              title = EXCLUDED.title,
              poster_path = EXCLUDED.poster_path,
              thumb_path = EXCLUDED.thumb_path,
              fanart_path = EXCLUDED.fanart_path,
              cover_url = EXCLUDED.cover_url,
              model = EXCLUDED.model,
              dim = EXCLUDED.dim,
              content_sha = EXCLUDED.content_sha,
              source_text = EXCLUDED.source_text,
              embedding = EXCLUDED.embedding,
              updated_at = now()
            """,
            (
                iid,
                item["region"],
                item["prefix"],
                item["code"],
                item["rel_path"],
                item["title"],
                item["poster_path"],
                item["thumb_path"],
                item["fanart_path"],
                item["cover_url"],
                item["model"],
                item["dim"],
                item["content_sha"],
                item["source_text"],
                zero_lit,
            ),
        )
        conn.commit()
    return {
        "ok": True,
        "patched": True,
        "embedded": False,
        "overwritten": True,
        "itemId": iid,
        "code": item.get("code"),
        "title": item.get("title"),
        "gaps": embed_svc._row_gaps(item),  # noqa: SLF001
    }


def _persist_enrich_result_to_queue_log(
    out: dict[str, Any],
    *,
    row: dict[str, Any],
    region: str = "",
    dry_run: bool = False,
) -> int:
    """刮削结果直接写入 enrich_queue_log（含 fields / sourceTimings）。"""
    if dry_run:
        return 0
    timings = list(out.get("sourceTimings") or [])
    fields = list(out.get("fields") or [])
    if not timings and not fields:
        return 0
    code_u = str(
        out.get("code") or (row or {}).get("code") or ""
    ).strip().upper()
    if not code_u:
        return 0
    rid = (
        _enrich._queue_log_region(region)
        or _enrich._queue_log_region(str(out.get("region") or ""))
        or _enrich._queue_log_region(str((row or {}).get("region") or ""))
    )
    st = "done" if out.get("ok") else "fail"
    gaps_after = list(out.get("gapsAfter") or [])
    # 成功以 gapsAfter 为准（空=缺口已清）；失败保留原 gaps 便于 UI 展示
    if out.get("ok"):
        gaps_persist = gaps_after
    else:
        gaps_persist = gaps_after or list(
            (row or {}).get("gaps") or out.get("gaps") or []
        )
    persist: dict[str, Any] = {
        "logId": _enrich._queue_log_int_id(row or {}),
        "itemId": str((row or {}).get("itemId") or out.get("itemId") or ""),
        "code": code_u,
        "status": st,
        "gaps": gaps_persist,
        "error": str(out.get("error") or "")[:500],
        "source": str(out.get("source") or ""),
        "fetchMs": out.get("fetchMs"),
        "detailTitle": str(out.get("detailTitle") or "")[:300],
        "actors": out.get("actors"),
        "nfoChanged": out.get("nfoChanged"),
        "posterDownloaded": out.get("posterDownloaded"),
        "vectorSynced": out.get("vectorSynced"),
        "vectorSkipped": out.get("vectorSkipped"),
        "vectorError": str(out.get("vectorError") or "")[:120],
        "fields": fields,
        "sourceTimings": timings,
        "coverMs": out.get("coverMs"),
        "actressMs": out.get("actressMs"),
        "vectorMs": out.get("vectorMs"),
        "totalMs": out.get("totalMs"),
        "partialOk": bool(out.get("partialOk")),
        "gapsAfter": gaps_after,
    }
    rel_p = str(
        (row or {}).get("rel_path")
        or (row or {}).get("relPath")
        or out.get("relPath")
        or ""
    ).strip()
    if rel_p:
        persist["rel_path"] = rel_p
        persist["relPath"] = rel_p
    try:
        lid = _enrich._queue_log_update_row(persist, region=rid or region)
        if st == "done":
            # prune 异步：绝不能挡 _done→item_end，否则监控假死在封面阶段
            _rid = rid or region
            _iid = str(persist.get("itemId") or "")

            def _prune_open_bg() -> None:
                try:
                    _enrich._queue_log_prune_open_if_done(
                        _rid, code=code_u, item_id=_iid
                    )
                except Exception:  # noqa: BLE001
                    pass

            threading.Thread(
                target=_prune_open_bg,
                name=f"prune-open-{code_u or 'x'}",
                daemon=True,
            ).start()
        # 番号目录落盘：清空队列表后仍可回读源耗时
        try:
            fol = _enrich._resolve_enrich_folder(
                region=rid or region,
                code=code_u,
                item_id=str(
                    persist.get("itemId")
                    or persist.get("relPath")
                    or persist.get("rel_path")
                    or ""
                ),
            )
            if fol is not None:
                _enrich.write_enrich_sidecar(fol, persist)
        except Exception as se:  # noqa: BLE001
            log.debug("enrich sidecar write skip code=%s: %s", code_u, se)
        src_n = sum(
            1
            for f in fields
            if isinstance(f, dict) and str(f.get("source") or "").strip()
        )
        log.info(
            "enrich queue persist code=%s region=%s lid=%s status=%s "
            "timings=%s fields=%s srcFields=%s",
            code_u,
            rid or region or "-",
            lid,
            st,
            len(timings),
            len(fields),
            src_n,
        )
        return int(lid or 0)
    except Exception as e:  # noqa: BLE001
        log.warning("enrich queue persist failed code=%s: %s", code_u, e)
        return 0


