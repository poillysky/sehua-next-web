# -*- coding: utf-8 -*-
"""1pondo（一本道）详情 —— 官网 JSON API（与 10musume 同结构）。

番号：`1PON-062014-830` / `1pondo-062014_830` → movie_id `062014_830`。
"""

from __future__ import annotations

import re
from typing import Any

from .common import fetch_json, is_junk_cover_url, is_junk_title, make_detail

DEFAULT_BASE = "https://www.1pondo.tv"
STUDIO = "一本道"
_SRC = "1pondo"

_KEY_RE = re.compile(
    r"^(?:1(?:PON|PONDO)[-_]?)?(\d{6})[-_](\d{1,3})$",
    re.I,
)


def parse_1pondo_movie_key(code: str) -> str | None:
    raw = str(code or "").strip()
    m = _KEY_RE.match(raw)
    if not m:
        return None
    return f"{m.group(1)}_{m.group(2).zfill(3)}"


def _as_str_list(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x or "").strip()]
    s = str(val or "").strip()
    return [s] if s else []


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    key = parse_1pondo_movie_key(code)
    if not key:
        raise RuntimeError("番号格式无效")

    base = (base_url or DEFAULT_BASE).rstrip("/") or DEFAULT_BASE
    if "1pondo" not in base.lower():
        base = DEFAULT_BASE
    api_url = f"{base}/dyn/phpauto/movie_details/movie_id/{key}.json"
    detail_url = f"{base}/movies/{key}/"

    try:
        data = fetch_json(
            api_url, cookie=cookie or None, source_id=_SRC, referer=f"{base}/"
        )
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}") from e
    if not isinstance(data, dict) or not data:
        raise RuntimeError("未找到")

    movie_id = str(data.get("MovieID") or "").strip().replace("-", "_")
    if movie_id and movie_id != key:
        raise RuntimeError("未找到")

    title = str(data.get("Title") or data.get("TitleEn") or "").strip()
    if is_junk_title(title):
        title = ""
    actors = _as_str_list(data.get("ActressesJa")) or _as_str_list(data.get("Actor"))
    if not actors:
        actors = _as_str_list(data.get("ActressesEn"))
    tags = _as_str_list(data.get("UCNAME")) or _as_str_list(data.get("UCNAMEEn"))
    overview = str(data.get("Desc") or data.get("DescEn") or "").strip()
    premiered = str(data.get("Release") or "").strip()[:10] or None
    year = str(data.get("Year") or "").strip() or (
        premiered[:4] if premiered else None
    )
    series = str(data.get("Series") or data.get("SeriesEn") or "").strip()

    runtime: int | None = None
    try:
        sec = float(data.get("Duration") or 0)
        if sec > 0:
            runtime = max(1, round(sec / 60))
    except (TypeError, ValueError):
        runtime = None

    cover = (
        str(
            data.get("ThumbHigh")
            or data.get("ThumbUltra")
            or data.get("ThumbMed")
            or ""
        ).strip()
        or None
    )
    if cover and is_junk_cover_url(cover):
        cover = None
    if not cover:
        cover = f"{base}/assets/sample/{key}/str.jpg"

    gallery = _as_str_list(data.get("Gallery"))
    extras = [u for u in gallery if u.startswith(("http://", "https://"))][:30]
    if not title and not cover and not actors:
        raise RuntimeError("未找到")

    code_u = str(code or "").strip().upper() or f"1PON-{key.replace('_', '-')}"
    if not re.match(r"^1PON", code_u, re.I):
        code_u = f"1PON-{key.replace('_', '-')}"

    return make_detail(
        source=_SRC,
        code=code_u,
        title=title or None,
        poster=cover,
        studio=STUDIO,
        actors=actors,
        tags=tags,
        overview=overview or None,
        date=premiered,
        year=year,
        extra={
            "series": series or None,
            "website": detail_url,
            "mosaic": "无码",
            "runtime": runtime,
            "extrafanartUrls": extras or None,
            "originalPlot": overview or None,
        },
    )
