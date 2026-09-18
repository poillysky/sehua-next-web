# -*- coding: utf-8 -*-
"""Tokyo Hot（東京熱）详情刮削。

番号：`TOKYOHOT-N1234` / `TOKYO-HOT-n1234` / `n1234` / `k1454`
→ `https://my.tokyo-hot.com/product/{id}/?lang=ja`
"""

from __future__ import annotations

import re
from typing import Any

from .common import (
    abs_url,
    clean_title,
    fetch_html,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    soup,
    strip_tags,
)

DEFAULT_BASE = "https://my.tokyo-hot.com"
STUDIO = "東京熱"
_SRC = "tokyohot"

_KEY_RE = re.compile(
    r"^(?:TOKYO(?:-?HOT)?|TOKYOHOT)[-_]?([NK])?(\d{3,5})$",
    re.I,
)
_BARE_RE = re.compile(r"^([NK])(\d{3,5})$", re.I)


def parse_tokyohot_movie_key(code: str) -> str | None:
    raw = str(code or "").strip().upper().replace(" ", "")
    m = _KEY_RE.match(raw) or _BARE_RE.match(raw)
    if not m:
        return None
    letter = (m.group(1) or "N").lower()
    return f"{letter}{int(m.group(2))}"


def tokyohot_detail_url(base: str, key: str) -> str:
    b = str(base or DEFAULT_BASE).rstrip("/")
    return f"{b}/product/{key}/?lang=ja"


def _info_map(html: str) -> dict[str, str]:
    doc = soup(html)
    out: dict[str, str] = {}
    wrap = doc.select_one(".infowrapper") or doc.select_one("#main .infowrapper")
    if not wrap:
        return out
    for dt in wrap.select("dt"):
        dd = dt.find_next_sibling("dd")
        label = strip_tags(dt.get_text())
        val = strip_tags(dd.get_text() if dd else "")
        if label and val:
            out[label] = val
    return out


def parse_tokyohot_actors(html: str) -> list[str]:
    doc = soup(html)
    out: list[str] = []
    wrap = doc.select_one(".infowrapper") or doc.select_one("#main .infowrapper")
    if wrap:
        for dt in wrap.select("dt"):
            if "出演" not in strip_tags(dt.get_text()):
                continue
            dd = dt.find_next_sibling("dd")
            if not dd:
                continue
            for a in dd.select("a"):
                n = strip_tags(a.get_text())
                if n and n != "不明" and 1 <= len(n) <= 40 and n not in out:
                    out.append(n)
            if not out:
                for part in re.split(r"[\s、,/|]+", strip_tags(dd.get_text())):
                    n = part.strip()
                    if n and n != "不明" and 1 <= len(n) <= 40 and n not in out:
                        out.append(n)
            break
    return out[:20]


def parse_tokyohot_tags(info: dict[str, str]) -> list[str]:
    out: list[str] = []
    for key in ("プレイ内容", "タグ"):
        for part in re.split(r"[\s、,/|]+", info.get(key) or ""):
            n = part.strip()
            if n and 1 <= len(n) <= 40 and n not in out:
                out.append(n)
    return out[:40]


def parse_tokyohot_cover(html: str, *, base: str, key: str) -> str | None:
    doc = soup(html)
    for a in doc.select("li.package a"):
        href = str(a.get("href") or "")
        if not href:
            continue
        u = abs_url(href, base) or href
        if u.endswith("L.jpg") or "jacket" in u.lower():
            return u
    for a in doc.select("li.package a"):
        href = str(a.get("href") or "")
        if href:
            return abs_url(href, base) or href
    vid = doc.select_one(".flowplayer video")
    if vid and vid.get("poster"):
        return abs_url(str(vid.get("poster")), base) or str(vid.get("poster"))
    # CDN 常见夹克
    return f"https://my.cdn.tokyo-hot.com/media/{key}/jacket/{key}.jpg"


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    key = parse_tokyohot_movie_key(code)
    if not key:
        raise RuntimeError("番号格式无效")

    base = (base_url or DEFAULT_BASE).rstrip("/") or DEFAULT_BASE
    if "tokyo-hot" not in base.lower() and "tokyohot" not in base.lower():
        base = DEFAULT_BASE
    detail_url = tokyohot_detail_url(base, key)

    try:
        html = fetch_html(
            detail_url,
            referer=f"{base}/",
            cookie=cookie or "age=yes; age_check=1",
            source_id=_SRC,
        )
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}") from e

    if not html or len(html) < 8000:
        raise RuntimeError("未找到")
    if "年齢確認" in (html[:4000] if html else "") and "infowrapper" not in html:
        raise RuntimeError("未找到")
    if f"/product/{key}" not in html and f"/media/{key}/" not in html:
        raise RuntimeError("未找到")

    doc = soup(html)
    h2 = doc.select_one("#main .contents h2") or doc.select_one(".contents h2")
    title = clean_title(strip_tags(h2.get_text() if h2 else ""), code)
    if is_junk_title(title):
        title = ""

    info = _info_map(html)
    plot_el = doc.select_one(".sentence")
    plot = strip_tags(plot_el.get_text() if plot_el else "")
    if len(plot) < 12:
        plot = ""

    actors = parse_tokyohot_actors(html)
    tags = parse_tokyohot_tags(info)
    premiered_raw = (info.get("配信開始日") or "").strip()
    premiered = None
    if premiered_raw:
        m = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})", premiered_raw)
        if m:
            premiered = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    series = (info.get("シリーズ") or "").strip() or None
    number = (info.get("作品番号") or key).strip().lower()

    cover = parse_tokyohot_cover(html, base=base, key=key)
    if cover and is_junk_cover_url(cover):
        cover = None

    extras: list[str] = []
    for a in doc.select('a[rel="cap"]'):
        href = str(a.get("href") or "")
        if href:
            u = abs_url(href, base) or href
            if u not in extras:
                extras.append(u)
    extras = extras[:30]

    if not title and not cover and not actors:
        raise RuntimeError("未找到")

    year = premiered[:4] if premiered else None
    code_u = str(code or "").strip().upper() or f"TOKYOHOT-{number.upper()}"
    if not re.match(r"^TOKYO", code_u, re.I):
        code_u = f"TOKYOHOT-{number.upper()}"

    extra: dict[str, Any] = {
        "series": series,
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
        tags=tags,
        overview=plot or None,
        date=premiered,
        year=year,
        extra=extra,
    )
