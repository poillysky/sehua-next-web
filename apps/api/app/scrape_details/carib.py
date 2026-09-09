# -*- coding: utf-8 -*-
"""Caribbeancom 详情刮削（对齐 MDCS carib.ts）。"""

from __future__ import annotations

import re

from .common import (
    abs_url,
    clean_title,
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
PLOT_BOILERPLATE = re.compile(r"動画詳細ページ|見放題|無修正動画|details?\s*page|sample\s*movie|お楽しみ", re.I)


def _collect_by_re(html: str, pattern: re.Pattern[str]) -> list[str]:
    out: list[str] = []
    for m in pattern.finditer(html or ""):
        val = strip_tags(m.group(1) or "")
        if val and val not in out:
            out.append(val)
    return out


def _parse_movie_key(code: str) -> str | None:
    raw = str(code or "").strip()
    m = re.match(r"^CARIB[-_]?(\d{6}-\d{3})$", raw, re.I) or re.match(r"^(\d{6}-\d{3})$", raw)
    return m.group(1) if m else None


def _parse_premiered_from_key(key: str) -> str | None:
    m = re.match(r"^(\d{2})(\d{2})(\d{2})-\d{3}$", str(key or ""))
    if not m:
        return None
    mm, dd, yy = m.group(1), m.group(2), m.group(3)
    return f"20{yy}-{mm.zfill(2)}-{dd.zfill(2)}"


def _detail_url(base: str, key: str) -> str:
    b = str(base or DEFAULT_BASE).rstrip("/")
    return f"{b}/moviepages/{key}/index.html"


def _is_detail_html(html: str, key: str) -> bool:
    if not html or len(html) < 4000:
        return False
    if not re.search(r'itemprop=["\']name["\']', html) and not re.search(r"movie-spec", html):
        return False
    page_id_m = re.search(r'movie_id\\?"\s*:\s*\\?"(\d{6}-\d{3})', html, re.I) or re.search(
        r"/moviepages/(\d{6}-\d{3})/", html, re.I
    )
    page_id = page_id_m.group(1) if page_id_m else ""
    return (not page_id) or page_id == key


def _parse_actors(html: str) -> list[str]:
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


def _parse_genres(html: str) -> list[str]:
    return [
        g
        for g in _collect_by_re(html, re.compile(r'itemprop=["\']genre["\'][^>]*>([^<]+)<', re.I))
        if g and len(g) <= 40
    ][:40]


def _parse_plot(html: str) -> str:
    doc = soup(html)
    desc = doc.select_one('p[itemprop="description"]')
    plot = strip_tags(desc.get_text() if desc else "")
    if not plot or len(plot) < 12 or PLOT_BOILERPLATE.search(plot):
        meta = doc.select_one('meta[name="description"]')
        plot = strip_tags((meta.get("content") if meta else "") or "")
    if not plot or len(plot) < 12 or PLOT_BOILERPLATE.search(plot):
        return ""
    return plot


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    key = _parse_movie_key(code)
    if not key:
        raise RuntimeError("番号格式无效")

    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")

    detail_url = _detail_url(base, key)
    try:
        html = fetch_html(detail_url, referer=f"{base}/", cookie=cookie or None, source_id="carib")
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}") from e

    if not _is_detail_html(html, key):
        raise RuntimeError("未找到")

    doc = soup(html)
    h1 = doc.select_one('h1[itemprop="name"]')
    title = clean_title(strip_tags(h1.get_text() if h1 else "") or pick_og_title(html), code)
    if is_junk_title(title):
        title = ""

    actors = _parse_actors(html)
    tags = _parse_genres(html)

    plot = _parse_plot(html)
    premiered = _parse_premiered_from_key(key)

    cover = pick_og_image(html) or None
    if not cover:
        m = re.search(r"/moviepages/[\d-]+/images/l_l\.jpg", html, re.I)
        cover = m.group(0) if m else f"/moviepages/{key}/images/l_l.jpg"
    cover = abs_url(cover, detail_url) or cover
    if cover and is_junk_cover_url(cover):
        cover = None

    if not title and not cover and not actors and not tags:
        raise RuntimeError("未找到")

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
    )
