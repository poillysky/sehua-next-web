# -*- coding: utf-8 -*-
"""AIO 家族（Avmoo / AvSox / AVHeat）共用解析。"""

from __future__ import annotations

import re
from urllib.parse import quote

from .common import (
    abs_url,
    clean_title,
    code_key,
    collect_by_re,
    fetch_html,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    page_mentions_code,
    std_code,
    strip_tags,
)


def is_aio_thin_shell(html: str) -> bool:
    if not html:
        return True
    if re.search(r'class=["\']movie-detail["\']', html):
        return False
    if "detail-label" in html:
        return False
    if len(html) < 2000:
        return True
    return len(html) < 4000


def aio_detail_value(html: str, label: str) -> str:
    esc = re.escape(label)
    plain = re.search(
        rf'detail-label[^>]*>\s*{esc}\s*:</span>\s*<span[^>]*class=["\'][^"\']*detail-value[^"\']*["\'][^>]*>([\s\S]*?)</span>',
        html,
        re.I,
    )
    linked = re.search(
        rf'detail-label[^>]*>\s*{esc}\s*:</span>\s*<a[^>]*class=["\'][^"\']*detail-value[^"\']*["\'][^>]*>([\s\S]*?)</a>',
        html,
        re.I,
    )
    return strip_tags((plain or linked).group(1) if (plain or linked) else "")


def pick_aio_movie_path(html: str, code: str, lang: str = "cn") -> str | None:
    std = std_code(code)
    code_pat = std.replace("-", "[-]?")
    for m in re.finditer(
        rf'href=["\']([^"\']*/{lang}/movies/[^"\'#]+)["\'][\s\S]{{0,1200}}?movie-meta[\s\S]{{0,300}}?<span[^>]*>\s*{code_pat}\s*</span>',
        html,
        re.I,
    ):
        href = (m.group(1) or "").strip()
        if href:
            return href
    code_re = re.compile(code_pat, re.I)
    for m in re.finditer(
        rf'href=["\']([^"\']*/{lang}/movies/[^"\'#]+)["\']([\s\S]{{0,800}})',
        html,
        re.I,
    ):
        href = (m.group(1) or "").strip()
        if href and code_re.search(f"{href} {m.group(2) or ''}"):
            return href
    return None


def mirror_netcdn_to_dmm(url: str) -> str | None:
    if not url or not re.search(r"netcdn\.space", url, re.I):
        return None
    return re.sub(r"https?://[^/]*netcdn\.space", "https://pics.dmm.co.jp", url, flags=re.I)


def parse_aio_detail_html(html: str, detail_url: str, code: str, *, source: str):
    if is_aio_thin_shell(html):
        return None
    id_span = aio_detail_value(html, "识别码") or aio_detail_value(html, "識別碼")
    if id_span and code_key(id_span) != code_key(code):
        return None
    if not page_mentions_code(html, code) and not id_span:
        return None
    h1_m = re.search(
        r'class=["\']movie-detail["\'][\s\S]*?<h1[^>]*>([\s\S]*?)</h1>',
        html,
        re.I,
    )
    title = clean_title(strip_tags(h1_m.group(1) if h1_m else ""), code)
    if is_junk_title(title):
        title = ""
    actors = collect_by_re(html, r'class=["\'][^"\']*actress-name[^"\']*["\'][^>]*>([^<]+)<')
    actors += collect_by_re(html, r'href=["\'][^"\']*/(?:cn/)?actresses/[^"\']+["\'][^>]*>([^<]+)<')
    actors = [a for a in dict.fromkeys(actors) if 1 <= len(a) <= 40][:20]
    genres = collect_by_re(html, r'class=["\']detail-link["\'][^>]*>([^<]+)<')
    genres = [g for g in dict.fromkeys(genres) if g and not re.search(r"更多|全部", g)][:40]
    studio = aio_detail_value(html, "制作商") or aio_detail_value(html, "製作商") or ""
    if studio == "-":
        studio = ""
    premiered = (aio_detail_value(html, "发行时间") or aio_detail_value(html, "發行時間") or "")[:10]
    cover_m = re.search(
        r'class=["\'][^"\']*poster-image[^"\']*["\'][\s\S]*?src=["\']([^"\']+)["\']',
        html,
        re.I,
    ) or re.search(
        r'(https?://[^\'">\s]+/(?:digital/video|pics_dig/digital/video)/[^\'">\s]+pl\.(?:jpg|jpeg|png|webp))',
        html,
        re.I,
    )
    cover = abs_url(cover_m.group(1), detail_url) if cover_m else None
    if cover and is_junk_cover_url(cover):
        cover = None
    if not title and not cover and not actors and not genres:
        return None
    return make_detail(
        source=source,
        code=code,
        title=title or None,
        poster=cover,
        studio=studio or None,
        actors=actors,
        tags=genres,
        date=premiered or None,
    )


def scrape_aio_family(
    code: str,
    *,
    source: str,
    default_base: str,
    base_url: str = "",
    cookie: str = "",
    search_code: str | None = None,
) -> dict:
    std = std_code(code)
    q = search_code or std
    base = (base_url or default_base).rstrip("/")
    lang = "cn"
    search_url = f"{base}/{lang}/search/{quote(q)}"
    search_html = fetch_html(
        search_url, referer=f"{base}/{lang}", cookie=cookie or None, source_id=source
    )
    movie_path = pick_aio_movie_path(search_html, std, lang)
    if not movie_path:
        raise RuntimeError(f"{source} 搜索无结果")
    detail_url = abs_url(movie_path, base)
    if not detail_url:
        raise RuntimeError(f"{source} 详情链接无效")
    detail_html = fetch_html(
        detail_url, referer=search_url, cookie=cookie or None, source_id=source
    )
    if is_aio_thin_shell(detail_html):
        raise RuntimeError(f"{source} SPA 未渲染（需 Flare）")
    parsed = parse_aio_detail_html(detail_html, detail_url, std, source=source)
    if not parsed:
        raise RuntimeError(f"{source} 详情解析失败")
    return parsed
