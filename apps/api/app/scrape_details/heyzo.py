# -*- coding: utf-8 -*-
"""HEYZO 详情刮削（官网 HTML）。

番号：`HEYZO-2034` / `heyzo 2034` → moviepages/`2034`。
封面优先 `thumbnail.jpg` / `player_thumbnail.jpg`（横图，不裁）。
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
    pick_og_image,
    pick_og_title,
    soup,
    strip_tags,
)

DEFAULT_BASE = "https://www.heyzo.com"
STUDIO = "HEYZO"
_SRC = "heyzo"

_KEY_RE = re.compile(r"^(?:HEYZO[-_]?)?0*(\d{1,5})$", re.I)


def parse_heyzo_movie_key(code: str) -> str | None:
    raw = str(code or "").strip().upper().replace(" ", "")
    m = _KEY_RE.match(raw)
    if not m:
        return None
    return str(int(m.group(1)))  # 去前导零，官网路径无补零


def heyzo_detail_url(base: str, key: str) -> str:
    b = str(base or DEFAULT_BASE).rstrip("/")
    return f"{b}/moviepages/{key}/index.html"


def _movie_info_map(html: str) -> dict[str, str]:
    doc = soup(html)
    out: dict[str, str] = {}
    table = doc.select_one("table.movieInfo")
    if not table:
        return out
    for tr in table.select("tr"):
        cells = tr.select("td")
        if len(cells) < 2:
            continue
        label = strip_tags(cells[0].get_text())
        # 标签行可能 colspan，值在同一行或下一行 ul
        if "タグ" in label or "キーワード" in label:
            continue
        val = strip_tags(cells[1].get_text())
        if label and val:
            out[label] = val
    return out


def parse_heyzo_actors(html: str) -> list[str]:
    doc = soup(html)
    out: list[str] = []
    for a in doc.select("tr.table-actor td a"):
        n = strip_tags(a.get_text())
        if n and 2 <= len(n) <= 40 and n not in out:
            out.append(n)
    return out[:20]


def parse_heyzo_tags(html: str) -> list[str]:
    doc = soup(html)
    out: list[str] = []
    for a in doc.select("ul.tag-keyword-list a"):
        n = strip_tags(a.get_text())
        if n and 1 <= len(n) <= 40 and n not in out:
            out.append(n)
    # 女優タイプ也并入标签
    for a in doc.select("tr.table-actor-type a"):
        n = strip_tags(a.get_text())
        if n and 1 <= len(n) <= 40 and n not in out:
            out.append(n)
    return out[:40]


def parse_heyzo_plot(html: str) -> str:
    doc = soup(html)
    el = doc.select_one("p.memo") or doc.select_one(".memo")
    plot = strip_tags(el.get_text() if el else "")
    return plot if len(plot) >= 12 else ""


def parse_heyzo_cover(html: str, *, base: str, key: str) -> str | None:
    # 优先本片目录下较大缩略图
    for name in ("thumbnail.jpg", "player_thumbnail.jpg", "player_thumbnail_450.jpg"):
        m = re.search(
            rf"/contents/\d+/{re.escape(key)}/images/{re.escape(name)}",
            html,
            re.I,
        )
        if m:
            return abs_url(m.group(0), base) or f"{base.rstrip('/')}{m.group(0)}"
    cover = pick_og_image(html)
    if cover:
        if cover.startswith("//"):
            cover = "https:" + cover
        return abs_url(cover, base) or cover
    return f"{base.rstrip('/')}/contents/3000/{key}/images/player_thumbnail.jpg"


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    key = parse_heyzo_movie_key(code)
    if not key:
        raise RuntimeError("番号格式无效")

    base = (base_url or DEFAULT_BASE).rstrip("/") or DEFAULT_BASE
    # 目录若误配其它站，仍打官网
    if "heyzo.com" not in base.lower():
        base = DEFAULT_BASE
    detail_url = heyzo_detail_url(base, key)

    try:
        html = fetch_html(
            detail_url, referer=f"{base}/", cookie=cookie or None, source_id=_SRC
        )
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}") from e

    if not html or len(html) < 4000:
        raise RuntimeError("未找到")
    if re.search(r"<title[^>]*>\s*404\b", html, re.I):
        raise RuntimeError("未找到")
    if f"/moviepages/{key}/" not in html and f"/contents/" not in html:
        raise RuntimeError("未找到")

    info = _movie_info_map(html)
    h1 = soup(html).select_one("h1")
    title = clean_title(
        strip_tags(h1.get_text() if h1 else "") or pick_og_title(html) or "",
        code,
    )
    # og 标题常带「演员 【读音】 标题 - HEYZO」杂质，h1 更干净
    if is_junk_title(title):
        title = ""

    actors = parse_heyzo_actors(html)
    tags = parse_heyzo_tags(html)
    plot = parse_heyzo_plot(html)
    premiered = (info.get("公開日") or "")[:10] or None
    series = ""
    for k, v in info.items():
        if "シリーズ" in k:
            series = v
            break

    cover = parse_heyzo_cover(html, base=base, key=key)
    if cover and is_junk_cover_url(cover):
        cover = None

    extras: list[str] = []
    for m in re.finditer(
        rf"/contents/\d+/{re.escape(key)}/images/capture\d+\.jpg", html, re.I
    ):
        u = abs_url(m.group(0), base) or f"{base}{m.group(0)}"
        if u not in extras:
            extras.append(u)
    extras = extras[:30]

    if not title and not cover and not actors:
        raise RuntimeError("未找到")

    year = premiered[:4] if premiered and re.match(r"^\d{4}", premiered) else None
    code_u = str(code or "").strip().upper() or f"HEYZO-{key}"
    if not code_u.startswith("HEYZO"):
        code_u = f"HEYZO-{key}"

    extra: dict[str, Any] = {
        "series": series or None,
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
