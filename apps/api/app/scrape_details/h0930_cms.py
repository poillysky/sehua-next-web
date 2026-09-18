# -*- coding: utf-8 -*-
"""H0930 / H4610 / C0930 同系 CMS 详情刮削。

番号示例：
- H0930-ki260908 / H0930-ori1224 / H0930-gol195
- H4610-ki260908
- C0930-hitozuma1369

详情：`{base}/moviepages/{key}/index.html`
封面：`…/moviepages/{key}/images/movie.jpg`（横图）
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

# site_id → (default_base, studio_label, code_prefix, host_needle)
SITE_META: dict[str, tuple[str, str, str, str]] = {
    "h0930": ("https://www.h0930.com", "エッチな0930", "H0930", "h0930"),
    "h4610": ("https://www.h4610.com", "エッチな4610", "H4610", "h4610"),
    "c0930": ("https://www.c0930.com", "人妻斬り", "C0930", "c0930"),
}


def parse_h0930_cms_movie_key(code: str, *, prefix: str) -> str | None:
    """提取官网 movie key（小写 slug）。"""
    raw = str(code or "").strip()
    if not raw:
        return None
    pref = str(prefix or "").strip().upper()
    # H0930-ki260908 / h0930_ki260908 / ki260908
    m = re.match(
        rf"^(?:{re.escape(pref)}[-_]?)?([A-Za-z][A-Za-z0-9]{{2,24}})$",
        raw,
        re.I,
    )
    if not m:
        return None
    key = m.group(1).lower()
    if key in {"h0930", "h4610", "c0930", "ki", "ori", "gol"}:
        return None
    return key


def _info_map(html: str) -> dict[str, str]:
    doc = soup(html)
    out: dict[str, str] = {}
    for dt in doc.select("dt"):
        dd = dt.find_next_sibling("dd")
        label = strip_tags(dt.get_text())
        val = strip_tags(dd.get_text() if dd else "")
        if label and val:
            out[label] = val
    return out


def _split_tags(*blobs: str) -> list[str]:
    out: list[str] = []
    for blob in blobs:
        for part in re.split(r"[\s、,/|]+", str(blob or "").strip()):
            n = part.strip()
            if n and n.upper() != "N/A" and 1 <= len(n) <= 40 and n not in out:
                out.append(n)
    return out[:40]


def scrape_h0930_cms(
    code: str,
    *,
    site_id: str,
    base_url: str = "",
    cookie: str = "",
    api_key: str = "",
) -> dict:
    del api_key
    meta = SITE_META.get(site_id)
    if not meta:
        raise RuntimeError(f"未知站点: {site_id}")
    default_base, studio, prefix, host_needle = meta
    key = parse_h0930_cms_movie_key(code, prefix=prefix)
    if not key:
        raise RuntimeError("番号格式无效")

    base = (base_url or default_base).rstrip("/") or default_base
    if host_needle not in base.lower():
        base = default_base
    detail_url = f"{base}/moviepages/{key}/index.html"

    try:
        html = fetch_html(
            detail_url,
            referer=f"{base}/",
            cookie=cookie or None,
            source_id=site_id,
        )
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}") from e

    if not html or len(html) < 3000:
        raise RuntimeError("未找到")
    if re.search(r"404\s*ERROR|ページが見つかりません", html, re.I):
        raise RuntimeError("未找到")
    if f"/moviepages/{key}/" not in html:
        raise RuntimeError("未找到")

    doc = soup(html)
    h1 = doc.select_one("h1")
    h1_text = strip_tags(h1.get_text() if h1 else "")
    # 「中村 あゆみ 24歳」→ 演员名去掉年龄
    actor = re.sub(r"\s*\d{1,3}\s*歳\s*$", "", h1_text).strip()
    title = clean_title(h1_text or actor, code)
    if is_junk_title(title):
        title = ""

    info = _info_map(html)
    premiered = (info.get("公開日") or "")[:10] or None
    tags = _split_tags(info.get("プレイ内容") or "", info.get("タイプ") or "")
    actors = [actor] if actor and 1 <= len(actor) <= 40 else []

    cover = f"{base}/moviepages/{key}/images/movie.jpg"
    # 页面里可能是协议相对路径
    m = re.search(
        rf"(?:https?:)?//[^\"']+/moviepages/{re.escape(key)}/images/movie\.jpg",
        html,
        re.I,
    )
    if m:
        cover = abs_url(m.group(0), base) or cover
        if cover.startswith("//"):
            cover = "https:" + cover
    if cover and is_junk_cover_url(cover):
        cover = None

    extras: list[str] = []
    for mm in re.finditer(
        rf"(?:https?:)?//[^\"']+/moviepages/{re.escape(key)}/images/g_[bs]\d+\.jpg",
        html,
        re.I,
    ):
        u = mm.group(0)
        if u.startswith("//"):
            u = "https:" + u
        u = abs_url(u, base) or u
        if u not in extras:
            extras.append(u)
    extras = extras[:30]

    if not title and not cover and not actors:
        raise RuntimeError("未找到")

    year = premiered[:4] if premiered and re.match(r"^\d{4}", premiered) else None
    code_u = str(code or "").strip().upper() or f"{prefix}-{key}"
    if not code_u.upper().startswith(prefix):
        code_u = f"{prefix}-{key}"

    extra: dict[str, Any] = {
        "website": detail_url,
        "mosaic": "无码",
        "extrafanartUrls": extras or None,
        "originalPlot": None,
    }
    return make_detail(
        source=site_id,
        code=code_u,
        title=title or None,
        poster=cover,
        studio=studio,
        actors=actors,
        tags=tags,
        overview=None,
        date=premiered,
        year=year,
        extra=extra,
    )
