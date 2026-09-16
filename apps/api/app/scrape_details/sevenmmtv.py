# -*- coding: utf-8 -*-
"""7MMTV 详情刮削（对齐 MDCS sevenmmtv.ts）。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from .common import (
    abs_url,
    clean_title,
    fetch_html,
    fetch_html_result,
    folded_code_matches,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    page_mentions_code,
    pick_og_image,
    pick_og_title,
    std_code,
    strip_tags,
    soup,
)
from app.core import detail_path_cache

DEFAULT_BASE = "https://7mmtv.sx/zh"
SOURCE = "sevenmmtv"


def _root(base_url: str) -> str:
    return re.sub(r"/zh/?$", "", str(base_url or DEFAULT_BASE).rstrip("/"), flags=re.I)


def pick_sevenmmtv_detail_href(html: str, code: str) -> str:
    """有码优先；必须折叠命中番号，禁止无番号 first-hit。"""
    hrefs = [
        m.group(1)
        for m in re.finditer(
            r'href=["\']([^"\']*/(?:censored|chinese|amateurjav|uncensored|reducing-mosaic|amateur)_content/\d+/[^"\']+)["\']',
            html or "",
            re.I,
        )
    ]
    scored: list[tuple[int, str]] = []
    for h in dict.fromkeys(hrefs):
        if not folded_code_matches(h, code, mode="endswith"):
            continue
        score = 0
        if re.search(r"censored_content", h, re.I) and not re.search(r"reducing", h, re.I):
            score += 50
        if re.search(r"chinese_content", h, re.I):
            score += 40
        if re.search(r"amateurjav_content", h, re.I):
            score += 30
        if re.search(r"uncensored_content", h, re.I):
            score += 20
        if re.search(r"reducing-mosaic", h, re.I):
            score += 5
        scored.append((score, h))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else ""


def normalize_sevenmmtv_title(raw: str, web_number: str) -> str:
    title = re.sub(r"\s+", " ", str(raw or "")).strip()
    if web_number:
        title = re.sub(rf"^{re.escape(web_number)}\s*", "", title, flags=re.I).strip()
    return re.sub(r"\s*[-|｜]\s*7mmtv.*$", "", title, flags=re.I).strip()


def parse_sevenmmtv_outline(html: str) -> str:
    doc = soup(html)
    block = doc.select_one(".video-introduction-images-text")
    if not block:
        return ""
    raw = str(block.decode_contents() if hasattr(block, "decode_contents") else block)
    with_breaks = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    with_breaks = re.sub(r"</p>", "\n", with_breaks, flags=re.I)
    parts = [
        re.sub(r"\s+", " ", strip_tags(p)).strip()
        for p in re.split(r"\n+", with_breaks)
    ]
    return "\n".join(p for p in parts if p)


def _detect_mosaic(html: str, code: str) -> str:
    crumb_m = re.search(
        r'<ol[^>]*class=["\'][^"\']*breadcrumb[^"\']*["\'][\s\S]*?</ol>', html or "", re.I
    )
    crumb = strip_tags(crumb_m.group(0) if crumb_m else "")
    if re.search(r"無碼AV|国产影片|國產影片", crumb, re.I):
        return "无码"
    if re.search(r"有碼AV|有码AV|素人AV", crumb, re.I):
        return "有码"
    return "无码" if re.match(r"^FC2", code, re.I) else "有码"


def _attr_value(doc, label: re.Pattern[str]) -> str:
    out = ""
    for el in doc.select(".fullvideo-attr .row, .fullvideo-attr"):
        strong = el.select_one("strong")
        lab = strip_tags(strong.get_text()) if strong else ""
        if not label.search(lab):
            continue
        children = [c for c in el.children if getattr(c, "name", None)]
        col = children[1] if len(children) > 1 else None
        if col is not None:
            a = col.select_one("a")
            out = (
                strip_tags(a.get_text())
                if a
                else strip_tags(col.get_text())
            ) or out
        if not out:
            a2 = el.select_one("a")
            out = strip_tags(a2.get_text()) if a2 else out
    return out.strip()


def parse_sevenmmtv_detail(html: str, page_url: str, code: str) -> dict[str, Any] | None:
    from app.core.outbound_http import looks_blocked_html

    if not html or looks_blocked_html(html):
        return None
    if not page_mentions_code(html, code) and not re.search(r"fullvideo-title", html, re.I):
        return None

    doc = soup(html)
    std = std_code(code)
    web_el = doc.select_one(".d-flex.mb-4 span")
    web_number = strip_tags(web_el.get_text()) if web_el else ""
    if not web_number:
        m = re.search(
            r'<span[^>]*class=["\'][^"\']*text-muted[^"\']*["\'][^>]*>([^<]+)</span>',
            html,
            re.I,
        )
        web_number = strip_tags(m.group(1) if m else "") or std

    h1 = doc.select_one("h1.fullvideo-title, h1")
    title = normalize_sevenmmtv_title(
        clean_title(strip_tags(h1.get_text()) if h1 else pick_og_title(html) or "", std),
        web_number,
    )
    if not title or is_junk_title(title) or re.search(r"Watch JAV Online|^搜索", title, re.I):
        return None

    actors: list[str] = []
    for a in doc.select(".fullvideo-idol a, a[href*='_avperformer/']"):
        n = re.sub(r"（.+）", "", strip_tags(a.get_text())).split()[0] if strip_tags(a.get_text()) else ""
        n = n.strip()
        if n and len(n) <= 40 and not re.search(r"女優|女优|演員|演员", n, re.I) and n not in actors:
            actors.append(n)

    genres: list[str] = []
    for a in doc.select(".categories a, a[href*='_category/']"):
        g = strip_tags(a.get_text()).strip()
        if (
            g
            and len(g) <= 20
            and not re.search(r"高畫質|高清|DMM獨家|切卡|VR|4K", g, re.I)
            and g not in genres
        ):
            genres.append(g)
    genres = genres[:40]

    publisher = _attr_value(doc, re.compile(r"發行商|发行商|Issuer", re.I))
    studio = _attr_value(doc, re.compile(r"製作商|制作商|Maker|メーカー", re.I))
    director = _attr_value(doc, re.compile(r"導演|导演|Director", re.I))
    if re.match(r"^N/?A$|^----$", director or "", re.I):
        director = ""

    premiered = ""
    runtime: int | None = None
    for el in doc.select(".fullvideo-details .text-muted, .d-flex .text-muted"):
        t = strip_tags(el.get_text())
        dm = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
        if dm:
            premiered = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"
        rm = re.search(r"(\d+)\s*分", t) or re.search(r"(\d+)\s*min", t, re.I)
        if rm:
            runtime = int(rm.group(1)) or None

    cover = None
    img = doc.select_one(".content_main_cover img, .mvspan_2_s_k_i_p_cover img")
    if img:
        cover = img.get("src")
    if not cover:
        m = re.search(
            r'class=["\']player-cover["\'][^>]*><a><img src=["\']([^"\']+)["\']',
            html,
            re.I,
        )
        cover = m.group(1) if m else pick_og_image(html)
    cover = abs_url(cover, page_url) if cover else None
    if cover and is_junk_cover_url(cover):
        cover = None

    extras = [
        u
        for u in re.findall(
            r'<(?:img)[^>]+(?:data-src|src)=["\'](https?://[^"\']+\.(?:jpe?g|png|webp))["\']',
            html,
            re.I,
        )
        if re.search(r"pics\.dmm|digital/video|7mmtv", u, re.I)
    ]
    extras = list(dict.fromkeys(extras))[:20]
    plot = parse_sevenmmtv_outline(html)

    if not title and not cover and not actors and not plot:
        return None

    extra: dict[str, Any] = {
        "titleZh": title,
        "originalTitle": title,
        "publisher": publisher or None,
        "series": None,
        "website": page_url,
        "mosaic": _detect_mosaic(html, std),
        "extrafanartUrls": extras or None,
        "runtime": runtime if runtime and runtime > 0 else None,
    }
    if director:
        extra["director"] = director
        extra["directors"] = [director]

    return make_detail(
        source=SOURCE,
        code=std,
        title=title,
        poster=cover,
        studio=studio or None,
        actors=actors,
        tags=genres,
        overview=plot or None,
        date=premiered or None,
        extra=extra,
    )


def _search_detail_path(root: str, code: str, *, cookie: str = "") -> str:
    ck = cookie or None
    for search_url in (
        f"{root}/zh/searchall_search/all/{quote(code)}/1.html",
        f"{root}/zh/searchform_search/all/{quote(code)}/1.html",
    ):
        try:
            html = fetch_html(
                search_url, referer=f"{root}/zh/", cookie=ck, source_id=SOURCE
            )
        except Exception:
            continue
        path = pick_sevenmmtv_detail_href(html or "", code)
        if path:
            return path

    # POST 搜索兜底
    try:
        from .common import fetch_post_form

        body = f"search_keyword={quote(code)}&search_type=searchall&op=search"
        search_html = fetch_post_form(
            f"{root}/zh/searchform_search/all/index.html",
            body,
            referer=f"{root}/zh/",
            cookie=ck,
            source_id=SOURCE,
            timeout=20.0,
        )
        return pick_sevenmmtv_detail_href(search_html or "", code)
    except Exception:
        return ""


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    normalized = str(code or "").strip().upper()
    if not normalized:
        raise RuntimeError("番号为空")
    root = _root(base_url or DEFAULT_BASE)
    if not root:
        raise RuntimeError("未配置网站地址")

    # 第十六轮：详情路径缓存命中 → 直接抓详情，跳过搜索（重复刮省 1 请求）。
    # 页面番号校验不过回落搜索；坏缓存最多浪费 1 请求，不会错绑。
    cached_path = detail_path_cache.lookup(SOURCE, normalized)
    if cached_path:
        try:
            cached_url = abs_url(cached_path, root)
            if cached_url:
                cached_html, cached_landed = fetch_html_result(
                    cached_url,
                    referer=f"{root}/zh/",
                    cookie=cookie or None,
                    source_id=SOURCE,
                )
                if cached_html and page_mentions_code(cached_html, normalized):
                    cached_parsed = parse_sevenmmtv_detail(
                        cached_html, cached_landed or cached_url, normalized
                    )
                    if cached_parsed:
                        return cached_parsed
        except Exception:
            pass  # 缓存失效 → 回落搜索

    detail_path = _search_detail_path(root, normalized, cookie=cookie)
    if not detail_path:
        raise RuntimeError("搜索无结果")
    # 第十六轮：记住详情路径，重复刮直接走缓存跳过搜索
    detail_path_cache.remember(SOURCE, normalized, detail_path)
    detail_url = abs_url(detail_path, root)
    if not detail_url:
        raise RuntimeError("详情链接无效")

    html, landed = fetch_html_result(
        detail_url,
        referer=f"{root}/zh/",
        cookie=cookie or None,
        source_id=SOURCE,
    )
    if not html:
        raise RuntimeError("详情页无响应")
    parsed = parse_sevenmmtv_detail(html, landed or detail_url, normalized)
    if not parsed:
        raise RuntimeError("未找到")
    return parsed
