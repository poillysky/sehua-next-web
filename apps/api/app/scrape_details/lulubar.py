# -*- coding: utf-8 -*-
"""LuluBar 详情（对齐 MDCS lulubar.ts）。强 CF：依赖 FlareSolverr。"""

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
    page_mentions_code,
    pick_og_image,
    soup,
    std_code,
    strip_tags,
)
from app.core import detail_path_cache

DEFAULT_BASE = "https://lulubar.co"
IMAGE_HOST = "https://image.lulubar.co"
SOURCE = "lulubar"


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


def _pick_detail_href(html: str, code: str) -> str:
    std = std_code(code)
    want = code_key(std)
    if not want:
        return ""
    if re.search(r"的搜寻结果\s*\(\s*0\s*\)", html or "", re.I):
        return ""
    doc = soup(html or "")
    best = ""
    best_score = -1
    for a in doc.select("a.imgBoxW[href*='/video/detail?id=']"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        img = a.select_one("img")
        text = " ".join(
            [
                strip_tags(a.get("title") or ""),
                strip_tags(img.get("alt") if img is not None else ""),
                strip_tags(img.get("title") if img is not None else ""),
                strip_tags(a.get_text(" ", strip=True)),
            ]
        )
        hay = code_key(text)
        if want not in hay:
            continue
        score = 10
        if want in hay:
            score += 20
        if re.search(std.replace("-", "[-]?"), text, re.I):
            score += 30
        if score > best_score:
            best_score = score
            best = href
    return best


def _parse_detail(html: str, detail_url: str, code: str) -> dict:
    std = std_code(code)
    want = code_key(std)
    if not html or len(html) < 2000 or not want:
        raise RuntimeError("解析失败")
    if want not in code_key(html):
        raise RuntimeError("解析失败")

    doc = soup(html)
    h2 = doc.select_one("#detail h2.mb-1") or doc.select_one("h2.mb-1")
    h2_text = ""
    if h2 is not None:
        # `soup()` 返回的是线程内共享只读树（同一份 html 只解析一次，见 common.soup）。
        # 想剔掉 a.ogtag 的文字必须在**副本**上变异，不能动共享树 ——
        # 否则同一次抓取里后续 helper 会看不到这些节点（结果静默变化）。
        clone = soup(str(h2))
        for og in clone.select("a.ogtag"):
            og.decompose()
        h2_text = strip_tags(clone.get_text())
    if not h2_text or want not in code_key(h2_text):
        raise RuntimeError("解析失败")

    title = re.sub(
        rf"^{re.escape(std).replace('-', '[-]?')}\s*[-|｜—]\s*",
        "",
        h2_text,
        flags=re.I,
    ).strip()
    title = clean_title(title, std)
    if is_junk_title(title):
        title = ""

    meta = doc.select_one("#detail .tag_box") or doc.select_one(".tag_box")
    premiered = ""
    actors: list[str] = []
    genres: list[str] = []
    studio = ""
    mosaic = "有码"
    if meta is not None:
        date_a = meta.select_one("a.tag[href*='bydatedetail']")
        premiered = strip_tags(date_a.get_text() if date_a else "")
        actors = [
            strip_tags(a.get_text())
            for a in meta.select("a.tag[href*='bygirldetail']")
            if strip_tags(a.get_text()) and 2 <= len(strip_tags(a.get_text())) <= 24
        ]
        actors = list(dict.fromkeys(actors))[:20]
        studio_a = meta.select_one("a.tag[title='片商']") or meta.select_one(
            "a.tag[href*='bysearch'][title='片商']"
        )
        studio = strip_tags(studio_a.get_text() if studio_a else "")
        genres = [
            strip_tags(a.get_text())
            for a in meta.select("a.tag[href*='bytagdetail']")
            if strip_tags(a.get_text()) and len(strip_tags(a.get_text())) <= 40
        ]
        genres = list(dict.fromkeys(genres))[:40]
        if meta.select_one("a.tag[href*='byunpix']"):
            mosaic = "无码"
        elif meta.select_one("a.tag[href*='bypixelization']"):
            mosaic = "有码"
    if not premiered:
        dm = re.search(r"bydatedetail\?date=(\d{4}-\d{2}-\d{2})", html or "", re.I)
        premiered = dm.group(1) if dm else ""

    plot_el = doc.select_one("#detail .video_container_info")
    plot = strip_tags(plot_el.get_text() if plot_el else "")
    if len(plot) < 12:
        meta_desc = doc.select_one('meta[name="description"]')
        meta_og = doc.select_one('meta[property="og:description"]')
        plot = strip_tags(
            (meta_desc.get("content") if meta_desc else "")
            or (meta_og.get("content") if meta_og else "")
            or ""
        )
    plot = re.sub(
        rf"^{re.escape(std).replace('-', '[-]?')}\s*[-|｜]?\s*",
        "",
        plot,
        flags=re.I,
    ).strip()
    if len(plot) < 12:
        plot = ""

    player = doc.select_one("#player")
    cover = _norm_cover(player.get("data-poster") if player is not None else None, detail_url)
    if not cover:
        cover = _norm_cover(pick_og_image(html), detail_url)
    if not cover:
        m = re.search(
            r"https?://image\.lulubar\.co/films/[^\"'>\s]+\.(?:jpe?g|png|webp)",
            html or "",
            re.I,
        )
        cover = _norm_cover(m.group(0) if m else None, detail_url)

    if not title and not cover and not actors:
        raise RuntimeError("解析失败")

    return make_detail(
        source=SOURCE,
        code=std,
        title=title or None,
        poster=cover,
        studio=studio or None,
        actors=actors,
        tags=genres,
        overview=plot or None,
        date=premiered[:10] or None,
        extra={"website": detail_url, "mosaic": mosaic, "titleZh": title or None},
    )


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    std = std_code(code)
    if not std:
        raise RuntimeError("番号格式无效")
    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")

    # 第十六轮：详情路径缓存命中 → 直接抓详情，跳过搜索（重复刮省 1 请求）。
    # 页面番号校验不过回落搜索；坏缓存最多浪费 1 请求，不会错绑。
    cached_href = detail_path_cache.lookup(SOURCE, std)
    if cached_href:
        try:
            cached_url = abs_url(cached_href, base) or cached_href
            cached_html = fetch_html(
                cached_url, referer=f"{base}/", cookie=cookie or None, source_id=SOURCE
            )
            if cached_html and page_mentions_code(cached_html, std):
                cached_parsed = _parse_detail(cached_html, cached_url, std)
                if cached_parsed:
                    return cached_parsed
        except Exception:
            pass  # 缓存失效 → 回落搜索

    search_url = f"{base}/video/bysearch?search={quote(std)}&page=1"
    html = fetch_html(
        search_url, referer=f"{base}/", cookie=cookie or None, source_id=SOURCE
    )
    detail_href = _pick_detail_href(html or "", std)
    if not detail_href:
        raise RuntimeError("未找到")
    # 第十六轮：记住详情路径，重复刮直接走缓存跳过搜索
    detail_path_cache.remember(SOURCE, std, detail_href)
    detail_url = abs_url(detail_href, base) or detail_href
    detail_html = fetch_html(
        detail_url, referer=search_url, cookie=cookie or None, source_id=SOURCE
    )
    return _parse_detail(detail_html or "", detail_url, std)
