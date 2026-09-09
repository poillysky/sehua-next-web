# -*- coding: utf-8 -*-
"""JavDB 详情刮削（对齐 MDCS javdb.ts；经 fetch_html 做 CF 感知拉页）。"""

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
    soup,
)

DEFAULT_BASE = "https://javdb.com"
SOURCE = "javdb"


def _panel_value(doc, label_re: re.Pattern[str]) -> tuple[str, list[str]]:
    text = ""
    links: list[str] = []
    for el in doc.select(".movie-panel-info .panel-block, .panel-block"):
        strong = el.select_one("strong")
        lab = strip_tags(strong.get_text()) if strong else ""
        if not label_re.search(lab):
            continue
        val = el.select_one("span.value")
        if val is not None:
            for a in val.select("a"):
                n = strip_tags(a.get_text())
                if n and len(n) < 60 and n not in links:
                    links.append(n)
            text = strip_tags(val.get_text())
        else:
            text = strip_tags(el.get_text().replace(lab, ""))
    return text, links


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

    search_url = f"{base}/search?q={quote(std.upper())}&f=all&locale=zh"
    try:
        search = fetch_html(
            search_url, referer=f"{base}/", cookie=ck, source_id=SOURCE
        )
    except RuntimeError as e:
        raise RuntimeError(str(e) or "搜索无响应") from e

    if re.search(r"banned your access|禁止了你的訪問|異常行為", search, re.I):
        raise RuntimeError("访问被禁止")

    doc_s = soup(search)
    want = code_key(std)
    detail_path = ""
    for el in doc_s.select(".movie-list .item a.box, #videos a.box, a.box[href*='/v/']"):
        if detail_path:
            break
        href = str(el.get("href") or "")
        if not re.search(r"/v/", href, re.I):
            continue
        uid_el = el.select_one(".uid, .video-title strong, .id") or el.select_one(
            ".video-title"
        )
        uid = strip_tags(uid_el.get_text() if uid_el else "")
        uid_key = code_key((uid.split() or [uid])[0] if uid else "")
        title_el = el.select_one(".video-title")
        title_text = strip_tags(title_el.get_text() if title_el else el.get_text())
        if uid_key == want or code_key(title_text).startswith(want):
            detail_path = href

    if not detail_path:
        code_pat = re.escape(std).replace(r"\-", "[-]?")
        m = re.search(
            rf'href=["\'](/v/[^"\']+)["\'][^>]*>[\s\S]{{0,400}}?{code_pat}',
            search,
            re.I,
        )
        detail_path = m.group(1) if m else ""

    if not detail_path:
        raise RuntimeError("搜索无结果")

    detail_url = abs_url(detail_path, base)
    if not detail_url:
        raise RuntimeError("详情链接无效")

    try:
        html = fetch_html(
            detail_url, referer=search_url, cookie=ck, source_id=SOURCE
        )
    except RuntimeError as e:
        raise RuntimeError("详情页不可用") from e

    if re.search(r"banned your access|禁止了你的訪問", html, re.I) or not page_mentions_code(
        html, std
    ):
        raise RuntimeError("详情页不可用")

    doc = soup(html)
    raw_title = ""
    for sel in ("strong.current-title", "h2.title strong"):
        el = doc.select_one(sel)
        if el is not None:
            raw_title = strip_tags(el.get_text())
            break
    if not raw_title:
        tel = doc.select_one("title")
        raw_title = re.sub(
            r"\s*\|\s*JavDB.*$", "", strip_tags(tel.get_text() if tel else ""), flags=re.I
        )
    title = clean_title(raw_title, std)
    title = re.sub(r"\s*[|｜].*$", "", title)
    title = re.sub(r"\s*(中文字幕|无码流出|無碼流出)\s*$", "", title, flags=re.I).strip()
    if is_junk_title(title):
        title = ""

    actors: list[str] = []
    has_female = bool(doc.select("a[href*='/actors/'] + strong.female"))
    for a in doc.select("a[href*='/actors/']"):
        n = strip_tags(a.get_text())
        if not n or len(n) < 2 or len(n) > 40 or n in actors:
            continue
        nxt = a.find_next_sibling("strong")
        nxt_cls = " ".join(nxt.get("class") or []) if nxt is not None else ""
        if "male" in nxt_cls and "female" not in nxt_cls:
            continue
        if has_female and "female" not in nxt_cls:
            continue
        actors.append(n)
    if not actors:
        _, links = _panel_value(doc, re.compile(r"演員|演员|Actor"))
        for n in links:
            if 2 <= len(n) <= 40 and n not in actors:
                actors.append(n)

    cover_el = doc.select_one("img.video-cover") or doc.select_one(
        ".column-video-cover img"
    )
    cover = abs_url(cover_el.get("src") if cover_el else None, base)
    if cover and is_junk_cover_url(cover):
        cover = None

    date_text, _ = _panel_value(doc, re.compile(r"日期|Released Date|発売日"))
    dm = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", date_text or "")
    premiered = (
        f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}" if dm else None
    )

    runtime_text, _ = _panel_value(doc, re.compile(r"時長|时长|Duration|収録時間"))
    rm = re.search(r"(\d+)", runtime_text or "")
    runtime = int(rm.group(1)) if rm else None

    pub_text, pub_links = _panel_value(doc, re.compile(r"發行|发行|Publisher|レーベル"))
    publisher = (pub_links[0] if pub_links else "") or pub_text
    maker_text, maker_links = _panel_value(
        doc, re.compile(r"片商|Maker|制作|製作|メーカー")
    )
    maker = (maker_links[0] if maker_links else "") or maker_text
    series_text, series_links = _panel_value(
        doc, re.compile(r"系列|Series|シリーズ")
    )
    series = (series_links[0] if series_links else "") or series_text

    tag_text, tag_links = _panel_value(doc, re.compile(r"類別|类别|Tags|タグ|标签"))
    del tag_text
    genres = []
    for n in tag_links + collect_by_re(
        html, r'href=["\'][^"\']*/tags\?[^"\']*["\'][^>]*>([^<]+)<'
    ):
        t = n.strip()
        if t and len(t) < 40 and t not in genres:
            genres.append(t)
    genres = genres[:40]

    ogd = doc.select_one("meta[property='og:description']")
    plot = strip_tags(ogd.get("content") if ogd else "")
    if not plot:
        pm = re.search(
            r'property=["\']og:description["\']\s+content=["\']([^"\']+)["\']', html, re.I
        )
        plot = strip_tags(pm.group(1) if pm else "")
    if len(plot) < 12 or is_junk_title(plot) or plot == title:
        plot = ""

    score_el = doc.select_one(".score")
    score_raw = strip_tags(score_el.get_text()) if score_el else ""
    if not score_raw:
        sm = re.search(r'class=["\']score["\'][^>]*>[\s\S]*?(\d\.\d+)', html, re.I)
        score_raw = sm.group(1) if sm else ""
    score_m = re.search(r"(\d\.\d+)", score_raw)
    rating_value = float(score_m.group(1)) if score_m else None

    if not title and not cover:
        raise RuntimeError("无标题与封面")

    extra: dict = {
        "publisher": publisher or None,
        "series": series or None,
        "runtime": runtime if runtime and runtime > 0 else None,
    }
    if rating_value is not None:
        extra.update(
            {
                "ratingValue": rating_value,
                "ratingMax": 5,
                "ratingSource": "javdb",
                "score": rating_value * 2,
            }
        )

    return make_detail(
        source=SOURCE,
        code=std,
        title=title or None,
        poster=cover,
        studio=maker or None,
        actors=actors[:20],
        tags=genres,
        overview=plot or None,
        date=premiered,
        extra=extra,
    )
