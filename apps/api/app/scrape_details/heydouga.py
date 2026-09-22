# -*- coding: utf-8 -*-
"""Hey動画（HEYDOUGA）详情刮削（官网 HTML）。

番号：`HEYDOUGA-4030-001` / `heydouga_4030_001`
→ moviepages/`{mc}/{fn}`；封面 `contents/{mc}/{fn}/player_thumb.webp`（横图）。

抓取与「未找到」判定见 `common.fetch_official_html`。
"""

from __future__ import annotations

import html as html_lib
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

DEFAULT_BASE = "https://www.heydouga.com"
STUDIO = "HEYDOUGA"
_SRC = "heydouga"

# mc=频道/系列号，fn=作品序号（常 3 位补零）
_KEY_RE = re.compile(
    r"^(?:HEYDOUGA[-_]?)?(\d{3,5})[-_](\d{1,4})$",
    re.I,
)


def parse_heydouga_movie_key(code: str) -> tuple[str, str] | None:
    """返回 (mc, fn)，fn 补零到至少 3 位。"""
    raw = str(code or "").strip().upper().replace(" ", "")
    m = _KEY_RE.match(raw)
    if not m:
        return None
    mc = str(int(m.group(1)))
    fn_raw = m.group(2)
    fn = fn_raw if len(fn_raw) >= 3 else fn_raw.zfill(3)
    return mc, fn


def _label_value(doc: Any, label: str) -> str:
    """从「标签：值」结构取 span 值或同 li 文本。"""
    for span in doc.select("span"):
        t = strip_tags(span.get_text()).strip()
        if t != label and t != label.rstrip("："):
            continue
        nxt = span.find_next_sibling("span")
        if nxt:
            return strip_tags(nxt.get_text()).strip()
        parent = span.parent
        if parent is not None:
            full = strip_tags(parent.get_text()).strip()
            if full.startswith(label):
                return full[len(label) :].strip()
    return ""


def _parse_actors(doc: Any) -> list[str]:
    raw = _label_value(doc, "主演：") or _label_value(doc, "主演")
    if not raw:
        return []
    parts = re.split(r"[,、/|]|　|\s{2,}", raw)
    out: list[str] = []
    for p in parts:
        n = re.sub(r"\s+", " ", str(p or "").strip())
        if n and 1 <= len(n) <= 40 and n not in out:
            out.append(n)
    return out


def _parse_title(html: str, actors: list[str]) -> str:
    og = html_lib.unescape(pick_og_title(html) or "").strip()
    # 「女神、中出し - 村上里沙」→ 取破折号前
    if " - " in og:
        left, right = og.rsplit(" - ", 1)
        right_n = right.strip()
        if actors and any(a in right_n or right_n in a for a in actors):
            og = left.strip()
        elif len(left) >= 2:
            og = left.strip()
    title = clean_title(og, "")
    if title and not is_junk_title(title):
        return title
    doc = soup(html)
    h1 = doc.select_one("h1")
    h1t = html_lib.unescape(strip_tags(h1.get_text() if h1 else "")).strip()
    h1t = re.sub(r"\s*単品販売\s*$", "", h1t).strip()
    # 「村上里沙 - 女神、中出し」
    if " - " in h1t:
        left, right = h1t.split(" - ", 1)
        if actors and any(a in left or left in a for a in actors):
            h1t = right.strip()
    title = clean_title(h1t, "")
    if is_junk_title(title):
        return ""
    return title


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    parsed = parse_heydouga_movie_key(code)
    if not parsed:
        raise RuntimeError("番号格式无效")
    mc, fn = parsed

    base = official_base(base_url, DEFAULT_BASE, require_domains=("heydouga.com",))
    detail_url = f"{base}/moviepages/{mc}/{fn}/index.html"
    html = fetch_official_html(
        detail_url,
        base=base,
        source_id=_SRC,
        cookie=cookie or None,
        must_contain=(f"/moviepages/{mc}/{fn}/", f"/contents/{mc}/{fn}/"),
    )

    doc = soup(html)
    actors = _parse_actors(doc)
    title = _parse_title(html, actors)

    desc_el = doc.select_one(".movie-description")
    plot = strip_tags(desc_el.get_text() if desc_el else "")
    plot = re.sub(r"\s*もっと見る\s*$", "", plot).strip()
    if len(plot) < 12:
        plot = ""

    premiered = (_label_value(doc, "配信日：") or _label_value(doc, "配信日"))[:10] or None
    if premiered and not re.match(r"^\d{4}-\d{2}-\d{2}$", premiered):
        premiered = None

    cover = pick_og_image(html)
    if cover and cover.startswith("//"):
        cover = "https:" + cover
    if not cover:
        cover = f"https://image01-www.heydouga.com/contents/{mc}/{fn}/player_thumb.webp"
    if cover and is_junk_cover_url(cover):
        cover = None

    extras: list[str] = []
    for m in re.finditer(
        rf"https?://[^\"']+/contents/{re.escape(mc)}/{re.escape(fn)}/[^\s\"']+\.(?:jpg|jpeg|webp|png)",
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
    code_u = official_code(
        code,
        prefix="HEYDOUGA",
        fallback=f"HEYDOUGA-{mc}-{fn}",
        underscore_to_dash=True,
    )

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
