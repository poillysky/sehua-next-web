# -*- coding: utf-8 -*-
"""人妻斬り（C0930）官网详情。"""

from __future__ import annotations

from .h0930_cms import parse_h0930_cms_movie_key, scrape_h0930_cms

_PREFIX = "C0930"


def parse_c0930_movie_key(code: str) -> str | None:
    return parse_h0930_cms_movie_key(code, prefix=_PREFIX)


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    return scrape_h0930_cms(
        code,
        site_id="c0930",
        base_url=base_url,
        cookie=cookie,
        api_key=api_key,
    )
