# -*- coding: utf-8 -*-
"""黄色仓库 / hsck 详情（对齐 MDCS hscangku.ts）。"""

from __future__ import annotations

import re
from urllib.parse import quote, urlparse

from .common import (
    abs_url,
    clean_title,
    fetch_html,
    fetch_html_result,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    soup,
    strip_tags,
)

DEFAULT_BASE = "http://hsck.net"
FALLBACK_MIRRORS = ("https://556897.xyz", "https://556822.xyz")
SOURCE = "hscangku"


def _norm(code: str) -> str:
    return str(code or "").strip().upper().replace("_", "-")


def _compact(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", _norm(code))


def _origin(url: str) -> str:
    try:
        p = urlparse(url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
    except Exception:
        pass
    return ""


def _parse_gateway_origin(html: str) -> str | None:
    """门户页 var strU=\"https://…/?u=\"+window.location …"""
    m = re.search(
        r'strU\s*=\s*"(https?://[^"]+\?u=)"\s*\+\s*window\.location',
        html or "",
        re.I,
    ) or re.search(
        r'"(https?://[^"]+\?u=)"\s*\+\s*window\.location',
        html or "",
        re.I,
    )
    if not m:
        return None
    raw = re.sub(r"\?u=$", "", m.group(1), flags=re.I)
    return _origin(raw) + "/" if _origin(raw) else None


def _resolve_mirror(base: str, cookie: str | None) -> str:
    """跟随 hsck.net 门户网关到活镜像；失败则退回 base。"""
    root = (base or DEFAULT_BASE).rstrip("/")
    try:
        home, _ = fetch_html_result(f"{root}/", referer=None, cookie=cookie, source_id=SOURCE)
        gate = _parse_gateway_origin(home or "")
        if not gate:
            return root
        gate_url = f"{gate}?u={quote(root + '/')}&p={quote('/')}"
        _html, landed = fetch_html_result(
            gate_url, referer=f"{root}/", cookie=cookie, source_id=SOURCE
        )
        landed_origin = _origin(landed or "")
        return landed_origin or root
    except Exception:
        return root


def _search_queries(code: str) -> list[str]:
    norm = _norm(code)
    compact = _compact(code)
    out = list(dict.fromkeys([norm, compact]))
    m = re.match(r"^([A-Z]{2,10})-?(\d{2,6}(?:-\d+)?)$", norm)
    if m:
        out.extend([f"{m.group(1)}-{m.group(2)}", f"{m.group(1)}{m.group(2)}"])
    return list(dict.fromkeys(out))


def _parse_search_hit(html: str, code: str, base_url: str) -> tuple[str, str]:
    compact = _compact(code)
    doc = soup(html or "")
    for a in doc.select("a.stui-vodlist__thumb.lazyload, a.stui-vodlist__thumb"):
        href = (a.get("href") or "").strip()
        title_a = strip_tags(a.get("title") or "")
        if not href:
            continue
        if not re.match(r"^/(?:v\d+|vodplay)/\d+-\d+-\d+\.html$", href, re.I):
            continue
        hay = _compact(f"{title_a} {href}")
        if compact and compact not in hay:
            continue
        detail_url = abs_url(href, base_url) or ""
        cover = (
            abs_url(
                a.get("data-original") or a.get("data-src") or a.get("src"),
                base_url,
            )
            or ""
        )
        return detail_url, cover
    return "", ""


def _parse_detail(html: str, detail_url: str, code: str, cover_hint: str) -> dict:
    compact = _compact(code)
    d = soup(html or "")
    title = ""
    for h in d.select("h3.title"):
        t = clean_title(strip_tags(h.get_text()), code)
        if t and not re.search(r"目录|为你推荐", t):
            title = t
            break
    if not title:
        title_el = d.select_one("title")
        title = clean_title(
            re.sub(
                r"\s*-\s*黄色仓库.*$",
                "",
                strip_tags(title_el.get_text() if title_el else ""),
                flags=re.I,
            ),
            code,
        )
    title = re.sub(rf"^{re.escape(compact)}\s*", "", title, flags=re.I).strip()
    title = re.sub(rf"^{re.escape(_norm(code))}\s*", "", title, flags=re.I).strip()
    if is_junk_title(title):
        title = ""

    cover = cover_hint or ""
    if cover and (is_junk_cover_url(cover) or re.search(r"\.gif(?:\?|$)", cover, re.I)):
        cover = ""
    if not cover:
        img = d.select_one(".stui-content__thumb img, .pic img, img.lazyload")
        if img is not None:
            cover = (
                abs_url(img.get("data-original") or img.get("src"), detail_url) or ""
            )
    if cover and is_junk_cover_url(cover):
        cover = ""
    if not title and not cover:
        raise RuntimeError("详情无有效内容")
    return make_detail(
        source=SOURCE,
        code=_norm(code),
        title=title or None,
        poster=cover or None,
        extra={"website": detail_url, "titleZh": title or None},
    )


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    norm = _norm(code)
    ck = cookie or None
    configured = (base_url or DEFAULT_BASE).rstrip("/")

    mirror = _resolve_mirror(configured, ck)
    bases = list(
        dict.fromkeys(
            [
                mirror,
                configured,
                *FALLBACK_MIRRORS,
            ]
        )
    )

    last_err: Exception | None = None
    tried_origins: set[str] = set()
    for sb in bases:
        root = sb.rstrip("/")
        origin = _origin(root) or root
        if origin in tried_origins:
            continue
        tried_origins.add(origin)
        for q in _search_queries(code):
            try:
                search_url = f"{root}/vodsearch/-------------.html?wd={quote(q)}&submit="
                html, search_final = fetch_html_result(
                    search_url, referer=f"{root}/", cookie=ck, source_id=SOURCE
                )
                search_final_base = _origin(search_final or "") or root
                # 旧镜像常 302 到新首页并丢掉搜索路径 → 在落地 origin 重搜一次
                final_path = urlparse(search_final or "").path or "/"
                if search_final_base != root and not re.search(
                    r"vodsearch|/search", final_path, re.I
                ):
                    if search_final_base not in tried_origins:
                        bases.append(search_final_base)
                    continue

                detail_url, cover = _parse_search_hit(html or "", code, search_final_base)
                if not detail_url:
                    continue

                detail_html = fetch_html(
                    detail_url, referer=search_url, cookie=ck, source_id=SOURCE
                )
                return _parse_detail(detail_html or "", detail_url, norm, cover)
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
    raise RuntimeError(f"hscangku 失败: {last_err}")
