# -*- coding: utf-8 -*-
"""黄色仓库 / hsck 详情。"""

from __future__ import annotations

import re
from urllib.parse import quote, urlparse

from .common import (
    abs_url,
    clean_title,
    fetch_html,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    soup,
    strip_tags,
)

DEFAULT_BASE = "http://hsck.net"


def _norm(code: str) -> str:
    return str(code or "").strip().upper().replace("_", "-")


def _compact(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", _norm(code))


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    norm = _norm(code)
    compact = _compact(code)
    base = (base_url or DEFAULT_BASE).rstrip("/")
    search_base = base
    try:
        home = fetch_html(base + "/", referer=None, cookie=cookie or None, source_id="hscangku")
        gm = re.search(r'"(https?://[^"]+\?u=)\+window\.location', home, re.I)
        if gm:
            raw = gm.group(1).replace("?u=", "")
            try:
                gate_origin = f"{urlparse(raw).scheme}://{urlparse(raw).netloc}"
                gate_url = f"{gate_origin}/?u={quote(base + '/')}&p={quote('/')}"
                # best-effort; may land on mirror
                gate_html = fetch_html(
                    gate_url, referer=base + "/", cookie=cookie or None, source_id="hscangku"
                )
                if gate_html and len(gate_html) > 500:
                    search_base = gate_origin
            except Exception:
                pass
    except Exception:
        pass

    queries = list(dict.fromkeys([norm, compact]))
    m = re.match(r"^([A-Z]{2,10})-?(\d{2,6}(?:-\d+)?)$", norm)
    if m:
        queries.extend([f"{m.group(1)}-{m.group(2)}", f"{m.group(1)}{m.group(2)}"])

    last_err: Exception | None = None
    for q in queries:
        try:
            search_url = (
                f"{search_base}/vodsearch/-------------.html?wd={quote(q)}&submit="
            )
            html = fetch_html(
                search_url,
                referer=f"{search_base}/",
                cookie=cookie or None,
                source_id="hscangku",
            )
            doc = soup(html)
            detail_url = ""
            cover = ""
            for a in doc.select("a.stui-vodlist__thumb.lazyload, a.stui-vodlist__thumb"):
                href = (a.get("href") or "").strip()
                title = strip_tags(a.get("title") or "")
                if not href:
                    continue
                if not re.match(r"^/(?:v\d+|vodplay)/\d+-\d+-\d+\.html$", href, re.I):
                    continue
                hay = _compact(f"{title} {href}")
                if compact and compact not in hay:
                    continue
                detail_url = abs_url(href, search_base) or ""
                cover = (
                    abs_url(
                        a.get("data-original") or a.get("data-src") or a.get("src"),
                        search_base,
                    )
                    or ""
                )
                break
            if not detail_url:
                continue
            detail_html = fetch_html(
                detail_url,
                referer=search_url,
                cookie=cookie or None,
                source_id="hscangku",
            )
            d = soup(detail_html)
            title = ""
            for h in d.select("h3.title"):
                title = clean_title(strip_tags(h.get_text()), code)
                if title:
                    break
            if is_junk_title(title):
                title = ""
            if cover and is_junk_cover_url(cover):
                cover = None
            if not cover:
                img = d.select_one(".stui-content__thumb img, .pic img, img.lazyload")
                if img is not None:
                    cover = abs_url(
                        img.get("data-original") or img.get("src"), detail_url
                    )
            if not title and not cover:
                raise RuntimeError("详情无有效内容")
            return make_detail(
                source="hscangku",
                code=norm,
                title=title or None,
                poster=cover,
            )
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise RuntimeError(f"hscangku 失败: {last_err}")
