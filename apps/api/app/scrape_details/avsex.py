# -*- coding: utf-8 -*-
"""AVSex 详情（中文元数据）。"""

from __future__ import annotations

import re
from urllib.parse import quote

from .common import (
    abs_url,
    clean_title,
    fetch_html,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    pick_og_image,
    soup,
    strip_tags,
)

DEFAULT_BASE = "https://avsex.cc"


def normalize_avsex_code(code: str) -> str:
    c = str(code or "").strip()
    if re.match(r"^n\d{4}$", c, re.I):
        return c.lower()
    return c.upper()


def match_search_title(title: str, code: str) -> bool:
    std = normalize_avsex_code(code)
    t = title.strip()
    if not t:
        return False
    upper = t.upper()
    if upper.startswith(std.upper()):
        return True
    if f"{std.upper()}-" in upper and re.match(r"^\d", t):
        return True
    return False


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    std = normalize_avsex_code(code)
    base = (base_url or DEFAULT_BASE).rstrip("/")
    search_url = f"{base}/tw/search?query={quote(std)}"
    html = fetch_html(search_url, referer=f"{base}/tw/", cookie=cookie or None, source_id="avsex")
    doc = soup(html)
    detail_url = ""
    poster = ""
    for a in doc.select("a[href*='/video/detail/']"):
        title = strip_tags(a.select_one("h4.truncate").get_text() if a.select_one("h4.truncate") else "")
        if not match_search_title(title, std):
            continue
        href = a.get("href") or ""
        if not href:
            continue
        detail_url = abs_url(href, base) or ""
        img = a.select_one("div.relative.overflow-hidden img")
        if img:
            poster = abs_url(img.get("src"), base) or ""
        break
    if not detail_url:
        raise RuntimeError("avsex 搜索无结果")
    detail_html = fetch_html(
        detail_url, referer=search_url, cookie=cookie or None, source_id="avsex"
    )
    d = soup(detail_html)
    title = ""
    h2 = d.select_one("article h2.text-xl")
    if h2:
        title = clean_title(h2.get_text(" ", strip=True), std)
    if is_junk_title(title):
        title = ""

    def dl_links(label: re.Pattern[str]) -> list[str]:
        out: list[str] = []
        for dt in d.select("dl dt"):
            if not label.search(strip_tags(dt.get_text())):
                continue
            dd = dt.find_next_sibling("dd")
            if dd is None:
                continue
            for a in dd.select("a[title], a"):
                t = (a.get("title") or "").strip() or strip_tags(a.get_text())
                if t and t != "N/A":
                    out.append(t)
        return list(dict.fromkeys(out))

    def dl_text(label: re.Pattern[str]) -> str:
        for dt in d.select("dl dt"):
            if not label.search(strip_tags(dt.get_text())):
                continue
            dd = dt.find_next_sibling("dd")
            if dd is None:
                continue
            return strip_tags(dd.get_text())
        return ""

    actors = dl_links(re.compile(r"演員|演员"))
    genres = dl_links(re.compile(r"標籤|标签|類別|类别"))
    studio = dl_text(re.compile(r"製作商|制作商"))
    if studio == "N/A":
        studio = ""
    plot = ""
    for h in d.select("h2"):
        if re.search(r"劇情簡介|剧情简介", strip_tags(h.get_text())):
            p = h.find_next_sibling("p")
            if p is not None:
                plot = strip_tags(p.get_text())
            break
    cover = pick_og_image(detail_html) or poster
    if cover:
        cover = abs_url(cover, base)
    if cover and is_junk_cover_url(cover):
        cover = None
    if not title and not cover and not actors:
        raise RuntimeError("avsex 详情解析失败")
    return make_detail(
        source="avsex",
        code=std,
        title=title or None,
        poster=cover,
        studio=studio or None,
        actors=actors,
        tags=genres,
        overview=plot if len(plot) >= 12 else None,
    )
