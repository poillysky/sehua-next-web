# -*- coding: utf-8 -*-
"""JavLibrary 详情刮削（对齐 MDCS javlibrary.ts）。"""

from __future__ import annotations

import re
from urllib.parse import quote, urlparse

from .common import (
    abs_url,
    clean_title,
    code_key,
    fetch_html_result,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    std_code,
    strip_tags,
    soup,
)

DEFAULT_BASE = "https://www.javlibrary.com/tw"
SOURCE = "javlibrary"


def _lang_base(base: str) -> str:
    return re.sub(r"/(ja|cn|tw)(?:/main\.php)?$", "", base.rstrip("/"), flags=re.I)


def _lang_path(base_url: str) -> str:
    """从配置 URL 取语种；默认 tw（繁体站较稳）。"""
    m = re.search(r"/(ja|cn|tw)(?:/main\.php)?/?$", str(base_url or "").rstrip("/"), re.I)
    if m:
        return m.group(1).lower()
    return "tw"


def _same_netloc(a: str, b: str) -> bool:
    try:
        ha = urlparse(a).hostname or ""
        hb = urlparse(b).hostname or ""
        return ha.replace("www.", "").lower() == hb.replace("www.", "").lower()
    except Exception:
        return False


def _is_detail_url(url: str) -> bool:
    return bool(re.search(r"/\?v=jav", url, re.I) or re.search(r"/jav[a-z0-9]+\.html", url, re.I))


def _code_token(code: str) -> str:
    return std_code(code).replace("-", "").upper() + " "


def _is_detail_html(html: str) -> bool:
    if not html or len(html) < 800:
        return False
    if re.search(r"Just a moment|cf-browser-verification|Attention Required", html, re.I):
        return False
    return bool(
        re.search(r'id=["\']video_title["\']', html)
        and re.search(r"video_jacket_img|video_id", html)
    )


def pick_javlibrary_detail_url(html: str, code: str, origin: str) -> str | None:
    doc = soup(html)
    token = _code_token(code).strip()
    base = origin.rstrip("/")

    for a in doc.select("#video_title h3 a"):
        text = strip_tags(a.get_text())
        if token in text.replace("-", "").upper():
            href = a.get("href") or ""
            if href:
                return abs_url(href, base) or href

    fallback = ""
    std = std_code(code)
    for a in doc.select("div.video[id] a"):
        box = a.find_parent("div", class_="video")
        if box is None:
            continue
        id_el = box.select_one("div.id")
        id_text = strip_tags(id_el.get_text()) if id_el else ""
        if id_text and code_key(id_text) != code_key(std):
            continue
        title = a.get("title") or strip_tags(a.get_text())
        if title and token not in title.replace("-", "").upper():
            continue
        if "ブルーレイディスク" in title:
            continue
        href = a.get("href") or ""
        if href:
            fallback = abs_url(href, base) or href
    if fallback:
        return fallback

    for a in doc.select("a[href*='/?v=jav'], a[href*='.html']"):
        title = a.get("title") or strip_tags(a.get_text())
        if token not in title.replace("-", "").upper():
            continue
        if "ブルーレイディスク" in title:
            continue
        href = a.get("href") or ""
        if href:
            fallback = abs_url(href, base) or href
    return fallback or None


def _parse_detail(html: str, detail_url: str, code: str) -> dict | None:
    if not _is_detail_html(html):
        return None
    doc = soup(html)
    std = std_code(code)

    page_num_el = doc.select_one("#video_id td.text")
    page_num = strip_tags(page_num_el.get_text()) if page_num_el else ""
    if page_num and code_key(page_num) != code_key(std):
        return None

    title_el = doc.select_one("#video_title h3 a")
    title = strip_tags(title_el.get_text()) if title_el else ""
    if page_num:
        title = re.sub(rf"^{re.escape(page_num)}\s*", "", title).strip()
    title = clean_title(title, std)
    if is_junk_title(title):
        title = ""

    actors = []
    for a in doc.select("#video_cast span.star a"):
        n = strip_tags(a.get_text())
        if n and len(n) <= 40 and n not in actors:
            actors.append(n)

    genres = []
    for a in doc.select("#video_genres td.text span a"):
        g = strip_tags(a.get_text())
        if g and g not in genres:
            genres.append(g)

    date_el = doc.select_one("#video_date td.text")
    premiered = strip_tags(date_el.get_text()) if date_el else ""
    maker_el = doc.select_one("#video_maker td.text span a")
    studio = strip_tags(maker_el.get_text()) if maker_el else ""
    label_el = doc.select_one("#video_label td.text span a")
    publisher = strip_tags(label_el.get_text()) if label_el else ""
    runtime_el = doc.select_one("#video_length span.text")
    runtime_raw = strip_tags(runtime_el.get_text()) if runtime_el else ""
    try:
        runtime = int(runtime_raw) if runtime_raw else None
    except ValueError:
        runtime = None
    score_el = doc.select_one("#video_review span.score")
    rating_raw = strip_tags(score_el.get_text()).replace("(", "").replace(")", "") if score_el else ""
    try:
        rating = float(rating_raw) if rating_raw else None
    except ValueError:
        rating = None
    votes_el = doc.select_one('a[href*="userswanted.php"]')
    votes_raw = strip_tags(votes_el.get_text()) if votes_el else ""
    votes = votes_raw if votes_raw.isdigit() else None
    director_el = doc.select_one("#video_director td.text span a")
    director = strip_tags(director_el.get_text()) if director_el else ""

    img = doc.select_one("#video_jacket_img")
    cover = img.get("src") if img else ""
    if cover.startswith("//"):
        cover = f"https:{cover}"
    cover = abs_url(cover, detail_url) or cover
    if cover and is_junk_cover_url(cover):
        cover = None
    if not cover:
        cover = None

    if not title and not cover and not actors:
        return None

    extra: dict = {
        "publisher": publisher or None,
        "directors": [director] if director else None,
        "runtime": runtime,
        "mosaic": "有码",
        "titleZh": title or None,
    }
    if rating is not None:
        # 源站分数多为 /10（如 8.30），直接沿用，不再按 /5 ×2
        extra.update(
            {
                "ratingValue": rating,
                "ratingMax": 10,
                "ratingSource": "javlibrary",
                "score": rating,
                "votes": votes,
            }
        )

    return make_detail(
        source=SOURCE,
        code=std,
        title=title or None,
        poster=cover,
        studio=studio or None,
        actors=actors,
        tags=genres,
        date=premiered or None,
        extra=extra,
    )


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    raw_base = base_url or DEFAULT_BASE
    base = _lang_base(raw_base)
    if not base:
        raise RuntimeError("未配置网站地址")
    std = std_code(code)
    if not std:
        raise RuntimeError("番号为空")
    ck = cookie or None
    lang_path = _lang_path(raw_base)
    search_url = f"{base}/{lang_path}/vl_searchbyid.php?keyword={quote(std)}"
    search_html, final_url = fetch_html_result(
        search_url,
        referer=f"{base}/{lang_path}/",
        cookie=ck,
        source_id=SOURCE,
    )

    detail_url: str | None = None
    detail_html = ""

    if final_url != search_url and _is_detail_url(final_url) and _same_netloc(final_url, search_url):
        detail_url = final_url
        detail_html = search_html
    elif _is_detail_html(search_html):
        detail_url = final_url
        detail_html = search_html
    else:
        detail_url = pick_javlibrary_detail_url(
            search_html, std, f"{base}/{lang_path}"
        )
        if detail_url:
            detail_html, landed = fetch_html_result(
                detail_url, referer=search_url, cookie=ck, source_id=SOURCE
            )
            detail_url = landed or detail_url

    if not detail_url or not _is_detail_html(detail_html):
        raise RuntimeError("未找到")

    parsed = _parse_detail(detail_html, detail_url, std)
    if not parsed:
        raise RuntimeError("解析失败")

    website = detail_url.replace(base, "https://www.javlibrary.com") if base != "https://www.javlibrary.com" else detail_url
    parsed["website"] = website
    return parsed
