# -*- coding: utf-8 -*-
"""麻豆区详情刮削（对齐 MDCS madouqu.ts）。"""

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
    pick_og_title,
    soup,
    strip_tags,
)
from app.core import detail_path_cache

DEFAULT_BASE = "https://madouqu.com"


def _madou_std(raw: str) -> str:
    s = str(raw or "").strip().upper().replace("_", "-")
    if not s:
        return ""
    if "-" not in s:
        m = re.match(r"^([A-Z]{1,12})(\d{2,}[A-Z0-9-]*)$", s)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
    return s


def _madou_compact(code: str) -> str:
    return str(code or "").replace("-", "").upper()


def _page_has_code(html: str, code: str) -> bool:
    compact = _madou_compact(code)
    head = html[:12000]
    if re.search(re.escape(compact), head, re.I):
        return True
    return bool(re.search(code.replace("-", "[-_]?"), head, re.I))


def _parse_detail(html: str, detail_url: str, code: str) -> dict | None:
    doc = soup(html)
    compact = _madou_compact(code)
    if not _page_has_code(html, code) and not re.search(compact, detail_url, re.I):
        return None

    h1 = doc.select_one("h1.entry-title, h1")
    title_el = doc.select_one("title")
    title = clean_title(
        strip_tags(h1.get_text() if h1 else "")
        or pick_og_title(html)
        or re.sub(r"\s*[-|｜].*麻豆.*$", "", strip_tags(title_el.get_text() if title_el else ""), flags=re.I),
        code,
    )
    title = re.sub(rf"^{re.escape(code)}\s*[!！]?\s*", "", title, flags=re.I)
    title = re.sub(rf"^{re.escape(compact)}\s*[!！]?\s*", "", title, flags=re.I)
    title = re.sub(r"\s*[-|｜]\s*麻豆区?\s*$", "", title, flags=re.I).strip()
    if is_junk_title(title) or re.search(r"的搜索结果|Web server is returning", title, re.I):
        title = ""

    meta_desc = doc.select_one("meta[name='description']")
    entry = doc.select_one(".entry-content")
    desc = (meta_desc.get("content") if meta_desc else "") or strip_tags(entry.get_text() if entry else "")
    actress_m = re.search(r"麻豆女郎\s*[:：]\s*([^\n下载下載]{2,80})", desc, re.I) or re.search(
        r"麻豆女郎\s*[:：]\s*([^<\"\n]{2,80})", html, re.I
    )
    actress_raw = actress_m.group(1) if actress_m else ""
    actors_from_desc = [
        strip_tags(s)
        for s in re.split(r"[,，、/|]", actress_raw)
        if strip_tags(s) and 2 <= len(strip_tags(s)) <= 20
    ]
    actors_from_tags = []
    for el in doc.select("a[rel='tag'], .entry-tags a"):
        n = strip_tags(el.get_text())
        if n and 2 <= len(n) <= 20:
            actors_from_tags.append(n)
    actors = list(dict.fromkeys([*actors_from_desc, *[n for n in actors_from_tags if n not in actors_from_desc]]))[
        :20
    ]

    cat_m = re.search(r"分类\s*[:：]\s*([^<\"\n{]{2,40})", html, re.I)
    cat_el = doc.select_one(".entry-meta a[rel='category tag'], a[rel='category tag']")
    studio = strip_tags(cat_m.group(1) if cat_m else "") or strip_tags(cat_el.get_text() if cat_el else "")
    if re.search(r"madou", studio, re.I):
        studio = re.sub(r"madou\s*", "", studio, flags=re.I).strip()

    img = doc.select_one(".entry-content img")
    cover = pick_og_image(html) or abs_url(
        (img.get("src") if img else "") or (img.get("data-src") if img else ""), detail_url
    )
    if cover:
        jp = re.search(r"i\d\.wp\.com/([^?]+)", cover, re.I)
        if jp:
            cover = f"https://{jp.group(1)}"
    if cover and is_junk_cover_url(cover):
        cover = None

    premiered = ""
    time_el = doc.select_one("time[datetime]")
    dt = (time_el.get("datetime") if time_el else "") or ""
    dm = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(dt))
    if dm:
        premiered = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"

    if not title and not cover:
        return None

    return {
        "title": title or None,
        "actors": actors,
        "studio": studio or None,
        "premiered": premiered or None,
        "cover": cover,
    }


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    std = _madou_std(code)
    if not std:
        raise RuntimeError("番号格式无效")

    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")

    compact = _madou_compact(std)
    want = compact.lower()

    def _finish(abs_u: str, referer: str) -> dict | None:
        """抓详情 + 解析 + 构造（搜索路径与缓存路径共用）。"""
        try:
            detail_html = fetch_html(abs_u, referer=referer, cookie=cookie or None, source_id="madouqu")
        except Exception:
            return None
        parsed = _parse_detail(detail_html, abs_u, std)
        if parsed and (parsed.get("title") or parsed.get("cover")):
            return make_detail(
                source="madouqu",
                code=std,
                title=parsed.get("title"),
                poster=parsed.get("cover"),
                studio=parsed.get("studio"),
                actors=parsed.get("actors") or [],
                date=parsed.get("premiered"),
                extra={"titleZh": parsed.get("title")},
            )
        return None

    # 第十六轮：详情路径缓存命中 → 直接抓详情，跳过搜索（重复刮省 1-2 请求）。
    # _parse_detail 校验不过返回 None → 回落搜索；坏缓存最多浪费 1 请求。
    cached_url = detail_path_cache.lookup("madouqu", std)
    if cached_url:
        try:
            cached_got = _finish(cached_url, f"{base}/")
            if cached_got:
                return cached_got
        except Exception:
            pass  # 缓存失效 → 回落搜索

    for q in list(dict.fromkeys([std, compact])):
        search_url = f"{base}/?s={quote(q)}"
        try:
            search_html = fetch_html(search_url, referer=f"{base}/", cookie=cookie or None, source_id="madouqu")
        except Exception:
            continue
        doc = soup(search_html)
        detail_url = ""
        for el in doc.select("h2 a, h3 a, .entry-title a, .post-title a"):
            href = str(el.get("href") or "")
            text = strip_tags(el.get_text())
            id_guess = (text.split()[0] if text.split() else "").replace("-", "").upper()
            if id_guess == compact:
                detail_url = href
                break
        if not detail_url:
            for el in doc.select("a[href*='/video/']"):
                href = str(el.get("href") or "")
                key = href.lower().replace("-", "")
                if f"/video/{want}/" in key or f"/video/{std.lower()}/" in key:
                    detail_url = href
                    break
        if not detail_url:
            continue
        abs_u = abs_url(detail_url, base)
        if not abs_u:
            continue
        got = _finish(abs_u, search_url)
        if got:
            # 第十六轮：记住详情 URL，重复刮直接走缓存跳过搜索
            detail_path_cache.remember("madouqu", std, abs_u)
            return got

    for slug in list(dict.fromkeys([std.lower(), want])):
        url = f"{base}/video/{quote(slug)}/"
        try:
            detail_html = fetch_html(url, referer=f"{base}/", cookie=cookie or None, source_id="madouqu")
            parsed = _parse_detail(detail_html, url, std)
            if parsed and (parsed.get("title") or parsed.get("cover")):
                return make_detail(
                    source="madouqu",
                    code=std,
                    title=parsed.get("title"),
                    poster=parsed.get("cover"),
                    studio=parsed.get("studio"),
                    actors=parsed.get("actors") or [],
                    date=parsed.get("premiered"),
                    extra={"titleZh": parsed.get("title")},
                )
        except Exception:
            continue

    raise RuntimeError("未找到")
