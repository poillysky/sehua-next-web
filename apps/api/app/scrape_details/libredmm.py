# -*- coding: utf-8 -*-
"""LibreDMM 详情刮削（对齐 MDCS libredmm.ts）。"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

from .common import code_key, fetch_json, make_detail, strip_tags

DEFAULT_BASE = "https://www.libredmm.com"


def _prefer_pl_cover(url: str | None) -> str | None:
    u = str(url or "").strip()
    if not u:
        return None
    return re.sub(r"ps\.jpg(\?|$)", r"pl.jpg\1", u, flags=re.I)


def _parse_hit(raw: Any, code: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    err = str(raw.get("err") or "")
    if err and err != "ok":
        return None

    title = str(raw.get("title") or "").strip()
    cover = _prefer_pl_cover(raw.get("cover_image_url")) or _prefer_pl_cover(raw.get("thumbnail_image_url"))

    actors: list[str] = []
    for a in raw.get("actresses") or []:
        if not isinstance(a, dict):
            continue
        name = re.sub(r"\s+\d+歳.*$", "", str(a.get("name") or ""), flags=re.U).strip()
        if name:
            actors.append(name)

    nid = re.sub(r"[-_\s]", "", str(raw.get("normalized_id") or "")).upper()
    if nid and code_key(nid) != code_key(code):
        return None

    if not title and not cover:
        return None

    plot = re.sub(
        r"\s+",
        " ",
        strip_tags(str(raw.get("description") or raw.get("comment") or raw.get("subtitle") or "")),
    ).strip()

    premiered = str(raw.get("date") or "")[:10]
    date = premiered if re.match(r"^\d{4}-\d{2}-\d{2}", premiered) else None

    makers = raw.get("makers") or []
    studio = str(makers[0] if makers else "").strip() or None
    labels = raw.get("labels") or []
    publisher = str(labels[0] if labels else "").strip() or None

    series_raw = raw.get("series")
    if isinstance(series_raw, list):
        series = str(series_raw[0] if series_raw else "").strip() or None
    else:
        series = str(series_raw or "").strip() or None

    runtime_raw = raw.get("minute")
    if not isinstance(runtime_raw, (int, float)):
        runtime_raw = raw.get("runtime")
    runtime = int(runtime_raw) if isinstance(runtime_raw, (int, float)) else None
    if runtime is not None and not (0 < runtime < 600):
        runtime = None

    genres = []
    for g in raw.get("genres") or []:
        gs = str(g).strip()
        if gs and not re.match(r"^(サンプル動画|デジタル配信)$", gs, re.I):
            genres.append(gs)

    return {
        "title": title or None,
        "overview": plot if len(plot) >= 12 else None,
        "actors": actors,
        "tags": genres,
        "studio": studio,
        "publisher": publisher,
        "series": series,
        "runtime": runtime,
        "date": date,
        "poster": cover,
    }


def _detail_from_hit(code: str, hit: dict[str, Any]) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if hit.get("publisher"):
        extra["publisher"] = hit["publisher"]
    if hit.get("series"):
        extra["series"] = hit["series"]
    if hit.get("runtime") is not None:
        extra["runtime"] = hit["runtime"]
    return make_detail(
        source="libredmm",
        code=code,
        title=hit.get("title"),
        poster=hit.get("poster"),
        studio=hit.get("studio"),
        actors=hit.get("actors") or [],
        tags=hit.get("tags") or [],
        overview=hit.get("overview"),
        date=hit.get("date"),
        extra=extra or None,
    )


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")

    code_u = str(code or "").strip().upper()
    if not code_u:
        raise RuntimeError("番号为空")

    movie_url = f"{base}/movies/{quote(code_u)}.json"
    for i in range(5):
        try:
            data = fetch_json(movie_url, cookie=cookie or None, source_id="libredmm")
        except Exception:
            data = None
        if isinstance(data, dict):
            err = str(data.get("err") or "")
            if err == "processing":
                time.sleep(1.2 + i * 0.4)
                continue
            if err == "not_found":
                break
            hit = _parse_hit(data, code_u)
            if hit and (hit.get("title") or hit.get("poster")):
                return _detail_from_hit(code_u, hit)
        if i < 2:
            time.sleep(0.8)
            continue
        break

    try:
        search_data = fetch_json(
            f"{base}/search.json?q={quote(code_u)}",
            cookie=cookie or None,
            source_id="libredmm",
        )
    except Exception as e:
        raise RuntimeError(f"未找到: {e}") from e

    from_search = _parse_hit(search_data, code_u)
    if from_search and (from_search.get("title") or from_search.get("poster")):
        return _detail_from_hit(code_u, from_search)

    raise RuntimeError("未找到")
