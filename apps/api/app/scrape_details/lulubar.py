# -*- coding: utf-8 -*-
"""LuluBar 详情。"""

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

DEFAULT_BASE = "https://lulubar.co"
IMAGE_HOST = "https://image.lulubar.co"


def _norm_cover(raw: str | None, detail_url: str) -> str | None:
    u = str(raw or "").strip()
    if not u:
        return None
    if u.startswith(("http://", "https://")):
        return None if is_junk_cover_url(u) else u
    if u.startswith("/films/"):
        cdn = f"{IMAGE_HOST}{u}"
        return None if is_junk_cover_url(cdn) else cdn
    abs_u = abs_url(u, detail_url)
    if not abs_u or is_junk_cover_url(abs_u):
        return None
    return abs_u


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    std = std_code(code)
    want = code_key(std)
    base = (base_url or DEFAULT_BASE).rstrip("/")
    search_url = f"{base}/video/bysearch?search={quote(std)}&page=1"
    html = fetch_html(
        search_url, referer=f"{base}/", cookie=cookie or None, source_id="lulubar"
    )
    if re.search(r"的搜寻结果\s*\(\s*0\s*\)", html, re.I):
        raise RuntimeError("lulubar 搜索无结果")
    doc = soup(html)
    best = ""
    best_score = -1
    for a in doc.select("a.imgBoxW[href*='/video/detail?id=']"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        text = " ".join(
            [
                strip_tags(a.get("title") or ""),
                strip_tags((a.select_one("img") or {}).get("alt") if a.select_one("img") else ""),
                strip_tags(a.get_text(" ", strip=True)),
            ]
        )
        blob = code_key(text + " " + href)
        score = 0
        if want and want in blob:
            score += 50
        if want and blob.startswith(want):
            score += 20
        if score > best_score:
            best_score = score
            best = href
    if not best or best_score <= 0:
        raise RuntimeError("lulubar 搜索无匹配")
    detail_url = abs_url(best, base) or best
    detail_html = fetch_html(
        detail_url, referer=search_url, cookie=cookie or None, source_id="lulubar"
    )
    d = soup(detail_html)
    title = clean_title(
        strip_tags((d.select_one("h1, .video-title, title") or d).get_text(" ", strip=True)),
        std,
    )
    if is_junk_title(title):
        title = ""
    actors: list[str] = []
    for a in d.select("a[href*='actress'], a[href*='actor'], .actor a"):
        n = strip_tags(a.get_text())
        if n and 1 < len(n) < 40 and n not in actors:
            actors.append(n)
    cover = pick_og_image(detail_html)
    cover = _norm_cover(cover, detail_url)
    if not cover:
        img = d.select_one("img.poster, .cover img, video[poster]")
        if img is not None:
            cover = _norm_cover(img.get("poster") or img.get("src"), detail_url)
    if not title and not cover:
        raise RuntimeError("lulubar 详情解析失败")
    return make_detail(
        source="lulubar",
        code=std,
        title=title or None,
        poster=cover,
        actors=actors,
    )
