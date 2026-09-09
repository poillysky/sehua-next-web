# -*- coding: utf-8 -*-
"""AvSox 详情（AIO 家族 · 无码）。"""

from __future__ import annotations

import re

from .aio_common import scrape_aio_family
from .common import std_code

DEFAULT_BASE = "https://avsox.click"


def _search_code(code: str) -> str:
    raw = str(code or "").strip()
    m = re.match(r"^CARIB[-_]?(\d{6}-\d{3})$", raw, re.I)
    if m:
        return m.group(1)
    if re.match(r"^\d{6}-\d{3}$", raw):
        return raw
    return std_code(code)


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    return scrape_aio_family(
        code,
        source="avsox",
        default_base=DEFAULT_BASE,
        base_url=base_url,
        cookie=cookie,
        search_code=_search_code(code),
    )
