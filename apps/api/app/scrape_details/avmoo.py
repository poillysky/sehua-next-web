# -*- coding: utf-8 -*-
"""Avmoo 详情（AIO 家族）。"""

from __future__ import annotations

from .aio_common import scrape_aio_family

DEFAULT_BASE = "https://avmoo.shop"


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    return scrape_aio_family(
        code,
        source="avmoo",
        default_base=DEFAULT_BASE,
        base_url=base_url,
        cookie=cookie,
    )
