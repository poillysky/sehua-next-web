# -*- coding: utf-8 -*-
"""10musume（天然むすめ）详情刮削 —— 官网 JSON API。

番号形如 `10MU-051124-01` / `10musume-051124_01` → movie_id `051124_01`。
API: `{base}/dyn/phpauto/movie_details/movie_id/{id}.json`
"""

from __future__ import annotations

import re
from typing import Any

from .common import fetch_json, is_junk_cover_url, is_junk_title, make_detail

DEFAULT_BASE = "https://www.10musume.com"
STUDIO = "天然むすめ"
_SRC = "10musume"

# 10MU-051124-01 / 10musume-051124_01 / 051124_01 / 051124-01
_KEY_RE = re.compile(
    r"^(?:10(?:MU|MUSUME)[-_]?)?(\d{6})[-_](\d{1,3})$",
    re.I,
)


def parse_tenmusume_movie_key(code: str) -> str | None:
    raw = str(code or "").strip()
    m = _KEY_RE.match(raw)
    if not m:
        return None
    seq = m.group(2).zfill(2)
    return f"{m.group(1)}_{seq}"


def tenmusume_detail_url(base: str, key: str) -> str:
    b = str(base or DEFAULT_BASE).rstrip("/")
    return f"{b}/moviepages/{key}/index.html"


def tenmusume_api_url(base: str, key: str) -> str:
    b = str(base or DEFAULT_BASE).rstrip("/")
    return f"{b}/dyn/phpauto/movie_details/movie_id/{key}.json"


def _as_str_list(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x or "").strip()]
    s = str(val or "").strip()
    return [s] if s else []


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    key = parse_tenmusume_movie_key(code)
    if not key:
        raise RuntimeError("番号格式无效")

    base = (base_url or DEFAULT_BASE).rstrip("/") or DEFAULT_BASE
    api_url = tenmusume_api_url(base, key)
    detail_url = tenmusume_detail_url(base, key)

    try:
        data = fetch_json(
            api_url,
            cookie=cookie or None,
            source_id=_SRC,
            referer=f"{base}/",
        )
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}") from e

    if not isinstance(data, dict) or not data:
        raise RuntimeError("未找到")

    movie_id = str(data.get("MovieID") or "").strip()
    if movie_id and movie_id.replace("-", "_") != key:
        raise RuntimeError("未找到")

    title = str(data.get("Title") or data.get("TitleEn") or "").strip()
    if is_junk_title(title):
        title = ""

    actors = _as_str_list(data.get("ActressesJa")) or _as_str_list(
        data.get("Actor")
    )
    if not actors:
        actors = _as_str_list(data.get("ActressesEn"))

    tags = _as_str_list(data.get("UCNAME")) or _as_str_list(data.get("UCNAMEEn"))
    overview = str(data.get("Desc") or data.get("DescEn") or "").strip()
    premiered = str(data.get("Release") or "").strip()[:10] or None
    year = str(data.get("Year") or "").strip() or None
    series = str(data.get("Series") or data.get("SeriesEn") or "").strip()

    runtime: int | None = None
    dur = data.get("Duration")
    try:
        # Duration 多为秒
        sec = float(dur)
        if sec > 0:
            runtime = max(1, round(sec / 60))
    except (TypeError, ValueError):
        runtime = None

    cover = (
        str(data.get("ThumbHigh") or data.get("ThumbUltra") or data.get("ThumbMed") or "")
        .strip()
        or None
    )
    if cover and is_junk_cover_url(cover):
        cover = None
    if not cover:
        cover = f"{base}/moviepages/{key}/images/str.jpg"

    gallery = _as_str_list(data.get("Gallery"))
    extras = [u for u in gallery if u.startswith(("http://", "https://"))][:30]

    if not title and not cover and not actors:
        raise RuntimeError("未找到")

    code_out = str(code or "").strip().upper()
    if not code_out.startswith("10MU"):
        code_out = f"10MU-{key.replace('_', '-')}"

    extra: dict[str, Any] = {
        "series": series or None,
        "website": detail_url,
        "mosaic": "无码",
        "runtime": runtime,
        "extrafanartUrls": extras or None,
        "originalPlot": overview or None,
        "titleEn": str(data.get("TitleEn") or "").strip() or None,
    }
    try:
        rating = float(data.get("AvgRating") or 0)
        if 0 < rating <= 5:
            extra.update(
                {
                    "ratingValue": rating,
                    "ratingMax": 5,
                    "ratingSource": _SRC,
                    "score": rating,
                }
            )
    except (TypeError, ValueError):
        pass

    return make_detail(
        source=_SRC,
        code=code_out,
        title=title or None,
        poster=cover,
        studio=STUDIO,
        actors=actors,
        tags=tags,
        overview=overview or None,
        date=premiered,
        year=year,
        extra=extra,
    )
