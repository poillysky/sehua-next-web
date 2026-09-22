# -*- coding: utf-8 -*-
"""KIN8tengoku（金髪天國）详情刮削（官网 HTML）。

番号：`KIN8-3500` / `kin8tengoku-3500` → moviepages/`3500`。
封面：`/{id}/pht/1.jpg`（横图）。

抓取与「未找到」判定见 `common.fetch_official_html`。
"""

from __future__ import annotations

import re
from typing import Any

from .common import (
    abs_url,
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

DEFAULT_BASE = "https://www.kin8tengoku.com"
STUDIO = "金髪天國"
_SRC = "kin8"

_KEY_RE = re.compile(r"^(?:KIN8(?:TENGOKU)?[-_]?)?0*(\d{3,5})$", re.I)


def parse_kin8_movie_key(code: str) -> str | None:
    raw = str(code or "").strip().upper().replace(" ", "")
    m = _KEY_RE.match(raw)
    if not m:
        return None
    return str(int(m.group(1)))


def parse_kin8_actors(html: str) -> list[str]:
    doc = soup(html)
    out: list[str] = []
    for el in doc.select("[class*='Movie_Detail_actor']"):
        cls = " ".join(el.get("class") or [])
        if "actor-type" in cls:
            continue
        text = strip_tags(el.get_text())
        # 「モデル:ローラ」/「模特:…」
        m = re.match(r"^(?:モデル|模特|Actress|Model)\s*[:：]\s*(.+)$", text, re.I)
        name = (m.group(1) if m else text).strip()
        if name and 1 <= len(name) <= 40 and name not in out:
            out.append(name)
    return out[:12]


def parse_kin8_tags(html: str) -> list[str]:
    doc = soup(html)
    out: list[str] = []
    for el in doc.select("[class*='Movie_Detail_actor-type']"):
        text = strip_tags(el.get_text())
        # 标签常粘在一起；按常见日文词界粗切失败时整段保留
        parts = re.findall(
            r"フェラチオ|ぶっかけ|顔射|イラマチオ|中出し|生ハメ|巨乳|美脚|T-バック|低画質|[A-Za-z][\w\-]+|[\u3040-\u30ff\u4e00-\u9fff]{2,12}",
            text,
        )
        for p in parts or ([text] if text else []):
            n = str(p or "").strip()
            if n and 1 <= len(n) <= 40 and n not in out:
                out.append(n)
    return out[:40]


def parse_kin8_plot(html: str) -> str:
    doc = soup(html)
    el = doc.select_one("[class*='Movie_Detail_memo']")
    plot = strip_tags(el.get_text() if el else "")
    return plot if len(plot) >= 12 else ""


def parse_kin8_cover(html: str, *, base: str, key: str) -> str | None:
    cover = pick_og_image(html)
    if cover:
        if cover.startswith("//"):
            cover = "https:" + cover
        return abs_url(cover, base) or cover
    return f"{base.rstrip('/')}/{key}/pht/1.jpg"


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    key = parse_kin8_movie_key(code)
    if not key:
        raise RuntimeError("番号格式无效")

    base = official_base(base_url, DEFAULT_BASE, require_domains=("kin8tengoku",))
    detail_url = f"{base}/moviepages/{key}/index.html"
    html = fetch_official_html(
        detail_url,
        base=base,
        source_id=_SRC,
        cookie=cookie or None,
        must_contain=(f"/moviepages/{key}/", f"/{key}/pht/"),
    )

    raw_title = pick_og_title(html) or ""
    raw_title = re.split(r"\s*\|\s*", raw_title, maxsplit=1)[0].strip()
    title = clean_title(raw_title, code)
    if is_junk_title(title):
        title = ""

    actors = parse_kin8_actors(html)
    tags = parse_kin8_tags(html)
    plot = parse_kin8_plot(html)
    cover = parse_kin8_cover(html, base=base, key=key)
    if cover and is_junk_cover_url(cover):
        cover = None

    extras: list[str] = []
    for m in re.finditer(
        rf"https?://[^\"']+/{re.escape(key)}/pht/(\d+)\.jpg", html, re.I
    ):
        u = m.group(0)
        if u not in extras:
            extras.append(u)
    if not extras and cover:
        # 常见连号缩略图
        for i in range(1, 9):
            extras.append(f"{base.rstrip('/')}/{key}/pht/{i}.jpg")
    extras = extras[:30]

    if not title and not cover and not actors:
        raise RuntimeError("未找到")

    code_u = official_code(code, prefix="KIN8", fallback=f"KIN8-{key}")

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
        tags=tags,
        overview=plot or None,
        date=None,
        year=None,
        extra=extra,
    )
