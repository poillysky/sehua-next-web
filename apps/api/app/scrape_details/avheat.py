# -*- coding: utf-8 -*-
"""AVHeat 详情（AIO 家族 · 欧美）。"""

from __future__ import annotations

from .aio_common import scrape_aio_family

DEFAULT_BASE = "https://avheat.shop"


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    return scrape_aio_family(
        code,
        source="avheat",
        default_base=DEFAULT_BASE,
        base_url=base_url,
        cookie=cookie,
    )
