# -*- coding: utf-8 -*-
"""airav.io 详情刮削（对齐 MDCS airav_io.ts）。"""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from .common import (
    abs_url,
    clean_title,
    collect_by_re,
    fetch_html_result,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    pick_og_image,
    pick_og_title,
    strip_tags,
)

DEFAULT_BASE = "https://airav.io/cn"
SOURCE = "airav_io"
_JUNK_ENTRY_RE = re.compile(
    r"克破|无码破解|無碼破解|无码流出|無碼流出|马赛克破坏|馬賽克破壞|馬賽克破解版|無碼流出版",
    re.I,
)
_TITLE_EPISODE_MARKERS = (
    "第一集",
    "第二集",
    " - 上",
    " - 下",
    " 上集",
    " 下集",
    " -上",
    " -下",
)


def normalize_airav_code(code: str) -> str:
    raw = str(code or "").strip().upper()
    if re.match(r"^N\d{4}$", raw, re.I):
        return raw.lower()
    return raw


def match_airav_number(text: str, number: str) -> bool:
    hay = str(text or "")
    num = str(number or "").strip()
    if not num:
        return False
    if re.match(r"^\d", num):
        return num.upper() in hay.upper()
    esc = re.escape(num)
    return bool(re.search(rf"(?<![A-Z0-9]){esc}(?![A-Z0-9])", hay, re.I))


def is_airav_junk_entry(title: str) -> bool:
    return bool(_JUNK_ENTRY_RE.search(str(title or "")))


def list_airav_search_cards(html: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in re.finditer(
        r'<div[^>]*class=["\'][^"\']*col oneVideo[^"\']*["\'][^>]*>([\s\S]*?)</div>\s*</div>',
        html or "",
        re.I,
    ):
        chunk = m.group(1) or ""
        hm = re.search(r'href=["\']([^"\']*/video\?hid=[^"\'#]+)["\']', chunk, re.I)
        href = (hm.group(1) if hm else "").strip()
        tm = re.search(r"<h5[^>]*>([\s\S]*?)</h5>", chunk, re.I)
        title = strip_tags(tm.group(1) if tm else "")
        if href:
            out.append({"href": href, "title": title})
    return out


def pick_airav_hid_from_search(html: str, code: str) -> str | None:
    hits = list_airav_search_cards(html)
    if len(hits) == 1:
        only = hits[0]
        return None if is_airav_junk_entry(only["title"]) else only["href"]
    for hit in hits:
        if not match_airav_number(hit["title"], code):
            continue
        if is_airav_junk_entry(hit["title"]):
            continue
        return hit["href"]
    for m in re.finditer(r"<h5[^>]*>([\s\S]*?)</h5>", html or "", re.I):
        h5 = strip_tags(m.group(1) or "")
        if not match_airav_number(h5, code) or is_airav_junk_entry(h5):
            continue
        before = html[max(0, m.start() - 800) : m.start()]
        near = re.search(r'href=["\']([^"\']*/video\?hid=[^"\'#]+)["\'][^>]*>\s*$', before, re.I)
        if near:
            return near.group(1)
        all_h = list(re.finditer(r'href=["\']([^"\']*/video\?hid=[^"\'#]+)["\']', before, re.I))
        if all_h:
            return all_h[-1].group(1)
    return None


def airav_detail_code_ok(html: str, code: str) -> bool:
    code_re = re.compile(rf"^{re.escape(code).replace('-', '[-_]?')}$", re.I)
    span_m = re.search(
        r"番[号號]\s*[：:]\s*<span[^>]*>([^<]+)</span>", html, re.I
    ) or re.search(r"番[号號]\s*<span[^>]*>([^<]+)</span>", html, re.I)
    if span_m and code_re.match(strip_tags(span_m.group(1))):
        return True
    h1_m = re.search(
        r'<div[^>]*class=["\'][^"\']*video-title[^"\']*["\'][^>]*>[\s\S]*?<h1[^>]*>([\s\S]*?)</h1>',
        html,
        re.I,
    ) or re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html, re.I)
    h1 = strip_tags(h1_m.group(1) if h1_m else "")
    prefix_re = re.compile(rf"^{re.escape(code).replace('-', '[-_]?')}\b", re.I)
    if h1 and prefix_re.search(h1):
        return True
    og = pick_og_title(html)
    return bool(og and prefix_re.search(og))


def pick_airav_ld_json_cover(html: str) -> str:
    raw_m = re.search(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>',
        html,
        re.I,
    )
    if not raw_m:
        return ""
    try:
        data = json.loads(raw_m.group(1).strip())
        thumbs = data.get("thumbnailUrl")
        if isinstance(thumbs, str):
            return thumbs.strip()
        if isinstance(thumbs, list) and thumbs:
            return str(thumbs[0]).strip()
    except Exception:
        pass
    return ""


def _strip_title_prefix(title: str, web_number: str) -> str:
    out = str(title or "").strip()
    for prefix in (f"[{web_number}]", web_number):
        if prefix and out.startswith(prefix):
            out = out[len(prefix) :].strip()
    for marker in _TITLE_EPISODE_MARKERS:
        out = out.replace(marker, "").strip()
    return out


def _detect_mosaic(genres: list[str]) -> str:
    joined = ",".join(genres)
    if re.search(r"无码|無修正|無码|uncensored", joined, re.I):
        return "无码"
    return "有码"


def parse_airav_io_detail(html: str, page_url: str, code: str) -> dict | None:
    if re.search(r"找不到|404|Not Found", html, re.I) and not re.search(
        r"video-title|og:title|oneVideo", html, re.I
    ):
        return None

    web_m = re.search(r"番[号號]\s*[：:]?\s*<span[^>]*>([^<]+)</span>", html, re.I)
    web_number = strip_tags(web_m.group(1) if web_m else "") or code

    title_m = re.search(
        r'<div[^>]*class=["\'][^"\']*video-title[^"\']*["\'][^>]*>[\s\S]*?<h1[^>]*>([\s\S]*?)</h1>',
        html,
        re.I,
    )
    title = clean_title(title_m.group(1) if title_m else pick_og_title(html), code)
    title = re.sub(r"\s*[-–—]\s*airav(?:\.io)?\s*$", "", title, flags=re.I).strip()
    title = _strip_title_prefix(title, web_number)
    if is_airav_junk_entry(title) or is_junk_title(title):
        title = ""

    cover = pick_airav_ld_json_cover(html) or pick_og_image(html)
    if cover:
        cover = abs_url(cover, page_url)
    if not cover:
        cm = re.search(
            r"(https?://[^\"'>\s]+/storage/cover/(?:big/)?[^\"'>\s]+\.(?:jpg|jpeg|png|webp))",
            html,
            re.I,
        )
        if cm and not is_junk_cover_url(cm.group(1)):
            cover = cm.group(1)
    if cover and is_junk_cover_url(cover):
        cover = None

    actor_block_m = (
        re.search(r"女[优優][\s\S]{0,40}?</[^>]+>([\s\S]*?)</(?:li|div)>", html, re.I)
        or re.search(r"女[优優]\s*[：:]([\s\S]*?)</li>", html, re.I)
        or re.search(r"女[优優]\s*[：:]([\s\S]*?)</div>", html, re.I)
    )
    actor_block = actor_block_m.group(1) if actor_block_m else ""
    actors_raw = (
        collect_by_re(html, r'href=["\'][^"\']*/(?:cn/)?actor\?id=\d+["\'][^>]*>([^<]+)<')
        + collect_by_re(html, r'href=["\'][^"\']*/(?:cn/)?actress/[^"\']+["\'][^>]*>([^<]+)<')
        + collect_by_re(actor_block, r'href=["\'][^"\']*["\'][^>]*>([^<]+)<')
        + collect_by_re(actor_block, r">([^<]{1,40})<")
    )
    actors: list[str] = []
    for a in actors_raw:
        t = a.strip()
        if (
            t
            and len(t) <= 40
            and not re.match(r"^(女[优優]|一覽|一览|發行|发行|factories|演员|詳|详情)$", t, re.I)
            and t not in actors
        ):
            actors.append(t)
    actors = actors[:20]

    tag_block_m = re.search(r"標[签籤]\s*[：:]([\s\S]*?)</li>", html, re.I) or re.search(
        r"标[签籤]\s*[：:]([\s\S]*?)</li>", html, re.I
    )
    tag_block = tag_block_m.group(1) if tag_block_m else ""
    genres_raw = collect_by_re(
        tag_block, r'href=["\'][^"\']*/(?:cn/)?tag\?tid=[^"\']*["\'][^>]*>([^<]+)<'
    ) + collect_by_re(
        html, r'href=["\'][^"\']*/(?:cn/)?(?:genre|genres)/[^"\']+["\'][^>]*>([^<]+)<'
    )
    genres: list[str] = []
    for g in genres_raw:
        t = g.strip()
        if (
            t
            and not re.search(
                r"更多|全部|标签|標籤|類型|类型|一覽|一览|VR|720p|1080p|HD高畫質|AV女優片|中文",
                t,
                re.I,
            )
            and not is_junk_title(t)
            and t not in genres
        ):
            genres.append(t)
    genres = genres[:40]

    studio_m = (
        re.search(r"廠商\s*[：:]([\s\S]*?)</li>", html, re.I)
        or re.search(r"厂商\s*[：:]([\s\S]*?)</li>", html, re.I)
        or re.search(r'href=["\'][^"\']*/(?:cn/)?tag\?fid=\d+["\'][^>]*>([^<]+)<', html, re.I)
        or re.search(
            r'href=["\'][^"\']*/(?:cn/)?factory(?:/|\?[^"\']*)["\'][^>]*>([^<]+)<', html, re.I
        )
    )
    studio = strip_tags(studio_m.group(1) if studio_m else "")
    if len(studio) < 2 or re.search(r"一覽|一览|發行商|发行商|廠商|厂商", studio, re.I):
        studio = ""

    series_m = (
        re.search(r"系列\s*[：:]([\s\S]*?)</li>", html, re.I)
        or re.search(r"シリーズ\s*[：:]([\s\S]*?)</li>", html, re.I)
        or re.search(r'href=["\'][^"\']*/(?:cn/)?series/[^"\']+["\'][^>]*>([^<]+)<', html, re.I)
    )
    series = strip_tags(series_m.group(1) if series_m else "")
    if len(series) < 2 or is_junk_title(series):
        series = ""

    plot_m = re.search(
        r'<div[^>]*class=["\'][^"\']*video-info[^"\']*["\'][^>]*>\s*<p[^>]*>([\s\S]*?)</p>',
        html,
        re.I,
    )
    plot = strip_tags(plot_m.group(1) if plot_m else "")
    if not plot:
        ogd = re.search(
            r'property=["\']og:description["\']\s+content=["\']([^"\']+)["\']', html, re.I
        ) or re.search(
            r'content=["\']([^"\']+)["\']\s+property=["\']og:description["\']', html, re.I
        )
        plot = strip_tags(ogd.group(1) if ogd else "")
    plot = plot.split("*根据分发", 1)[0].replace("\n", "").replace("\t", "").strip()
    plot_min = 4 if re.search(r'<div[^>]*class=["\'][^"\']*video-info', html, re.I) else 12
    if len(plot) < plot_min or is_airav_junk_entry(plot) or is_junk_title(plot):
        plot = ""

    date_m = re.search(
        r'<i[^>]*class=["\'][^"\']*fa-clock[^"\']*["\'][^>]*>\s*</i>\s*(\d{4}-\d{2}-\d{2})',
        html,
        re.I,
    ) or re.search(r"fa-clock[\s\S]{0,80}?(\d{4}-\d{2}-\d{2})", html, re.I)
    premiered = date_m.group(1) if date_m else ""

    if not title and not cover and not actors and not plot and not genres and not series:
        return None

    return make_detail(
        source=SOURCE,
        code=code,
        title=title or None,
        poster=cover,
        studio=studio or None,
        actors=actors,
        tags=genres,
        overview=plot or None,
        date=premiered or None,
        extra={
            "titleZh": title or None,
            "originalTitle": title or None,
            "series": series or None,
            "mosaic": _detect_mosaic(genres),
            "website": page_url,
        },
    )


def _normalize_cn_base(url: str) -> str:
    u = str(url or "").strip().rstrip("/")
    if not u:
        return DEFAULT_BASE
    if not re.search(r"/cn$", u, re.I):
        # keep host; append /cn if looks like airav root
        if re.search(r"airav", u, re.I) and not re.search(r"/video", u, re.I):
            return f"{u}/cn"
    return u


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    normalized = normalize_airav_code(code)
    if not normalized:
        raise RuntimeError("番号为空")
    cn_base = _normalize_cn_base(base_url or DEFAULT_BASE)
    ck = cookie or None

    search_url = f"{cn_base}/search_result?kw={quote(normalized)}"
    search_html, landed = fetch_html_result(
        search_url, referer=f"{cn_base}/", cookie=ck, source_id=SOURCE
    )
    landed_base = _normalize_cn_base(landed or cn_base)

    hid_href = pick_airav_hid_from_search(search_html, normalized)
    if not hid_href:
        raise RuntimeError("未找到")

    detail_url = abs_url(hid_href, landed_base) or (
        f"{landed_base.rstrip('/')}{'' if hid_href.startswith('/') else '/'}{hid_href}"
    )
    detail_html, detail_landed = fetch_html_result(
        detail_url, referer=search_url, cookie=ck, source_id=SOURCE
    )
    if not airav_detail_code_ok(detail_html, normalized):
        raise RuntimeError("未找到")

    parsed = parse_airav_io_detail(detail_html, detail_landed or detail_url, normalized)
    if not parsed:
        raise RuntimeError("未找到")
    return parsed
