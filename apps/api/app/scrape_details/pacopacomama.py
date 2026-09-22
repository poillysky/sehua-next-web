# -*- coding: utf-8 -*-
"""pacopacomama（パコパコママ）详情 —— 官网 JSON API。

番号：`PACO-122615-557` / `pacopacomama-122615_557` → movie_id `122615_557`。

实现见 `common.scrape_official_json_detail`（与 10musume / 1pondo 共用）。
"""

from __future__ import annotations

import re

from .common import scrape_official_json_detail

DEFAULT_BASE = "https://www.pacopacomama.com"
STUDIO = "パコパコママ"
_SRC = "pacopacomama"

_KEY_RE = re.compile(
    r"^(?:PACO(?:PACOMAMA)?[-_]?)?(\d{6})[-_](\d{1,3})$",
    re.I,
)


def parse_paco_movie_key(code: str) -> str | None:
    m = _KEY_RE.match(str(code or "").strip())
    if not m:
        return None
    return f"{m.group(1)}_{m.group(2).zfill(3)}"


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    key = parse_paco_movie_key(code)
    if not key:
        raise RuntimeError("番号格式无效")
    return scrape_official_json_detail(
        code,
        source=_SRC,
        movie_key=key,
        default_base=DEFAULT_BASE,
        studio=STUDIO,
        detail_path="/movies/{key}/",
        cover_path="/assets/sample/{key}/str.jpg",
        code_prefix="PACO",
        base_url=base_url,
        cookie=cookie,
        require_domains=("pacopacomama",),
        year_from_premiered=True,
    )
