# -*- coding: utf-8 -*-
"""AIO 家族（Avmoo / AvSox / AVHeat）共用解析。"""

from __future__ import annotations

import re
from urllib.parse import quote

from .common import (
    abs_url,
    clean_title,
    code_equiv,
    collect_by_re,
    fetch_html,
    fold_code,
    folded_code_matches,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    std_code,
    strip_tags,
    append_std_pad_variants,
    date6_search_variants,
    western_code_candidates,
)

# 对齐 MDCS avmoo.ts：SPA 需 FlareSolverr waitInSeconds
_AIO_FLARE_WAIT_SEC = 3


def is_aio_thin_shell(html: str) -> bool:
    if not html:
        return True
    if re.search(r'class=["\']movie-detail["\']', html):
        return False
    if "detail-label" in html:
        return False
    # 搜索结果已渲染
    if re.search(r'class=["\'][^"\']*movie-(?:card|meta|info)', html, re.I):
        return False
    if len(html) < 2000:
        return True
    return len(html) < 4000 and not re.search(r"/cn/movies/", html, re.I)


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
    # 优先：卡片 span 展示番号（近精确）
    for m in re.finditer(
        rf'href=["\']([^"\']*/{lang}/movies/[^"\'#]+)["\'][\s\S]{{0,1200}}?movie-meta[\s\S]{{0,300}}?<span[^>]*>\s*{code_pat}\s*</span>',
        html,
        re.I,
    ):
        href = (m.group(1) or "").strip()
        if href:
            return href
    # 回退：仅 path/块内折叠命中番号；禁止裸 substring（ABF-005 错页）
    want = fold_code(code)
    for m in re.finditer(
        rf'href=["\']([^"\']*/{lang}/movies/[^"\'#]+)["\']([\s\S]{{0,800}})',
        html,
        re.I,
    ):
        href = (m.group(1) or "").strip()
        if not href:
            continue
        chunk = m.group(2) or ""
        if folded_code_matches(href, code, mode="endswith"):
            return href
        # span/文本里折叠全等才认（避免 ABF005 ⊂ 更长串）
        span = re.search(
            rf"<span[^>]*>\s*([A-Z0-9][A-Z0-9._\-\s]{{2,24}})\s*</span>",
            chunk,
            re.I,
        )
        if span and (
            fold_code(span.group(1)) == want or code_equiv(span.group(1), code)
        ):
            return href
    return None


def mirror_netcdn_to_dmm(url: str) -> str | None:
    if not url or not re.search(r"netcdn\.space", url, re.I):
        return None
    return re.sub(r"https?://[^/]*netcdn\.space", "https://pics.dmm.co.jp", url, flags=re.I)


def parse_aio_extrafanart(html: str, detail_url: str) -> list[str]:
    urls = collect_by_re(
        html,
        r'(?:sample-grid|samples)[\s\S]{0,4000}?<img[^>]+src=["\']([^"\']+)["\']',
    )
    if not urls:
        urls = collect_by_re(
            html,
            r'src=["\'](https?://[^"\']+/(?:digital/video|pics_dig/digital/video)/[^"\']+-\d+\.(?:jpg|jpeg|png|webp))["\']',
        )
    out: list[str] = []
    for u in urls:
        abs_u = abs_url(u, detail_url) or u
        if abs_u and not re.search(r"iframe\.html", abs_u, re.I) and abs_u not in out:
            out.append(abs_u)
    return out[:30]


def parse_aio_detail_html(
    html: str,
    detail_url: str,
    code: str,
    *,
    source: str,
    alt_codes: list[str] | None = None,
):
    if is_aio_thin_shell(html):
        return None

    id_span = aio_detail_value(html, "识别码") or aio_detail_value(html, "識別碼")
    # 必须有识别码且等价命中；禁止「页内某处提到番号」放过错页（ABF-005→ジュポニカ）
    if not id_span:
        return None
    want_codes = [c for c in [code, *(alt_codes or [])] if c]
    if not any(code_equiv(id_span, c) for c in want_codes):
        return None
    h1_m = re.search(
        r'class=["\']movie-detail["\'][\s\S]*?<h1[^>]*>([\s\S]*?)</h1>',
        html,
        re.I,
    )
    title = clean_title(strip_tags(h1_m.group(1) if h1_m else ""), code)
    for a in alt_codes or []:
        if a:
            title = clean_title(title, a)
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
    publisher = aio_detail_value(html, "发行商") or aio_detail_value(html, "發行商") or ""
    if publisher == "-":
        publisher = ""
    series = aio_detail_value(html, "系列") or ""
    if series == "-" or len(series) < 2 or is_junk_title(series):
        series = ""
    director = aio_detail_value(html, "导演") or aio_detail_value(html, "導演") or ""
    if director == "-":
        director = ""
    premiered = (aio_detail_value(html, "发行时间") or aio_detail_value(html, "發行時間") or "")[:10]
    runtime_raw = aio_detail_value(html, "长度") or aio_detail_value(html, "長度") or ""
    runtime_m = re.search(r"(\d+)", runtime_raw)
    runtime = int(runtime_m.group(1)) if runtime_m else None
    if runtime is not None and not (0 < runtime < 600):
        runtime = None
    cover_m = re.search(
        r'class=["\'][^"\']*poster-image[^"\']*["\'][\s\S]*?src=["\']([^"\']+)["\']',
        html,
        re.I,
    ) or re.search(
        r'(https?://[^\'">\s]+/(?:digital/video|storage/caribbeancom|pics_dig/digital/video)/[^\'">\s]+(?:pl|l_l)\.(?:jpg|jpeg|png|webp))',
        html,
        re.I,
    )
    cover = abs_url(cover_m.group(1), detail_url) if cover_m else None
    if cover and is_junk_cover_url(cover):
        cover = None
    extras = parse_aio_extrafanart(html, detail_url)
    dmm_alt = mirror_netcdn_to_dmm(cover) if cover else None
    if not title and not cover and not actors and not genres:
        return None
    extra: dict = {
        "publisher": publisher or None,
        "series": series or None,
        "website": detail_url,
        "extrafanartUrls": extras or None,
        "mosaic": "无码" if source in {"avsox", "avheat"} else None,
    }
    if director:
        extra["director"] = director
        extra["directors"] = [director]
    if runtime is not None:
        extra["runtime"] = runtime
    if dmm_alt and dmm_alt != cover:
        extra["alternateCoverUrls"] = [dmm_alt]
    return make_detail(
        source=source,
        code=code,
        title=title or None,
        poster=cover,
        studio=studio or None,
        actors=actors,
        tags=genres,
        date=premiered or None,
        extra=extra,
    )


def _fetch_aio_html(
    url: str,
    *,
    referer: str,
    cookie: str = "",
    source_id: str,
) -> str:
    """先普通拉取；SPA 空壳则 FlareSolverr + wait（对齐 MDCS）。"""
    html = fetch_html(
        url, referer=referer, cookie=cookie or None, source_id=source_id
    )
    need_flare = is_aio_thin_shell(html)
    if "/search/" in url and not re.search(r"/cn/movies/", html or "", re.I):
        need_flare = True
    if not need_flare:
        return html
    try:
        from app.core.outbound_http import (
            flaresolverr_request,
            thread_allow_flare,
            thread_request_timeout,
        )

        if not thread_allow_flare():
            return html
        tls = thread_request_timeout()
        # 批量策略超时优先；勿默认 90s 拖死整批
        max_ms = int(max(8.0, min(35.0, float(tls) if tls else 22.0)) * 1000)
        html2, _final = flaresolverr_request(
            url,
            max_timeout_ms=max_ms,
            referer=referer,
            cookie=cookie or None,
            wait_in_seconds=min(_AIO_FLARE_WAIT_SEC, 5),
        )
        return html2 or html
    except Exception:
        return html


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
    q = (search_code or std).strip()
    base = (base_url or default_base).rstrip("/")
    lang = "cn"
    # MDCS：多候选搜索词（无码 date6 / 欧美 YYYY↔YY / pad）
    queries: list[str] = []

    def _add_q(s: str) -> None:
        t = str(s or "").strip()
        if t and t not in queries:
            queries.append(t)

    for cand in western_code_candidates(code):
        _add_q(cand)
    _add_q(q)
    _add_q(std)
    append_std_pad_variants(_add_q, code)
    for cand in date6_search_variants(code):
        _add_q(cand)
    m = re.match(r"^([A-Z]{2,12})[-_]?(\d{6}-\d{3})$", std, re.I)
    if m:
        _add_q(m.group(2))

    movie_path: str | None = None
    search_url = ""
    search_html = ""
    matched_query = std
    for query in queries:
        search_url = f"{base}/{lang}/search/{quote(query)}"
        search_html = _fetch_aio_html(
            search_url, referer=f"{base}/{lang}", cookie=cookie, source_id=source
        )
        if re.search(r"没有结果|沒有結果|no results", search_html or "", re.I):
            continue
        # 优先用本次搜索词挑链（CARIB 页上是 010117-339；欧美页上是 YY 形）
        movie_path = pick_aio_movie_path(search_html, query, lang)
        if not movie_path:
            for alt in queries:
                movie_path = pick_aio_movie_path(search_html, alt, lang)
                if movie_path:
                    break
        if movie_path:
            matched_query = query
            break

    if not movie_path:
        raise RuntimeError(f"{source} 搜索无结果")
    detail_url = abs_url(movie_path, base)
    if not detail_url:
        raise RuntimeError(f"{source} 详情链接无效")
    detail_html = _fetch_aio_html(
        detail_url, referer=search_url, cookie=cookie, source_id=source
    )
    if is_aio_thin_shell(detail_html):
        raise RuntimeError(f"{source} SPA 未渲染（需 Flare）")
    parsed = parse_aio_detail_html(
        detail_html,
        detail_url,
        matched_query or std,
        source=source,
        alt_codes=queries,
    )
    if not parsed:
        raise RuntimeError(f"{source} 详情解析失败")
    return parsed
