# -*- coding: utf-8 -*-
"""R18.dev 详情刮削（对齐 MDCS r18dev.ts）。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from .common import fetch_json, make_detail, std_code
from app.core.maps_paths import load_json_map

API_BASE = "https://r18.dev"

# MDCX r18dev.py _content_id_prefixes
CONTENT_ID_PREFIXES: dict[str, list[str]] = {
    str(k): [str(x) for x in (v if isinstance(v, list) else [v])]
    for k, v in dict(load_json_map("r18-content-id-prefixes.json")).items()
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


def _r18_detail_matches_code(detail: dict[str, Any] | None, code: str) -> bool:
    """拒绝 dvd_id=juk00400 却命中 content_id=juk004（JUK-004）这类错配。"""
    if not isinstance(detail, dict):
        return False
    want = std_code(code)
    if not want:
        return False
    dvd = str(detail.get("dvd_id") or "").strip()
    if dvd:
        return std_code(dvd) == want
    series, num = _parse_series_number(code)
    if not series or not num:
        return True
    cid = str(detail.get("content_id") or "").strip().lower()
    if not cid:
        return False
    m = re.search(r"([a-z]+)(\d+)$", cid)
    if not m:
        return False
    return m.group(1) == series and int(m.group(2)) == int(num)


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


def _parse_r18_movie(detail: dict[str, Any], fallback_code: str) -> dict[str, Any]:
    """对齐 MDCS parseR18MovieJson。"""
    from .common import clean_title, is_junk_cover_url, is_junk_title

    dvd_id = str(detail.get("dvd_id") or fallback_code)
    number = _format_r18_number(dvd_id) or std_code(fallback_code) or fallback_code

    title_ja = str(detail.get("title_ja") or "").strip()
    title_en = str(detail.get("title_en_uncensored") or detail.get("title_en") or "").strip()
    title_raw = title_ja or title_en
    title = clean_title(title_raw, number)
    if not title or is_junk_title(title):
        raise RuntimeError("未找到标题")

    actors: list[str] = []
    for a in detail.get("actresses") or []:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name_kanji") or a.get("name_romaji") or "").strip()
        if name and name not in actors:
            actors.append(name)
    actress = str(detail.get("actress") or "").strip()
    if actress and actress not in actors:
        actors.append(actress)

    directors: list[str] = []
    for d in detail.get("directors") or []:
        if not isinstance(d, dict):
            continue
        name = str(d.get("name_kanji") or d.get("name_romaji") or "").strip()
        if name and name not in directors:
            directors.append(name)

    tags: list[str] = []
    for c in detail.get("categories") or []:
        if not isinstance(c, dict):
            continue
        g = str(c.get("name_ja") or c.get("name_en") or "").strip()
        if g and g not in tags:
            tags.append(g)

    cover = (
        str(detail.get("jacket_full_url") or "").strip()
        or str(
            ((detail.get("images") or {}).get("jacket_image") or {}).get("large2")
            or ((detail.get("images") or {}).get("jacket_image") or {}).get("large")
            or ""
        ).strip()
    )
    if cover and is_junk_cover_url(cover):
        cover = ""

    trailer = str(
        detail.get("sample_url")
        or ((detail.get("sample") or {}).get("high") if isinstance(detail.get("sample"), dict) else "")
        or ((detail.get("sample") or {}).get("low") if isinstance(detail.get("sample"), dict) else "")
        or ""
    ).strip()
    if trailer.startswith("//"):
        trailer = f"https:{trailer}"

    extras = [
        str(g.get("image_full") or "").strip()
        for g in (detail.get("gallery") or [])
        if isinstance(g, dict)
        and str(g.get("image_full") or "").strip()
        and re.search(r"\.(jpe?g|png|webp)(?:\?|$)", str(g.get("image_full") or ""), re.I)
    ]
    extras = list(dict.fromkeys(extras))

    runtime_raw = detail.get("runtime_mins")
    runtime = int(runtime_raw) if isinstance(runtime_raw, (int, float)) and runtime_raw > 0 else None
    premiered = str(detail.get("release_date") or "")[:10]
    date = premiered if re.match(r"^\d{4}-\d{2}-\d{2}", premiered) else None

    content_id = str(detail.get("content_id") or "").strip()
    publisher = (
        str(detail.get("label_name_ja") or detail.get("label_name_en") or "").strip() or None
    )
    series = (
        str(
            detail.get("series_name_ja")
            or detail.get("series_name_en")
            or detail.get("series_name")
            or ""
        ).strip()
        or None
    )
    studio = str(detail.get("maker_name_ja") or detail.get("maker_name_en") or "").strip() or None

    return {
        "code": number,
        "title": title,
        "titleJa": title_ja or title,
        "actors": actors,
        "directors": directors,
        "tags": tags,
        "cover": cover or None,
        "studio": studio,
        "publisher": publisher,
        "series": series,
        "date": date,
        "runtime": runtime,
        "trailer": trailer or None,
        "website": _build_combined_url(content_id) if content_id else None,
        "extras": extras or None,
    }


def _upgrade_r18_cover(code: str, cover_url: str | None) -> str | None:
    """DMM jacket 优先升级到 pl（对齐 MDCS upgradeR18Cover，轻量不探测）。"""
    if not cover_url or not re.search(r"dmm\.(?:co\.jp|com)", cover_url, re.I):
        return cover_url
    if re.search(r"pl\.jpe?g", cover_url, re.I):
        return cover_url
    try:
        from .dmm import guess_dmm_cids

        for cid in guess_dmm_cids(code):
            pl = f"https://pics.dmm.co.jp/digital/video/{cid}/{cid}pl.jpg"
            return pl
    except Exception:
        pass
    # ps → pl 同路径替换
    up = re.sub(r"ps(\.jpe?g)(?:\?|$)", r"pl\1", cover_url, flags=re.I)
    return up or cover_url


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del base_url, api_key
    trimmed = str(code or "").strip().upper()
    if not trimmed:
        raise RuntimeError("番号为空")

    detail: dict[str, Any] | None = None

    search = _fetch_r18_json(_build_dvd_search_url(trimmed), cookie)
    if search and _r18_detail_matches_code(search, trimmed):
        detail_url = _resolve_detail_url(search, trimmed) or ""
        if detail_url:
            hit = _fetch_r18_json(detail_url, cookie)
            if hit and _r18_detail_matches_code(hit, trimmed):
                detail = hit
        if not (detail and (detail.get("title_ja") or detail.get("title_en"))) and search.get(
            "title_ja"
        ):
            detail = search
    elif search and not _r18_detail_matches_code(search, trimmed):
        search = None

    if not detail or not (detail.get("dvd_id") or detail.get("title_ja") or detail.get("title_en")):
        for cid in _generate_content_id_variations(trimmed):
            hit = _fetch_r18_json(_build_combined_url(cid), cookie)
            if not hit or not _r18_detail_matches_code(hit, trimmed):
                continue
            if hit.get("content_id") and (
                hit.get("dvd_id") or hit.get("title_ja") or hit.get("title_en")
            ):
                detail = hit
                break

    if not detail or not _r18_detail_matches_code(detail, trimmed):
        raise RuntimeError("未找到")

    parsed = _parse_r18_movie(detail, trimmed)
    cover = _upgrade_r18_cover(trimmed, parsed.get("cover"))

    extra: dict[str, Any] = {
        "originalTitle": parsed.get("titleJa"),
        "publisher": parsed.get("publisher"),
        "series": parsed.get("series"),
        "website": parsed.get("website"),
        "mosaic": "有码",
        "runtime": parsed.get("runtime"),
        "trailerUrl": parsed.get("trailer"),
        "extrafanartUrls": parsed.get("extras"),
    }
    if parsed.get("directors"):
        extra["director"] = parsed["directors"][0]
        extra["directors"] = parsed["directors"]

    return make_detail(
        source="r18dev",
        code=parsed["code"],
        title=parsed["title"],
        poster=cover,
        studio=parsed.get("studio"),
        actors=parsed.get("actors") or [],
        tags=parsed.get("tags") or [],
        date=parsed.get("date"),
        extra=extra,
    )
