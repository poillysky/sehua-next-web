"""片商额外目录源：7MMTV / Madou（可直连，补全空分类）。"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

import app.makers.settings as makers_settings
import app.core.site_mirror as site_mirror
from app.makers.urls import join_url as _abs

log = logging.getLogger(__name__)

_CODE_RE = re.compile(r"\b([A-Z]{2,10}-\d{2,5})\b", re.I)
_MD_CODE_RE = re.compile(r"\b(MD[-_]?\d{2,5}|MKY[-_]?\d{2,5}|JDSY[-_]?\d{2,5})\b", re.I)


def _origin(raw: str) -> str:
    return site_mirror.origin(raw)


# _abs 已由文件顶部的 `from app.makers.urls import join_url as _abs` 直接绑定
# （原与 makers/catalog_routes.py 各写一份逐字节相同的实现，已收敛）


def _year_from(s: str | None) -> str | None:
    m = re.search(r"(20\d{2}|19\d{2})", str(s or ""))
    return m.group(1) if m else None


def _item(
    *,
    source: str,
    id_: str,
    title: str,
    code: str | None = None,
    poster: str | None = None,
    year: str | None = None,
    date: str | None = None,
    overview: str | None = None,
    actors: list[str] | None = None,
) -> dict[str, Any]:
    code_s = (code or "").strip().upper() or None
    title_s = (title or code_s or id_).strip()
    return {
        "source": source,
        "provider": source,
        "id": id_,
        "code": code_s,
        "title": title_s,
        "originalTitle": code_s,
        "posterUrl": poster,
        "year": year,
        "date": date,
        "studio": None,
        "actors": actors or [],
        "tags": [],
        "overview": overview,
    }


# —— 7MMTV ——

def sevenmm_bases() -> list[str]:
    ordered = site_mirror.ordered_bases("7mmtv", makers_settings.sevenmm_seeds())
    return ordered or list(makers_settings.DEFAULT_SEVENMM_SEEDS)


def sevenmm_base() -> str:
    bases = sevenmm_bases()
    return bases[0] if bases else makers_settings.DEFAULT_SEVENMM_SEEDS[0]


def _sevenmm_zh_root(base: str) -> str:
    o = _origin(base) or base.rstrip("/")
    return f"{o}/zh"


def parse_sevenmm_list(html: str, base: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    by_id: dict[str, dict[str, Any]] = {}
    for a in soup.select("a.video-preview, a.video-title"):
        href = a.get("href") or ""
        if not re.search(r"_content/\d+/", href, re.I):
            continue
        url = _abs(base, href)
        if not url:
            continue
        # id: censored_content/205647/DAZD-306
        path = urlparse(url).path
        m = re.search(r"/zh/(.+?)\.html?$", path, re.I)
        id_ = (m.group(1) if m else path.strip("/")).strip("/")
        if not id_:
            continue
        row = by_id.get(id_) or {
            "id": id_,
            "title": "",
            "poster": None,
            "code": None,
        }
        if "video-preview" in (a.get("class") or []):
            img = a.select_one("img")
            if img:
                row["poster"] = _abs(
                    base,
                    img.get("data-src")
                    or img.get("data-original")
                    or img.get("src"),
                )
        else:
            title = a.get_text(" ", strip=True)
            if title:
                row["title"] = title
                cm = _CODE_RE.search(title)
                if cm:
                    row["code"] = cm.group(1).upper()
                else:
                    # filename in URL often holds code
                    tail = id_.rsplit("/", 1)[-1]
                    cm2 = _CODE_RE.search(tail.replace("_", "-"))
                    if cm2:
                        row["code"] = cm2.group(1).upper()
        by_id[id_] = row

    out: list[dict[str, Any]] = []
    for row in by_id.values():
        title = row["title"] or row.get("code") or row["id"]
        out.append(
            _item(
                source="7mmtv",
                id_=row["id"],
                title=title,
                code=row.get("code"),
                poster=row.get("poster"),
            )
        )
    return out


def sevenmm_list_by_path(
    list_path: str,
    page: int,
    *,
    fetch_html,
) -> dict[str, Any]:
    """list_path 形如 /zh/censored_list/all/{page}.html （{page} 可替换）。"""
    p = max(1, page)
    raw = (list_path or "").strip()
    if "{page}" in raw:
        path = raw.replace("{page}", str(p))
    else:
        # .../all/1.html → 翻页
        path = re.sub(r"/(\d+)\.html?$", f"/{p}.html", raw, flags=re.I)
        if path == raw and not raw.endswith(".html"):
            path = raw.rstrip("/") + f"/{p}.html"

    items: list[dict[str, Any]] = []
    used = sevenmm_base()
    last_err: Exception | None = None
    for base in sevenmm_bases():
        try:
            root = _sevenmm_zh_root(base)
            # path 可能已含 /zh
            if path.startswith("/zh/"):
                url = f"{_origin(base)}{path}"
            elif path.startswith("http"):
                url = path
            else:
                url = f"{root}/{path.lstrip('/')}"
            html = fetch_html(url, referer=f"{root}/")
            items = parse_sevenmm_list(html, _origin(base) or base)
            used = _origin(base) or base
            if items:
                site_mirror.remember("7mmtv", used, discovered_from=used)
                break
        except Exception as e:
            last_err = e
            log.warning("7mmtv list %s @ %s: %s", path, base, e)
    return {
        "items": items,
        "base": used,
        "page": p,
        "totalPages": p + (1 if len(items) >= 18 else 0),
        "error": str(last_err) if last_err and not items else None,
    }


def sevenmm_detail(item_id: str, *, fetch_html) -> dict[str, Any]:
    rid = (item_id or "").strip().lstrip("/")
    if rid.endswith(".html"):
        rid = rid[: -len(".html")]
    if not rid:
        raise ValueError("无效 id")

    last_err: Exception | None = None
    for base in sevenmm_bases():
        try:
            o = _origin(base) or base
            if rid.startswith("http"):
                url = rid if rid.endswith(".html") else f"{rid}.html"
            elif "/" in rid:
                url = f"{o}/zh/{rid}.html"
            else:
                # 仅番号：走内容搜索页失败时尝试常见栏目（详情直链未知）
                url = f"{o}/zh/censored_content/0/{rid}.html"
            html = fetch_html(url, referer=f"{o}/zh/")
            soup = BeautifulSoup(html, "lxml")
            title = ""
            h = soup.select_one("h1, .video-title, .content-title, title")
            if h:
                title = h.get_text(" ", strip=True)
                title = re.sub(r"\s*[-|｜].*7mm.*$", "", title, flags=re.I).strip()
            og = soup.select_one('meta[property="og:image"]')
            poster = _abs(o, og.get("content") if og else None)
            if not poster:
                img = soup.select_one(".video-preview img, .content img, img.img-fluid")
                if img:
                    poster = _abs(
                        o,
                        img.get("data-src") or img.get("src"),
                    )
            code = None
            cm = _CODE_RE.search(title) or _CODE_RE.search(rid)
            if cm:
                code = cm.group(1).upper()
            overview = ""
            desc = soup.select_one('meta[property="og:description"], meta[name="description"]')
            if desc:
                overview = (desc.get("content") or "").strip()
            actors: list[str] = []
            for a in soup.select("a[href*='actress'], a[href*='star'], .actress a"):
                n = a.get_text(strip=True)
                if n and 1 < len(n) < 40 and n not in actors:
                    actors.append(n)
            if not title and not poster:
                raise RuntimeError("详情页无有效内容")
            site_mirror.remember("7mmtv", o, discovered_from=o)
            return _item(
                source="7mmtv",
                id_=rid,
                title=title or code or rid,
                code=code,
                poster=poster,
                overview=overview or None,
                actors=actors[:20],
            )
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"7mmtv 详情失败: {last_err}")


# —— Madou ——

def madou_bases() -> list[str]:
    ordered = site_mirror.ordered_bases("madou", makers_settings.madou_seeds())
    return ordered or list(makers_settings.DEFAULT_MADOU_SEEDS)


def madou_base() -> str:
    bases = madou_bases()
    return bases[0] if bases else makers_settings.DEFAULT_MADOU_SEEDS[0]


def parse_madou_list(html: str, base: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for art in soup.select("article"):
        a = art.select_one("a[href]")
        if not a:
            continue
        href = a.get("href") or ""
        url = _abs(base, href)
        if not url or "/category/" in url:
            continue
        path = urlparse(url).path.strip("/")
        if not path or path in seen:
            continue
        h = art.select_one("h2, h3, .entry-title, .post-title")
        title = (h.get_text(strip=True) if h else a.get_text(strip=True)) or path
        img = art.select_one("img")
        poster = None
        if img:
            poster = _abs(
                base,
                img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("src"),
            )
        code = None
        cm = _MD_CODE_RE.search(title) or _CODE_RE.search(title) or _MD_CODE_RE.search(path)
        if cm:
            code = cm.group(1).upper().replace("_", "-")
            if re.match(r"^MD\d", code):
                code = "MD-" + code[2:]
        seen.add(path)
        out.append(
            _item(
                source="madou",
                id_=path,
                title=title,
                code=code,
                poster=poster,
            )
        )
    return out


def madou_list_by_path(
    list_path: str,
    page: int,
    *,
    fetch_html,
) -> dict[str, Any]:
    p = max(1, page)
    raw = (list_path or "/").strip() or "/"
    items: list[dict[str, Any]] = []
    used = madou_base()
    last_err: Exception | None = None
    for base in madou_bases():
        try:
            o = _origin(base) or base
            if raw in ("/", ""):
                url = f"{o}/" if p <= 1 else f"{o}/page/{p}/"
            elif "{page}" in raw:
                url = f"{o}{raw.replace('{page}', str(p))}"
            elif p > 1:
                url = f"{o}{raw.rstrip('/')}/page/{p}/"
            else:
                url = f"{o}{raw}"
            html = fetch_html(url, referer=f"{o}/")
            items = parse_madou_list(html, o)
            used = o
            if items:
                site_mirror.remember("madou", o, discovered_from=o)
                break
        except Exception as e:
            last_err = e
            log.warning("madou list @ %s: %s", base, e)
    return {
        "items": items,
        "base": used,
        "page": p,
        "totalPages": p + (1 if len(items) >= 12 else 0),
        "error": str(last_err) if last_err and not items else None,
    }


def madou_detail(item_id: str, *, fetch_html) -> dict[str, Any]:
    rid = (item_id or "").strip().lstrip("/")
    if not rid:
        raise ValueError("无效 id")
    last_err: Exception | None = None
    for base in madou_bases():
        try:
            o = _origin(base) or base
            url = rid if rid.startswith("http") else f"{o}/{rid}"
            if not url.endswith(".html") and "/" in rid and not rid.startswith("http"):
                # slug may already include .html encoding
                pass
            html = fetch_html(url if url.endswith("/") or url.endswith(".html") else url, referer=f"{o}/")
            soup = BeautifulSoup(html, "lxml")
            title = ""
            h = soup.select_one("h1.entry-title, h1, .entry-title, title")
            if h:
                title = h.get_text(" ", strip=True)
                title = re.sub(r"\s*[-|｜].*麻豆.*$", "", title, flags=re.I).strip()
            og = soup.select_one('meta[property="og:image"]')
            poster = _abs(o, og.get("content") if og else None)
            if not poster:
                img = soup.select_one(".entry-content img, article img, .post img")
                if img:
                    poster = _abs(o, img.get("data-src") or img.get("src"))
            code = None
            cm = _MD_CODE_RE.search(title or "") or _MD_CODE_RE.search(rid)
            if cm:
                code = cm.group(1).upper().replace("_", "-")
                if re.match(r"^MD\d", code):
                    code = "MD-" + code[2:]
            overview = ""
            desc = soup.select_one('meta[property="og:description"], meta[name="description"]')
            if desc:
                overview = (desc.get("content") or "").strip()
            if not title and not poster:
                raise RuntimeError("详情页无有效内容")
            site_mirror.remember("madou", o, discovered_from=o)
            return _item(
                source="madou",
                id_=rid,
                title=title or code or rid,
                code=code,
                poster=poster,
                overview=overview or None,
            )
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"madou 详情失败: {last_err}")


def looks_sevenmm(html: str) -> bool:
    """必须能解析出真实作品链，空壳/关键词页不算。"""
    return site_mirror._looks_sevenmm(html)


def looks_madou(html: str) -> bool:
    """必须有真实文章列表。"""
    return site_mirror._looks_madou(html)


# —— MissAV（proxy_adaptive） ——

_MISSAV_SKIP_RE = re.compile(
    r"/(search|genres?|makers?|actresses?|directors?|studios?|labels?|series|lists?|"
    r"login|register|page|tags?|type|filter)/",
    re.I,
)
_MISSAV_DETAIL_RE = re.compile(
    r"/(?:dm\d+/)?cn/([a-z0-9][a-z0-9-]{2,80})/?$",
    re.I,
)
_MISSAV_SUFFIX_RE = re.compile(
    r"-(?:uncensored-leak|uncensored|chinese-subtitle|english-subtitle|chinese|english)$",
    re.I,
)


def missav_bases() -> list[str]:
    ordered = site_mirror.ordered_bases("missav", makers_settings.missav_seeds())
    return ordered or list(makers_settings.DEFAULT_MISSAV_SEEDS)


def missav_base() -> str:
    bases = missav_bases()
    return bases[0] if bases else makers_settings.DEFAULT_MISSAV_SEEDS[0]


def _missav_cn_root(base: str) -> str:
    o = _origin(base) or base.rstrip("/")
    return f"{o}/cn"


def _missav_slug_to_code(slug: str) -> str | None:
    s = (slug or "").strip()
    if not s:
        return None
    s = _MISSAV_SUFFIX_RE.sub("", s)
    # sone-001 → SONE-001；fc2-ppv-1234567 → FC2-PPV-1234567
    if re.match(r"^fc2[-_]?ppv[-_]?\d+", s, re.I):
        digits = re.sub(r"\D", "", s)
        return f"FC2-PPV-{digits}" if digits else None
    m = re.match(r"^([a-z]+)[-_]?(\d+)$", s, re.I)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}"
    cm = _CODE_RE.search(s.replace("_", "-").upper())
    return cm.group(1).upper() if cm else None


def parse_missav_list(html: str, base: str) -> list[dict[str, Any]]:
    if re.search(r"just a moment|attention required", html or "", re.I):
        return []
    soup = BeautifulSoup(html, "lxml")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if _MISSAV_SKIP_RE.search(href):
            continue
        m = _MISSAV_DETAIL_RE.search(href.split("?")[0])
        if not m:
            continue
        slug = m.group(1)
        if slug.lower() in {
            "new",
            "release",
            "uncensored-leak",
            "uncensored",
            "fc2",
            "chinese-av",
            "madou",
            "chinese-subtitle",
            "today",
            "weekly",
            "monthly",
        }:
            continue
        if slug in seen:
            continue
        url = _abs(base, href)
        if not url:
            continue
        img = a.select_one("img")
        poster = None
        title = a.get_text(" ", strip=True)
        if img:
            poster = _abs(
                base,
                img.get("data-src")
                or img.get("data-original")
                or img.get("src"),
            )
            if not title:
                title = (img.get("alt") or img.get("title") or "").strip()
        code = _missav_slug_to_code(slug)
        if not title:
            title = code or slug
        seen.add(slug)
        out.append(
            _item(
                source="missav",
                id_=slug,
                title=title,
                code=code,
                poster=poster,
            )
        )
    return out


def missav_list_by_path(
    list_path: str,
    page: int,
    *,
    fetch_html,
) -> dict[str, Any]:
    """list_path 相对 /cn，如 /new、/uncensored-leak、/fc2。"""
    p = max(1, page)
    raw = (list_path or "").strip()
    if raw in ("", "/"):
        path = "/cn"
    elif raw.startswith("/cn"):
        path = raw
    else:
        path = "/cn" + (raw if raw.startswith("/") else f"/{raw}")

    items: list[dict[str, Any]] = []
    used = missav_base()
    last_err: Exception | None = None
    for base in missav_bases():
        try:
            o = _origin(base) or base
            url = f"{o}{path}"
            if p > 1:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}page={p}"
            html = fetch_html(url, referer=f"{o}/cn/")
            if re.search(r"just a moment|attention required", html or "", re.I):
                last_err = RuntimeError("CF 盾拦截（代理自适应未过）")
                continue
            items = parse_missav_list(html, o)
            used = o
            if items:
                site_mirror.remember("missav", o, discovered_from=o)
                break
        except Exception as e:
            last_err = e
            log.warning("missav list %s @ %s: %s", path, base, e)
    return {
        "items": items,
        "base": used,
        "page": p,
        "totalPages": p + (1 if len(items) >= 12 else 0),
        "error": str(last_err) if last_err and not items else None,
    }


def missav_detail(item_id: str, *, fetch_html) -> dict[str, Any]:
    rid = (item_id or "").strip().lstrip("/")
    if rid.startswith("cn/"):
        rid = rid[3:]
    if not rid:
        raise ValueError("无效 id")
    last_err: Exception | None = None
    for base in missav_bases():
        try:
            o = _origin(base) or base
            # 优先直链 /cn/{slug}，再试搜索
            candidates = [
                f"{o}/cn/{quote(rid)}",
                f"{o}/cn/search/{quote(rid)}",
            ]
            # 若是番号，再试 compact
            code = _missav_slug_to_code(rid) or rid.upper()
            compact = re.sub(r"[^A-Z0-9]", "", code.upper())
            if compact and compact.lower() != rid.lower():
                candidates.insert(1, f"{o}/cn/{quote(compact.lower())}")
            html = ""
            final_url = candidates[0]
            for url in candidates:
                try:
                    html = fetch_html(url, referer=f"{o}/cn/")
                    if re.search(r"just a moment|attention required", html or "", re.I):
                        last_err = RuntimeError("CF 盾拦截（代理自适应未过）")
                        html = ""
                        continue
                    if html and len(html) > 2000:
                        final_url = url
                        # 搜索页挑详情
                        if "/search/" in url:
                            hrefs = re.findall(
                                r'href=["\']([^"\']+/cn/[^"\'#?]+)["\']',
                                html,
                                re.I,
                            )
                            pick = ""
                            want = code.lower().replace("-", "")
                            for h in hrefs:
                                slug = h.rstrip("/").split("/")[-1].lower()
                                if _MISSAV_SKIP_RE.search(h):
                                    continue
                                if want and (
                                    slug == want
                                    or slug.replace("-", "") == want
                                    or slug.startswith(want)
                                ):
                                    pick = h
                                    break
                            if pick:
                                detail = _abs(o, pick) or pick
                                html = fetch_html(detail, referer=url)
                                final_url = detail
                        break
                except Exception as e:
                    last_err = e
                    continue
            if not html or len(html) < 2000:
                raise RuntimeError(last_err or "详情页无响应")
            soup = BeautifulSoup(html, "lxml")
            title = ""
            h = soup.select_one("h1.text-base, h1")
            if h:
                title = h.get_text(" ", strip=True)
            og = soup.select_one('meta[property="og:image"]')
            poster = _abs(o, og.get("content") if og else None)
            overview = ""
            desc = soup.select_one(
                'meta[property="og:description"], meta[name="description"]'
            )
            if desc:
                overview = (desc.get("content") or "").strip()
            actors: list[str] = []
            for a in soup.select("a.text-nord13, a[href*='/actresses/']"):
                n = a.get_text(strip=True)
                n = re.sub(r"\s*\([^)]*\)\s*$", "", n).strip()
                if n and 1 < len(n) < 40 and n not in actors:
                    actors.append(n)
            code_out = _missav_slug_to_code(rid)
            if not code_out and title:
                cm = _CODE_RE.search(title)
                if cm:
                    code_out = cm.group(1).upper()
            if not title and not poster:
                raise RuntimeError("详情页无有效内容")
            site_mirror.remember("missav", o, discovered_from=o)
            return _item(
                source="missav",
                id_=rid,
                title=title or code_out or rid,
                code=code_out,
                poster=poster,
                overview=overview or None,
                actors=actors[:20],
            )
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"missav 详情失败: {last_err}")


def looks_missav(html: str) -> bool:
    """必须有真实详情 slug 列表，非 CF/空壳。"""
    return site_mirror._looks_missav(html)
