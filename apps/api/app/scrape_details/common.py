# -*- coding: utf-8 -*-
"""刮削详情公共工具（对齐 MDCS htmlUtils + 统一写库字段）。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

DetailDict = dict[str, Any]


def strip_tags(s: str) -> str:
    import html as _html

    t = _html.unescape(str(s or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()


def code_key(s: str) -> str:
    return re.sub(r"[-_\s]", "", str(s or "")).upper()


def fold_code(s: str) -> str:
    """对齐 MDCX/Amane：去掉 - _ . 空白后大写，供 URL/番号精确匹配。"""
    return re.sub(r"[-_.\s]", "", str(s or "")).upper()


def _code_bucket(folded: str) -> tuple[str, int, str] | None:
    """把折叠后的番号拆成 (字母前缀, 数字, 尾字母)，数字去掉前导零。"""
    m = re.fullmatch(r"([A-Z]+)0*(\d+)([A-Z]?)", str(folded or ""))
    if not m:
        return None
    return (m.group(1), int(m.group(2)), m.group(3))


def code_equiv(a: str, b: str) -> bool:
    """番号等价判定：忽略分隔符/大小写，并容忍数字段**前导零补齐差异**。

    例：`NAMH-0028` ≡ `NAMH-028`；`ABC-001` ≡ `ABC-1`。
    仅在「字母前缀 + 数字 + 可选尾字母」结构相同时才放宽，避免 `ABF0051`
    被当成 `ABF-005`（数字续写是另一个番号，仍判不等）。
    """
    fa, fb = fold_code(a), fold_code(b)
    if not fa or not fb:
        return False
    if fa == fb:
        return True
    ba, bb = _code_bucket(fa), _code_bucket(fb)
    if ba is None or bb is None:
        return False
    return ba == bb


def folded_code_matches(
    candidate: str,
    code: str,
    *,
    mode: str = "endswith",
) -> bool:
    """candidate 为 href / path / 页面番号文本。

    - exact: 折叠后全等（或末段 slug 全等）
    - endswith: 末段 slug 折叠等于番号，或番号后仅为非数字续缀（_CD1 / U）；
      拒绝 ABF0051 这类数字续写误命中
    """
    want = fold_code(code)
    if not want:
        return False
    raw = str(candidate or "").strip()
    if not raw:
        return False

    def _slug_ok(slug: str) -> bool:
        sf = fold_code(slug.split("?")[0].split("#")[0])
        if not sf:
            return False
        if sf == want:
            return True
        if mode == "exact":
            return False
        if not sf.startswith(want):
            return False
        rest = sf[len(want) :]
        # 数字续写 → 另一番号（ABF0051）；下划线/字母后缀可接受
        if rest[:1].isdigit():
            return False
        return True

    if _slug_ok(raw):
        return True
    try:
        path = urlparse(
            raw if "://" in raw else f"http://local{raw if raw.startswith('/') else '/' + raw}"
        ).path
    except Exception:  # noqa: BLE001
        path = raw
    parts = [p for p in str(path or "").split("/") if p]
    if parts and _slug_ok(parts[-1]):
        return True
    # MDCX: .../ABF005_xxx
    hay = fold_code(raw)
    return (want + "_") in hay


def pick_href_by_folded_code(
    candidates: list[str] | tuple[str, ...],
    code: str,
) -> str | None:
    """首个 path 折叠后命中番号的 href；无命中则 None（禁止 first-hit 兜底）。"""
    for href in candidates:
        h = str(href or "").strip()
        if not h:
            continue
        if folded_code_matches(h, code, mode="endswith"):
            return h
    return None


def page_mentions_code(html: str, code: str) -> bool:
    want = fold_code(code) or code_key(code)
    if not want:
        return False
    # 边界：避免 ABF005 ⊂ ABF0051；用非字母数字包围
    hay = fold_code(html)
    if want not in hay:
        return False
    for m in re.finditer(re.escape(want), hay):
        left = hay[m.start() - 1] if m.start() > 0 else ""
        right = hay[m.end()] if m.end() < len(hay) else ""
        if left.isalnum() or right.isdigit():
            continue
        return True
    return False


def std_code(raw: str) -> str:
    s = str(raw or "").strip().upper().replace("_", "-")
    if not s:
        return ""
    if "-" not in s:
        m = re.match(r"^([A-Z]{1,12})(\d{2,}[A-Z0-9-]*)$", s)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
    return s


def abs_url(href: str | None, base: str) -> str | None:
    u = str(href or "").strip()
    if not u:
        return None
    if u.startswith(("http://", "https://")):
        return u
    if u.startswith("//"):
        return f"https:{u}"
    try:
        root = base if base.endswith("/") else base + "/"
        return urljoin(root, u)
    except Exception:
        b = base.rstrip("/")
        return f"{b}{u if u.startswith('/') else '/' + u}"


def clean_title(raw: str, code: str) -> str:
    t = strip_tags(raw)
    if code:
        t = re.sub(rf"\b{re.escape(code)}\b", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def is_junk_title(s: str) -> bool:
    t = str(s or "").strip()
    if not t or len(t) < 2:
        return True
    return bool(re.match(r"^(undefined|null|n/a|unknown|untitled)$", t, re.I))


def is_junk_cover_url(url: str) -> bool:
    return bool(re.search(r"/(?:logo|icon|avatar|placeholder|1x1|blank)\.", url, re.I))


def collect_by_re(html: str, pattern: str | re.Pattern[str]) -> list[str]:
    out: list[str] = []
    for m in re.finditer(pattern, html or ""):
        if not m.lastindex:
            continue
        val = strip_tags(m.group(1) or "")
        if val and val not in out:
            out.append(val)
    return out


def pick_og_image(html: str) -> str | None:
    m = re.search(
        r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.I,
    ) or re.search(
        r'content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
        html,
        re.I,
    )
    return m.group(1) if m else None


def pick_og_title(html: str) -> str:
    m = re.search(
        r'property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.I,
    ) or re.search(
        r'content=["\']([^"\']+)["\']\s+property=["\']og:title["\']',
        html,
        re.I,
    )
    return strip_tags(m.group(1)) if m else ""


def year_from(s: str | None) -> str | None:
    m = re.search(r"(20\d{2}|19\d{2})", str(s or ""))
    return m.group(1) if m else None


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "lxml")


def make_detail(
    *,
    source: str,
    code: str,
    title: str | None = None,
    poster: str | None = None,
    studio: str | None = None,
    actors: list[str] | None = None,
    tags: list[str] | None = None,
    overview: str | None = None,
    date: str | None = None,
    year: str | None = None,
    extra: dict[str, Any] | None = None,
) -> DetailDict:
    code_s = std_code(code) or str(code or "").strip().upper()
    title_s = clean_title(title or "", code_s) if title else ""
    if is_junk_title(title_s):
        title_s = ""
    poster_s = str(poster or "").strip() or None
    if poster_s and is_junk_cover_url(poster_s):
        poster_s = None
    actors_l = [a for a in (actors or []) if str(a).strip()]
    tags_l = [t for t in (tags or []) if str(t).strip()]
    out: DetailDict = {
        "source": source,
        "provider": source,
        "id": code_s,
        "code": code_s,
        "title": title_s or code_s,
        "posterUrl": poster_s,
        "studio": (studio or "").strip() or None,
        "maker": (studio or "").strip() or None,
        "actors": actors_l[:20],
        "tags": tags_l[:40],
        "overview": (overview or "").strip() or None,
        "date": (date or "").strip()[:10] or None,
        "year": year or year_from(date),
    }
    if extra:
        out.update(extra)
    # directors ↔ director 归一（DMM/avbase 等只给数组，javbus/NFO 读单数字段）
    dir_s = str(out.get("director") or "").strip()
    dirs_raw = out.get("directors")
    dir_names: list[str] = []
    if isinstance(dirs_raw, list):
        for d in dirs_raw:
            if isinstance(d, dict):
                n = str(d.get("name") or "").strip()
            else:
                n = str(d or "").strip()
            if n and n not in dir_names:
                dir_names.append(n)
    if not dir_s and dir_names:
        out["director"] = dir_names[0]
    elif dir_s and not dir_names:
        out["directors"] = [dir_s]
    return out


def _page_fetch(
    url: str,
    *,
    referer: str | None = None,
    cookie: str | None = None,
    source_id: str | None = None,
    access: str | None = None,
    fast: bool = False,
):
    from .. import makers_settings
    from ..outbound_http import fetch_page, looks_blocked_html

    sid = source_id
    # 与数据源测链一致：优先调用方传入 / 目录 access，再回退 makers
    mode = str(access or "").strip()
    if not mode:
        try:
            from .. import scrape_sources_settings as scrape_src

            if sid:
                mode = scrape_src.catalog_access(sid)
        except Exception:
            mode = ""
    if not mode:
        mode = makers_settings.provider_access(sid) if sid else "proxy_adaptive"
    page = fetch_page(
        url,
        referer=referer,
        cookie=cookie or None,
        access=mode,
        timeout=12.0 if fast else 28.0,
        source_id=sid,
    )
    text = page.html or ""
    if len(text) < 200:
        raise RuntimeError("页面过短")
    if looks_blocked_html(text) and len(text) < 12000:
        raise RuntimeError("站点盾拦截")
    return page


def fetch_html(
    url: str,
    *,
    referer: str | None = None,
    cookie: str | None = None,
    source_id: str | None = None,
    access: str | None = None,
    fast: bool = False,
) -> str:
    """走与数据源测链相同的出站拉页（代理 / access / Cookie）。"""
    return (
        _page_fetch(
            url,
            referer=referer,
            cookie=cookie,
            source_id=source_id,
            access=access,
            fast=fast,
        ).html
        or ""
    )


def fetch_html_result(
    url: str,
    *,
    referer: str | None = None,
    cookie: str | None = None,
    source_id: str | None = None,
    access: str | None = None,
    fast: bool = False,
) -> tuple[str, str]:
    """返回 (html, final_url)。"""
    page = _page_fetch(
        url,
        referer=referer,
        cookie=cookie,
        source_id=source_id,
        access=access,
        fast=fast,
    )
    return page.html or "", page.final_url or url


def fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    cookie: str | None = None,
    source_id: str | None = None,
    referer: str | None = None,
) -> Any:
    import json as _json

    from ..outbound_http import curl_request, resolve_scrape_proxy_url

    hdrs = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        **(headers or {}),
    }
    if cookie:
        hdrs["Cookie"] = cookie
    if referer:
        hdrs["Referer"] = referer
    elif source_id:
        try:
            site = prepare_provider_site(source_id)
            hdrs.setdefault("Referer", site["baseUrl"].rstrip("/") + "/")
        except Exception:
            pass
    proxy = resolve_scrape_proxy_url()
    r = curl_request(
        "GET",
        url,
        headers=hdrs,
        timeout=28.0,
        verify=False,
        proxy=proxy,
        use_panel_proxy=True,
    )
    text = (getattr(r, "text", None) or "").strip()
    if not text:
        raise RuntimeError("empty json")
    return _json.loads(text)


def fetch_post_form(
    url: str,
    body: str,
    *,
    referer: str | None = None,
    cookie: str | None = None,
    source_id: str | None = None,
    timeout: float = 20.0,
) -> str:
    """对齐 MDCS fetchPostForm：面板代理 + Cookie（不支持强制 Flare）。"""
    from ..outbound_http import looks_blocked_html, resolve_scrape_proxy_url

    access = ""
    if source_id:
        try:
            from .. import scrape_sources_settings as scrape_src

            access = scrape_src.catalog_access(source_id)
        except Exception:
            access = ""
    if access == "proxy_flare":
        raise RuntimeError("fetchPostForm 不支持 proxy_flare")

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
    }
    if referer:
        headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie

    proxy = resolve_scrape_proxy_url()
    try:
        from curl_cffi import requests as creq

        kwargs: dict[str, Any] = {
            "headers": headers,
            "data": body,
            "timeout": timeout,
            "allow_redirects": True,
            "verify": False,
            "impersonate": "chrome124",
        }
        if proxy:
            kwargs["proxy"] = proxy
        r = creq.post(url, **kwargs)
        text = str(getattr(r, "text", "") or "")
        if int(getattr(r, "status_code", 500) or 500) < 400 and len(text) > 200:
            if not looks_blocked_html(text):
                return text
    except Exception:
        pass

    try:
        import httpx

        opts: dict[str, Any] = {
            "timeout": timeout,
            "follow_redirects": True,
            "verify": False,
            "trust_env": False,
        }
        if proxy:
            opts["proxy"] = proxy
        with httpx.Client(**opts) as client:
            r2 = client.post(url, content=body, headers=headers)
        text = r2.text or ""
        if r2.status_code < 400 and len(text) > 200 and not looks_blocked_html(text):
            return text
    except Exception:
        pass

    raise RuntimeError(f"HTTP POST 失败 {url}")


_last_provider_hit: dict[str, float] = {}


def respect_provider_cooldown(source_id: str, cooldown_sec: float = 0) -> None:
    """对齐 MDCS respectProviderCooldown。"""
    import time

    sid = str(source_id or "").strip().lower()
    sec = float(cooldown_sec or 0)
    if not sid or sec <= 0:
        return
    last = _last_provider_hit.get(sid) or 0.0
    wait = last + sec - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_provider_hit[sid] = time.time()


def prepare_provider_site(
    source_id: str, *, fallback_base: str = ""
) -> dict[str, Any]:
    """对齐 MDCS prepareProviderFetch：baseUrl / cookie / access / 冷却。"""
    from .. import scrape_source_catalog as catalog
    from .. import scrape_sources_settings as scrape_src

    sid = catalog.canonicalize_id(source_id)
    meta = catalog.catalog_by_id().get(sid) or {}
    cooldown = float(meta.get("defaultCooldownSec") or 0)
    try:
        cfg = scrape_src.provider_settings(sid)
        if cfg.get("cooldownSec") is not None:
            cooldown = float(cfg.get("cooldownSec") or cooldown)
    except Exception:
        pass
    respect_provider_cooldown(sid, cooldown)

    try:
        ctx = scrape_src.resolve_fetch_context(sid)
        return {
            "id": sid,
            "baseUrl": str(ctx.get("baseUrl") or fallback_base or "").rstrip("/"),
            "cookie": str(ctx.get("cookie") or ""),
            "apiKey": str(ctx.get("apiKey") or ""),
            "access": str(ctx.get("access") or "proxy_adaptive"),
            "label": str(ctx.get("label") or sid),
        }
    except Exception:
        base = (
            scrape_src.effective_display_url(sid)
            or str(fallback_base or meta.get("defaultUrl") or "")
        ).rstrip("/")
        cfg = scrape_src.provider_settings(sid)
        return {
            "id": sid,
            "baseUrl": base,
            "cookie": str(cfg.get("cookie") or meta.get("defaultCookie") or ""),
            "apiKey": str(cfg.get("apiKey") or ""),
            "access": scrape_src.catalog_access(sid),
            "label": str(meta.get("label") or sid),
        }


def origin_of(base: str) -> str:
    try:
        u = urlparse(base)
        if u.scheme and u.netloc:
            return f"{u.scheme}://{u.netloc}"
    except Exception:
        pass
    return str(base or "").rstrip("/")
