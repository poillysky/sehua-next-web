# -*- coding: utf-8 -*-
"""女体のしんぴ（Nyoshin）详情刮削。

番号：`NYOSHIN-2500` / `NYOSHIN-n2500` / `n2500`
→ moviepages/`n2500`；封面 `contents/{digits}/thum2.jpg`

抓取与「未找到」判定见 `common.fetch_official_html`。
"""

from __future__ import annotations

import re
from typing import Any

from .common import (
    clean_title,
    fetch_official_html,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    official_base,
    official_code,
    pick_og_image,
    pick_og_title,
    soup,
    strip_tags,
)

DEFAULT_BASE = "https://www.nyoshin.com"
STUDIO = "女体のしんぴ"
_SRC = "nyoshin"

_KEY_RE = re.compile(r"^(?:NYOSHIN[-_]?)?n?(\d{3,5})$", re.I)


def parse_nyoshin_movie_key(code: str) -> str | None:
    """返回官网 moviepages 键（带 n 前缀），如 n2500。"""
    raw = str(code or "").strip().upper().replace(" ", "")
    m = _KEY_RE.match(raw)
    if not m:
        return None
    return f"n{int(m.group(1))}"


def _parse_jp_date(text: str) -> str | None:
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text or "")
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    key = parse_nyoshin_movie_key(code)
    if not key:
        raise RuntimeError("番号格式无效")
    digits = key[1:]  # contents/{digits}/

    base = official_base(base_url, DEFAULT_BASE, require_domains=("nyoshin",))
    detail_url = f"{base}/moviepages/{key}/index.html"
    html = fetch_official_html(
        detail_url,
        base=base,
        source_id=_SRC,
        cookie=cookie or None,
        must_contain=(f"/moviepages/{key}/", f"/contents/{digits}/"),
    )

    doc = soup(html)
    title_el = doc.select_one("[class*='MovieHeader_title__']")
    title = clean_title(
        strip_tags(title_el.get_text() if title_el else "")
        or re.split(r"\s*\|\s*", pick_og_title(html) or "", maxsplit=1)[0],
        code,
    )
    if is_junk_title(title):
        title = ""

    actor_el = doc.select_one("[class*='MovieHeader_actress__']")
    actor = strip_tags(actor_el.get_text() if actor_el else "")
    actors = [actor] if actor and 1 <= len(actor) <= 40 else []

    desc_el = doc.select_one("[class*='MovieHeader_description__']")
    plot = strip_tags(desc_el.get_text() if desc_el else "")
    if len(plot) < 12:
        plot = ""

    date_el = doc.select_one("[class*='MovieHeader_release_date__']")
    premiered = _parse_jp_date(strip_tags(date_el.get_text() if date_el else ""))

    cover = pick_og_image(html) or f"{base}/contents/{digits}/thum2.jpg"
    if cover.startswith("//"):
        cover = "https:" + cover
    if cover and is_junk_cover_url(cover):
        cover = None

    extras: list[str] = []
    for m in re.finditer(
        rf"https?://[^\"']+/contents/{re.escape(digits)}/[^\s\"']+\.jpg",
        html,
        re.I,
    ):
        u = m.group(0)
        if u not in extras and (not cover or u != cover):
            extras.append(u)
    extras = extras[:30]

    if not title and not cover and not actors:
        raise RuntimeError("未找到")

    year = premiered[:4] if premiered else None
    code_u = official_code(code, prefix="NYOSHIN", fallback=f"NYOSHIN-{digits}")

    extra: dict[str, Any] = {
        "website": detail_url,
        "mosaic": "无码",
        "extrafanartUrls": extras or None,
        "originalPlot": plot or None,
    }
    return make_detail(
        source=_SRC,
        code=code_u,
        title=title or None,
        poster=cover,
        studio=STUDIO,
        actors=actors,
        tags=[],
        overview=plot or None,
        date=premiered,
        year=year,
        extra=extra,
    )
