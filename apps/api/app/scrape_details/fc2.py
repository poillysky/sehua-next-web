# -*- coding: utf-8 -*-
"""FC2 详情刮削（对齐 MDCS fc2.ts）。"""

from __future__ import annotations

import json
import re

from .common import (
    abs_url,
    clean_title,
    fetch_html,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    pick_og_image,
    pick_og_title,
    soup,
    strip_tags,
)

DEFAULT_BASE = "https://adult.contents.fc2.com"
DEFAULT_COOKIE = "adult_check=1"
PREMIERED_RE = re.compile(
    r"(?:販売日|販売開始日|上架时间|登録日|発売日|销售日期)\s*[:：]?\s*([0-9]{4})[/-]([0-9]{1,2})[/-]([0-9]{1,2})",
    re.I,
)
NOT_FOUND_RE = re.compile(r"未找到您要找的商品|お探しの商品は見つかりません|販売を終了", re.I)


def _parse_fc2_id(code: str) -> tuple[str, str] | None:
    m = re.search(r"FC2[-_]?PPV[-_]?(\d+)", code, re.I) or re.search(r"FC2[-_]?(\d+)", code, re.I)
    if not m:
        return None
    fid = m.group(1)
    return fid, f"FC2-PPV-{fid}"


def _pick_twitter_image(html: str) -> str | None:
    m = re.search(
        r'name=["\']twitter:image(?::src)?["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.I,
    ) or re.search(
        r'content=["\']([^"\']+)["\']\s+name=["\']twitter:image(?::src)?["\']',
        html,
        re.I,
    )
    return m.group(1) if m else None


def _format_premiered(y: str, m: str, d: str) -> str:
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


def _parse_premiered(html: str) -> str | None:
    doc = soup(html)
    blocks = [
        strip_tags(doc.select_one(".items_article_headerInfo").get_text() if doc.select_one(".items_article_headerInfo") else ""),
        strip_tags(doc.select_one(".items_article_softDevice").get_text() if doc.select_one(".items_article_softDevice") else ""),
        strip_tags(doc.body.get_text() if doc.body else ""),
    ]
    for text in blocks:
        m = PREMIERED_RE.search(text)
        if m:
            return _format_premiered(m.group(1), m.group(2), m.group(3))
    return None


def _parse_runtime(html: str) -> int | None:
    doc = soup(html)
    el = doc.select_one("p.items_article_info, .items_article_info")
    t = strip_tags(el.get_text() if el else "").strip()
    if not t:
        return None
    hms = re.match(r"^(\d+):(\d{2}):(\d{2})$", t)
    if hms:
        return round(int(hms.group(1)) * 60 + int(hms.group(2)) + int(hms.group(3)) / 60)
    ms = re.match(r"^(\d+):(\d{2})$", t)
    if ms:
        return round(int(ms.group(1)) + int(ms.group(2)) / 60)
    mins = re.search(r"(\d+)\s*分", t)
    if mins:
        return int(mins.group(1))
    return None


def _iter_ld(html: str):
    for block in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>',
        html,
        re.I,
    ):
        try:
            data = json.loads(block.group(1) or "")
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                yield item


def _parse_ld_product(html: str) -> dict:
    out: dict = {}
    for item in _iter_ld(html):
        if str(item.get("@type") or "") != "Product":
            continue
        desc = str(item.get("description") or "").strip()
        if len(desc) >= 12 and not is_junk_title(desc):
            out["description"] = desc
        rating = item.get("aggregateRating")
        if isinstance(rating, dict):
            try:
                val = float(rating.get("ratingValue"))
            except (TypeError, ValueError):
                val = None
            try:
                mx = float(rating.get("bestRating") or 5)
            except (TypeError, ValueError):
                mx = 5.0
            count = rating.get("reviewCount", rating.get("ratingCount"))
            if val is not None and val == val:  # finite
                out["ratingValue"] = val
                out["ratingMax"] = mx
            if count is not None and str(count).strip():
                out["votes"] = str(count)
    return out


def _parse_ld_image(html: str) -> str | None:
    for item in _iter_ld(html):
        if str(item.get("@type") or "") != "Product":
            continue
        img = item.get("image")
        if isinstance(img, str) and img.strip():
            return img.strip()
        if isinstance(img, list):
            for entry in img:
                if isinstance(entry, str) and entry.strip():
                    return entry.strip()
                if isinstance(entry, dict) and isinstance(entry.get("url"), str):
                    return entry["url"].strip()
        if isinstance(img, dict) and isinstance(img.get("url"), str):
            return img["url"].strip()
    return None


def _parse_cover(html: str, page_url: str) -> str | None:
    doc = soup(html)
    thumb = doc.select_one(".items_article_MainitemThumb img")
    cover = (
        pick_og_image(html)
        or _pick_twitter_image(html)
        or _parse_ld_image(html)
        or (thumb.get("src") if thumb else None)
        or (thumb.get("data-src") if thumb else None)
        or (thumb.get("data-original") if thumb else None)
    )
    if cover:
        cover = abs_url(cover, page_url) or cover
    if cover and is_junk_cover_url(cover):
        cover = None
    return cover


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    parsed = _parse_fc2_id(code)
    if not parsed:
        raise RuntimeError("番号格式无效")
    fid, display = parsed

    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")

    url = f"{base}/article/{fid}/"
    ck = cookie or DEFAULT_COOKIE
    try:
        html = fetch_html(url, referer=f"{base}/", cookie=ck, source_id="fc2")
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}") from e

    if NOT_FOUND_RE.search(html):
        raise RuntimeError("未找到")

    doc = soup(html)
    title = clean_title(
        pick_og_title(html)
        or (doc.select_one("meta[property='og:title']").get("content") if doc.select_one("meta[property='og:title']") else "")
        or (
            doc.select_one("h2.items_article_Title, .items_article_headerInfo h2, h1").get_text()
            if doc.select_one("h2.items_article_Title, .items_article_headerInfo h2, h1")
            else ""
        ),
        display,
    )
    title = re.sub(rf"^FC2[-_]?PPV[-_]?{re.escape(fid)}\s*[-–—:]?\s*", "", title, flags=re.I).strip()
    if not title or is_junk_title(title):
        raise RuntimeError("未找到")

    cover = _parse_cover(html, url)

    genres: list[str] = []
    for el in doc.select(".items_article_TagArea a, a.tagTag[href*='tag'], a[href*='tag=']"):
        n = strip_tags(str(el.get("data-tag") or el.get_text()))
        if not n or len(n) > 40 or re.search(r"もっと見る|タグ|ジャンル|商品标签|FC2", n, re.I):
            continue
        if n not in genres:
            genres.append(n)

    writer = doc.select_one('.items_article_writer a[href*="/users/"]')
    header_user = doc.select_one('.items_article_headerInfo a[href*="/users/"]')
    seller = (
        strip_tags(writer.get_text() if writer else "")
        or strip_tags(header_user.get_text() if header_user else "")
        or "FC2"
    )

    premiered = _parse_premiered(html)
    runtime = _parse_runtime(html)
    ld = _parse_ld_product(html)

    og_desc = doc.select_one("meta[property='og:description']")
    plot = strip_tags((og_desc.get("content") if og_desc else "") or "")
    if (not plot or len(plot) < 12 or is_junk_title(plot)) and ld.get("description"):
        plot = str(ld["description"])
    # 拒番号串 / 过短垃圾简介（本样例 og:description 常为空或等于番号）
    plot_u = re.sub(r"[^A-Z0-9]", "", plot.upper())
    code_u = re.sub(r"[^A-Z0-9]", "", display.upper())
    code_u_alt = re.sub(r"^FC2PPV", "FC2", code_u)
    if (
        len(plot) < 12
        or is_junk_title(plot)
        or plot_u in {code_u, code_u_alt, fid}
        or plot.strip().upper() in {display.upper(), f"FC2-{fid}", f"FC2-PPV-{fid}"}
    ):
        plot = ""

    og_video = doc.select_one("meta[property='og:video']")
    tw_player = doc.select_one("meta[name='twitter:player']")
    trailer = ((og_video.get("content") if og_video else "") or (tw_player.get("content") if tw_player else "")).strip() or None
    og_url = doc.select_one("meta[property='og:url']")
    website = ((og_url.get("content") if og_url else "") or "").strip() or url

    extra: dict = {
        "runtime": runtime,
        "trailerUrl": trailer,
        "website": website,
        "actors": [],
    }
    if ld.get("ratingValue") is not None:
        mx = float(ld.get("ratingMax") or 5) or 5.0
        val = float(ld["ratingValue"])
        # 源站分数（多为 /5），不对齐 MDCS ×10
        extra.update(
            {
                "ratingValue": val,
                "ratingMax": mx,
                "ratingSource": "fc2",
                "score": val,
            }
        )
        if ld.get("votes"):
            extra["votes"] = ld["votes"]

    return make_detail(
        source="fc2",
        code=display,
        title=title,
        poster=cover,
        studio=seller,
        actors=[],
        tags=genres[:40],
        overview=plot or None,
        date=premiered,
        extra=extra,
    )
