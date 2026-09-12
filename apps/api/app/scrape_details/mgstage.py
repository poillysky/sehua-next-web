# -*- coding: utf-8 -*-
"""MGStage 详情刮削（对齐 MDCS mgstage.ts）。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from .common import (
    abs_url,
    clean_title,
    fetch_html,
    fetch_json,
    fold_code,
    is_junk_cover_url,
    make_detail,
    page_mentions_code,
    pick_href_by_folded_code,
    std_code,
    strip_tags,
    soup,
)

DEFAULT_BASE = "https://www.mgstage.com"
SOURCE = "mgstage"


def _normalize_label(raw: str) -> str:
    return re.sub(r"[：:\s]", "", strip_tags(raw))


def _table_value(html: str, label: str) -> str:
    doc = soup(html)
    out = ""
    for th in doc.select(".detail_data th"):
        if label not in _normalize_label(th.get_text()):
            continue
        td = th.find_next_sibling("td")
        if td is None:
            continue
        links = [
            strip_tags(a.get_text()).strip()
            for a in td.select("a")
            if strip_tags(a.get_text()).strip()
        ]
        out = ", ".join(links) if links else strip_tags(td.get_text())
    return re.sub(r"\s+", " ", out).strip()


def _parse_date(raw: str) -> str | None:
    m = re.search(r"(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})", str(raw or ""))
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _parse_runtime(raw: str) -> int | None:
    digits = re.sub(r"\D", "", str(raw or ""))
    try:
        n = int(digits)
    except ValueError:
        return None
    return n if 0 < n < 600 else None


def _parse_rating(html: str) -> dict[str, Any] | None:
    """对齐 MDCS parseMgstageRating；score 用源站分数（多为 /5）。"""
    doc = soup(html)
    review = doc.select_one(".detail_data td.review")
    if review is None:
        return None
    text = strip_tags(review.get_text())
    m = re.search(r"([\d.]+)\s*\(\s*(\d+)\s*件\s*\)", text)
    if m:
        rating_value = float(m.group(1))
        if rating_value > 0:
            return {
                "ratingValue": rating_value,
                "ratingMax": 5,
                "ratingSource": "mgstage",
                "score": rating_value,
                "votes": m.group(2),
            }
    # 回退：纯数字如 4.2
    m2 = re.search(r"([\d.]+)", text)
    if m2:
        rating_value = float(m2.group(1))
        if 0 < rating_value <= 5:
            return {
                "ratingValue": rating_value,
                "ratingMax": 5,
                "ratingSource": "mgstage",
                "score": rating_value,
            }
    star = review.select_one('span[class*="star_"]')
    cls = " ".join(star.get("class") or []) if star else ""
    star_m = re.search(r"star_(\d{2})", cls)
    if star_m:
        rating_value = int(star_m.group(1)) / 10
        if rating_value > 0:
            return {
                "ratingValue": rating_value,
                "ratingMax": 5,
                "ratingSource": "mgstage",
                "score": rating_value,
            }
    return None


def _parse_actors(html: str) -> list[str]:
    raw = _table_value(html, "出演")
    if not raw:
        return []
    return [s.strip() for s in re.split(r"[,、/]", raw) if s.strip() and len(s.strip()) <= 40]


def _parse_genres(html: str) -> list[str]:
    doc = soup(html)
    out: list[str] = []
    for th in doc.select(".detail_data th"):
        if "ジャンル" not in _normalize_label(th.get_text()):
            continue
        td = th.find_next_sibling("td")
        if td is None:
            continue
        for a in td.select("a"):
            g = strip_tags(a.get_text()).strip()
            if g and g not in out:
                out.append(g)
    return out[:40]


def _parse_outline(html: str) -> str:
    doc = soup(html)
    p = doc.select_one("#introduction dd p.txt.introduction")
    if p:
        return strip_tags(p.get_text()).strip()
    dd = doc.select_one("#introduction dd")
    return re.sub(r"…すべてを見る", "", strip_tags(dd.get_text() if dd else "")).strip()


def _parse_cover(html: str) -> str | None:
    doc = soup(html)
    el = doc.select_one("#EnlargeImage") or doc.select_one(
        'a.link_magnify[href*="image.mgstage.com"]'
    )
    href = (el.get("href") if el else "") or ""
    if not href.startswith("http") or is_junk_cover_url(href):
        return None
    return re.sub(r"^http://", "https://", href, flags=re.I)


def _parse_extrafanart(html: str) -> list[str]:
    doc = soup(html)
    urls: list[str] = []
    for a in doc.select("#sample-photo a.sample_image"):
        href = a.get("href") or ""
        if href.startswith("http") and href not in urls:
            urls.append(href)
    return urls[:20]


def _pick_detail_href(html: str, code: str) -> str:
    """仅接受 path 番号精确命中；禁止首个 product_detail 兜底。"""
    std = std_code(code).upper()
    esc = re.escape(std)
    m = re.search(rf"/product/product_detail/{esc}/?", html, re.I)
    if m:
        hit = m.group(0)
        return hit if hit.startswith("/") else f"/{hit}"
    # 折叠匹配（如 path 大小写 / 连字符差异）
    hrefs = [
        hm.group(1)
        for hm in re.finditer(
            r'href=["\'](/product/product_detail/[^"\'/]+/)[^"\']*["\']',
            html or "",
            re.I,
        )
    ]
    hit = pick_href_by_folded_code(hrefs, code)
    if hit:
        return hit
    # 少数页仅写 id=ABF005 形态
    want = fold_code(code)
    for hm in re.finditer(
        r'href=["\'](/product/product_detail/([^"\'/]+)/)[^"\']*["\']',
        html or "",
        re.I,
    ):
        if fold_code(hm.group(2)) == want:
            return hm.group(1)
    return ""


def _extract_sample_pid(html: str) -> str | None:
    for pat in (
        r"sampleplayer\.html/([0-9a-f-]{36})",
        r"review\.php\?pid=([0-9a-f-]{36})",
        r"sampleplayer/sampleRespons\.php\?pid=([0-9a-f-]{36})",
    ):
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1)
    return None


def _fetch_trailer(html: str, base: str, *, referer: str, cookie: str) -> str | None:
    pid = _extract_sample_pid(html)
    if not pid:
        return None
    api = f"{base.rstrip('/')}/sampleplayer/sampleRespons.php?pid={quote(pid)}"
    try:
        data = fetch_json(
            api,
            headers={"Referer": referer, "Accept": "application/json"},
            cookie=cookie or None,
            source_id=SOURCE,
        )
    except Exception:
        return None
    raw = str((data or {}).get("url") or "")
    m = re.search(r"(https.+?)ism/request", raw, re.I) or re.search(
        r"(https.+\.mp4)", raw, re.I
    )
    if m:
        return f"{m.group(1)}mp4"
    if raw.startswith("http") and ".mp4" in raw:
        return raw
    return None


def _parse_detail(html: str, page_url: str, code: str) -> dict[str, Any] | None:
    from ..outbound_http import looks_blocked_html

    if not html or looks_blocked_html(html):
        return None
    if not page_mentions_code(html, code) and not re.search(
        r"detail_data|product_detail", html, re.I
    ):
        return None

    std = std_code(code)
    num = _table_value(html, "品番") or std
    if (
        num
        and std_code(num).upper() != std.upper()
        and std.upper() not in page_url.upper()
    ):
        return None

    doc = soup(html)
    h1 = doc.select_one("h1.tag") or doc.select_one("h1")
    raw_title = strip_tags(h1.get_text() if h1 else "")
    title = clean_title(raw_title, std)
    plot = _parse_outline(html)
    actors = _parse_actors(html)
    genres = _parse_genres(html)
    studio = _table_value(html, "メーカー") or None
    publisher = _table_value(html, "レーベル") or None
    series = _table_value(html, "シリーズ") or None
    premiered = (
        _parse_date(_table_value(html, "配信開始日"))
        or _parse_date(_table_value(html, "商品発売日"))
    )
    runtime = _parse_runtime(_table_value(html, "収録時間"))
    cover = _parse_cover(html)
    extras = _parse_extrafanart(html)
    rating = _parse_rating(html)

    if not title and not cover and not actors and not plot:
        return None

    extra: dict[str, Any] = {
        "publisher": publisher or None,
        "series": series or None,
        "runtime": runtime,
        "website": page_url,
        "mosaic": "有码",
        "extrafanartUrls": extras or None,
    }
    if rating:
        extra.update(rating)

    return make_detail(
        source=SOURCE,
        code=std,
        title=title or None,
        poster=cover,
        studio=studio,
        actors=actors,
        tags=genres,
        overview=plot or None,
        date=premiered,
        extra=extra,
    )


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")
    std = std_code(code).upper()
    if not std:
        raise RuntimeError("番号为空")
    referer = f"{base}/"
    ck = cookie or ""

    detail_url = f"{base}/product/product_detail/{quote(std)}/"
    try:
        html = fetch_html(
            detail_url, referer=referer, cookie=ck or None, source_id=SOURCE
        )
        parsed = _parse_detail(html, detail_url, std)
        if parsed and (parsed.get("title") or parsed.get("posterUrl")):
            trailer = _fetch_trailer(html, base, referer=detail_url, cookie=ck)
            if trailer:
                parsed["trailerUrl"] = trailer
            return parsed
    except RuntimeError:
        pass

    search_url = f"{base}/search/cSearch.php?search_word={quote(std)}&type=top"
    try:
        search_html = fetch_html(
            search_url, referer=referer, cookie=ck or None, source_id=SOURCE
        )
    except RuntimeError as e:
        raise RuntimeError("搜索无响应") from e

    if re.search(r"該当する作品がありません", search_html, re.I):
        raise RuntimeError("未找到")

    path = _pick_detail_href(search_html, std)
    if not path:
        raise RuntimeError("未找到")
    url = abs_url(path, base) or f"{base}{path}"
    html = fetch_html(url, referer=search_url, cookie=ck or None, source_id=SOURCE)
    parsed = _parse_detail(html, url, std)
    if not parsed:
        raise RuntimeError("未找到")
    trailer = _fetch_trailer(html, base, referer=url, cookie=ck)
    if trailer:
        parsed["trailerUrl"] = trailer
    return parsed
