# -*- coding: utf-8 -*-
"""FD2PPV 详情刮削（对齐 MDCS fd2ppv.ts）。"""

from __future__ import annotations

import re

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

DEFAULT_BASE = "https://fd2ppv.cc"
CF_RE = re.compile(r"Too many requests|Just a moment|cf-browser-verification", re.I)
NOT_FOUND_RE = re.compile(r"作品が見つかりません|ページが見つかりません|404 Page Not Found", re.I)


def _parse_fc2_id(code: str) -> tuple[str, str] | None:
    m = re.search(r"FC2[-_]?PPV[-_]?(\d+)", code, re.I) or re.search(r"FC2[-_]?(\d+)", code, re.I)
    if not m:
        return None
    fid = m.group(1)
    return fid, f"FC2-PPV-{fid}"


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    parsed = _parse_fc2_id(code)
    if not parsed:
        raise RuntimeError("番号格式无效")
    fid, display = parsed

    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")

    url = f"{base}/articles/{fid}"
    try:
        html = fetch_html(url, referer=f"{base}/", cookie=cookie or None, source_id="fd2ppv")
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}") from e

    if CF_RE.search(html) and len(html) < 8000:
        raise RuntimeError("访问被限制")
    if NOT_FOUND_RE.search(html):
        raise RuntimeError("未找到")

    doc = soup(html)
    brief = doc.select_one(".work-brief")
    meta_desc = doc.select_one("meta[name='description']")
    title_el = doc.select_one("title")
    title = clean_title(
        strip_tags(brief.get_text() if brief else "")
        or ((meta_desc.get("content") if meta_desc else "") or "")
        or pick_og_title(html)
        or strip_tags(title_el.get_text() if title_el else ""),
        display,
    )
    title = re.sub(rf"^FC2[-_]?PPV[-_]?{re.escape(fid)}\s*[-–—:]?\s*", "", title, flags=re.I)
    title = re.sub(r"\s*[|｜].*$", "", title).strip()
    if not title or re.match(r"^\d{5,}$", title) or is_junk_title(title):
        title = ""

    def meta_val(label: re.Pattern[str]) -> str:
        for el in doc.select(".work-meta-label"):
            if not label.search(strip_tags(el.get_text())):
                continue
            cand = el.find_all_next(class_="work-meta-value", limit=1)
            if cand:
                return strip_tags(cand[0].get_text())
        return ""

    premiered_raw = meta_val(re.compile(r"配信日|販売日|公開日"))
    premiered = ""
    dm = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", premiered_raw)
    if dm:
        premiered = f"{dm.group(1)}-{dm.group(2).zfill(2)}-{dm.group(3).zfill(2)}"

    runtime_raw = meta_val(re.compile(r"収録時間|再生時間"))
    runtime: int | None = None
    hm = re.search(r"(?:(\d+):)?(\d{1,2}):(\d{2})", runtime_raw)
    if hm:
        runtime = int(hm.group(1) or 0) * 60 + int(hm.group(2) or 0) or None
    else:
        mins = re.search(r"(\d+)\s*分", runtime_raw)
        if mins:
            runtime = int(mins.group(1)) or None

    seller = meta_val(re.compile(r"販売者|作者|投稿者")) or ""
    studio = seller or meta_val(re.compile(r"配信元")) or "FC2"

    genres: list[str] = []
    for el in doc.select(".work-tags a"):
        n = strip_tags(el.get_text())
        if not n or len(n) > 40 or re.search(r"タグ|tag", n, re.I) or n in genres:
            continue
        genres.append(n)
    for el in doc.select('a[href*="/tags/actresses/"]'):
        n = strip_tags(el.get_text())
        if not n or len(n) > 40 or re.search(r"AV女優|女優|タグ", n, re.I) or n in genres:
            continue
        genres.append(n)
    cat = meta_val(re.compile(r"カテゴリ"))
    if cat and cat not in genres:
        genres.insert(0, cat)

    actors: list[str] = []
    for el in doc.select('a[href*="/actresses/"]'):
        href = el.get("href") or ""
        if re.search(r"/tags/actresses/", href, re.I) or not re.search(r"/actresses/\d+", href, re.I):
            continue
        n = strip_tags(el.get_text())
        if not n or len(n) > 40 or re.search(r"AV女優|女優", n, re.I) or n in actors:
            continue
        actors.append(n)

    photo_m = re.search(
        r'class=["\'][^"\']*work-original-photos[^"\']*["\'][^>]*>([\s\S]*?)</div>',
        html,
        re.I,
    ) or re.search(
        r'class=["\'][^"\']*work-photos[^"\']*["\'][^>]*>([\s\S]*?)</div>',
        html,
        re.I,
    )
    photo_block = photo_m.group(1) if photo_m else ""
    photos = [m.group(1) for m in re.finditer(r'(https?://[^\s"\'<>]+\.(?:jpg|jpeg|png|webp|avif))', photo_block, re.I)]
    cover = photos[0] if photos else pick_og_image(html)
    if cover:
        cover = abs_url(cover, url) or cover
    if cover and is_junk_cover_url(cover):
        cover = None

    if not title and not cover:
        raise RuntimeError("无标题与封面")

    alts = []
    for p in photos[1:8]:
        u = abs_url(p, url)
        if u:
            alts.append(u)

    return make_detail(
        source="fd2ppv",
        code=display,
        title=title or None,
        poster=cover,
        studio=studio,
        actors=actors[:20],
        tags=genres[:40],
        date=premiered or None,
        extra={
            "publisher": studio,
            "runtime": runtime if runtime and runtime > 0 else None,
            "website": url,
            "alternateCoverUrls": alts or None,
        },
    )
