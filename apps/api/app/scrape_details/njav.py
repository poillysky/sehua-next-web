# -*- coding: utf-8 -*-
"""NJAV / 123AV 详情刮削（对齐 MDCS njav.ts）。"""

from __future__ import annotations

import re
from urllib.parse import quote, unquote

from .common import (
    abs_url,
    clean_title,
    code_key,
    fetch_html,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    soup,
    std_code,
    strip_tags,
)

DEFAULT_BASE = "https://123av.com/ja"
DETAIL_SUFFIX_RE = re.compile(
    r"-(?:uncensored-leaked|uncensored-leak|english-subtitle|chinese-subtitle)$",
    re.I,
)


def _locale_base(base_url: str) -> str:
    raw = str(base_url or DEFAULT_BASE).rstrip("/")
    if re.search(r"/(ja|en|cn|zh|ko)(?:/|$)", raw, re.I):
        return raw
    return f"{raw}/ja"


def _search_url(base: str, code: str) -> str:
    return f"{_locale_base(base)}/search?keyword={quote(std_code(code))}"


def _pick_detail_href(html: str, code: str) -> str:
    std = std_code(code).lower()
    compact = std.replace("-", "")
    hrefs: list[str] = []
    for pat in (
        r'href=["\']([^"\']+/v/[^"\'#?]+)["\']',
        r'href=["\']([^"\']+/videos/[^"\'#?]+)["\']',
        r'class=["\'][^"\']*(?:box-item|detail)[^"\']*["\'][^>]*>[\s\S]*?href=["\']([^"\']+)["\']',
    ):
        hrefs.extend(m.group(1) for m in re.finditer(pat, html or "", re.I))

    scored: list[tuple[str, int]] = []
    for h in dict.fromkeys(hrefs):
        path = h.split("?")[0].lower()
        slug = path.rstrip("/").split("/")[-1] if path else ""
        score = 0
        if DETAIL_SUFFIX_RE.search(slug):
            score -= 80
        if slug == std or slug == compact:
            score += 100
        elif slug.startswith(std) or slug.startswith(compact):
            score += 40
        if re.search(r"/search/", path, re.I):
            score -= 50
        if re.search(r"uncensored", slug, re.I):
            score -= 20
        scored.append((h, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0] if scored and scored[0][1] > 0 else ""


def _is_detail_html(html: str, code: str) -> bool:
    if not html or len(html) < 4000:
        return False
    if re.search(r"123av\.com に移転|moved__title|404 — 123AV", html[:12000], re.I):
        return False
    std = std_code(code)
    m = re.search(r"<dt>コード</dt>\s*<dd[^>]*>([^<]+)<", html, re.I) or re.search(
        r"<dt>代码</dt>\s*<dd[^>]*>([^<]+)<", html, re.I
    )
    page_code = strip_tags(m.group(1) if m else "")
    if page_code and code_key(page_code) != code_key(std):
        return False
    return bool(
        re.search(r'class=["\']watch__title["\']', html)
        or re.search(r'class=["\']watch__info-row["\']', html)
        or (re.search(r'id=["\']player["\']', html) and re.search(r"detail-item", html))
    )


def _parse_info_rows(html: str) -> dict[str, list[str]]:
    doc = soup(html)
    out: dict[str, list[str]] = {}
    for el in doc.select("div.watch__info-row"):
        dt = el.select_one("dt")
        key = strip_tags(dt.get_text() if dt else "")
        chips = [strip_tags(a.get_text()) for a in el.select("dd a.chip") if strip_tags(a.get_text())]
        if chips:
            out[key] = chips
            continue
        dd = el.select_one("dd")
        if not dd:
            continue
        # clone text without children
        plain_parts: list[str] = []
        for child in dd.children:
            if getattr(child, "name", None) is None:
                plain_parts.append(str(child))
        plain = strip_tags("".join(plain_parts))
        if plain:
            out[key] = [plain]
    return out


def _parse_legacy_rows(html: str) -> dict[str, list[str]]:
    doc = soup(html)
    out: dict[str, list[str]] = {}
    for el in doc.select("div.detail-item > div"):
        spans = el.select("span")
        if not spans:
            continue
        key = re.sub(r"[:：\s]", "", strip_tags(spans[0].get_text()))
        links: list[str] = []
        plain = ""
        if len(spans) > 1:
            links = [strip_tags(a.get_text()) for a in spans[1].select("a") if strip_tags(a.get_text())]
            plain = strip_tags(spans[1].get_text())
        if re.search(r"女優|女优|Actress", key, re.I):
            out["出演者"] = links if links else ([plain] if plain else [])
        elif re.search(r"ジャンル|类型|Genre", key, re.I):
            out["ジャンル"] = links
        elif re.search(r"メーカー|片商|Maker", key, re.I):
            val = plain or (links[0] if links else "")
            if val:
                out["メーカー"] = [val]
        elif re.search(r"シリーズ|系列|Series", key, re.I):
            val = plain or (links[0] if links else "")
            if val:
                out["シリーズ"] = [val]
        elif re.search(r"コード|番号|Code", key, re.I):
            if plain:
                out["コード"] = [plain]
        elif re.search(r"公開日|发行|Release", key, re.I):
            if plain:
                out["発売日"] = [plain]
        elif re.search(r"再生時間|时长|Duration", key, re.I):
            if plain:
                out["再生時間"] = [plain]
    return out


def _first_row(rows: dict[str, list[str]], *keys: str) -> str:
    for k in keys:
        vals = rows.get(k) or []
        if vals and str(vals[0]).strip():
            return str(vals[0]).strip()
    return ""


def _row_list(rows: dict[str, list[str]], *keys: str) -> list[str]:
    for k in keys:
        vals = rows.get(k)
        if vals:
            return list(vals)
    return []


def _parse_cover(html: str, page_url: str) -> str | None:
    decoded = html.replace("\\u002F", "/").replace("\\u0026", "&")
    m = re.search(r"https?://icdn\.123av\.me/[^\"'\\\s]+cover\.jpg[^\"'\\\s]*", decoded, re.I) or re.search(
        r"poster=https%3A%2F%2Ficdn\.123av\.me[^\"'\\]+cover\.jpg[^\"'\\]*", decoded, re.I
    )
    if m:
        url = m.group(0)
        if url.startswith("poster="):
            url = unquote(url[len("poster=") :])
        return abs_url(url, page_url) or url
    doc = soup(html)
    player = doc.select_one("#player")
    poster = (player.get("data-poster") if player else "") or ""
    if poster:
        return abs_url(poster, page_url)
    return None


def _parse_title(html: str, code: str) -> str:
    doc = soup(html)
    h1 = doc.select_one("h1.watch__title") or doc.select_one("h1")
    raw = strip_tags(h1.get_text() if h1 else "")
    if not raw:
        tm = re.search(r"<title>([^<]+)</title>", html, re.I)
        raw = re.sub(r"\s*—\s*123AV.*", "", tm.group(1) if tm else "", flags=re.I)
    std = std_code(code)
    pat = re.escape(std).replace(r"\-", "[-]?")
    title = re.sub(rf"^{pat}\s*[—–-]\s*", "", raw, flags=re.I).strip()
    title = re.sub(rf"^{pat}\s*", "", title, flags=re.I).strip()
    return clean_title(title, std)


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    std = std_code(code)
    if not std:
        raise RuntimeError("番号为空")

    base = _locale_base(base_url or DEFAULT_BASE)
    if not base:
        raise RuntimeError("未配置网站地址")

    referer = f"{base}/"
    search_url = _search_url(base, std)
    try:
        search_html = fetch_html(search_url, referer=referer, cookie=cookie or None, source_id="njav")
    except Exception as e:
        raise RuntimeError(f"搜索无响应: {e}") from e
    if not search_html or len(search_html) < 2000:
        raise RuntimeError("搜索无响应")

    detail_path = _pick_detail_href(search_html, std)
    if not detail_path:
        raise RuntimeError("未找到")

    detail_url = abs_url(detail_path, f"{base}/") or detail_path
    try:
        detail_html = fetch_html(detail_url, referer=search_url, cookie=cookie or None, source_id="njav")
    except Exception as e:
        raise RuntimeError(f"详情页无响应: {e}") from e
    if not detail_html or len(detail_html) < 2000:
        raise RuntimeError("详情页无响应")

    if not _is_detail_html(detail_html, std):
        raise RuntimeError("解析失败")

    rows = _parse_info_rows(detail_html)
    if not rows:
        rows = _parse_legacy_rows(detail_html)

    title = _parse_title(detail_html, std)
    if title and is_junk_title(title):
        raise RuntimeError("解析失败")

    actors = _row_list(rows, "出演者", "女優", "女优", "Actress")[:20]
    tags = []
    for g in _row_list(rows, "ジャンル", "类型", "Genre") + _row_list(rows, "タグ", "标签", "Tag"):
        if g and g not in tags:
            tags.append(g)
    tags = tags[:40]

    studio = _first_row(rows, "メーカー", "片商", "Maker") or None
    premiered = (_first_row(rows, "発売日", "发行日", "Release", "公開日") or "")[:10] or None

    doc = soup(detail_html)
    desc = doc.select_one("div.description p")
    plot = strip_tags(desc.get_text() if desc else "")
    if not plot or len(plot) < 12:
        plot = ""

    cover = _parse_cover(detail_html, detail_url)
    if cover and is_junk_cover_url(cover):
        cover = None

    if not title and not cover and not actors and not tags:
        raise RuntimeError("解析失败")

    return make_detail(
        source="njav",
        code=std,
        title=title or None,
        poster=cover,
        studio=studio,
        actors=actors,
        tags=tags,
        overview=plot or None,
        date=premiered,
    )
