"""片商目录：JavBus / iQQTV 榜单·搜索·详情（对齐影视页交互）。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Query

from app.core.db import data_dir
import app.makers.settings as makers_settings
import app.makers.providers_extra as makers_extra
import app.core.site_mirror as site_mirror
from app.core.outbound_http import fetch_page, looks_blocked_html
from app.core.ttl_cache import cache_get as _cache_get_ttl
from app.core.ttl_cache import enforce_max, prune_by_expiry
from app.core.year_utils import year_search as _year_from
from app.makers.urls import join_url as _abs

log = logging.getLogger(__name__)

router = APIRouter(tags=["makers-catalog"])

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
_TIMEOUT = httpx.Timeout(12.0, connect=4.0)
_TIMEOUT_FAST = httpx.Timeout(8.0, connect=3.0)

_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 2 * 3600
_CACHE_MAX = 256

SOURCES = (
    {"id": "javbus", "label": "JavBus"},
    {"id": "iqqtv", "label": "iQQTV"},
    {"id": "missav", "label": "MissAV"},
    {"id": "7mmtv", "label": "7MMTV"},
    {"id": "madou", "label": "Madou"},
)

# 六区（顶栏）；列表以 JavBus 实测可用路径为主（原写真并入有码）
KIND_ORDER = (
    "japan_censored",
    "japan_uncensored",
    "japan_amateur",
    "fc2",
    "china",
    "western",
)

KIND_LABELS: dict[str, str] = {
    "japan_censored": "有码",
    "japan_uncensored": "无码",
    "japan_amateur": "素人",
    "fc2": "FC2",
    "china": "国产",
    "western": "欧美",
}

# 仅保留与六区 100% 对应的官方栏目；一个站点一行
KIND_SHELVES: dict[str, list[dict[str, str]]] = {
    "japan_censored": [
        {"id": "javbus", "label": "JavBus", "provider": "javbus", "list": "/"},
        {
            "id": "missav",
            "label": "MissAV",
            "provider": "missav",
            "list": "/new",
        },
        {
            "id": "7mmtv",
            "label": "7MMTV",
            "provider": "7mmtv",
            "list": "/zh/censored_list/all/{page}.html",
        },
    ],
    "japan_uncensored": [
        {
            "id": "javbus",
            "label": "JavBus",
            "provider": "javbus",
            "list": "/uncensored",
        },
        {
            "id": "missav",
            "label": "MissAV",
            "provider": "missav",
            "list": "/uncensored-leak",
        },
        {
            "id": "7mmtv",
            "label": "7MMTV",
            "provider": "7mmtv",
            "list": "/zh/uncensored_list/all/{page}.html",
        },
    ],
    "japan_amateur": [
        {
            "id": "7mmtv",
            "label": "7MMTV",
            "provider": "7mmtv",
            "list": "/zh/amateurjav_list/all/{page}.html",
        },
    ],
    "fc2": [
        {
            "id": "missav",
            "label": "MissAV",
            "provider": "missav",
            "list": "/fc2",
        },
        {
            "id": "7mmtv",
            "label": "7MMTV",
            "provider": "7mmtv",
            "list": "/zh/uncensored_makersr/37/FC2/{page}.html",
        },
    ],
    "china": [
        {
            "id": "missav",
            "label": "MissAV",
            "provider": "missav",
            "list": "/chinese-av",
        },
        {
            "id": "7mmtv",
            "label": "7MMTV",
            "provider": "7mmtv",
            "list": "/zh/chinese_list/all/{page}.html",
        },
        {"id": "madou", "label": "Madou", "provider": "madou", "list": "/"},
    ],
    "western": [],
}

JAVBUS_CHARTS = (
    {"id": "latest", "label": "最新有码"},
    {"id": "uncensored", "label": "无码"},
    {"id": "hd", "label": "高清"},
    {"id": "4k", "label": "4K"},
    {"id": "sub", "label": "字幕"},
)

IQQTV_CHARTS = (
    {"id": "latest", "label": "最新"},
    {"id": "hot", "label": "热门"},
)


def _wrap(data: Any, message: str = "ok", status: int = 200) -> dict[str, Any]:
    return {"data": data, "message": message, "status": status}


def _cache_get(key: str) -> Any | None:
    return _cache_get_ttl(_cache, key)


def _cache_set(key: str, payload: Any, ttl: float = _CACHE_TTL) -> None:
    prune_by_expiry(_cache)
    _cache[key] = (time.time() + ttl, payload)
    enforce_max(_cache, _CACHE_MAX)


def _item(
    *,
    source: str,
    id_: str,
    title: str,
    code: str | None = None,
    poster: str | None = None,
    year: str | None = None,
    date: str | None = None,
    studio: str | None = None,
    actors: list[str] | None = None,
    tags: list[str] | None = None,
    overview: str | None = None,
    kind: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    code_s = (code or id_ or "").strip().upper()
    title_s = (title or code_s or id_).strip()
    return {
        "source": source,
        "kind": kind or source,
        "provider": provider or source,
        "id": id_,
        "code": code_s or None,
        "title": title_s,
        "originalTitle": code_s or None,
        "posterUrl": poster,
        "year": year,
        "date": date,
        "studio": studio,
        "actors": actors or [],
        "tags": tags or [],
        "overview": overview,
    }


def _clear_makers_cache(*, wipe_mirrors: bool = False) -> None:
    """清列表缓存。默认保留全局落地镜像，避免设置页又退回种子站。"""
    _cache.clear()
    if not wipe_mirrors:
        return
    try:
        site_mirror.invalidate("javbus")
        site_mirror.invalidate("iqqtv")
        site_mirror.invalidate("missav")
        site_mirror.invalidate("7mmtv")
        site_mirror.invalidate("madou")
    except Exception:
        pass
    from app.core.db import iqqtv_mirror_legacy_path

    for path in (iqqtv_mirror_legacy_path(), data_dir() / "iqqtv-mirror.json"):
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
    try:
        from app.core.outbound_http import clear_cached_clearance

        clear_cached_clearance()
    except Exception:
        pass


def _infer_source_id(host: str) -> str | None:
    h = (host or "").lower()
    if makers_settings.is_javbus_host(h):
        return "javbus"
    if "iqq" in h:
        return "iqqtv"
    if "missav" in h:
        return "missav"
    if "7mm" in h:
        return "7mmtv"
    if "madou" in h:
        return "madou"
    return None


def _fetch_html(url: str, *, referer: str | None = None, fast: bool = False) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    sid = _infer_source_id(host)
    # 与数据源测链一致
    try:
        import app.scrape.sources_settings as scrape_src

        access = (
            scrape_src.catalog_access(sid)
            if sid
            else makers_settings.provider_access(sid)
        )
    except Exception:
        access = makers_settings.provider_access(sid) if sid else "proxy_adaptive"
    # Cookie：javbus 用配置 Cookie；其它源也尝试数据源页 Cookie
    if makers_settings.is_javbus_host(host):
        cookie = makers_settings.javbus_cookie() or None
    elif sid:
        try:
            import app.scrape.sources_settings as scrape_src

            cookie = scrape_src.provider_settings(sid).get("cookie") or None
        except Exception:
            cookie = None
    else:
        cookie = None
    timeout = _TIMEOUT_FAST if fast else _TIMEOUT
    try:
        page = fetch_page(
            url,
            referer=referer,
            cookie=cookie,
            access=access,
            timeout=timeout,
            source_id=sid,
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"拉页失败: {e}",
        ) from e
    text = page.html or ""
    if len(text) < 200:
        raise HTTPException(status_code=502, detail="页面过短")
    if looks_blocked_html(text) and len(text) < 12000:
        raise HTTPException(
            status_code=502, detail="站点盾拦截，请检查代理或 FlareSolverr"
        )
    if makers_settings.is_javbus_host(host) and re.search(
        r"Age Verification|年齡驗證|年龄验证", text, re.I
    ) and not re.search(r"bigImage|movie-box", text, re.I):
        raise HTTPException(
            status_code=502,
            detail="需要年龄验证 Cookie（设置 → 片商管理）",
        )
    return text


# _abs 已由文件顶部的 `from app.makers.urls import join_url as _abs` 直接绑定
# （原与 makers/providers_extra.py 各写一份逐字节相同的实现，已收敛）


# —— JavBus ——

def _javbus_bases() -> tuple[str, ...]:
    """延迟最低的 activeBase 优先，再跟可用种子。"""
    ordered = site_mirror.ordered_bases("javbus", makers_settings.javbus_bases())
    return tuple(ordered) if ordered else makers_settings.DEFAULT_JAVBUS_BASES


def _javbus_base() -> str:
    bases = _javbus_bases()
    return bases[0] if bases else makers_settings.DEFAULT_JAVBUS_BASES[0]


def _remember_javbus(base: str) -> None:
    try:
        site_mirror.remember("javbus", base)
    except Exception:
        pass


def _parse_javbus_list(html: str, base: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in soup.select("a.movie-box"):
        href = a.get("href") or ""
        url = _abs(base, href)
        if not url:
            continue
        code = url.rstrip("/").rsplit("/", 1)[-1].strip().upper()
        if not code or code in seen:
            continue
        img = a.select_one("img")
        poster = None
        title = ""
        if img:
            poster = _abs(base, img.get("src") or img.get("data-src"))
            title = (img.get("title") or img.get("alt") or "").strip()
        info = a.select_one(".photo-info")
        date_s = ""
        if info:
            span = info.select_one("span")
            if span and not title:
                title = span.get_text(" ", strip=True)
            date_el = info.select_one("date")
            if date_el:
                date_s = date_el.get_text(strip=True)
            # photo-info 常为「番号\n日期」
            texts = [t.strip() for t in info.stripped_strings if t.strip()]
            if texts:
                if re.match(r"^[A-Z0-9]+-\d+", texts[0], re.I):
                    code = texts[0].upper()
                if len(texts) > 1 and re.match(r"\d{4}-\d{2}", texts[-1]):
                    date_s = texts[-1]
        if not title:
            title = code
        seen.add(code)
        out.append(
            _item(
                source="javbus",
                id_=code,
                title=title,
                code=code,
                poster=poster,
                year=_year_from(date_s),
                date=date_s or None,
            )
        )
    return out


def _javbus_paged_path(list_path: str, page: int) -> str:
    """把货架 list 路径翻成带页码的 JavBus URL path。"""
    p = max(1, page)
    raw = (list_path or "/").strip() or "/"
    if not raw.startswith("/"):
        raw = "/" + raw
    base = raw.rstrip("/") or ""
    if base.startswith("/search/"):
        # /search/素人 → /search/素人/2
        return f"{base}/{p}" if p > 1 else base
    if base.startswith("/genre/"):
        return f"{base}/{p}" if p > 1 else base
    if base == "/uncensored":
        return f"/uncensored/{p}" if p > 1 else "/uncensored"
    if base in ("", "/"):
        return f"/page/{p}" if p > 1 else "/"
    return f"{base}/{p}" if p > 1 else base


def _javbus_chart_path(chart: str, page: int) -> str:
    """兼容旧 chart id（javbus 源）。"""
    c = (chart or "latest").strip().lower()
    legacy = {
        "latest": "/",
        "uncensored": "/uncensored",
        "hd": "/genre/hd",
        "4k": "/genre/4k",
        "sub": "/genre/sub",
        "genre": "/genre/hd",
    }
    return _javbus_paged_path(legacy.get(c, "/"), page)


def _tag_kind_items(
    items: list[dict[str, Any]], *, kind: str, provider: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items:
        row = dict(it)
        row["kind"] = kind
        row["provider"] = provider
        row["source"] = kind  # 顶栏六区 id，前端当 source 用
        out.append(row)
    return out


def _javbus_list_by_path(
    list_path: str, page: int, *, kind: str, chart: str
) -> dict[str, Any]:
    path = _javbus_paged_path(list_path, page)
    # 路径中文番号关键词需百分号编码
    path_enc = "/".join(quote(seg, safe="") if seg else "" for seg in path.split("/"))
    key = f"javbus:list:{kind}:{chart}:{page}:{path}"
    hit = _cache_get(key)
    if hit is not None:
        return hit

    items: list[dict[str, Any]] = []
    used_base = _javbus_base()
    last_err: Exception | None = None
    for base in _javbus_bases():
        try:
            html = _fetch_html(f"{base}{path_enc}", referer=f"{base}/")
            items = _parse_javbus_list(html, base)
            used_base = base
            if items:
                _remember_javbus(base)
                break
        except Exception as e:
            last_err = e
            log.warning("javbus list %s @ %s: %s", path_enc, base, e)
            continue

    if not items and last_err is not None:
        detail = getattr(last_err, "detail", None) or str(last_err)
        raise HTTPException(status_code=502, detail=f"列表失败: {detail}") from last_err

    items = _tag_kind_items(items, kind=kind, provider="javbus")
    payload = {
        "source": kind,
        "kind": kind,
        "chart": chart,
        "page": page,
        "totalPages": page + (1 if len(items) >= 20 else 0),
        "items": items,
        "base": used_base,
    }
    _cache_set(key, payload)
    return payload


def _kind_charts(kind: str, chart: str, page: int) -> dict[str, Any]:
    shelves = KIND_SHELVES.get(kind) or []
    if not shelves:
        return {
            "source": kind,
            "kind": kind,
            "chart": chart or "latest",
            "page": page,
            "totalPages": 1,
            "items": [],
            "message": "暂无与该分类 100% 对应的站点栏目",
        }
    hit = next((s for s in shelves if s["id"] == chart), None)
    if hit is None:
        hit = shelves[0]
    provider = hit.get("provider") or "javbus"
    list_path = hit.get("list") or "/"
    chart_id = hit["id"]

    if provider == "javbus":
        return _javbus_list_by_path(list_path, page, kind=kind, chart=chart_id)

    if provider == "missav":
        if not makers_settings.missav_enabled():
            raise HTTPException(status_code=400, detail="MissAV 未启用")
        key = f"missav:list:{kind}:{chart_id}:{page}:{list_path}"
        cached = _cache_get(key)
        if cached is not None:
            return cached
        data = makers_extra.missav_list_by_path(
            list_path, page, fetch_html=_fetch_html
        )
        if data.get("error") and not data.get("items"):
            raise HTTPException(status_code=502, detail=f"列表失败: {data['error']}")
        items = _tag_kind_items(data.get("items") or [], kind=kind, provider="missav")
        payload = {
            "source": kind,
            "kind": kind,
            "chart": chart_id,
            "page": page,
            "totalPages": data.get("totalPages") or 1,
            "items": items,
            "base": data.get("base"),
        }
        _cache_set(key, payload)
        return payload

    if provider == "7mmtv":
        if not makers_settings.sevenmm_enabled():
            raise HTTPException(status_code=400, detail="7MMTV 未启用")
        key = f"7mmtv:list:{kind}:{chart_id}:{page}:{list_path}"
        cached = _cache_get(key)
        if cached is not None:
            return cached
        data = makers_extra.sevenmm_list_by_path(
            list_path, page, fetch_html=_fetch_html
        )
        if data.get("error") and not data.get("items"):
            raise HTTPException(status_code=502, detail=f"列表失败: {data['error']}")
        items = _tag_kind_items(data.get("items") or [], kind=kind, provider="7mmtv")
        payload = {
            "source": kind,
            "kind": kind,
            "chart": chart_id,
            "page": page,
            "totalPages": data.get("totalPages") or 1,
            "items": items,
            "base": data.get("base"),
        }
        _cache_set(key, payload)
        return payload

    if provider == "madou":
        if not makers_settings.madou_enabled():
            raise HTTPException(status_code=400, detail="Madou 未启用")
        key = f"madou:list:{kind}:{chart_id}:{page}:{list_path}"
        cached = _cache_get(key)
        if cached is not None:
            return cached
        data = makers_extra.madou_list_by_path(list_path, page, fetch_html=_fetch_html)
        if data.get("error") and not data.get("items"):
            raise HTTPException(status_code=502, detail=f"列表失败: {data['error']}")
        items = _tag_kind_items(data.get("items") or [], kind=kind, provider="madou")
        payload = {
            "source": kind,
            "kind": kind,
            "chart": chart_id,
            "page": page,
            "totalPages": data.get("totalPages") or 1,
            "items": items,
            "base": data.get("base"),
        }
        _cache_set(key, payload)
        return payload

    raise HTTPException(status_code=502, detail=f"暂不支持源 {provider}")


def _kind_search(kind: str, q: str, page: int) -> dict[str, Any]:
    # 六区搜索优先 JavBus；未启用时回落空
    if makers_settings.javbus_enabled():
        data = _javbus_search(q, page)
        items = _tag_kind_items(data.get("items") or [], kind=kind, provider="javbus")
        return {
            "source": kind,
            "kind": kind,
            "query": q,
            "page": page,
            "totalPages": data.get("totalPages") or 1,
            "items": items,
        }
    return {
        "source": kind,
        "kind": kind,
        "query": q,
        "page": page,
        "totalPages": 1,
        "items": [],
    }


def _kind_detail(kind: str, item_id: str) -> dict[str, Any]:
    rid = (item_id or "").strip()
    # 7mmtv 详情 id 含栏目路径
    if "/" in rid and "_content/" in rid:
        item = makers_extra.sevenmm_detail(rid, fetch_html=_fetch_html)
        return _tag_kind_items([item], kind=kind, provider="7mmtv")[0]
    # missav slug（小写连字符）
    if re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)+$", rid) and not re.match(
        r"^[A-Z0-9]+-\d+", rid
    ):
        try:
            item = makers_extra.missav_detail(rid, fetch_html=_fetch_html)
            return _tag_kind_items([item], kind=kind, provider="missav")[0]
        except Exception:
            pass
    # madou slug（无标准番号格式且非 javbus 风格）
    if "/" not in rid and not re.match(r"^[A-Z0-9]+-\d+", rid, re.I):
        # 可能是 madou URL 编码 slug
        if "%" in rid or re.search(r"[\u4e00-\u9fff]", rid):
            item = makers_extra.madou_detail(rid, fetch_html=_fetch_html)
            return _tag_kind_items([item], kind=kind, provider="madou")[0]
    # madou path with encoded segments
    if "%" in rid or (rid.endswith(".html") and "content/" not in rid):
        try:
            item = makers_extra.madou_detail(rid, fetch_html=_fetch_html)
            return _tag_kind_items([item], kind=kind, provider="madou")[0]
        except Exception:
            pass
    # 默认 JavBus 番号详情
    item = _javbus_detail(rid)
    tagged = _tag_kind_items([item], kind=kind, provider="javbus")[0]
    return tagged


def _javbus_charts(chart: str, page: int) -> dict[str, Any]:
    path = _javbus_chart_path(chart, page)
    # 反查 list 根路径
    list_root = path
    if "/page/" in path:
        list_root = "/"
    elif path.startswith("/uncensored"):
        list_root = "/uncensored"
    elif path.startswith("/genre/"):
        parts = path.strip("/").split("/")
        list_root = "/" + "/".join(parts[:2]) if len(parts) >= 2 else path
    elif path.startswith("/search/"):
        parts = path.strip("/").split("/")
        list_root = "/" + "/".join(parts[:2]) if len(parts) >= 2 else path
    return _javbus_list_by_path(list_root, page, kind="javbus", chart=chart)

def _javbus_search(q: str, page: int) -> dict[str, Any]:
    q = q.strip()
    key = f"javbus:search:{q.lower()}:{page}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    enc = quote(q)
    path = f"/search/{enc}/{page}" if page > 1 else f"/search/{enc}"
    items: list[dict[str, Any]] = []
    used_base = _javbus_base()
    last_err: Exception | None = None
    for base in _javbus_bases():
        try:
            html = _fetch_html(f"{base}{path}", referer=f"{base}/")
            items = _parse_javbus_list(html, base)
            used_base = base
            if items:
                _remember_javbus(base)
                break
        except Exception as e:
            last_err = e
            log.warning("javbus search @ %s: %s", base, e)
    if not items and last_err is not None:
        raise HTTPException(status_code=502, detail=f"搜索失败: {last_err}") from last_err
    payload = {
        "source": "javbus",
        "query": q,
        "page": page,
        "totalPages": page + (1 if len(items) >= 20 else 0),
        "items": items,
        "base": used_base,
    }
    _cache_set(key, payload, ttl=1800)
    return payload


def _javbus_star(star_id: str, page: int) -> dict[str, Any]:
    """女优作品列表 /star/{id}。"""
    sid = re.sub(r"[^A-Za-z0-9_\-]", "", (star_id or "").strip())
    if not sid:
        raise HTTPException(status_code=400, detail="无效女优 id")
    p = max(1, page)
    key = f"javbus:star:v1:{sid}:{p}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    path = f"/star/{sid}/{p}" if p > 1 else f"/star/{sid}"
    last_err: Exception | None = None
    items: list[dict[str, Any]] = []
    for root in _javbus_bases():
        try:
            html = _fetch_html(f"{root}{path}", referer=f"{root}/")
            items = _parse_javbus_list(html, root)
            if items:
                _remember_javbus(root)
                break
        except Exception as e:
            last_err = e
            log.warning("javbus star %s @ %s: %s", sid, root, e)
    if not items and last_err:
        raise HTTPException(status_code=502, detail=f"女优作品失败: {last_err}")
    payload = {
        "source": "javbus",
        "starId": sid,
        "page": p,
        "totalPages": p + (1 if len(items) >= 20 else 0),
        "items": _tag_kind_items(items, kind="javbus", provider="javbus"),
    }
    _cache_set(key, payload, ttl=1800)
    return payload


def _javbus_slug_matches(slug: str, want: str, candidates: list[str]) -> bool:
    """列表/search 结果 slug 是否对应当前查询番号。"""
    from app.scrape_details.common import code_equiv, fold_code

    s = str(slug or "").strip()
    if not s:
        return False
    if code_equiv(s, want):
        return True
    fs = fold_code(s)
    for c in candidates:
        if not c:
            continue
        if code_equiv(s, c) or fs == fold_code(c):
            return True
    return False


def _javbus_search_detail_path(
    html: str, want: str, candidates: list[str]
) -> str | None:
    """从 search HTML 里挑出详情路径（末段 slug）。"""
    soup = BeautifulSoup(html or "", "lxml")
    for a in soup.select("a.movie-box"):
        href = str(a.get("href") or "").strip()
        if not href:
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if _javbus_slug_matches(slug, want, candidates):
            return slug
        # photo-info 里的番号文本（有时与 URL slug 不一致）
        info = a.select_one(".photo-info")
        if info:
            texts = [t.strip() for t in info.stripped_strings if t.strip()]
            if texts and _javbus_slug_matches(texts[0], want, candidates):
                return slug
    return None


def _javbus_detail(
    code: str, *, base_url: str = "", cookie: str = ""
) -> dict[str, Any]:
    from app.scrape_details.common import javbus_code_candidates

    want = str(code or "").strip()
    display = want.upper()
    key = f"javbus:detail:v5:{display}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    candidates = javbus_code_candidates(want)
    if not candidates:
        candidates = [display]
    last_err: Exception | None = None
    bases = list(_javbus_bases())
    pref = (base_url or "").strip().rstrip("/")
    if pref:
        bases = [pref] + [b for b in bases if str(b).rstrip("/") != pref]
    # cookie 由 _fetch_html → javbus_cookie / 数据源配置读取；此处仅保证测通链接置顶
    del cookie

    def _parse_ok(html: str, base: str, path_code: str) -> dict[str, Any] | None:
        nonlocal last_err
        # 对齐 MDCS parseJavbusDetailHtml：404 页明确报未找到
        if re.search(
            r"404|找不到頁面|找不到页面|Page Not Found", html or "", re.I
        ) and not re.search(
            r"bigImage|movie-title|class=[\"'][^\"']*container", html or "", re.I
        ):
            last_err = RuntimeError("未找到影片")
            return None
        if re.search(r"Age Verification|年齡驗證|年龄验证", html or "", re.I) and not re.search(
            r"bigImage", html or "", re.I
        ):
            last_err = RuntimeError(
                "需要年龄验证 Cookie（默认 existmag=all; age=verified; dv=1）"
            )
            return None
        soup = BeautifulSoup(html, "lxml")
        if not soup.select_one(".bigImage, .movie .info"):
            last_err = RuntimeError("未找到影片")
            return None
        # 页面展示番号优先；否则用请求码
        page_code = display
        for p in soup.select(".movie .info p"):
            lab_el = p.select_one("span.header")
            lab = (
                (lab_el.get_text(strip=True) if lab_el else "")
                .replace(":", "")
                .replace("：", "")
                .strip()
            )
            if any(x in lab for x in ("識別", "识别", "番號", "番号", "Code", "ID")):
                rest = p.get_text(" ", strip=True)
                if lab:
                    rest = rest.replace(lab, "", 1).lstrip(":： ").strip()
                if rest:
                    page_code = rest.upper()
                break
        h3 = soup.select_one("h3")
        title = (h3.get_text(" ", strip=True) if h3 else "") or page_code
        title = (
            re.sub(rf"^{re.escape(page_code)}\s+", "", title, flags=re.I).strip()
            or re.sub(rf"^{re.escape(path_code)}\s+", "", title, flags=re.I).strip()
            or page_code
        )
        big = soup.select_one(".bigImage img, .bigImage")
        poster = None
        if big:
            if big.name == "img":
                poster = _abs(base, big.get("src"))
            else:
                poster = _abs(base, big.get("href"))

        info: dict[str, str] = {}
        info_links: dict[str, list[str]] = {}
        for p in soup.select(".movie .info p"):
            lab_el = p.select_one("span.header")
            lab = (
                (lab_el.get_text(strip=True) if lab_el else "")
                .replace(":", "")
                .replace("：", "")
                .strip()
            )
            links = [
                a.get_text(" ", strip=True)
                for a in p.select("a")
                if a.get_text(" ", strip=True)
            ]
            rest = p.get_text(" ", strip=True)
            if lab:
                rest = rest.replace(lab, "", 1).lstrip(":： ").strip()
                info[lab] = rest
                if links:
                    info_links[lab] = links

        def _pick(*keys: str) -> str:
            for k, v in info.items():
                if any(x in k for x in keys):
                    return (v or "").strip()
            return ""

        def _pick_links(*keys: str) -> list[str]:
            for k, links in info_links.items():
                if any(x in k for x in keys):
                    return [x for x in links if x]
            return []

        date_s = _pick("日期", "Date", "發行", "发行")
        # 長度：120分鐘
        runtime_raw = _pick("長度", "长度", "Runtime", "Duration", "時長", "时长")
        runtime_m: int | None = None
        m = re.search(r"(\d+)\s*分", runtime_raw) or re.search(r"(\d+)", runtime_raw)
        if m:
            try:
                runtime_m = int(m.group(1))
            except ValueError:
                runtime_m = None
        director = _pick("導演", "导演", "Director")
        maker = _pick("製作", "制作", "Maker", "Studio")
        # 製作商常带链接文字
        maker_links = _pick_links("製作", "制作", "Maker", "Studio")
        if maker_links:
            maker = maker_links[0]
        publisher = _pick("發行商", "发行商", "Label", "Publisher")
        pub_links = _pick_links("發行商", "发行商", "Label", "Publisher")
        if pub_links:
            publisher = pub_links[0]
        series = _pick("系列", "Series")
        series_links = _pick_links("系列", "Series")
        if series_links:
            series = series_links[0]
        tags = _pick_links("類別", "类别", "Genre", "Tags")
        if not tags:
            # JavBus：類別标题是 <p class="header">，标签在下一行 span.genre a
            tags = [
                a.get_text(" ", strip=True)
                for a in soup.select(
                    ".movie .info span.genre a, .movie .info .genre a, span.genre a"
                )
                if a.get_text(" ", strip=True)
            ]
        if not tags:
            for k, v in info.items():
                if any(x in k for x in ("類別", "类别", "Genre")):
                    tags = [t for t in re.split(r"[\s,，、]+", v) if t]
                    break
        # 去重保序
        seen_tags: set[str] = set()
        tags_uniq: list[str] = []
        for t in tags:
            if t in seen_tags:
                continue
            seen_tags.add(t)
            tags_uniq.append(t)
        tags = tags_uniq

        # 女优：info 链接 + 头像瀑布 + /star/ 锚点
        actors = _pick_links("女優", "女优", "Actor", "Actors", "演員", "演员")
        cast: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        star_rows: dict[str, dict[str, Any]] = {}

        def _star_id(href: str | None) -> str | None:
            m = re.search(r"/star/([^/?#]+)", str(href or ""), re.I)
            return m.group(1).strip() if m else None

        def _add_cast(
            name: str,
            *,
            avatar: str | None = None,
            star_id: str | None = None,
        ) -> None:
            name = re.sub(r"\s+", " ", (name or "").strip())
            # 去掉「本名（别名）」/ 半截「本名（」，避免瀑布 span 与 img title 重复
            name = re.sub(r"\s*[\(（][^)）]*[\)）]\s*$", "", name).strip()
            name = re.sub(r"\s*[\(（][^)）]*$", "", name).strip()
            name = name.rstrip("（(").strip()
            if not name:
                return
            # 同一 star_id 只能是一个人：javbus 同一女优会在头像瀑布 span（全名）、
            # 裸 a[href*="/star/"] 锚点（常被站点截断）等处给出不同显示文本。
            # 只按名字去重会让同一人变两条（案例 BONY-012 `ありすがわりな`+`ありすがわ`、
            # OERO-009 `きょうこさん`+`きょうこさ`，两者 star_id 相同）→ 同号内计数虚高。
            # 取**显示名更长**的那条，短的是截断。
            prev = star_rows.get(star_id) if star_id else None
            if prev is not None:
                old = str(prev.get("name") or "")
                if len(name) <= len(old):
                    return
                prev["name"] = name
                if avatar and not prev.get("avatarUrl"):
                    prev["avatarUrl"] = avatar
                seen_names.discard(old)
                seen_names.add(name)
                if old in actors:
                    actors[actors.index(old)] = name
                if name not in actors:
                    actors.append(name)
                return
            if name in seen_names:
                return
            seen_names.add(name)
            if name not in actors:
                actors.append(name)
            row: dict[str, Any] = {"name": name, "avatarUrl": avatar}
            if star_id:
                row["id"] = star_id
                star_rows[star_id] = row
            cast.append(row)

        for box in soup.select(
            "#avatar-waterfall .avatar-box, #avatar-waterfall a.avatar-box, "
            "#avatar-waterfall a"
        ):
            name_el = box.select_one(".star-name, span")
            name = (
                (name_el.get_text(" ", strip=True) if name_el else "")
                or box.get_text(" ", strip=True)
                or ""
            )
            img = box.select_one("img")
            # JavBus 常把完整「本名（别名）」放在 img title，span 却截成「本名（」
            img_title = ""
            if img is not None:
                img_title = str(img.get("title") or img.get("alt") or "").strip()
            if img_title and (
                name.endswith(("（", "("))
                or (
                    len(img_title) > len(name)
                    and name.rstrip("（(")
                    and name.rstrip("（(") in img_title
                )
            ):
                name = img_title
            avatar = _abs(base, img.get("src") or img.get("data-src")) if img else None
            href = box.get("href") if hasattr(box, "get") else None
            if not href and box.parent and getattr(box.parent, "name", None) == "a":
                href = box.parent.get("href")
            _add_cast(name, avatar=avatar, star_id=_star_id(href))
        for a in soup.select('.movie .info a[href*="/star/"], a[href*="/star/"]'):
            _add_cast(
                a.get_text(" ", strip=True),
                star_id=_star_id(a.get("href")),
            )
        for name in actors:
            _add_cast(name)

        # 样品图
        samples: list[str] = []
        for a in soup.select("#sample-waterfall a.sample-box, #sample-waterfall a"):
            href = a.get("href") or ""
            url = _abs(base, href)
            if url and url not in samples:
                samples.append(url)
        if not samples:
            for img in soup.select("#sample-waterfall img"):
                url = _abs(base, img.get("src") or img.get("data-src"))
                if url and url not in samples:
                    samples.append(url)

        studio = maker or publisher or None
        item = _item(
            source="javbus",
            id_=page_code,
            title=title,
            code=page_code,
            poster=poster,
            year=_year_from(date_s),
            date=date_s or None,
            studio=studio,
            actors=actors[:20],
            tags=tags[:24],
        )
        item["runtime"] = runtime_m
        item["director"] = director or None
        item["maker"] = maker or None
        item["publisher"] = publisher or None
        item["series"] = series or None
        item["cast"] = cast[:20]
        item["samples"] = samples[:24]
        item["provider"] = "javbus"
        return item

    # 1) 直接路径：补零 / date6 slug 变体
    for base in bases:
        for cand in candidates:
            path = quote(str(cand).strip(), safe="-_.~")
            try:
                html = _fetch_html(f"{base}/{path}", referer=f"{base}/", fast=True)
                item = _parse_ok(html, base, str(cand))
                if item is not None:
                    _remember_javbus(base)
                    _cache_set(key, item)
                    return item
            except Exception as e:
                last_err = e
                log.warning("javbus detail %s @ %s/%s: %s", display, base, cand, e)

    # 2) search 回退（有码 /search、无码 /uncensored/search）
    search_queries: list[str] = []
    for c in candidates:
        if c and c not in search_queries:
            search_queries.append(c)
        if len(search_queries) >= 6:
            break
    for base in bases:
        for q in search_queries:
            enc = quote(q)
            for spath in (f"/search/{enc}", f"/uncensored/search/{enc}"):
                try:
                    html = _fetch_html(f"{base}{spath}", referer=f"{base}/", fast=True)
                    slug = _javbus_search_detail_path(html, want, candidates)
                    if not slug:
                        continue
                    path = quote(slug, safe="-_.~")
                    detail_html = _fetch_html(
                        f"{base}/{path}", referer=f"{base}{spath}", fast=True
                    )
                    item = _parse_ok(detail_html, base, slug)
                    if item is not None:
                        _remember_javbus(base)
                        _cache_set(key, item)
                        return item
                except Exception as e:
                    last_err = e
                    log.warning(
                        "javbus search-detail %s @ %s%s: %s", display, base, spath, e
                    )

    raise HTTPException(
        status_code=502,
        detail=f"详情失败: {last_err}" if last_err else "未找到",
    )


# —— iQQTV ——

def _resolve_iqqtv_root(force: bool = False) -> str:
    if not force:
        try:
            cfg = makers_settings.resolve_makers_catalog()["iqqtv"]
            active = str(cfg.get("activeBase") or "").strip()
            if active:
                root = re.sub(r"/cn/?$", "", active, flags=re.I).rstrip("/")
                if root:
                    site_mirror.remember("iqqtv", root, discovered_from=root)
                    return root
        except Exception:
            pass
    try:
        return site_mirror.resolve("iqqtv", force=force)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"iQQTV 镜像不可用: {e}",
        ) from e


def _remember_iqqtv(root: str) -> None:
    try:
        site_mirror.remember("iqqtv", root)
    except Exception:
        pass


def _parse_iqqtv_list(html: str, base: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    out: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    # 现站：player.php?uuid=；旧站：/h/{id}
    candidates = soup.select(
        'a[href*="player.php"], a[href*="/h/"], a[href*="/cn/h/"], '
        ".video-item a, .movie_list a, .item a"
    )
    for a in candidates:
        href = a.get("href") or ""
        uuid_m = re.search(r"[?&]uuid=([A-Za-z0-9_-]{4,40})", href, re.I)
        h_m = re.search(r"/h/([^/?#]+?)(?:\.html)?/?$", href, re.I)
        if not uuid_m and not h_m and "/h/" not in href:
            continue
        url = _abs(base, href)
        if not url:
            continue
        if uuid_m:
            id_ = uuid_m.group(1).strip()
        elif h_m:
            id_ = h_m.group(1).strip()
        else:
            continue
        id_ = re.sub(r"\.html$", "", id_, flags=re.I)
        if not id_:
            continue
        img = a.select_one("img")
        poster = None
        title = ""
        if img is not None:
            poster = _abs(
                base, img.get("src") or img.get("data-src") or img.get("data-original")
            )
            title = (img.get("alt") or img.get("title") or "").strip()
        if not title:
            title = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
        title = re.sub(r"\s+", " ", title).strip()
        if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", title or ""):
            title = ""
        code_m = re.search(r"([A-Za-z]{2,15}-\d{2,5})", title) if title else None
        code = code_m.group(1).upper() if code_m else None
        prev = by_id.get(id_)
        if prev:
            if poster and not prev.get("posterUrl"):
                prev["posterUrl"] = poster
            if title and len(title) > len(str(prev.get("title") or "")):
                prev["title"] = title
            if code and (
                not prev.get("code")
                or str(prev.get("code") or "").upper() == id_.upper()
            ):
                prev["code"] = code
                prev["originalTitle"] = code
            continue
        if not title and not poster:
            continue
        item = _item(
            source="iqqtv",
            id_=id_,
            title=title or id_,
            code=code,
            poster=poster,
        )
        by_id[id_] = item
        out.append(item)
        if len(out) >= 48:
            break
    return out


def _iqqtv_charts(chart: str, page: int) -> dict[str, Any]:
    root = _resolve_iqqtv_root()
    key = f"iqqtv:chart:{chart}:{page}:{root}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    if chart == "hot":
        path = f"/cn/menu/hot/page/{page}.html" if page > 1 else "/cn/menu/hot/"
    else:
        path = f"/cn/page/{page}.html" if page > 1 else "/cn/"
    try:
        html = _fetch_html(f"{root}{path}", referer=f"{root}/cn/")
        _remember_iqqtv(root)
    except HTTPException:
        root = _resolve_iqqtv_root(force=True)
        html = _fetch_html(f"{root}{path}", referer=f"{root}/cn/")
        _remember_iqqtv(root)
    items = _parse_iqqtv_list(html, root)
    payload = {
        "source": "iqqtv",
        "chart": chart,
        "page": page,
        "totalPages": page + (1 if len(items) >= 20 else 0),
        "items": items,
    }
    _cache_set(key, payload)
    return payload


def _iqqtv_search(q: str, page: int) -> dict[str, Any]:
    root = _resolve_iqqtv_root()
    q = q.strip()
    key = f"iqqtv:search:{q.lower()}:{page}:{root}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    enc = quote(q)
    # 常见搜索路径
    paths = [
        f"/cn/search/{enc}/page/{page}.html" if page > 1 else f"/cn/search/{enc}/",
        f"/cn/search.php?keys={enc}&page={page}",
    ]
    items: list[dict[str, Any]] = []
    for path in paths:
        try:
            html = _fetch_html(f"{root}{path}", referer=f"{root}/cn/")
            items = _parse_iqqtv_list(html, root)
            if items:
                _remember_iqqtv(root)
                break
        except Exception as e:
            log.warning("iqqtv search path %s: %s", path, e)
    payload = {
        "source": "iqqtv",
        "query": q,
        "page": page,
        "totalPages": page + (1 if len(items) >= 20 else 0),
        "items": items,
    }
    _cache_set(key, payload, ttl=1800)
    return payload


def _iqqtv_detail(
    id_: str, *, base_url: str = "", cookie: str = ""
) -> dict[str, Any]:
    id_ = id_.strip()
    key = f"iqqtv:detail:{id_}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    del cookie
    if base_url.strip():
        root = re.sub(r"/(cn|ja|en|zh)/?$", "", base_url.strip().rstrip("/"), flags=re.I).rstrip("/")
        if root:
            try:
                site_mirror.remember("iqqtv", root, discovered_from=root)
            except Exception:
                pass
        else:
            root = _resolve_iqqtv_root()
    else:
        root = _resolve_iqqtv_root()
    candidates = [
        f"{root}/cn/player.php?uuid={id_}",
        f"{root}/cn/h/{id_}.html",
        f"{root}/cn/h/{id_}",
        f"{root}/cn/{id_}.html",
        f"{root}/{id_}",
    ]
    last_err: Exception | None = None
    for url in candidates:
        try:
            html = _fetch_html(url, referer=f"{root}/cn/")
            soup = BeautifulSoup(html, "lxml")
            h1 = soup.select_one("h1, .title, .video-title")
            title = (h1.get_text(" ", strip=True) if h1 else "") or id_
            title_l = title.casefold()
            if any(
                m in title_l
                for m in (
                    "会员登入",
                    "會員登入",
                    "会员登录",
                    "請先登入",
                    "请先登录",
                    "login",
                    "sign in",
                )
            ):
                raise RuntimeError(f"iqqtv login wall: {title}")
            img = soup.select_one(".video-pic img, .detail img, .cover img, img.poster")
            poster = _abs(root, img.get("src") or img.get("data-src")) if img else None
            if not poster and not soup.select_one(".movie, .video-detail, .detail, #player"):
                raise RuntimeError("iqqtv detail page missing content")
            code_m = re.search(r"([A-Za-z]{2,15}-\d{2,5})", title) or re.search(
                r"([A-Za-z]{2,15}-\d{2,5})", id_
            )
            code = code_m.group(1).upper() if code_m else id_.upper()
            # 简介
            overview = ""
            for sel in (".introduction", ".desc", ".summary", "#intro"):
                el = soup.select_one(sel)
                if el:
                    overview = el.get_text(" ", strip=True)[:800]
                    break
            actors: list[str] = []
            tags: list[str] = []
            studio = None
            for a in soup.select("a[href*='actor'], a[href*='star'], .actor a"):
                n = a.get_text(" ", strip=True)
                if n and n not in actors and len(n) < 40:
                    actors.append(n)
            for a in soup.select("a[href*='genre'], a[href*='tag'], .tag a"):
                n = a.get_text(" ", strip=True)
                if n and n not in tags and len(n) < 30:
                    tags.append(n)
            item = _item(
                source="iqqtv",
                id_=id_,
                title=title,
                code=code,
                poster=poster,
                studio=studio,
                actors=actors[:20],
                tags=tags[:20],
                overview=overview or None,
            )
            _cache_set(key, item)
            return item
        except Exception as e:
            last_err = e
    raise HTTPException(
        status_code=502,
        detail=f"详情失败: {last_err}" if last_err else "未找到",
    )


# —— Routes ——

@router.get("/makers/meta")
def makers_meta() -> dict[str, Any]:
    enabled = {
        "javbus": makers_settings.javbus_enabled(),
        "iqqtv": makers_settings.iqqtv_enabled(),
        "missav": makers_settings.missav_enabled(),
        "7mmtv": makers_settings.sevenmm_enabled(),
        "madou": makers_settings.madou_enabled(),
    }
    kinds = []
    for kid in KIND_ORDER:
        shelves = []
        for s in KIND_SHELVES.get(kid, []):
            prov = s.get("provider") or ""
            if prov and not enabled.get(prov, True):
                continue
            shelves.append({"id": s["id"], "label": s["label"]})
        kinds.append(
            {
                "id": kid,
                "label": KIND_LABELS[kid],
                "charts": shelves,
            }
        )
    return _wrap(
        {
            "kinds": kinds,
            # 兼容旧前端字段
            "sources": kinds,
        }
    )


@router.get("/makers/{source}/charts")
def makers_charts(
    source: str,
    chart: str = Query("latest"),
    page: int = Query(1, ge=1, le=50),
) -> dict[str, Any]:
    src = source.strip().lower()
    if src in KIND_SHELVES:
        return _wrap(_kind_charts(src, chart or "latest", page))
    if src == "javbus":
        return _wrap(_javbus_charts(chart or "latest", page))
    if src == "iqqtv":
        return _wrap(_iqqtv_charts(chart or "latest", page))
    raise HTTPException(status_code=404, detail="未知分类")


@router.get("/makers/{source}/search")
def makers_search(
    source: str,
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1, le=50),
) -> dict[str, Any]:
    src = source.strip().lower()
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="请输入关键词")
    if src in KIND_SHELVES:
        return _wrap(_kind_search(src, query, page))
    if src == "javbus":
        return _wrap(_javbus_search(query, page))
    if src == "iqqtv":
        return _wrap(_iqqtv_search(query, page))
    raise HTTPException(status_code=404, detail="未知分类")


@router.get("/makers/{source}/star")
def makers_star(
    source: str,
    star_id: str = Query("", alias="id"),
    page: int = Query(1, ge=1, le=50),
    q: str = Query("", description="无 star id 时回退按名搜索"),
) -> dict[str, Any]:
    """女优作品汇总：优先 /star/{id}，否则按名字搜索。"""
    src = source.strip().lower()
    sid = star_id.strip()
    name = q.strip()

    def _as_kind(data: dict[str, Any], kind: str) -> dict[str, Any]:
        items = _tag_kind_items(data.get("items") or [], kind=kind, provider="javbus")
        return {**data, "items": items, "kind": kind}

    if src in KIND_SHELVES:
        if sid and sid.lower() not in ("-", "none", "null"):
            return _wrap(_as_kind(_javbus_star(sid, page), src))
        if not name:
            raise HTTPException(status_code=400, detail="请提供女优 id 或名字")
        return _wrap(_as_kind(_javbus_search(name, page), src))
    if src == "javbus":
        if sid and sid.lower() not in ("-", "none", "null"):
            return _wrap(_javbus_star(sid, page))
        if not name:
            raise HTTPException(status_code=400, detail="请提供女优 id 或名字")
        return _wrap(_javbus_search(name, page))
    raise HTTPException(status_code=404, detail="未知分类")


@router.get("/makers/{source}/detail")
def makers_detail(
    source: str,
    item_id: str = Query(..., min_length=1, alias="id"),
) -> dict[str, Any]:
    src = source.strip().lower()
    rid = item_id.strip()
    if src in KIND_SHELVES:
        return _wrap(_kind_detail(src, rid))
    if src == "javbus":
        return _wrap(_javbus_detail(rid))
    if src == "iqqtv":
        return _wrap(_iqqtv_detail(rid))
    raise HTTPException(status_code=404, detail="未知分类")
