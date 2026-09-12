# -*- coding: utf-8 -*-
"""airav 详情：优先委托 airav_io，失败再走 wiki 回退（对齐 MDCS airav.ts）。"""

from __future__ import annotations

import re
from urllib.parse import quote

from . import airav_io
from .common import fetch_html_result, page_mentions_code

WIKI_DEFAULT = "https://www.airav.wiki"
SOURCE = "airav"


def _wiki_fallback(code: str, *, base_url: str = "", cookie: str = "") -> dict | None:
    from ..outbound_http import looks_blocked_html

    normalized = str(code or "").strip().upper()
    if not normalized:
        return None
    wiki_base = (base_url or WIKI_DEFAULT).rstrip("/")
    url = f"{wiki_base}/video/{quote(normalized)}"
    try:
        html, landed = fetch_html_result(
            url, referer=f"{wiki_base}/", cookie=cookie or None, source_id=SOURCE
        )
    except RuntimeError:
        return None
    if not html or looks_blocked_html(html):
        return None
    head = html[:2500]
    if re.search(r"找不到|404|Not Found|521:\s*Web server", head, re.I) and not re.search(
        r"video-title|og:title|番[号號]", html, re.I
    ):
        return None
    if not airav_io.airav_detail_code_ok(html, normalized) and not page_mentions_code(
        html, normalized
    ):
        return None
    parsed = airav_io.parse_airav_io_detail(html, landed or url, normalized)
    if not parsed or (not parsed.get("title") and not parsed.get("posterUrl")):
        return None
    parsed["source"] = SOURCE
    parsed["provider"] = SOURCE
    return parsed


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    io_err: str | None = None
    try:
        # Prefer airav.io when base_url points there; otherwise use airav_io defaults.
        # 配置里常见 https://airav.io（无 /cn）→ 交给 airav_io 强制简体站。
        io_base = ""
        if base_url and re.search(r"airav\.io", base_url, re.I):
            io_base = base_url
        from_io = airav_io.scrape_detail(
            code, base_url=io_base, cookie=cookie, api_key=api_key
        )
        if from_io.get("title") or from_io.get("posterUrl"):
            from_io = dict(from_io)
            from_io["source"] = SOURCE
            from_io["provider"] = SOURCE
            return from_io
    except RuntimeError as e:
        io_err = str(e)

    wiki_base = base_url if base_url and re.search(r"airav\.wiki", base_url, re.I) else ""
    fallback = _wiki_fallback(code, base_url=wiki_base, cookie=cookie)
    if fallback:
        return fallback

    raise RuntimeError(io_err or "未找到")
