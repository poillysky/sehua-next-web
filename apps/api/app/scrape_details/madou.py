# -*- coding: utf-8 -*-
"""麻豆社 madou.club 详情刮削（对齐 MDCS madou.ts）。"""

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
    soup,
    std_code,
    strip_tags,
)
from app.core import detail_path_cache

DEFAULT_BASE = "https://madou.club"
SOURCE = "madou"

GENRE_WORDS = {
    s.lower()
    for s in (
        "口交", "后入", "骑乘位", "女上位", "白虎", "少妇", "巨乳", "美乳", "美臀", "黑丝", "丝袜",
        "调教", "自拍", "出轨", "人妻", "学生", "制服", "创意", "内射", "颜射", "中出", "无套",
        "潮吹", "剧情", "无码", "有码", "3P", "足交", "肛交", "群交", "露出", "偷拍", "约炮",
    )
}


# 与 madouqu._madou_std / common.std_code 逐字节相同，收敛为同一实现（保留旧名）
_madou_std = std_code


def _madou_compact(code: str) -> str:
    return str(code or "").replace("-", "").upper()


def _page_has_code(html: str, code: str) -> bool:
    compact = _madou_compact(code)
    head = (html or "")[:12000]
    if re.search(re.escape(compact), head, re.I):
        return True
    return bool(re.search(code.replace("-", "[-_]?"), head, re.I))


def _parse_detail(html: str, detail_url: str, code: str) -> dict | None:
    doc = soup(html)
    compact = _madou_compact(code)
    h1 = doc.select_one(".article-title, h1.article-title, h1")
    title_el = doc.select_one("title")
    title = clean_title(
        strip_tags(h1.get_text() if h1 else "")
        or re.sub(
            r"\s*[-|｜].*麻豆.*$",
            "",
            strip_tags(title_el.get_text() if title_el else ""),
            flags=re.I,
        ),
        code,
    )
    title = re.sub(rf"^{re.escape(compact)}\s*[／/:\-–—]?\s*", "", title, flags=re.I)
    title = re.sub(rf"^{re.escape(code)}\s*[／/:\-–—]?\s*", "", title, flags=re.I)
    title = re.sub(r"\s*[-|｜]\s*麻豆社?\s*$", "", title, flags=re.I).strip()
    if is_junk_title(title) or re.search(r"未找到页面|没有找到|Nothing Found", title, re.I):
        title = ""

    studio_el = doc.select_one(".article-meta a[rel='category tag'], a[rel='category tag']")
    studio = strip_tags(studio_el.get_text() if studio_el else "") or None

    tags = [
        strip_tags(a.get_text())
        for a in doc.select("a[rel='tag'], .article-tags a")
        if strip_tags(a.get_text()) and len(strip_tags(a.get_text())) < 40
    ]
    actors: list[str] = []
    genres: list[str] = []
    for t in tags:
        key = t.lower()
        as_genre = (
            key in GENRE_WORDS
            or bool(re.search(r"[a-z0-9]", t, re.I))
            or len(t) > 3
            or bool(re.search(r"丝|交|入|射|码|P$", t, re.I))
        )
        if as_genre:
            if t not in genres:
                genres.append(t)
        elif re.match(r"^[\u4e00-\u9fff]{2,3}$", t):
            if t not in actors:
                actors.append(t)
        elif t not in genres:
            genres.append(t)

    cover_cands: list[str] = []

    def push_cover(raw: str | None) -> None:
        u = abs_url(str(raw or "").strip(), detail_url)
        if u and re.search(r"/covers/", u, re.I) and not re.search(r"avatar|logo", u, re.I):
            cover_cands.append(u)

    for img in doc.select("img"):
        push_cover(img.get("data-src"))
        push_cover(img.get("src"))
    for m in re.finditer(
        r"https?://[^\"'>\s]+/covers/[^\"'>\s]+\.(?:jpe?g|png|webp)", html or "", re.I
    ):
        push_cover(m.group(0))

    cover = next((u for u in cover_cands if not re.search(r"-\d+x\d+\.", u, re.I)), None)
    if not cover and cover_cands:
        cover = cover_cands[0]
    if cover and is_junk_cover_url(cover):
        cover = None

    if not title and not cover:
        return None
    if (
        not _page_has_code(html, code)
        and not re.search(compact, detail_url, re.I)
        and not re.search(compact, title, re.I)
    ):
        return None

    return {
        "title": title or None,
        "actors": actors[:20],
        "genres": genres[:40],
        "studio": studio,
        "cover": cover,
        "website": detail_url,
    }


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    std = _madou_std(code)
    if not std:
        raise RuntimeError("番号格式无效")
    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")
    compact = _madou_compact(std)
    want = compact.lower()
    ck = cookie or None

    def _finish(abs_u: str, referer: str) -> dict | None:
        """抓详情 + 解析 + 构造（搜索路径与缓存路径共用）。"""
        try:
            detail_html = fetch_html(
                abs_u, referer=referer, cookie=ck, source_id=SOURCE
            )
        except Exception:
            return None
        parsed = _parse_detail(detail_html or "", abs_u, std)
        if parsed and (parsed.get("title") or parsed.get("cover")):
            return make_detail(
                source=SOURCE,
                code=std,
                title=parsed.get("title"),
                poster=parsed.get("cover"),
                studio=parsed.get("studio"),
                actors=list(parsed.get("actors") or []),
                tags=list(parsed.get("genres") or []),
                extra={
                    "titleZh": parsed.get("title"),
                    "website": parsed.get("website"),
                },
            )
        return None

    # 第十六轮：详情路径缓存命中 → 直接抓详情，跳过搜索（重复刮省 1-2 请求）。
    # _parse_detail 校验不过返回 None → 回落搜索；坏缓存最多浪费 1 请求。
    cached_url = detail_path_cache.lookup(SOURCE, std)
    if cached_url:
        try:
            cached_got = _finish(cached_url, f"{base}/")
            if cached_got:
                return cached_got
        except Exception:
            pass  # 缓存失效 → 回落搜索

    for q in list(dict.fromkeys([compact, std])):
        search_url = f"{base}/?s={quote(q)}"
        try:
            search_html = fetch_html(
                search_url, referer=f"{base}/", cookie=ck, source_id=SOURCE
            )
        except Exception:
            continue
        if re.search(r"没有找到|未找到|Nothing Found", search_html or "", re.I) and not _page_has_code(
            search_html or "", std
        ):
            continue
        doc = soup(search_html)
        detail_url = ""
        for el in doc.select("h2 a, h3 a, .entry-title a, .article-title a"):
            href = str(el.get("href") or "")
            text = strip_tags(el.get_text())
            if want in f"{href} {text}".lower().replace("-", ""):
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
            detail_path_cache.remember(SOURCE, std, abs_u)
            return got

    raise RuntimeError("未找到")
