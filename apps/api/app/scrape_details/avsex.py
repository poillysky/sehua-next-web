# -*- coding: utf-8 -*-
"""AVSex 详情刮削（对齐 MDCS avsex.ts · 中文元数据 · 过盾）。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from .common import (
    abs_url,
    clean_title,
    fetch_html,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    page_mentions_code,
    pick_og_image,
    soup,
    strip_tags,
)
from app.core import detail_path_cache

DEFAULT_BASE = "https://avsex.cc"
SOURCE = "avsex"

TITLE_PREFIXES = [
    "[VIP会员点播] ",
    "[VIP會員點播] ",
    "[VIP] ",
    "★ (请到免费赠片区观赏)",
    "(破解版独家中文)",
]


def normalize_avsex_code(code: str) -> str:
    c = str(code or "").strip()
    if re.match(r"^n\d{4}$", c, re.I):
        return c.lower()
    return c.upper()


def match_avsex_search_title(title: str, code: str) -> bool:
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


def get_avsex_real_url(html: str, code: str, base: str) -> dict[str, str] | None:
    doc = soup(html)
    for a in doc.select("a[href*='/video/detail/']"):
        h4 = a.select_one("h4.truncate")
        title = strip_tags(h4.get_text()) if h4 else ""
        if not match_avsex_search_title(title, code):
            continue
        href = a.get("href") or ""
        if not href:
            continue
        img = a.select_one(
            "div.relative.overflow-hidden.rounded-t-md img"
        ) or a.select_one("div.relative.overflow-hidden img")
        poster = ""
        if img and img.get("src"):
            poster = abs_url(img.get("src"), base) or ""
        return {
            "detailUrl": abs_url(href, base) or "",
            "posterUrl": poster,
        }
    return None


def _dl_links(doc, label: re.Pattern[str]) -> list[str]:
    out: list[str] = []
    for dt in doc.select("dl dt"):
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


def _dl_text(doc, label: re.Pattern[str]) -> str:
    found = ""
    for dt in doc.select("dl dt"):
        if not label.search(strip_tags(dt.get_text())):
            continue
        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue
        found = strip_tags(dd.get_text())
    return re.sub(r"^N/A$", "", found, flags=re.I).strip()


def parse_avsex_runtime(raw: str) -> int | None:
    t = str(raw or "").strip()
    hms = re.search(r"(\d+)\s*:\s*(\d+)\s*:\s*(\d+)", t)
    if hms:
        return int(hms.group(1)) * 60 + int(hms.group(2))
    m = re.search(r"(\d+)", t)
    n = int(m.group(1)) if m else 0
    return n if n > 0 else None


def parse_avsex_premiered(raw: str) -> str | None:
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", str(raw or "").strip())
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def parse_avsex_title(html: str, code: str) -> str:
    doc = soup(html)
    std = normalize_avsex_code(code)
    h1 = doc.select_one("h1.sr-only")
    title = strip_tags(h1.get_text()) if h1 else ""
    if not title:
        m = re.search(r'<meta\s+name="title"\s+content="([^"]+)"', html or "", re.I)
        if m:
            parts = m.group(1).split("|")
            title = (parts[1] if len(parts) > 1 else parts[0]).strip()
    for prefix in TITLE_PREFIXES:
        title = title.replace(prefix, "")
    title = re.sub(
        rf"^{re.escape(std).replace('-', '[-_]?')}\s*",
        "",
        title,
        flags=re.I,
    )
    title = re.sub(r"\s+", " ", title).strip()
    title = clean_title(title, code)
    return "" if is_junk_title(title) else title


def parse_avsex_mosaic(html: str, studio: str = "") -> str:
    if re.search(r"國產|国产", studio or ""):
        return "国产"
    doc = soup(html)
    legacy = doc.select_one("article span.bg-blue-800")
    if legacy:
        t = strip_tags(legacy.get_text())
        return "无码" if re.search(r"無|无", t) else "有码"
    badges = " ".join(
        strip_tags(el.get_text()) for el in doc.select("article h2.text-xl span")
    )
    if re.search(r"無碼|无码|not-pixelated", badges, re.I):
        return "无码"
    return "有码"


def pick_best_avsex_image_url(src: str | None = None, srcset: str | None = None) -> str:
    if srcset:
        best = ""
        best_w = 0
        for part in srcset.split(","):
            m = re.match(r"^(\S+)\s+(\d+)w$", part.strip())
            if not m:
                continue
            url = m.group(1)
            if not url.startswith("http"):
                continue
            w = int(m.group(2) or 0)
            if w >= best_w:
                best_w = w
                best = url
        if best:
            return best
    s = (src or "").strip()
    return s if s.startswith("http") else ""


def parse_avsex_extrafanart(html: str, base: str) -> list[str]:
    doc = soup(html)
    out: list[str] = []
    for h in doc.select("h2"):
        if not re.search(r"精彩劇照|精彩剧照", strip_tags(h.get_text())):
            continue
        ul = h.find_next_sibling("ul")
        if ul is None:
            continue
        for img in ul.select("img[src]"):
            picked = pick_best_avsex_image_url(img.get("src"), img.get("srcset"))
            if not picked:
                continue
            absed = abs_url(picked, base) or ""
            if absed:
                out.append(absed)
    return list(dict.fromkeys(out))


def parse_avsex_outline(html: str) -> str:
    doc = soup(html)
    plot = ""
    for h in doc.select("h2"):
        if not re.search(r"劇情簡介|剧情简介", strip_tags(h.get_text())):
            continue
        p = h.find_next_sibling("p")
        if p is not None:
            plot = strip_tags(p.get_text())
        break
    for s in (
        "(中文字幕1280x720)",
        "(日本同步最新‧中文字幕1280x720)",
        "(日本同步最新‧中文字幕)",
        "(日本同步最新‧完整激薄版‧中文字幕1280x720)",
        "＊日本女優＊ 劇情做愛影片 ＊完整日本版＊",
        "＊日本女优＊ 剧情做爱影片 ＊完整日本版＊",
        "★ (请到免费赠片区观赏)",
    ):
        plot = plot.replace(s, "")
    plot = re.sub(r"\s+", " ", plot).strip()
    return plot if len(plot) >= 12 and not is_junk_title(plot) else ""


def parse_avsex_detail_html(
    html: str,
    code: str,
    base: str,
    poster_from_search: str = "",
) -> dict[str, Any]:
    doc = soup(html)
    std = normalize_avsex_code(code)
    title = parse_avsex_title(html, std)
    if not title:
        h2 = doc.select_one("article h2.text-xl")
        visible = strip_tags(h2.get_text()) if h2 else ""
        title = clean_title(
            re.sub(rf"^{re.escape(std).replace('-', '[-_]?')}\s*", "", visible, flags=re.I),
            std,
        )
        if is_junk_title(title):
            title = ""

    actors = _dl_links(doc, re.compile(r"演員|演员"))
    genres = _dl_links(doc, re.compile(r"標籤|标签|類別|类别"))
    studio = _dl_text(doc, re.compile(r"製作商|制作商"))
    if studio == "N/A":
        studio = ""
    runtime = parse_avsex_runtime(_dl_text(doc, re.compile(r"片長|片长")))
    premiered = parse_avsex_premiered(_dl_text(doc, re.compile(r"上架日")))
    plot = parse_avsex_outline(html)
    mosaic = parse_avsex_mosaic(html, studio)
    extras = parse_avsex_extrafanart(html, base)

    video = doc.select_one("video[poster]")
    img = doc.select_one("div.relative.overflow-hidden.rounded-md img")
    cover = (
        pick_og_image(html)
        or (video.get("poster") if video else None)
        or (img.get("src") if img else None)
        or poster_from_search
        or ""
    )
    if cover:
        cover = abs_url(cover, base)
    if cover and is_junk_cover_url(cover):
        cover = None

    return {
        "title": title or None,
        "plot": plot or None,
        "actors": actors,
        "genres": genres,
        "studio": studio or None,
        "premiered": premiered,
        "runtime": runtime,
        "mosaic": mosaic,
        "coverUrl": cover,
        "extrafanartUrls": extras or None,
    }


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict[str, Any]:
    del api_key
    std = normalize_avsex_code(code)
    if not std:
        raise RuntimeError("番号为空")
    base = (base_url or DEFAULT_BASE).rstrip("/")
    ck = cookie or None

    def _finish(parsed: dict[str, Any], detail_url: str, alt: str) -> dict[str, Any]:
        extra: dict[str, Any] = {
            "titleZh": parsed.get("title"),
            "originalPlot": parsed.get("plot"),
            "website": detail_url,
            "mosaic": parsed.get("mosaic"),
            "runtime": parsed.get("runtime"),
            "extrafanartUrls": parsed.get("extrafanartUrls"),
        }
        if alt and alt != parsed.get("coverUrl"):
            extra["alternateCoverUrls"] = [alt]
        return make_detail(
            source=SOURCE,
            code=std,
            title=parsed.get("title"),
            poster=parsed.get("coverUrl"),
            studio=parsed.get("studio"),
            actors=list(parsed.get("actors") or []),
            tags=list(parsed.get("genres") or []),
            overview=parsed.get("plot"),
            date=parsed.get("premiered"),
            extra=extra,
        )

    # 第十六轮：详情路径缓存命中 → 直接抓详情，跳过搜索（重复刮省 1 请求）。
    # 页面番号校验不过回落搜索；坏缓存最多浪费 1 请求，不会错绑。
    # 缓存路径没有搜索页，alternateCoverUrls（搜索页海报）不可得 —— 详情页封面兜底。
    cached_url = detail_path_cache.lookup(SOURCE, std)
    if cached_url:
        try:
            cached_html = fetch_html(
                cached_url, referer=f"{base}/", cookie=ck, source_id=SOURCE
            )
            if cached_html and page_mentions_code(cached_html, std):
                cached_parsed = parse_avsex_detail_html(cached_html, std, base, "")
                if cached_parsed.get("title"):
                    return _finish(cached_parsed, cached_url, "")
        except Exception:
            pass  # 缓存失效 → 回落搜索

    # MDCS：query 用小写
    search_url = f"{base}/tw/search?query={quote(std.lower())}"
    search_html = fetch_html(
        search_url, referer=f"{base}/", cookie=ck, source_id=SOURCE
    )
    hit = get_avsex_real_url(search_html or "", std, base)
    if not hit or not hit.get("detailUrl"):
        raise RuntimeError("搜索无结果")

    detail_url = hit["detailUrl"]
    # 第十六轮：记住详情 URL，重复刮直接走缓存跳过搜索
    detail_path_cache.remember(SOURCE, std, detail_url)
    detail_html = fetch_html(
        detail_url, referer=search_url, cookie=ck, source_id=SOURCE
    )
    parsed = parse_avsex_detail_html(
        detail_html or "", std, base, hit.get("posterUrl") or ""
    )
    if not parsed.get("title"):
        raise RuntimeError("未找到标题")

    return _finish(parsed, detail_url, hit.get("posterUrl") or "")
