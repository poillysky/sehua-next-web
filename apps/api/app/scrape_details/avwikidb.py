# -*- coding: utf-8 -*-
"""AVWikiDB 详情刮削：解析页面 __NEXT_DATA__（FANZA 索引站）。"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from .common import (
    fetch_html,
    is_junk_cover_url,
    make_detail,
    std_code,
)

DEFAULT_BASE = "https://avwikidb.com"
SOURCE = "avwikidb"

_NEXT_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.I | re.S,
)


def _parse_next(html: str) -> dict[str, Any]:
    m = _NEXT_RE.search(html or "")
    if not m:
        raise RuntimeError("页面无结构化数据")
    try:
        return json.loads(m.group(1))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("结构化数据解析失败") from e


def _page_props(html: str) -> dict[str, Any]:
    nd = _parse_next(html)
    props = ((nd.get("props") or {}).get("pageProps") or {})
    return props if isinstance(props, dict) else {}


def _dmm_poster(cid: str) -> str:
    c = str(cid or "").strip()
    if not c:
        return ""
    return f"https://pics.dmm.co.jp/digital/video/{c}/{c}pl.jpg"


def _names_from_rel(items: Any, key: str) -> list[str]:
    out: list[str] = []
    if not isinstance(items, list):
        return out
    for row in items:
        if not isinstance(row, dict):
            continue
        node = row.get(key) if key in row else row
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def _movie_to_detail(movie: dict[str, Any], *, code: str) -> dict[str, Any]:
    code_s = std_code(str(movie.get("adultVideoId") or code)) or std_code(code)
    title = str(movie.get("title") or "").strip()
    overview = str(movie.get("summary") or movie.get("notes") or "").strip()
    date = str(movie.get("dateOfPublication") or "")[:10]
    studio = ""
    makers = movie.get("maker")
    if isinstance(makers, list) and makers:
        m0 = makers[0] if isinstance(makers[0], dict) else {}
        node = m0.get("maker") if isinstance(m0.get("maker"), dict) else m0
        studio = str((node or {}).get("name") or "").strip()
    if not studio:
        labels = movie.get("label")
        if isinstance(labels, list) and labels:
            l0 = labels[0] if isinstance(labels[0], dict) else {}
            node = l0.get("label") if isinstance(l0.get("label"), dict) else l0
            studio = str((node or {}).get("name") or "").strip()

    actors = _names_from_rel(movie.get("actor"), "actor")
    tags = _names_from_rel(movie.get("genre"), "genre")
    series = _names_from_rel(movie.get("series"), "series")
    directors = _names_from_rel(movie.get("director"), "director")

    poster = ""
    mgs = str(movie.get("mgsImageUrl") or "").strip()
    if mgs and not is_junk_cover_url(mgs):
        poster = mgs
    if not poster:
        poster = _dmm_poster(str(movie.get("fanzaContentId") or ""))

    extra: dict[str, Any] = {
        "fanzaContentId": movie.get("fanzaContentId"),
        "fanzaId": movie.get("fanzaContentId") or movie.get("fanzaMonoId"),
        "mgsProductCode": movie.get("mgsProductCode"),
        "adultVideoAlias": movie.get("adultVideoAlias"),
        "floor": movie.get("floor"),
        "runtime": movie.get("durationMin"),
        "sourceUrl": f"{DEFAULT_BASE}/work/{quote(code_s)}/",
    }
    if series:
        extra["series"] = series[0]
    if directors:
        extra["director"] = directors[0]
    if movie.get("reviewAverage") is not None:
        extra["rating"] = movie.get("reviewAverage")

    return make_detail(
        source=SOURCE,
        code=code_s or code,
        title=title,
        poster=poster or None,
        studio=studio or None,
        actors=actors,
        tags=tags,
        overview=overview or None,
        date=date or None,
        extra=extra,
    )


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")
    std = std_code(code) or str(code or "").strip().upper()
    if not std:
        raise RuntimeError("番号为空")
    ck = cookie or None

    # /video/ 与 /work/ 均落到 work/[slug]
    last_err: Exception | None = None
    for path in (f"/video/{quote(std)}/", f"/work/{quote(std)}/"):
        url = f"{base}{path}"
        try:
            html = fetch_html(
                url, referer=f"{base}/", cookie=ck, source_id=SOURCE
            )
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
        try:
            props = _page_props(html)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
        movie = props.get("movie")
        if not isinstance(movie, dict) or not movie:
            # 列表页：取首条匹配
            movies = props.get("movies")
            if isinstance(movies, list):
                want = re.sub(r"[^A-Z0-9]", "", std.upper())
                for row in movies:
                    if not isinstance(row, dict):
                        continue
                    cid = str(row.get("adultVideoId") or "")
                    if re.sub(r"[^A-Z0-9]", "", cid.upper()) == want:
                        movie = row
                        break
        if not isinstance(movie, dict) or not movie:
            # Next 真 404 / 空壳：无 movie 且无 __NEXT_DATA__ 作品字段
            last_err = RuntimeError("未找到")
            continue
        return _movie_to_detail(movie, code=std)

    raise RuntimeError(str(last_err) if last_err else "未找到")
