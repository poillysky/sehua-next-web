# -*- coding: utf-8 -*-
"""iQQTV 详情刮削（对齐 MDCS iqqtv.ts · CN/JP 双页）。"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import quote

from .common import (
    abs_url,
    clean_title,
    fetch_html,
    fetch_html_result,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    page_mentions_code,
    pick_og_image,
    std_code,
    strip_tags,
    soup,
)

DEFAULT_ROOT = "https://iqqk4.quest"
SOURCE = "iqqtv"

TITLE_TRAILING_MARKERS = {
    "HD",
    "FHD",
    "UHD",
    "SD",
    "VR",
    "2K",
    "4K",
    "720P",
    "1080P",
    "2160P",
}
OUTLINE_PREFIX = re.compile(r"^(?:简介|簡介|介绍|介紹|紹介)\s*[:：]?\s*")
JUNK_TITLE_RE = re.compile(r"克破|无码破解|無碼破解|无码流出|無碼流出|马赛克破坏|馬賽克破壞", re.I)
WEB_NUMBER_PREFIX = re.compile(
    r"^(?:_?1pondo|1pon|caribbeancom(?:pr)?|carib|pacopacomama|pacoma|paco|10musume|10mu)[_-]*",
    re.I,
)
WEB_NUMBER_SUFFIX = re.compile(r"^(?=.*\d)[a-z0-9]+(?:[-_][a-z0-9]+)*$", re.I)


def match_iqqtv_number(text: str, number: str) -> bool:
    """MDCX number.match_number：BF-002 不匹配 ABF-002。"""
    hay = str(text or "")
    num = str(number or "").strip()
    if not num:
        return False
    if re.match(r"^\d", num):
        return num.upper() in hay.upper()
    esc = re.escape(num)
    return bool(re.search(rf"(?<![A-Z0-9]){esc}(?![A-Z0-9])", hay, re.I))


def junk_iqqtv_title(title: str) -> bool:
    return bool(JUNK_TITLE_RE.search(title or ""))


def get_iqqtv_real_title(title: str) -> str:
    parts = title.strip().split()
    if len(parts) > 1 and parts[-1].upper() in TITLE_TRAILING_MARKERS:
        parts.pop()
    return " ".join(parts).strip()


def _clean_iqqtv_web_number_token(value: str) -> str:
    result = str(value or "").strip()
    result = re.sub(r"-PPV$", "", result, flags=re.I)
    result = WEB_NUMBER_PREFIX.sub("", result)
    return result.strip().lstrip("_-")


def _same_iqqtv_web_number(left: str, right: str) -> bool:
    a = re.sub(r"[-_]", "", _clean_iqqtv_web_number_token(left)).upper()
    b = re.sub(r"[-_]", "", _clean_iqqtv_web_number_token(right)).upper()
    return bool(a and b and a == b)


def _looks_like_iqqtv_web_number(value: str) -> bool:
    return bool(WEB_NUMBER_SUFFIX.match(_clean_iqqtv_web_number_token(value)))


def remove_iqqtv_web_number_suffix(title: str, number: str) -> str:
    t = title.strip()
    if not t:
        return ""
    parts = t.split()
    if len(parts) < 2:
        return t
    suffix = parts[-1]
    if _looks_like_iqqtv_web_number(suffix) and _same_iqqtv_web_number(suffix, number):
        return " ".join(parts[:-1]).strip()
    return t


def _clean_iqqtv_page_title(raw: str, number: str) -> str:
    title = get_iqqtv_real_title(remove_iqqtv_web_number_suffix(raw.strip(), number))
    title = re.sub(r"\s*iQQTV\s*.*$", "", title, flags=re.I).strip()
    title = clean_title(title, number)
    if not title or is_junk_title(title) or junk_iqqtv_title(title):
        return ""
    return title


def parse_iqqtv_outline(html: str) -> str:
    doc = soup(html)
    result = ""
    intro = doc.select_one('div[class*="intro"] p')
    if intro:
        result = strip_tags(intro.get_text())
    if not result:
        for el in doc.select("p"):
            t = strip_tags(el.get_text())
            if re.search(r"简介|簡介|介绍|介紹|紹介", t):
                result = t
                break
    result = re.sub(r"[\r\n\t]", "", result)
    result = OUTLINE_PREFIX.sub("", result)
    result = result.split("*根据分发")[0].strip()
    if not result or junk_iqqtv_title(result):
        return ""
    return result if len(result) >= 2 else ""


def get_iqqtv_real_url(html: str, number: str) -> str:
    doc = soup(html)
    num = re.sub(r"FC2", "", number, flags=re.I)
    num = re.sub(r"-PPV", "", num, flags=re.I)
    for span in doc.select("span.title"):
        a = span.find("a")
        if not a:
            continue
        href = a.get("href") or ""
        title = a.get("title") or ""
        if not href or not title:
            continue
        if not match_iqqtv_number(title, num) or junk_iqqtv_title(title):
            continue
        return href
    return ""


def parse_iqqtv_detail_html(html: str, code: str, page_url: str) -> dict[str, Any]:
    std = std_code(code)
    doc = soup(html)
    h1 = doc.select_one("h1.h4.b")
    raw_title = strip_tags(h1.get_text()) if h1 else ""
    title = _clean_iqqtv_page_title(raw_title, std)

    actors: list[str] = []
    for el in doc.select('a[href*="actor"] span'):
        n = strip_tags(el.get_text())
        if n and len(n) < 40 and n not in actors:
            actors.append(n)

    genres: list[str] = []
    for el in doc.select('.tag-info a[href*="tag"], a[href*="s_type=tag"]'):
        n = strip_tags(el.get_text())
        if not n or len(n) > 24 or re.search(r"更多|全部|类别", n, re.I) or n in genres:
            continue
        genres.append(n)

    studio_el = doc.select_one('a[href*="fac"] [itemprop="name"]')
    studio = strip_tags(studio_el.get_text()) if studio_el else ""
    if len(studio) > 60:
        studio = ""

    series_el = doc.select_one('a[href*="series"]')
    series = strip_tags(series_el.get_text()) if series_el else ""
    if len(series) < 2 or is_junk_title(series):
        series = ""

    plot = parse_iqqtv_outline(html)
    date_el = doc.select_one("div.date")
    date_raw = strip_tags(date_el.get_text()).replace("/", "-") if date_el else ""
    dm = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", date_raw)
    premiered = (
        f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}" if dm else ""
    )

    img = doc.select_one('img[itemprop="image"]')
    cover = pick_og_image(html) or (
        abs_url(img.get("src"), page_url) if img and img.get("src") else None
    )
    if cover and is_junk_cover_url(cover):
        cover = None

    return {
        "title": title or None,
        "plot": plot or None,
        "actors": actors,
        "genres": genres,
        "studio": studio or None,
        "series": series or None,
        "premiered": premiered or None,
        "website": page_url,
        "coverUrl": cover,
    }


def _root(base_url: str) -> str:
    raw = str(base_url or DEFAULT_ROOT).strip().rstrip("/")
    if not raw:
        return DEFAULT_ROOT
    return re.sub(r"/(cn|ja|en|zh|jp)/?$", "", raw, flags=re.I).rstrip("/") or DEFAULT_ROOT


def _lang_bases(root: str) -> tuple[str, str]:
    base = root.rstrip("/")
    if re.search(r"/cn$", base, re.I):
        return re.sub(r"/cn$", "/jp", base, flags=re.I), base
    return f"{base}/jp", f"{base}/cn"


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict[str, Any]:
    del api_key
    std = std_code(code)
    if not std:
        raise RuntimeError("番号为空")

    root = _root(base_url or DEFAULT_ROOT)
    if base_url:
        try:
            from .. import site_mirror

            site_mirror.remember("iqqtv", root, discovered_from=root)
        except Exception:
            pass

    jp_base, cn_base = _lang_bases(root)
    ck = cookie or None
    search_url = f"{jp_base}/search.php?kw={quote(std)}"
    try:
        search_html, landed = fetch_html_result(
            search_url,
            referer=f"{jp_base}/",
            cookie=ck,
            source_id=SOURCE,
        )
    except Exception as e:
        raise RuntimeError(f"搜索失败: {e}") from e

    if landed:
        try:
            from .. import site_mirror

            host = re.match(r"https?://[^/]+", landed)
            if host:
                site_mirror.remember("iqqtv", host.group(0), discovered_from=search_url)
                root = _root(host.group(0))
                jp_base, cn_base = _lang_bases(root)
        except Exception:
            pass

    if not search_html or len(search_html) < 400:
        raise RuntimeError("搜索无响应")

    detail_path = get_iqqtv_real_url(search_html, std)
    if not detail_path:
        raise RuntimeError("搜索无结果")

    rel = re.sub(r"^/(cn|jp)/", "", detail_path, flags=re.I).lstrip("/")
    jp_url = abs_url(f"/jp/{rel}", f"{jp_base}/") or f"{jp_base}/{rel}"
    cn_url = abs_url(f"/cn/{rel}", f"{cn_base}/") or f"{cn_base}/{rel}"

    def _fetch(url: str) -> str:
        return fetch_html(url, referer=search_url, cookie=ck, source_id=SOURCE)

    with ThreadPoolExecutor(max_workers=2) as pool:
        jp_f = pool.submit(_fetch, jp_url)
        cn_f = pool.submit(_fetch, cn_url)
        jp_html = jp_f.result()
        cn_html = cn_f.result()

    if not jp_html or len(jp_html) < 800 or not page_mentions_code(jp_html, std):
        raise RuntimeError("日文详情不可用")
    if not cn_html or len(cn_html) < 800 or not page_mentions_code(cn_html, std):
        raise RuntimeError("中文详情不可用")

    jp = parse_iqqtv_detail_html(jp_html, std, jp_url)
    cn = parse_iqqtv_detail_html(cn_html, std, cn_url)
    if not cn.get("title") and not jp.get("title"):
        raise RuntimeError("未找到标题")

    cover = cn.get("coverUrl") or jp.get("coverUrl")
    actors = cn.get("actors") or jp.get("actors") or []
    genres = cn.get("genres") or jp.get("genres") or []
    title_jp = jp.get("title") or cn.get("title")
    title_zh = cn.get("title") or jp.get("title")
    plot = cn.get("plot") or jp.get("plot")
    original_plot = jp.get("plot") or cn.get("plot")

    return make_detail(
        source=SOURCE,
        code=std,
        # 合并侧偏中文：title 优先 CN，日文进 originalTitle
        title=title_zh or title_jp,
        poster=cover,
        studio=(cn.get("studio") or jp.get("studio")),
        actors=list(actors),
        tags=list(genres),
        overview=plot,
        date=(cn.get("premiered") or jp.get("premiered")),
        extra={
            "titleZh": title_zh,
            "originalTitle": title_jp,
            "originalPlot": original_plot,
            "series": cn.get("series") or jp.get("series"),
            "website": cn_url,
        },
    )
