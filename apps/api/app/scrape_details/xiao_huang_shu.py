# -*- coding: utf-8 -*-
"""小黄书 / xchina 详情。"""

from __future__ import annotations

import json
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

DEFAULT_BASE = "https://xchina.co"


def _norm(code: str) -> str:
    return str(code or "").strip().upper().replace("_", "-")


def _compact(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", _norm(code))


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    norm = _norm(code)
    compact = _compact(code)
    base = (base_url or DEFAULT_BASE).rstrip("/")
    queries = list(dict.fromkeys([norm, compact]))
    m = re.match(r"^([A-Z]{2,10})-?(\d{2,6}(?:-\d+)?)$", norm)
    if m:
        queries.extend([f"{m.group(1)}-{m.group(2)}", f"{m.group(1)}{m.group(2)}"])
    last_err: Exception | None = None
    for q in queries:
        try:
            search_url = f"{base}/search.html?keyword={quote(q)}"
            html = fetch_html(
                search_url,
                referer=f"{base}/",
                cookie=cookie or None,
                source_id="xiao_huang_shu",
            )
            doc = soup(html)
            hit_url = ""
            hit_cover = ""
            hit_actors: list[str] = []
            hit_studio = ""
            for item in doc.select(".item.video"):
                a = item.select_one('a[href*="/video/id-"]')
                if a is None:
                    continue
                href = (a.get("href") or "").strip()
                if not href:
                    continue
                hay = _compact(f"{item.get_text(' ', strip=True)} {a.get('title') or ''} {href}")
                if compact and compact not in hay:
                    continue
                hit_url = abs_url(href, base) or href
                style = (item.select_one(".img") or {}).get("style") if item.select_one(".img") else ""
                cm = re.search(r"url\(['\"]?([^'\")]+)['\"]?\)", style or "", re.I)
                if cm:
                    hit_cover = abs_url(cm.group(1), base) or ""
                hit_actors = [
                    strip_tags(x.get_text())
                    for x in item.select("a.model-item")
                    if strip_tags(x.get_text())
                ]
                tags = [strip_tags(t.get_text()) for t in item.select(".tags > div")]
                hit_studio = next(
                    (
                        t
                        for t in tags
                        if t
                        and t != compact
                        and not re.match(r"^\d+:\d{2}", t)
                        and _compact(t) != compact
                    ),
                    "",
                )
                break
            if not hit_url:
                continue
            detail_html = fetch_html(
                hit_url,
                referer=search_url,
                cookie=cookie or None,
                source_id="xiao_huang_shu",
            )
            d = soup(detail_html)
            title = strip_tags(
                (d.select_one("h1.hero-title-text") or d).get_text(" ", strip=True)
            ) or pick_og_title(detail_html)
            title = clean_title(re.sub(r"（[^）]*）|\([^)]*\)", "", title), code)
            if is_junk_title(title):
                title = ""
            actors = list(hit_actors)
            for a in d.select("a.model-item, .model-container a[href*='/model/']"):
                n = strip_tags(a.get_text())
                if n and 2 <= len(n) <= 20 and n not in actors:
                    actors.append(n)
            studio = hit_studio
            cover = pick_og_image(detail_html) or hit_cover
            if cover and is_junk_cover_url(cover):
                cover = None
            # ld+json
            for m_ld in re.finditer(
                r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>',
                detail_html,
                re.I,
            ):
                try:
                    data = json.loads(m_ld.group(1) or "")
                    arr = data if isinstance(data, list) else [data]
                    for vo in arr:
                        if not isinstance(vo, dict) or vo.get("@type") != "VideoObject":
                            continue
                        if vo.get("name") and not title:
                            title = clean_title(str(vo["name"]), code)
                        if isinstance(vo.get("thumbnailUrl"), str) and not cover:
                            cover = vo["thumbnailUrl"]
                except Exception:
                    continue
            if not title and not cover:
                raise RuntimeError("详情无有效内容")
            return make_detail(
                source="xiao_huang_shu",
                code=norm,
                title=title or None,
                poster=cover,
                studio=studio or None,
                actors=actors,
            )
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise RuntimeError(f"xiao_huang_shu 失败: {last_err}")
