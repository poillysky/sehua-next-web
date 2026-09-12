# -*- coding: utf-8 -*-
"""Caribbeancom 详情刮削（对齐 MDCS carib.ts）。"""

from __future__ import annotations

import re
from typing import Any

from .common import (
    abs_url,
    clean_title,
    collect_by_re,
    fetch_html,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    pick_og_image,
    pick_og_title,
    soup,
    strip_tags,
)

DEFAULT_BASE = "https://www.caribbeancom.com"
STUDIO = "カリビアンコム"
PLOT_BOILERPLATE = re.compile(
    r"動画詳細ページ|見放題|無修正動画|details?\s*page|sample\s*movie|お楽しみ", re.I
)


def parse_carib_movie_key(code: str) -> str | None:
    raw = str(code or "").strip()
    m = re.match(r"^CARIB[-_]?(\d{6}-\d{3})$", raw, re.I) or re.match(
        r"^(\d{6}-\d{3})$", raw
    )
    return m.group(1) if m else None


def parse_carib_premiered_from_key(key: str) -> str | None:
    m = re.match(r"^(\d{2})(\d{2})(\d{2})-\d{3}$", str(key or ""))
    if not m:
        return None
    mm, dd, yy = m.group(1), m.group(2), m.group(3)
    return f"20{yy}-{mm.zfill(2)}-{dd.zfill(2)}"


def parse_carib_iso_duration(raw: str) -> int | None:
    t = str(raw or "").strip()
    m = re.match(r"^T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$", t, re.I)
    if not m:
        return None
    sec = int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3) or 0)
    return max(1, round(sec / 60)) if sec > 0 else None


def carib_detail_url(base: str, key: str) -> str:
    b = str(base or DEFAULT_BASE).rstrip("/")
    return f"{b}/moviepages/{key}/index.html"


def _carib_spec_map(html: str) -> dict[str, list[str]]:
    doc = soup(html)
    out: dict[str, list[str]] = {}
    for el in doc.select("li.movie-spec"):
        title_el = el.select_one(".spec-title")
        label = strip_tags(title_el.get_text() if title_el else "")
        links = [
            strip_tags(a.get_text())
            for a in el.select(".spec-content a")
            if strip_tags(a.get_text())
        ]
        if links:
            out[label] = links
            continue
        content = el.select_one(".spec-content")
        plain = strip_tags(content.get_text() if content else "")
        if plain:
            out[label] = [plain]
    return out


def _first_spec(rows: dict[str, list[str]], *labels: str) -> str:
    for label in labels:
        for k, vals in rows.items():
            if label in k and vals:
                return vals[0]
    return ""


def parse_carib_actors(html: str) -> list[str]:
    doc = soup(html)
    out: list[str] = []
    for el in doc.select("li.movie-spec"):
        title_el = el.select_one(".spec-title")
        label = strip_tags(title_el.get_text() if title_el else "")
        if not re.search(r"出演|女優|スター|Actress", label, re.I):
            continue
        for name_el in el.select('[itemprop="name"]'):
            n = strip_tags(name_el.get_text())
            if n and 2 <= len(n) <= 40 and n not in out:
                out.append(n)
    return out[:20]


def parse_carib_genres(html: str) -> list[str]:
    return [
        g
        for g in collect_by_re(html, r'itemprop=["\']genre["\'][^>]*>([^<]+)<')
        if g and len(g) <= 40
    ][:40]


def parse_carib_plot(html: str) -> str:
    doc = soup(html)
    desc = doc.select_one('p[itemprop="description"]')
    plot = strip_tags(desc.get_text() if desc else "")
    if not plot or len(plot) < 12 or PLOT_BOILERPLATE.search(plot):
        meta = doc.select_one('meta[name="description"]')
        plot = strip_tags((meta.get("content") if meta else "") or "")
    if not plot or len(plot) < 12 or PLOT_BOILERPLATE.search(plot):
        return ""
    return plot


def parse_carib_trailer(html: str) -> str | None:
    m = re.search(
        r'sample_flash_url\\?"\s*:\s*\\?"((?:https?:\\\/\\\/|https?://)[^"\']+)\\?"',
        html or "",
        re.I,
    )
    if m:
        raw = m.group(1).replace("\\/", "/")
        if re.match(r"^https?://", raw, re.I):
            return raw
    sm = re.search(
        r"(https?://smovie\.caribbeancom\.com/sample/movies/\d{6}-\d{3}/[^\"'\s]+\.mp4)",
        html or "",
        re.I,
    )
    return sm.group(1) if sm else None


def parse_carib_rating(html: str) -> dict[str, Any] | None:
    """用户 ★ 评分；score 用源站 /5（不对齐 MDCS ×10）。"""
    doc = soup(html)
    el = doc.select_one(".meta-rating, .spec-content.rating")
    text = strip_tags(el.get_text() if el else "")
    stars = len(re.findall(r"★", text))
    if 1 <= stars <= 5:
        return {
            "ratingValue": stars,
            "ratingMax": 5,
            "ratingSource": "carib",
            "score": stars,
        }
    frac = re.search(r"(\d+(?:\.\d+)?)\s*/\s*5", text)
    if frac:
        val = float(frac.group(1))
        if 0 < val <= 5:
            return {
                "ratingValue": val,
                "ratingMax": 5,
                "ratingSource": "carib",
                "score": val,
            }
    return None


def parse_carib_extrafanart(html: str, detail_url: str) -> list[str]:
    urls = collect_by_re(
        html, r'fancy-gallery[^>]+href=["\']([^"\']+/images/l/\d+\.jpg)["\']'
    )
    out: list[str] = []
    for u in urls:
        abs_u = abs_url(u, detail_url) or u
        if abs_u and abs_u not in out:
            out.append(abs_u)
    return out[:30]


def is_carib_detail_html(html: str, key: str) -> bool:
    if not html or len(html) < 4000:
        return False
    if not re.search(r'itemprop=["\']name["\']', html) and not re.search(
        r"movie-spec", html
    ):
        return False
    page_id_m = re.search(r'movie_id\\?"\s*:\s*\\?"(\d{6}-\d{3})', html, re.I) or re.search(
        r"/moviepages/(\d{6}-\d{3})/", html, re.I
    )
    page_id = page_id_m.group(1) if page_id_m else ""
    return (not page_id) or page_id == key


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    key = parse_carib_movie_key(code)
    if not key:
        raise RuntimeError("番号格式无效")

    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")

    detail_url = carib_detail_url(base, key)
    try:
        html = fetch_html(
            detail_url, referer=f"{base}/", cookie=cookie or None, source_id="carib"
        )
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}") from e

    if not is_carib_detail_html(html, key):
        raise RuntimeError("未找到")

    doc = soup(html)
    h1 = doc.select_one('h1[itemprop="name"]')
    title = clean_title(
        strip_tags(h1.get_text() if h1 else "") or pick_og_title(html), code
    )
    if is_junk_title(title):
        title = ""

    actors = parse_carib_actors(html)
    tags = parse_carib_genres(html)
    rows = _carib_spec_map(html)
    series = _first_spec(rows, "シリーズ", "系列") or (
        collect_by_re(html, r"gaDetailEvent\('Series Name',\s*'([^']+)'") or [""]
    )[0]

    duration_el = doc.select_one('[itemprop="duration"]')
    duration_raw = (
        (duration_el.get("content") if duration_el else "")
        or _first_spec(rows, "収録時間", "播放時間", "时长")
        or ""
    )
    runtime = parse_carib_iso_duration(duration_raw)
    if runtime is None:
        hm = re.search(r"(\d{1,2}):(\d{2}):(\d{2})", duration_raw)
        if hm:
            runtime = parse_carib_iso_duration(
                f"T{hm.group(1)}H{hm.group(2)}M{hm.group(3)}S"
            )

    plot = parse_carib_plot(html)
    premiered = parse_carib_premiered_from_key(key)
    trailer = parse_carib_trailer(html)
    rating = parse_carib_rating(html)
    extras = parse_carib_extrafanart(html, detail_url)

    cover = pick_og_image(html) or None
    if not cover:
        m = re.search(r"/moviepages/[\d-]+/images/l_l\.jpg", html, re.I)
        cover = m.group(0) if m else f"/moviepages/{key}/images/l_l.jpg"
    cover = abs_url(cover, detail_url) or cover
    if cover and is_junk_cover_url(cover):
        cover = None

    if not title and not cover and not actors and not tags:
        raise RuntimeError("未找到")

    extra: dict[str, Any] = {
        "series": series or None,
        "website": detail_url,
        "mosaic": "无码",
        "runtime": runtime,
        "trailerUrl": trailer,
        "extrafanartUrls": extras or None,
        "originalPlot": plot or None,
    }
    if rating:
        extra.update(rating)

    return make_detail(
        source="carib",
        code=str(code or "").strip().upper() or f"CARIB-{key}",
        title=title or None,
        poster=cover,
        studio=STUDIO,
        actors=actors,
        tags=tags,
        overview=plot or None,
        date=premiered,
        extra=extra,
    )
