# -*- coding: utf-8 -*-
"""JavDay 详情刮削（对齐 MDCS javday.ts）。"""

from __future__ import annotations

import re
from urllib.parse import quote

from .common import (
    abs_url,
    clean_title,
    code_key,
    fetch_html,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    pick_og_image,
    soup,
    std_code,
    strip_tags,
)

DEFAULT_BASE = "https://javday.app"


def _javday_path_code(code: str) -> str:
    return std_code(code).replace("-", "").upper()


def _javday_url_path_codes(code: str) -> list[str]:
    std = std_code(code)
    out: list[str] = []
    seen: set[str] = set()

    def _add(v: str) -> None:
        if v and v not in seen:
            seen.add(v)
            out.append(v)

    _add(_javday_path_code(std))
    if re.match(r"^FC2", std, re.I):
        _add(re.sub(r"\s+", "-", std).upper())
    m = re.match(r"^([A-Z]{2,12})-(\d{2,}[A-Z0-9]*)$", std, re.I)
    if m:
        _add(f"{m.group(1)}{m.group(2)}".upper())
    return out


def _is_detail_html(html: str) -> bool:
    if not html or len(html) < 2000:
        return False
    if re.search(r"荒原|沒有視頻|没有视频|aks-404-page", html, re.I):
        return False
    return bool(re.search(r'id=["\']videoInfo["\']', html) and re.search(r"video-title|jpnum", html))


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    std = std_code(code)
    if not std:
        raise RuntimeError("番号为空")

    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")

    detail_html = ""
    detail_url = ""
    for path_code in _javday_url_path_codes(std):
        url = f"{base}/videos/{quote(path_code)}/"
        try:
            html = fetch_html(url, referer=f"{base}/", cookie=cookie or None, source_id="javday")
        except Exception:
            continue
        if _is_detail_html(html):
            detail_html = html
            detail_url = url
            break

    if not detail_html:
        raise RuntimeError("未找到")

    doc = soup(detail_html)
    page_code = strip_tags(doc.select_one(".jpnum").get_text() if doc.select_one(".jpnum") else "")
    if page_code and code_key(page_code) != code_key(std):
        raise RuntimeError("番号不匹配")

    title_el = doc.select_one("#videoInfo h1.video-title") or doc.select_one("#videoInfo h1")
    title = strip_tags(title_el.get_text() if title_el else "")
    title = clean_title(re.sub(rf"^{re.escape(std).replace('-', '[-]?')}\s*", "", title, flags=re.I), std)
    if is_junk_title(title):
        title = ""

    actors: list[str] = []
    for a in doc.select(".vod_actor a"):
        n = strip_tags(a.get_text())
        if n and n != "N/A" and not re.search(r"未知", n):
            if n not in actors:
                actors.append(n)
    actors = actors[:20]

    tags: list[str] = []
    for a in doc.select("#videoInfo .tag a"):
        g = strip_tags(a.get_text())
        if g and len(g) <= 40 and g not in tags:
            tags.append(g)
    tags = tags[:40]

    meta_desc = doc.select_one('meta[name="description"]')
    meta_og = doc.select_one('meta[property="og:description"]')
    plot = strip_tags(
        (meta_desc.get("content") if meta_desc else "")
        or (meta_og.get("content") if meta_og else "")
        or ""
    )
    plot = re.sub(rf"^{re.escape(std).replace('-', '[-]?')}\s*", "", plot, flags=re.I).strip()
    if len(plot) < 8 or (re.search(r"JAVDAY|免費高清|在线看", plot, re.I) and len(plot) < 40):
        plot = ""

    cover = pick_og_image(detail_html) or ""
    if cover:
        cover = abs_url(cover, detail_url) or cover
    if cover and is_junk_cover_url(cover):
        cover = ""

    if not title and not cover and not actors and not tags:
        raise RuntimeError("解析失败")

    return make_detail(
        source="javday",
        code=std,
        title=title or None,
        poster=cover or None,
        actors=actors,
        tags=tags,
        overview=plot or None,
    )
