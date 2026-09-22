# -*- coding: utf-8 -*-
"""embed_recommend —— 自 scrap_library/embed.py 拆出（机械搬移，行为不变）。"""

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
from app.scrap_library.embed import (_RECOMMEND_SNAP_VERSION, _recommend_snap_path, log)
from app.scrap_library.embed_runtime import (_RECOMMEND_CACHE)


def list_recommend(*, region: str = "") -> dict[str, Any]:
    """Emby「推荐」：六区各自一条「最近刮削入库」横向货架。

    region 参数保留兼容；推荐页始终返回全部有内容的区。
    按向量库 updated_at 新→旧（enrich/写回会刷新该字段），排除仅番号骨架。
    结果走内存 + 磁盘快照，打开推荐页秒开。
    """
    now = time.monotonic()
    prune_by_age(_RECOMMEND_CACHE, _RECOMMEND_CACHE_TTL_S, now=now)
    hit = _RECOMMEND_CACHE.get("all")
    if hit and now - hit[0] < _RECOMMEND_CACHE_TTL_S:
        data = dict(hit[1])
    else:
        data = _load_recommend_snapshot()
        if data is None:
            data = _build_recommend()
            try:
                _save_recommend_snapshot(data)
            except Exception as e:  # noqa: BLE001
                log.warning("recommend snapshot write failed: %s", e)
        _RECOMMEND_CACHE["all"] = (now, dict(data))
        enforce_max(_RECOMMEND_CACHE, 4)

    # 兼容旧字段：取当前/第一区
    shelves = list(data.get("shelves") or [])
    focus = str(region or "").strip()
    focus_shelf = next((s for s in shelves if s.get("region") == focus), None)
    if focus_shelf is None and shelves:
        focus_shelf = shelves[0]
    latest = list((focus_shelf or {}).get("latest") or [])
    return {
        "shelves": shelves,
        "latest": latest,
        "genres": [],
        "collections": [],
        "folders": [],
        "total": int(data.get("total") or 0),
    }


_RECOMMEND_CACHE_TTL_S = 180.0


def _load_recommend_snapshot() -> dict[str, Any] | None:
    path = _recommend_snap_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("recommend snapshot read failed: %s", e)
        return None
    if not isinstance(raw, dict):
        return None
    if int(raw.get("v") or 0) != _RECOMMEND_SNAP_VERSION:
        return None
    shelves = raw.get("shelves")
    if not isinstance(shelves, list):
        return None
    return {
        "shelves": shelves,
        "total": int(raw.get("total") or 0),
    }


def _save_recommend_snapshot(data: dict[str, Any]) -> None:
    path = _recommend_snap_path()
    payload = {
        "v": _RECOMMEND_SNAP_VERSION,
        "updatedAt": time.time(),
        "total": int(data.get("total") or 0),
        "shelves": list(data.get("shelves") or []),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp.replace(path)


def _build_recommend() -> dict[str, Any]:
    from app.core.region_meta import REGION_META, REGION_ORDER

    shelves: list[dict[str, Any]] = []
    total_all = 0
    for rid in REGION_ORDER:
        page = _embed.list_items(
            region=rid,
            sort="recent",
            order="desc",
            offset=0,
            limit=12,
            display_only=True,
        )
        items = page.get("items") or []
        if not items:
            continue
        n = int(page.get("total") or 0)
        total_all += n
        label = str((REGION_META.get(rid) or {}).get("label") or rid)
        shelves.append(
            {
                "region": rid,
                "label": label,
                "latest": items,
                "total": n,
            }
        )
    return {"shelves": shelves, "total": total_all}


def refresh_recommend_snapshot() -> dict[str, Any]:
    """重建推荐货架磁盘快照。"""
    data = _build_recommend()
    _save_recommend_snapshot(data)
    _RECOMMEND_CACHE.clear()
    _RECOMMEND_CACHE["all"] = (time.monotonic(), dict(data))
    return {
        "shelves": len(data.get("shelves") or []),
        "total": int(data.get("total") or 0),
        "updatedAt": time.time(),
    }
