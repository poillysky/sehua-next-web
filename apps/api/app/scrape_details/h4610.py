# -*- coding: utf-8 -*-
"""エッチな4610（H4610）官网详情。"""

from __future__ import annotations

from .h0930_cms import parse_h0930_cms_movie_key, scrape_h0930_cms

_PREFIX = "H4610"


def parse_h4610_movie_key(code: str) -> str | None:
    return parse_h0930_cms_movie_key(code, prefix=_PREFIX)


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    return scrape_h0930_cms(
        code,
        site_id="h4610",
        base_url=base_url,
        cookie=cookie,
        api_key=api_key,
    )
