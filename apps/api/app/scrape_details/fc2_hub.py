# -*- coding: utf-8 -*-
"""FC2 Hub (javten) 详情刮削（对齐 MDCS fc2_hub.ts）。"""

from __future__ import annotations

import json
import re

from .common import (
    abs_url,
    clean_title,
    fetch_html,
    fetch_json,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    pick_og_title,
    soup,
    strip_tags,
)

DEFAULT_BASE = "https://javten.com"
BLOCKED_RE = re.compile(r"Edge IP Restricted|Just a moment|cf-browser-verification|Access Denied", re.I)


def _parse_fc2_id(code: str) -> tuple[str, str] | None:
    m = re.search(r"FC2[-_]?PPV[-_]?(\d+)", code, re.I) or re.search(r"FC2[-_]?(\d+)", code, re.I)
    if not m:
        return None
    fid = m.group(1)
    return fid, f"FC2-PPV-{fid}"


def _hub_abs(href: str, base: str) -> str | None:
    trimmed = str(href or "").strip()
    if not trimmed:
        return None
    if trimmed.startswith("//"):
        return abs_url(f"https:{trimmed}", base)
    return abs_url(trimmed, base)


def _parse_title(html: str, display: str, fid: str) -> str:
    h1s = [strip_tags(m.group(1) or "") for m in re.finditer(r"<h1[^>]*>([\s\S]*?)</h1>", html, re.I)]
    if len(h1s) >= 2:
        h1_title = h1s[1]
    else:
        h1_title = next((t for t in h1s if t and not re.match(r"^FC2", t, re.I)), h1s[0] if h1s else "")
    title = clean_title(h1_title or pick_og_title(html), display)
    return re.sub(rf"^FC2[-_]?PPV[-_]?{re.escape(fid)}\s*[-–—:]?\s*", "", title, flags=re.I).strip()


def _parse_cover(html: str, base_url: str) -> str | None:
    candidates: list[str] = []
    for m in re.finditer(r'<a[^>]+data-fancybox=["\']gallery["\'][^>]+href=["\']([^"\']+)["\']', html, re.I):
        candidates.append(m.group(1))
    for m in re.finditer(r'href=["\']([^"\']+)["\'][^>]+data-fancybox=["\']gallery["\']', html, re.I):
        candidates.append(m.group(1))
    urls = []
    for raw in candidates:
        u = _hub_abs(raw, base_url)
        if u and not is_junk_cover_url(u):
            urls.append(u)
    return next((u for u in urls if re.search(r"contents-thumbnail\d*\.fc2\.com", u, re.I)), None) or (
        urls[0] if urls else None
    )


def _parse_extrafanart(html: str, base_url: str) -> list[str]:
    doc = soup(html)
    urls: list[str] = []
    for el in doc.select('div[style*="padding: 0"] a[href], div[style*="padding:0"] a[href]'):
        href = el.get("href") or ""
        u = _hub_abs(href, base_url)
        if not u or is_junk_cover_url(u) or u in urls:
            continue
        if (
            not re.search(r"\.(jpe?g|png|webp)(\?|$)", u, re.I)
            and not re.search(r"/file/", u, re.I)
            and not re.search(r"contents-thumbnail", u, re.I)
        ):
            continue
        urls.append(u)
    return urls[:30]


def _parse_studio(html: str) -> str | None:
    doc = soup(html)
    el = doc.select_one("div.col-8")
    t = strip_tags(el.get_text() if el else "")
    t = re.sub(r"\s+\d+(\.\d+)?\s*$", "", t).strip()
    return t if t and len(t) <= 80 else None


def _parse_tags(html: str) -> list[str]:
    doc = soup(html)
    tags: list[str] = []
    for el in doc.select('p.card-text a[href*="/tag/"]'):
        n = strip_tags(el.get_text())
        if n and len(n) <= 40 and n not in tags:
            tags.append(n)
    return tags


def _parse_outline(html: str) -> str | None:
    doc = soup(html)
    el = doc.select_one("div.col.des")
    t = strip_tags(el.get_text() if el else "").replace("・", " ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\(function\(\)\s*\{[\s\S]*$", "", t, flags=re.I).strip()
    if len(t) >= 12 and not is_junk_title(t):
        return t
    return None


def _parse_trailer_video_id(html: str, number: str) -> str:
    doc = soup(html)
    api = doc.select_one('[class*="player-api"][data-id]')
    from_api = (api.get("data-id") if api else "") or ""
    if re.match(r"^\d+$", from_api):
        return from_api
    iframe = doc.select_one('iframe[data-src*="/embed/"]') or doc.select_one('iframe[src*="/embed/"]')
    src = ((iframe.get("data-src") if iframe else "") or (iframe.get("src") if iframe else "") or "")
    emb = re.search(r"/embed/(\d+)", src, re.I)
    if emb:
        return emb.group(1)
    return number


def _parse_ld_meta(html: str) -> dict:
    ld_date = ""
    ld_runtime: int | None = None
    ld_genres: list[str] = []
    ld_actors: list[str] = []
    for block in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>',
        html,
        re.I,
    ):
        try:
            data = json.loads(block.group(1) or "")
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            t = str(item.get("@type") or "")
            if t not in ("Movie", "VideoObject", "Product"):
                continue
            ld_date = str(item.get("datePublished") or ld_date or "").strip()
            dur = str(item.get("duration") or "")
            mins = re.search(r"PT(?:(\d+)H)?(?:(\d+)M)?", dur, re.I)
            if mins:
                ld_runtime = int(mins.group(1) or 0) * 60 + int(mins.group(2) or 0) or ld_runtime
            if isinstance(item.get("genre"), list):
                for g in item["genre"]:
                    n = str(g or "").strip()
                    if n and n not in ld_genres:
                        ld_genres.append(n)
            if isinstance(item.get("actor"), list):
                for a in item["actor"]:
                    n = str((a.get("name") if isinstance(a, dict) else a) or "").strip()
                    if n and n not in ld_actors:
                        ld_actors.append(n)
    return {"date": ld_date, "runtime": ld_runtime, "genres": ld_genres, "actors": ld_actors}


def _pick_detail_link(html: str, base: str, fid: str) -> str | None:
    lang_skip = re.compile(r"/tw/|/ko/|/en/", re.I)
    for m in re.finditer(rf'<link[^>]+href=["\']([^"\']*id{re.escape(fid)}[^"\']*)["\']', html, re.I):
        h = m.group(1)
        if not lang_skip.search(h):
            return _hub_abs(h, base)
    landed = re.search(rf'https?://[^"\'\s]+/video/\d+/id{re.escape(fid)}\b', html, re.I)
    if landed:
        return landed.group(0)
    href = None
    for m in re.finditer(rf'(?:href|content)=["\']([^"\']*id{re.escape(fid)}[^"\']*)["\']', html, re.I):
        h = m.group(1)
        if re.search(r"/video/\d+/id", h, re.I) and not lang_skip.search(h):
            href = h
            break
    if not href:
        m2 = re.search(rf'href=["\']([^"\']*(?:id)?{re.escape(fid)}[^"\']*)["\']', html, re.I)
        href = m2.group(1) if m2 else None
    return _hub_abs(href, base) if href else None


def _fetch_trailer(video_id: str) -> str | None:
    try:
        data = fetch_json(
            f"https://adult.contents.fc2.com/api/v2/videos/{video_id}/sample",
            headers={"Accept": "application/json", "Referer": "https://adult.contents.fc2.com/"},
            source_id="fc2_hub",
        )
        path = data.get("path") if isinstance(data, dict) else None
        if isinstance(path, str) and path.startswith("http"):
            return path
    except Exception:
        return None
    return None


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    parsed = _parse_fc2_id(code)
    if not parsed:
        raise RuntimeError("番号格式无效")
    fid, display = parsed

    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")

    from urllib.parse import quote

    search_url = f"{base}/search?kw={quote(fid)}"
    try:
        search_html = fetch_html(search_url, referer=f"{base}/", cookie=cookie or None, source_id="fc2_hub")
    except Exception as e:
        raise RuntimeError(f"搜索失败: {e}") from e

    detail_url = None
    html = None
    if len(search_html) >= 500 and not BLOCKED_RE.search(search_html):
        detail_url = _pick_detail_link(search_html, base, fid)
        if detail_url:
            if re.search(r'data-fancybox=["\']gallery["\']', search_html, re.I):
                html = search_html
            else:
                try:
                    html = fetch_html(
                        detail_url, referer=search_url, cookie=cookie or None, source_id="fc2_hub"
                    )
                except Exception:
                    html = None

    if not html or not detail_url:
        raise RuntimeError("未找到")

    trailer_id = _parse_trailer_video_id(html, fid)
    trailer_url = _fetch_trailer(trailer_id)

    title = _parse_title(html, display, fid)
    if not title or is_junk_title(title):
        raise RuntimeError("未找到标题")

    cover = _parse_cover(html, detail_url)
    extrafanart = _parse_extrafanart(html, detail_url)
    studio = _parse_studio(html)
    tag_genres = _parse_tags(html)
    plot = _parse_outline(html)
    ld = _parse_ld_meta(html)

    genres = list(dict.fromkeys([*tag_genres, *ld["genres"]]))[:40]
    actors = [a for a in ld["actors"] if a and a != studio][:20]
    mosaic = "无码" if re.search(r"無修正|无码|uncensored", f'{" ".join(genres)} {title}', re.I) else "有码"

    premiered = ""
    dm = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", ld["date"])
    if dm:
        premiered = f"{dm.group(1)}-{dm.group(2).zfill(2)}-{dm.group(3).zfill(2)}"
    runtime = ld["runtime"] if ld["runtime"] and ld["runtime"] > 0 else None

    return make_detail(
        source="fc2_hub",
        code=display,
        title=title,
        poster=cover,
        studio=studio,
        actors=actors,
        tags=genres,
        overview=plot,
        date=premiered or None,
        extra={
            "originalPlot": plot,
            "publisher": studio,
            "series": "FC2系列",
            "runtime": runtime,
            "trailerUrl": trailer_url,
            "website": detail_url,
            "mosaic": mosaic,
            "extrafanartUrls": extrafanart or None,
        },
    )
