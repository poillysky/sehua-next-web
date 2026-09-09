# -*- coding: utf-8 -*-
"""R18.dev 详情刮削（对齐 MDCS r18dev.ts）。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from .common import fetch_json, make_detail, std_code

API_BASE = "https://r18.dev"

# MDCX r18dev.py _content_id_prefixes
CONTENT_ID_PREFIXES: dict[str, list[str]] = {
    "abf": ["118"],
    "abp": ["118"],
    "abs": ["118"],
    "abw": ["118"],
    "aky": ["118"],
    "ap": ["", "1"],
    "apak": ["118"],
    "bf": ["118"],
    "bjd": ["118"],
    "bkd": ["118"],
    "blk": ["118"],
    "cawd": ["118"],
    "cnd": ["118"],
    "cre": ["118"],
    "dldss": ["118"],
    "dmow": ["118"],
    "dok": ["118"],
    "ebod": ["118"],
    "eyan": ["118"],
    "fb": ["118"],
    "gbs": ["118"],
    "gvh": ["118"],
    "hnd": ["118"],
    "hunt": ["118"],
    "husr": ["118"],
    "hzn": ["118"],
    "ipx": ["118"],
    "ipvr": ["118"],
    "ism": ["118"],
    "joe": ["118"],
    "jul": ["118"],
    "kawd": ["118"],
    "kire": ["118"],
    "kiss": ["118"],
    "ksb": ["118"],
    "laf": ["118"],
    "lilu": ["118"],
    "lulu": ["118"],
    "mczt": ["118"],
    "md": ["118"],
    "mey": ["118"],
    "mgt": ["118"],
    "midv": ["118"],
    "miim": ["118"],
    "mimk": ["118"],
    "mism": ["118"],
    "mkmp": ["118"],
    "mmgh": ["118"],
    "mmsl": ["118"],
    "mvsd": ["118"],
    "nkk": ["118"],
    "nsps": ["118"],
    "nvh": ["118"],
    "ofje": ["118"],
    "okb": ["118"],
    "onhr": ["118"],
    "pbd": ["118"],
    "pd": ["118"],
    "pgd": ["118"],
    "pkse": ["118"],
    "ppbd": ["118"],
    "pppe": ["118"],
    "pred": ["118"],
    "prtd": ["118"],
    "rbd": ["118"],
    "rbk": ["118"],
    "rctd": ["118"],
    "reys": ["118"],
    "royz": ["118"],
    "sac": ["118"],
    "sdab": ["118"],
    "sdam": ["118"],
    "sdde": ["118"],
    "sdmf": ["118"],
    "sdmua": ["118"],
    "shic": ["118"],
    "shkd": ["118"],
    "siv": ["118"],
    "skhj": ["118"],
    "sma": ["118"],
    "soe": ["118"],
    "sone": ["118"],
    "sqis": ["118"],
    "ssis": ["118"],
    "stars": ["118"],
    "start": ["118"],
    "svis": ["118"],
    "tbf": ["118"],
    "tkt": ["118"],
    "tmn": ["118"],
    "tora": ["118"],
    "tt": ["118"],
    "und": ["118"],
    "vnds": ["118"],
    "vv": ["118"],
    "wanz": ["118"],
    "wss": ["118"],
    "xvsr": ["118"],
    "ymdd": ["118"],
}


def _normalize_r18_id(id_: str) -> str:
    raw = re.sub(r"[-_\s]", "", str(id_ or "").lower())
    m = re.match(r"^([a-z]+)(\d+)$", raw)
    if not m:
        return raw
    return f"{m.group(1)}{int(m.group(2)):05d}"


def _parse_series_number(id_: str) -> tuple[str, str]:
    raw = re.sub(r"[-_\s]", "", str(id_ or "").lower())
    m = re.match(r"^([a-z]+)(\d+)$", raw)
    return (m.group(1), m.group(2)) if m else ("", "")


def _generate_content_id_variations(id_: str) -> list[str]:
    raw = re.sub(r"[-_\s]", "", str(id_ or "").lower())
    m = re.match(r"^([a-z]+)(\d+)$", raw)
    if not m:
        return []
    series = m.group(1)
    num_int = int(m.group(2))
    padded3 = f"{num_int:03d}"
    padded5 = f"{num_int:05d}"
    prefixes = CONTENT_ID_PREFIXES.get(series, ["", "1"])
    seen: set[str] = set()
    out: list[str] = []
    for p in prefixes:
        for v in (f"{p}{series}{padded5}", f"{p}{series}{padded3}"):
            if v not in seen:
                seen.add(v)
                out.append(v)
    return out


def _build_dvd_search_url(code: str) -> str:
    return f"{API_BASE}/videos/vod/movies/detail/-/dvd_id={_normalize_r18_id(code)}/json"


def _build_combined_url(content_id: str) -> str:
    return f"{API_BASE}/videos/vod/movies/detail/-/combined={quote(str(content_id), safe='')}/json"


def _resolve_detail_url(search: dict[str, Any], code: str) -> str | None:
    content_id = search.get("content_id") or search.get("dvd_id")
    if not content_id:
        return None
    return _build_combined_url(str(content_id))


def _format_r18_number(dvd_id: str) -> str:
    number = str(dvd_id or "").upper().replace("-", "")
    m = re.match(r"^([A-Z]+)\d+$", number)
    if m:
        series, num_str = _parse_series_number(dvd_id)
        if series and num_str:
            number = f"{series.upper()}-{int(num_str):03d}"
    return number


def _fetch_r18_json(url: str, cookie: str = "") -> dict[str, Any] | None:
    try:
        data = fetch_json(url, cookie=cookie or None, source_id="r18dev")
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del base_url, api_key
    trimmed = str(code or "").strip().upper()
    if not trimmed:
        raise RuntimeError("番号为空")

    detail: dict[str, Any] | None = None

    search = _fetch_r18_json(_build_dvd_search_url(trimmed), cookie)
    if search:
        detail_url = _resolve_detail_url(search, trimmed) or ""
        if detail_url:
            detail = _fetch_r18_json(detail_url, cookie)
        if not (detail and (detail.get("title_ja") or detail.get("title_en"))) and search.get("title_ja"):
            detail = search

    if not detail or not (detail.get("dvd_id") or detail.get("title_ja") or detail.get("title_en")):
        for cid in _generate_content_id_variations(trimmed):
            hit = _fetch_r18_json(_build_combined_url(cid), cookie)
            if not hit:
                continue
            if hit.get("content_id") and (hit.get("dvd_id") or hit.get("title_ja") or hit.get("title_en")):
                detail = hit
                break

    if not detail:
        raise RuntimeError("未找到")

    dvd_id = str(detail.get("dvd_id") or trimmed)
    number = _format_r18_number(dvd_id) or std_code(trimmed) or trimmed

    title_ja = str(detail.get("title_ja") or "").strip()
    title_en = str(detail.get("title_en_uncensored") or detail.get("title_en") or "").strip()
    title_raw = title_ja or title_en
    if not title_raw:
        raise RuntimeError("未找到标题")

    actors: list[str] = []
    for a in detail.get("actresses") or []:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name_kanji") or a.get("name_romaji") or "").strip()
        if name:
            actors.append(name)
    actress = str(detail.get("actress") or "").strip()
    if actress and actress not in actors:
        actors.append(actress)

    tags = []
    for c in detail.get("categories") or []:
        if not isinstance(c, dict):
            continue
        g = str(c.get("name_ja") or c.get("name_en") or "").strip()
        if g:
            tags.append(g)

    cover = (
        str(detail.get("jacket_full_url") or "").strip()
        or str(
            ((detail.get("images") or {}).get("jacket_image") or {}).get("large2")
            or ((detail.get("images") or {}).get("jacket_image") or {}).get("large")
            or ""
        ).strip()
    )

    studio = str(detail.get("maker_name_ja") or detail.get("maker_name_en") or "").strip() or None
    premiered = str(detail.get("release_date") or "")[:10]
    date = premiered if re.match(r"^\d{4}-\d{2}-\d{2}", premiered) else None

    return make_detail(
        source="r18dev",
        code=number,
        title=title_raw,
        poster=cover or None,
        studio=studio,
        actors=actors,
        tags=tags,
        date=date,
    )
