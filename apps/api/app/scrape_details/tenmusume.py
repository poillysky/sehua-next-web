# -*- coding: utf-8 -*-
"""10musume（天然むすめ）详情刮削 —— 官网 JSON API。

番号形如 `10MU-051124-01` / `10musume-051124_01` → movie_id `051124_01`。
API: `{base}/dyn/phpauto/movie_details/movie_id/{id}.json`

实现见 `common.scrape_official_json_detail`（与 1pondo / pacopacomama 共用）。
"""

from __future__ import annotations

import re

from .common import scrape_official_json_detail

DEFAULT_BASE = "https://www.10musume.com"
STUDIO = "天然むすめ"
_SRC = "10musume"

# 10MU-051124-01 / 10musume-051124_01 / 051124_01 / 051124-01
_KEY_RE = re.compile(
    r"^(?:10(?:MU|MUSUME)[-_]?)?(\d{6})[-_](\d{1,3})$",
    re.I,
)


def parse_tenmusume_movie_key(code: str) -> str | None:
    m = _KEY_RE.match(str(code or "").strip())
    if not m:
        return None
    return f"{m.group(1)}_{m.group(2).zfill(2)}"


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    key = parse_tenmusume_movie_key(code)
    if not key:
        raise RuntimeError("番号格式无效")
    return scrape_official_json_detail(
        code,
        source=_SRC,
        movie_key=key,
        default_base=DEFAULT_BASE,
        studio=STUDIO,
        detail_path="/moviepages/{key}/index.html",
        cover_path="/moviepages/{key}/images/str.jpg",
        code_prefix="10MU",
        base_url=base_url,
        cookie=cookie,
        with_title_en=True,
        # 10MU 的 Year 字段自身可靠，不做 Release 回落
        with_rating=True,
    )
