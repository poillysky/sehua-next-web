# -*- coding: utf-8 -*-
"""AVBase 详情刮削（对齐 MDCS avbase.ts，解析 __NEXT_DATA__）。"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from .common import (
    abs_url,
    append_amateur_board_variants,
    append_std_pad_variants,
    clean_title,
    date6_search_variants,
    fetch_html,
    is_junk_cover_url,
    make_detail,
    parse_fc2_id,
    std_code,
)

DEFAULT_BASE = "https://www.avbase.net"
SOURCE = "avbase"


def avbase_code_candidates(code: str) -> list[str]:
    """直链 / 搜索词：pad / 素人加剥板 / FC2-PPV / 无码 date6。"""
    raw = str(code or "").strip()
    if not raw:
        return []
    out: list[str] = []

    def _add(val: str) -> None:
        s = str(val or "").strip()
        if not s:
            return
        if "_" in s and re.search(r"\d{6}_\d+", s):
            u = s
        else:
            u = std_code(s) or s
        if u and u not in out:
            out.append(u)

    _add(raw)
    append_std_pad_variants(_add, raw)
    append_amateur_board_variants(_add, raw)
    for v in date6_search_variants(raw):
        _add(v)
    fc2 = parse_fc2_id(raw)
    if fc2:
        fid, canon = fc2
        _add(canon)
        _add(f"FC2-PPV-{fid}")
        _add(f"FC2-{fid}")
    return out


def is_avbase_actor_name(name: str) -> bool:
    t = str(name or "").strip()
    if not t or len(t) > 40:
        return False
    if re.match(r"^\d+$", t):
        return False
    return True


def match_avbase_work_id(work_id: str, code: str) -> bool:
    """work_id 与查询番号等价（含 pad / 素人板号）；带 ``source:CODE`` 前缀的异源条目不认。"""
    from .common import code_equiv

    raw = str(work_id or "").strip()
    if not raw or ":" in raw:
        return False
    return code_equiv(raw, code)


def parse_avbase_next_data(html: str) -> dict[str, Any] | None:
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">([\s\S]*?)</script>',
        html or "",
        re.I,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1).strip())
    except Exception:
        return None


def parse_avbase_date(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).strip()
    iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    # AVBase 常给 JS Date 字符串：Fri Dec 08 2023 10:00:00 GMT+0900 (...)
    mon = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    m = re.search(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(\d{4})\b",
        s,
        re.I,
    )
    if m:
        month = mon.get(m.group(1).lower())
        if month:
            return f"{m.group(3)}-{month:02d}-{int(m.group(2)):02d}"
    try:
        from datetime import datetime

        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"
    except Exception:
        return None


def strip_avbase_description(raw: str | None) -> str:
    if not raw:
        return ""
    s = (
        str(raw)
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    # JSON 截断时可能留下残缺标签，如末尾 `<br`
    s = re.sub(r"<[^>]*$", "", s)
    s = re.sub(r"…+$", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _normalize_cover(url: str | None) -> str | None:
    if not url:
        return None
    u = re.sub(r"^http://", "https://", url, flags=re.I)
    u = re.sub(r"(\d)(ps|pt)\.jpg$", r"\1pl.jpg", u, flags=re.I)
    return u


def pick_avbase_product(products: list[dict] | None) -> dict | None:
    if not products:
        return None
    scored = []
    for p in products:
        score = 0
        if "pl." in str(p.get("image_url") or ""):
            score += 20
        if p.get("source") == "fanza" or p.get("product_id"):
            score += 10
        if (p.get("iteminfo") or {}).get("description"):
            score += 5
        if p.get("sample_image_urls"):
            score += 3
        scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else None


def parse_avbase_actors(work: dict) -> list[str]:
    names: list[str] = []
    for c in work.get("casts") or []:
        n = ((c or {}).get("actor") or {}).get("name")
        if n and is_avbase_actor_name(n):
            names.append(n.strip())
    for a in work.get("actors") or []:
        n = (a or {}).get("name")
        if n and is_avbase_actor_name(n):
            names.append(n.strip())
    out: list[str] = []
    for n in names:
        if n not in out:
            out.append(n)
    return out[:20]


def parse_avbase_genres(work: dict) -> list[str]:
    out: list[str] = []
    for g in work.get("genres") or []:
        name = g if isinstance(g, str) else (g or {}).get("name")
        t = str(name or "").strip()
        if t and t not in out:
            out.append(t)
    return out[:40]


def pick_avbase_work_from_search(works: list[dict] | None, code: str) -> dict | None:
    if not works:
        return None
    for w in works:
        if match_avbase_work_id(str(w.get("work_id") or ""), code):
            return w
    return works[0] if len(works) == 1 else None


def parse_avbase_work(work: dict | None, page_url: str, code: str) -> dict | None:
    if not work or (not work.get("work_id") and not work.get("title")):
        return None
    std = std_code(code)
    product = pick_avbase_product(work.get("products"))
    title = clean_title(str(work.get("title") or (product or {}).get("title") or ""), std)
    if not title and not (product or {}).get("image_url"):
        return None

    actors = parse_avbase_actors(work)
    genres = parse_avbase_genres(work)
    iteminfo = (product or {}).get("iteminfo") or {}
    plot = strip_avbase_description(iteminfo.get("description"))
    director = str(iteminfo.get("director") or "").strip()
    runtime_raw = re.sub(r"\D", "", str(iteminfo.get("volume") or ""))
    runtime = int(runtime_raw) if runtime_raw else None
    premiered = parse_avbase_date((product or {}).get("date")) or parse_avbase_date(
        work.get("min_date")
    )
    cover = _normalize_cover(
        (product or {}).get("image_url") or (product or {}).get("thumbnail_url")
    )
    if cover and is_junk_cover_url(cover):
        cover = None

    extras: list[str] = []
    for s in (product or {}).get("sample_image_urls") or []:
        u = (s or {}).get("l") or (s or {}).get("s")
        if u and str(u).startswith("http") and u not in extras:
            extras.append(str(u))
    extras = extras[:20]

    trailer = (product or {}).get("sample_movie_url")
    if not (isinstance(trailer, str) and trailer.startswith("http")):
        trailer = None

    if not title and not cover and not actors and not plot:
        return None

    return make_detail(
        source=SOURCE,
        code=std,
        title=title or None,
        poster=cover,
        studio=str(((product or {}).get("maker") or {}).get("name") or "").strip() or None,
        actors=actors,
        tags=genres,
        overview=plot or None,
        date=premiered,
        extra={
            "publisher": str(((product or {}).get("label") or {}).get("name") or "").strip()
            or None,
            "series": str(((product or {}).get("series") or {}).get("name") or "").strip()
            or None,
            "directors": [director] if director else None,
            "runtime": runtime if runtime and runtime > 0 else None,
            "trailerUrl": trailer,
            "website": page_url,
            "extrafanartUrls": extras or None,
        },
    )


def parse_avbase_detail_html(html: str, page_url: str, code: str) -> dict | None:
    data = parse_avbase_next_data(html)
    work = ((data or {}).get("props") or {}).get("pageProps", {}).get("work")
    if not work:
        return None
    if not match_avbase_work_id(str(work.get("work_id") or ""), code) and std_code(
        code
    ).upper() not in page_url.upper():
        return None
    return parse_avbase_work(work, page_url, code)


def parse_avbase_search_html(html: str, code: str) -> dict | None:
    data = parse_avbase_next_data(html)
    works = ((data or {}).get("props") or {}).get("pageProps", {}).get("works")
    return pick_avbase_work_from_search(works, code)


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")
    std = std_code(code)
    if not std:
        raise RuntimeError("番号为空")
    ck = cookie or None
    referer = f"{base}/"
    candidates = avbase_code_candidates(code) or [std]

    seen_paths: set[str] = set()
    for cand in candidates:
        for path in (f"/works/{quote(cand)}", f"/works/{quote(cand.lower())}"):
            if path in seen_paths:
                continue
            seen_paths.add(path)
            url = f"{base}{path}"
            try:
                html = fetch_html(url, referer=referer, cookie=ck, source_id=SOURCE)
            except RuntimeError:
                continue
            if len(html) < 500:
                continue
            parsed = parse_avbase_detail_html(html, url, std)
            if parsed:
                return parsed

    work = None
    search_url = ""
    for cand in candidates:
        search_url = f"{base}/works?q={quote(cand)}"
        try:
            search_html = fetch_html(
                search_url, referer=referer, cookie=ck, source_id=SOURCE
            )
        except RuntimeError:
            continue
        work = parse_avbase_search_html(search_html, std)
        if work:
            break
    if not work:
        raise RuntimeError("未找到")

    work_id = work.get("work_id")
    if work_id:
        detail_path = f"/works/{quote(str(work_id))}"
        detail_url = abs_url(detail_path, base) or f"{base}{detail_path}"
        try:
            detail_html = fetch_html(
                detail_url, referer=search_url or referer, cookie=ck, source_id=SOURCE
            )
            parsed = parse_avbase_detail_html(detail_html, detail_url, std)
            if parsed:
                return parsed
        except RuntimeError:
            pass

    from_search = parse_avbase_work(work, search_url or referer, std)
    if not from_search:
        raise RuntimeError("未找到")
    return from_search
