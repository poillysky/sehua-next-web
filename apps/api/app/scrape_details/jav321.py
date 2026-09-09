# -*- coding: utf-8 -*-
"""Jav321 详情刮削（对齐 MDCS jav321.ts）。"""

from __future__ import annotations

import re
from urllib.parse import quote

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
    std_code,
    strip_tags,
)

DEFAULT_BASE = "https://www.jav321.com"


def _collect_by_re(html: str, pattern: re.Pattern[str]) -> list[str]:
    out: list[str] = []
    for m in pattern.finditer(html or ""):
        val = strip_tags(m.group(1) or "")
        if val and val not in out:
            out.append(val)
    return out


def _page_mentions_code(html: str, code: str) -> bool:
    want = code_key_local(code)
    if not want:
        return False
    return want in code_key_local(html)


def code_key_local(s: str) -> str:
    return re.sub(r"[-_\s]", "", str(s or "")).upper()


def _meta_after_bold(panel, lab: re.Pattern[str]) -> str:
    found = ""
    for el in panel.find_all("b"):
        name = strip_tags(el.get_text())
        if not lab.search(name):
            continue
        parts: list[str] = []
        for node in el.next_siblings:
            if getattr(node, "name", None):
                tag = str(node.name or "").lower()
                if tag in ("br", "b"):
                    break
                text = strip_tags(node.get_text() if hasattr(node, "get_text") else str(node))
                if text:
                    parts.append(text)
            else:
                text = strip_tags(str(node or ""))
                if text and text != ":":
                    parts.append(re.sub(r"^[:：]\s*", "", text))
        found = re.sub(r"^[:：]\s*", "", " ".join(parts)).strip()
        if found:
            break
    return found


def _studio_from_tokushu(html: str) -> str | None:
    m = re.search(r"『([^』]{2,48})』", html)
    name = (m.group(1) if m else "").strip()
    if not name or re.search(r"最新作|セール|こちら", name):
        return None
    return name


def _fetch_post_search(base: str, code: str, cookie: str = "") -> str:
    """POST /search with sn=CODE — 对齐 MDCS fetchPostForm（面板代理）。"""
    from .common import fetch_post_form

    url = f"{base}/search"
    body = f"sn={quote(code.upper())}"
    try:
        return fetch_post_form(
            url,
            body,
            referer=f"{base}/",
            cookie=cookie or None,
            source_id="jav321",
            timeout=20.0,
        )
    except Exception:
        pass

    # GET fallback (some mirrors accept query)
    return fetch_html(
        f"{url}?{body}",
        referer=f"{base}/",
        cookie=cookie or None,
        source_id="jav321",
    )


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")

    raw_code = str(code or "").strip()
    if not raw_code:
        raise RuntimeError("番号为空")

    try:
        html = _fetch_post_search(base, raw_code, cookie)
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}") from e

    if re.search(r"AVが見つかりませんでした|還沒有人投稿|not found|找不到|没有找到", html, re.I) and not re.search(
        r"panel-info|og:title", html, re.I
    ):
        raise RuntimeError("未找到")

    if (
        not _page_mentions_code(html, raw_code)
        and not re.search(r"panel-info", html, re.I)
        and not pick_og_title(html)
    ):
        raise RuntimeError("页面不匹配")

    doc = soup(html)
    panel = doc.select_one(".panel-info")
    if not panel:
        raise RuntimeError("未找到")

    std = std_code(raw_code)
    sn_raw = _meta_after_bold(panel, re.compile(r"品番|番號|番号|SN", re.I))
    sn = std_code(sn_raw) or ""
    if sn and sn != std and sn.replace("-", "") != std.replace("-", ""):
        if not _page_mentions_code(str(panel) or "", raw_code):
            raise RuntimeError("番号不匹配")

    h3 = panel.select_one(".panel-heading h3") or panel.select_one("h3")
    title_raw = ""
    if h3:
        # clone without small
        clone = soup(str(h3))
        for sm in clone.find_all("small"):
            sm.decompose()
        title_raw = clone.get_text()
    title = clean_title(title_raw or pick_og_title(html), raw_code)
    title = re.sub(r"\s*bittorrent\s*Download\s*dmm\s*$", "", title, flags=re.I)
    title = re.sub(rf"\b{re.escape(std).replace('-', '[-_]?')}\b", "", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip()
    if is_junk_title(title):
        title = ""

    panel_html = str(panel) or ""
    actors = [
        n
        for n in _collect_by_re(panel_html, re.compile(r'href=["\'][^"\']*/star/[^"\']+["\'][^>]*>([^<]+)<', re.I))
        if len(n) < 40
    ]
    studio = (
        (_collect_by_re(panel_html, re.compile(r'href=["\'][^"\']*/company/[^"\']+["\'][^>]*>([^<]+)<', re.I)) or [None])[0]
        or _meta_after_bold(panel, re.compile(r"メーカー|片商|Maker", re.I))
        or _studio_from_tokushu(panel_html)
        or None
    )
    if studio:
        studio = str(studio).strip() or None

    tags = [
        n
        for n in _collect_by_re(panel_html, re.compile(r'href=["\'][^"\']*/genre/[^"\']+["\'][^>]*>([^<]+)<', re.I))
        if len(n) < 40 and not re.search(r"ジャンル|类别|類型", n, re.I)
    ][:40]

    date_raw = _meta_after_bold(panel, re.compile(r"配信開始日|發行日期|发行日期|Release\s*Date|発売日", re.I))
    dm = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", date_raw)
    premiered = f"{dm.group(1)}-{dm.group(2).zfill(2)}-{dm.group(3).zfill(2)}" if dm else None

    plot = ""
    for el in panel.select(".row .col-md-12"):
        if el.select("video,img"):
            continue
        clone = soup(str(el))
        root = clone.find(True)
        if root:
            for bad in root.select("script,h2,ul,p.mg-t6"):
                bad.decompose()
            t = strip_tags(root.get_text())
        else:
            t = strip_tags(clone.get_text())
        t = re.sub(r"※\s*配信方法によって[\s\S]*$", "", t, flags=re.I)
        t = re.sub(r"特集[\s\S]*$", "", t, flags=re.I)
        t = re.sub(r"(?:（\d+）[^\s（]{0,40}\s*)+$", "", t)
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) < 20:
            continue
        if len(t) > len(plot):
            plot = t
    if len(plot) < 20 or is_junk_title(plot):
        plot = ""

    def tidy_url(u: str) -> str:
        u = re.sub(r"^(https?:)/+", r"\1//", u, flags=re.I)
        return re.sub(r"([^:/])/{2,}", r"\1/", u)

    cover: str | None = None
    video = panel.select_one("video[poster]")
    poster_attr = (video.get("poster") if video else "") or ""
    if not poster_attr:
        m = re.search(r'poster=["\']([^"\']+pl\.jpg[^"\']*)["\']', html, re.I)
        poster_attr = m.group(1) if m else ""
    img = panel.select_one(".col-md-3 img.img-responsive") or panel.select_one("img.img-responsive")
    panel_img = (img.get("src") if img else "") or ""
    if poster_attr:
        cover = abs_url(tidy_url(poster_attr), base)
    if not cover and panel_img:
        cover = abs_url(tidy_url(panel_img), base)
    if not cover:
        og = pick_og_image(html)
        if og:
            cover = abs_url(tidy_url(og), base)
    if cover and re.search(r"ps\.jpg", cover, re.I):
        cover = re.sub(r"ps\.jpg", "pl.jpg", cover, flags=re.I)
    if cover and is_junk_cover_url(cover):
        cover = None
    if cover:
        cover = re.sub(r"^http://", "https://", cover, flags=re.I)

    if not title:
        raise RuntimeError("未找到标题")

    return make_detail(
        source="jav321",
        code=std,
        title=title,
        poster=cover,
        studio=studio,
        actors=actors,
        tags=tags,
        overview=plot or None,
        date=premiered,
    )
