# -*- coding: utf-8 -*-
"""MissAV 详情刮削（对齐 MDCS miss_av.ts）。"""

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

DEFAULT_BASE = "https://missav123.com"
DETAIL_SUFFIX_RE = re.compile(
    r"-(?:uncensored-leak|uncensored|chinese-subtitle|english-subtitle|chinese|english)$",
    re.I,
)
SOURCE = "miss_av"


def _path_codes(code: str) -> list[str]:
    std = std_code(code)
    out: list[str] = []
    for v in (std.replace("-", "").lower(), std.lower()):
        if v and v not in out:
            out.append(v)
    if re.match(r"^FC2", std, re.I):
        v = re.sub(r"\s+", "-", std).lower()
        if v not in out:
            out.append(v)
    return out


def _looks_blocked(html: str) -> bool:
    head = (html or "")[:8000].lower()
    return bool(
        re.search(
            r"just a moment|attention required|cf-browser-verification|challenge-platform|enable javascript and cookies",
            head,
            re.I,
        )
    )


def _is_detail_html(html: str, code: str) -> bool:
    if not html or len(html) < 5000:
        return False
    if _looks_blocked(html):
        return False
    if not re.search(r'property=["\']og:type["\']\s+content=["\']video\.other["\']', html, re.I):
        return False
    std = std_code(code)
    m = re.search(r"<span>番号:</span>\s*<span[^>]*>([^<]+)<", html, re.I) or re.search(
        r"dvdId:\s*['\"]([^'\"]+)['\"]", html, re.I
    )
    page_code = strip_tags(m.group(1) if m else "")
    if page_code and code_key(page_code) != code_key(std):
        return False
    token = std.replace("-", "[-]?")
    return bool(re.search(token, html[:80000], re.I))


def _pick_detail_href(html: str, code: str) -> str:
    std = std_code(code).lower()
    compact = std.replace("-", "")
    hrefs = [m.group(1) for m in re.finditer(r'href=["\']([^"\']+/cn/[^"\'#?]+)["\']', html or "", re.I)]
    scored: list[tuple[str, int]] = []
    for h in dict.fromkeys(hrefs):
        path = h.split("?")[0].lower()
        slug = path.rstrip("/").split("/")[-1] if path else ""
        score = 0
        if DETAIL_SUFFIX_RE.search(slug):
            score -= 80
        if slug == std or slug == compact:
            score += 100
        # 禁止 startswith 模糊命中
        if re.search(r"/cn/search/", path, re.I):
            score -= 50
        if re.search(r"-uncensored-leak", slug, re.I):
            score -= 30
        if re.search(r"-chinese-subtitle|-english-subtitle", slug, re.I):
            score -= 10
        if re.search(r"/dm\d+/cn/", path, re.I):
            score += 5
        scored.append((h, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0] if scored and scored[0][1] >= 100 else ""


def _norm_label(raw: str) -> str:
    return re.sub(r"[:：\s]", "", strip_tags(raw))


def _label_hit(key: str, labels: list[str]) -> bool:
    k = _norm_label(key)
    if not k:
        return False
    # 排行榜/导航块常含「女优」字样，勿当详情女优行
    if re.search(r"排行|榜单|榜單|ranking|more|更多", k, re.I):
        return False
    wanted = {_norm_label(l) for l in labels if str(l).strip()}
    if k in wanted:
        return True
    # 允许「出演女优」等短前缀，拒绝「女优排行…」长串
    return any(
        k.endswith(w) and 0 < len(k) - len(w) <= 2 for w in wanted if w
    )


def _parse_label_links(html: str, labels: list[str]) -> list[str]:
    doc = soup(html)
    out: list[str] = []
    for el in doc.select("div.text-secondary"):
        spans = el.select("span")
        if not spans:
            continue
        key = strip_tags(spans[0].get_text())
        if not _label_hit(key, labels):
            continue
        for a in el.select("a.text-nord13"):
            t = re.sub(r"\s*\([^)]*\)\s*$", "", strip_tags(a.get_text())).strip()
            if t and t not in out:
                out.append(t)
    return out


def _parse_inline_value(html: str, labels: list[str]) -> str:
    doc = soup(html)
    out = ""
    for el in doc.select("div.text-secondary"):
        spans = el.select("span")
        if not spans:
            continue
        key = strip_tags(spans[0].get_text())
        if not _label_hit(key, labels):
            continue
        font = el.select_one("span.font-medium")
        if font is not None:
            out = strip_tags(font.get_text())
        else:
            raw = strip_tags(el.get_text())
            stripped = raw
            for lab in labels:
                stripped = re.sub(rf"^{re.escape(lab)}[:：]?", "", stripped)
            out = stripped.strip()
        break
    return out.strip()


def _parse_plot(html: str) -> str:
    m = re.search(r'property=["\']og:description["\']\s+content=["\']([^"\']+)["\']', html, re.I) or re.search(
        r'content=["\']([^"\']+)["\']\s+property=["\']og:description["\']', html, re.I
    )
    plot = strip_tags(m.group(1) if m else "").strip()
    doc = soup(html)
    block = doc.select_one("div.line-clamp-2, div.line-clamp-none")
    from_body = strip_tags(block.get_text() if block else "").strip()
    if len(from_body) > len(plot):
        plot = from_body
    plot = re.sub(r"^\[[^\]]+\]\s*", "", plot).strip()
    if len(plot) < 20:
        return ""
    if re.search(r"免费高清|MissAV|在线看", plot, re.I) and len(plot) < 60:
        return ""
    return plot


def _parse_title(html: str, code: str) -> str:
    doc = soup(html)
    h1 = doc.select_one("h1.text-base, h1")
    raw = strip_tags(h1.get_text() if h1 else "")
    std = std_code(code)
    pat = re.escape(std).replace(r"\-", "[-]?")
    title = re.sub(rf"^{pat}\s*", "", raw, flags=re.I).strip()
    title = re.sub(r"\s*[-–—]\s*[^-–—]+$", "", title).strip()
    return clean_title(title, std)


def _parse_mosaic(html: str, page_url: str) -> str:
    blob = f"{page_url} {(html or '')[:12000]}"
    if re.search(r"-uncensored-leak|无码影片", blob, re.I):
        return "无码"
    if re.search(r"国产|chinese-av|chinese_av", (html or "")[:15000], re.I):
        return "国产"
    return "有码"


def _parse_detail(html: str, page_url: str, code: str) -> dict:
    if not _is_detail_html(html, code):
        raise RuntimeError("解析失败")
    std = std_code(code)
    title_zh = _parse_title(html, std)
    original = _parse_inline_value(html, ["标题", "標題"]) or ""
    title = title_zh or original
    if title and is_junk_title(title):
        raise RuntimeError("解析失败")

    actors = _parse_label_links(html, ["女优", "女優"])[:20]
    genres = _parse_label_links(html, ["类型", "類型"])[:40]
    directors = _parse_label_links(html, ["导演", "導演"])[:5]
    series = _parse_inline_value(html, ["系列"]) or None
    studio = _parse_inline_value(html, ["发行商", "發行商", "片商"]) or None
    publisher = _parse_inline_value(html, ["标籤", "標籤", "标签", "Label"]) or None
    m_date = re.search(
        r'property=["\']og:video:release_date["\']\s+content=["\']([^"\']+)["\']', html, re.I
    )
    premiered = (m_date.group(1) if m_date else "")[:10] or (
        _parse_inline_value(html, ["发行日期", "發行日期", "上映日期"])[:10] or None
    )
    m_dur = re.search(r'property=["\']og:video:duration["\']\s+content=["\'](\d+)["\']', html, re.I)
    runtime_sec = int(m_dur.group(1)) if m_dur else 0
    runtime = max(1, round(runtime_sec / 60)) if runtime_sec > 0 else None
    plot = _parse_plot(html)

    cover = pick_og_image(html) or ""
    if cover:
        cover = abs_url(cover, page_url) or cover
    if cover and is_junk_cover_url(cover):
        cover = None

    extra: dict = {
        "website": page_url,
        "mosaic": _parse_mosaic(html, page_url),
        "titleZh": title_zh or title or None,
    }
    if original and original != title:
        extra["originalTitle"] = original
    if publisher:
        extra["publisher"] = publisher
    if series:
        extra["series"] = series
    if directors:
        extra["director"] = directors[0]
        extra["directors"] = directors
    if runtime:
        extra["runtime"] = runtime

    if not title and not cover and not actors and not genres and not plot:
        raise RuntimeError("解析失败")

    return make_detail(
        source=SOURCE,
        code=std,
        title=title or None,
        poster=cover,
        studio=studio,
        actors=actors,
        tags=genres,
        overview=plot or None,
        date=premiered,
        extra=extra,
    )


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    std = std_code(code)
    if not std:
        raise RuntimeError("番号为空")
    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")
    referer = f"{base}/cn/"
    ck = cookie or None

    last_err: Exception | None = None
    for path_code in _path_codes(std):
        url = f"{base}/cn/{quote(path_code)}"
        try:
            html = fetch_html(url, referer=referer, cookie=ck, source_id=SOURCE)
            if html and len(html) >= 5000:
                return _parse_detail(html, url, std)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue

    search_url = f"{base}/cn/search/{quote(std)}"
    try:
        search_html = fetch_html(search_url, referer=referer, cookie=ck, source_id=SOURCE)
    except Exception as e:
        raise RuntimeError(f"搜索无响应: {e}") from e
    if not search_html or len(search_html) < 5000:
        raise RuntimeError(f"搜索无响应: {last_err}")

    detail_path = _pick_detail_href(search_html, std)
    if not detail_path:
        raise RuntimeError("未找到")
    detail_url = abs_url(detail_path, base) or detail_path
    try:
        detail_html = fetch_html(detail_url, referer=search_url, cookie=ck, source_id=SOURCE)
    except Exception as e:
        raise RuntimeError(f"详情页无响应: {e}") from e
    if not detail_html or len(detail_html) < 5000:
        raise RuntimeError("详情页无响应")
    return _parse_detail(detail_html, detail_url, std)
