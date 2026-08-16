"""影视榜单：TMDB 官方 API + 豆瓣榜单（服务端抓取缓存）。"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from .translate_routes import get_tmdb_api_key

log = logging.getLogger(__name__)

router = APIRouter(tags=["media"])

_HTTPX_KW: dict[str, Any] = {
    # 外网慢/代理挂时勿拖死整站；connect 先失败，设置 Hub 才能及时返回
    "timeout": httpx.Timeout(8.0, connect=4.0),
    "trust_env": True,
    "follow_redirects": True,
}

# 豆瓣直连：本机系统代理常会打断 TLS（ConnectError 空消息），勿 trust_env。
_DOUBAN_HTTPX_KW: dict[str, Any] = {
    "timeout": httpx.Timeout(10.0, connect=5.0),
    "trust_env": False,
    "follow_redirects": True,
}

_TMDB_IMG = "https://image.tmdb.org/t/p/w500"
_DOUBAN_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_DOUBAN_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
    "Mobile/15E148 Safari/604.1"
)

# 内存缓存：key -> (expires_at, payload)
_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL_S = 6 * 3600

CATEGORIES = ("movie", "tv", "anime", "variety")
TMDB_CHARTS = (
    "popular",
    "top_rated",
    "trending",
    "on_the_air",
    "now_playing",
    "upcoming",
)
DOUBAN_CHARTS = (
    "hot",
    "top250",
    "new",
    "cn",
    "western",
    "jp",
    "kr",
)


def _wrap(data: Any, message: str = "ok", status: int = 200) -> dict[str, Any]:
    return {"data": data, "message": message, "status": status}


def _cache_get(key: str) -> Any | None:
    hit = _cache.get(key)
    if not hit:
        return None
    exp, payload = hit
    if time.time() > exp:
        _cache.pop(key, None)
        return None
    return payload


def _cache_set(key: str, payload: Any, ttl: float = _CACHE_TTL_S) -> None:
    _cache[key] = (time.time() + ttl, payload)


def _year_from(date_s: str | None) -> str | None:
    s = str(date_s or "").strip()
    if len(s) >= 4 and s[:4].isdigit():
        return s[:4]
    return None


def _poster_tmdb(path: str | None) -> str | None:
    p = str(path or "").strip()
    if not p:
        return None
    if p.startswith("http"):
        return p
    return f"{_TMDB_IMG}{p}"


def _norm_item(
    *,
    source: str,
    id_: str,
    media_type: str,
    title: str,
    original_title: str = "",
    aka: list[str] | None = None,
    poster_url: str | None = None,
    year: str | None = None,
    rating: float | None = None,
    overview: str = "",
) -> dict[str, Any]:
    titles = []
    for t in [title, original_title, *(aka or [])]:
        s = str(t or "").strip()
        if s and s not in titles:
            titles.append(s)
    return {
        "source": source,
        "id": str(id_),
        "mediaType": media_type if media_type in {"movie", "tv"} else "movie",
        "title": titles[0] if titles else str(id_),
        "originalTitle": original_title or None,
        "aka": titles[1:],
        "posterUrl": poster_url or None,
        "year": year or None,
        "rating": rating,
        "overview": (overview or "").strip() or None,
    }


# ─── TMDB ─────────────────────────────────────────────


def _require_tmdb_key() -> str:
    key = get_tmdb_api_key()
    if not key:
        raise HTTPException(
            status_code=400,
            detail="未配置 TMDB API Key，请到 设置 → TMDB 填写",
        )
    return key


async def _tmdb_get(
    client: httpx.AsyncClient, path: str, params: dict[str, Any]
) -> dict[str, Any]:
    r = await client.get(f"https://api.themoviedb.org{path}", params=params)
    if r.status_code == 401:
        raise HTTPException(status_code=400, detail="TMDB API Key 无效")
    if not r.is_success:
        raise HTTPException(
            status_code=502, detail=f"TMDB 返回 {r.status_code}"
        )
    data = r.json() or {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="TMDB 响应异常")
    return data


def _map_tmdb_list_item(raw: dict[str, Any], fallback_type: str) -> dict[str, Any]:
    mt = str(raw.get("media_type") or fallback_type or "movie")
    if mt not in {"movie", "tv"}:
        mt = "movie" if raw.get("title") else "tv"
    title = str(raw.get("title") or raw.get("name") or "").strip()
    original = str(
        raw.get("original_title") or raw.get("original_name") or ""
    ).strip()
    date = raw.get("release_date") or raw.get("first_air_date")
    rating = raw.get("vote_average")
    try:
        rating_f = float(rating) if rating is not None else None
    except (TypeError, ValueError):
        rating_f = None
    return _norm_item(
        source="tmdb",
        id_=str(raw.get("id") or ""),
        media_type=mt,
        title=title,
        original_title=original,
        poster_url=_poster_tmdb(raw.get("poster_path")),
        year=_year_from(str(date) if date else None),
        rating=rating_f,
        overview=str(raw.get("overview") or ""),
    )


@router.get("/media/tmdb/charts")
async def tmdb_charts(
    category: str = Query("movie", description="movie|tv|anime|variety"),
    chart: str = Query("popular", description="popular|top_rated|trending|on_the_air"),
    page: int = Query(1, ge=1, le=20),
) -> dict[str, Any]:
    cat = (category or "movie").strip().lower()
    ch = (chart or "popular").strip().lower()
    if cat not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"未知分类: {category}")
    if ch not in TMDB_CHARTS:
        raise HTTPException(status_code=400, detail=f"未知榜单: {chart}")

    cache_key = f"tmdb:charts:{cat}:{ch}:{page}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return _wrap(cached)

    key = _require_tmdb_key()
    params: dict[str, Any] = {
        "api_key": key,
        "language": "zh-CN",
        "page": page,
        "include_adult": "false",
    }

    try:
        async with httpx.AsyncClient(**_HTTPX_KW) as client:
            if cat == "movie":
                if ch == "trending":
                    data = await _tmdb_get(
                        client, "/3/trending/movie/week", params
                    )
                    fallback = "movie"
                elif ch == "top_rated":
                    data = await _tmdb_get(client, "/3/movie/top_rated", params)
                    fallback = "movie"
                elif ch == "now_playing":
                    data = await _tmdb_get(client, "/3/movie/now_playing", params)
                    fallback = "movie"
                elif ch == "upcoming":
                    data = await _tmdb_get(client, "/3/movie/upcoming", params)
                    fallback = "movie"
                else:
                    data = await _tmdb_get(client, "/3/movie/popular", params)
                    fallback = "movie"
            elif cat == "tv":
                if ch == "trending":
                    data = await _tmdb_get(client, "/3/trending/tv/week", params)
                    fallback = "tv"
                elif ch == "top_rated":
                    data = await _tmdb_get(client, "/3/tv/top_rated", params)
                    fallback = "tv"
                elif ch == "on_the_air":
                    data = await _tmdb_get(client, "/3/tv/on_the_air", params)
                    fallback = "tv"
                else:
                    data = await _tmdb_get(client, "/3/tv/popular", params)
                    fallback = "tv"
            elif cat == "anime":
                # Animation genre = 16
                disc = {
                    **params,
                    "with_genres": "16",
                    "sort_by": (
                        "vote_average.desc" if ch == "top_rated" else "popularity.desc"
                    ),
                    "vote_count.gte": 50 if ch == "top_rated" else 0,
                }
                data = await _tmdb_get(client, "/3/discover/tv", disc)
                fallback = "tv"
            else:
                # variety ≈ Reality(10764) + Talk(10767)
                disc = {
                    **params,
                    "with_genres": "10764|10767",
                    "sort_by": "popularity.desc",
                    "with_origin_country": "CN|JP|KR|TW|HK",
                }
                data = await _tmdb_get(client, "/3/discover/tv", disc)
                fallback = "tv"
    except httpx.TimeoutException as e:
        log.warning("tmdb charts timeout cat=%s chart=%s: %s", cat, ch, e)
        raise HTTPException(status_code=504, detail="TMDB 连接超时，请检查代理/网络") from e
    except httpx.HTTPError as e:
        log.warning("tmdb charts http error cat=%s chart=%s: %s", cat, ch, e)
        raise HTTPException(status_code=502, detail="TMDB 网络异常") from e

    results = data.get("results") if isinstance(data.get("results"), list) else []
    items = [
        _map_tmdb_list_item(x, fallback)
        for x in results
        if isinstance(x, dict) and x.get("id")
    ]
    payload = {
        "source": "tmdb",
        "category": cat,
        "chart": ch,
        "page": page,
        "totalPages": int(data.get("total_pages") or 1),
        "items": items,
    }
    _cache_set(cache_key, payload, ttl=3600)
    return _wrap(payload)


@router.get("/media/tmdb/{media_type}/{media_id}")
async def tmdb_detail(media_type: str, media_id: str) -> dict[str, Any]:
    mt = (media_type or "").strip().lower()
    if mt not in {"movie", "tv"}:
        raise HTTPException(status_code=400, detail="media_type 须为 movie 或 tv")
    mid = str(media_id or "").strip()
    if not mid.isdigit():
        raise HTTPException(status_code=400, detail="无效 id")

    cache_key = f"tmdb:detail:{mt}:{mid}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return _wrap(cached)

    key = _require_tmdb_key()
    async with httpx.AsyncClient(**_HTTPX_KW) as client:
        data = await _tmdb_get(
            client,
            f"/3/{mt}/{mid}",
            {
                "api_key": key,
                "language": "zh-CN",
                "append_to_response": "alternative_titles,credits",
            },
        )
        # 英文原名兜底
        en = await _tmdb_get(
            client,
            f"/3/{mt}/{mid}",
            {"api_key": key, "language": "en-US"},
        )

    title = str(data.get("title") or data.get("name") or "").strip()
    original = str(
        data.get("original_title")
        or data.get("original_name")
        or en.get("original_title")
        or en.get("original_name")
        or en.get("title")
        or en.get("name")
        or ""
    ).strip()
    aka: list[str] = []
    alt = data.get("alternative_titles") or {}
    titles_list = alt.get("titles") or alt.get("results") or []
    if isinstance(titles_list, list):
        for row in titles_list:
            if not isinstance(row, dict):
                continue
            t = str(row.get("title") or "").strip()
            if t and t not in aka and t != title and t != original:
                aka.append(t)
    for extra in (
        en.get("title"),
        en.get("name"),
        en.get("original_title"),
        en.get("original_name"),
    ):
        t = str(extra or "").strip()
        if t and t not in aka and t != title and t != original:
            aka.append(t)

    date = data.get("release_date") or data.get("first_air_date")
    rating = data.get("vote_average")
    try:
        rating_f = float(rating) if rating is not None else None
    except (TypeError, ValueError):
        rating_f = None

    cast = []
    credits = data.get("credits") if isinstance(data.get("credits"), dict) else {}
    for c in (credits.get("cast") or [])[:8]:
        if isinstance(c, dict) and c.get("name"):
            cast.append(str(c["name"]))

    genres: list[str] = []
    for g in data.get("genres") or []:
        if isinstance(g, dict) and g.get("name"):
            genres.append(str(g["name"]))

    runtime = data.get("runtime")
    if runtime in (None, 0) and isinstance(data.get("episode_run_time"), list):
        ert = data.get("episode_run_time") or []
        runtime = ert[0] if ert else None
    try:
        runtime_i = int(runtime) if runtime not in (None, "") else None
    except (TypeError, ValueError):
        runtime_i = None

    countries: list[str] = []
    for row in data.get("production_countries") or data.get("origin_country") or []:
        if isinstance(row, dict) and row.get("name"):
            countries.append(str(row["name"]))
        elif isinstance(row, str) and row.strip():
            countries.append(row.strip())

    item = _norm_item(
        source="tmdb",
        id_=mid,
        media_type=mt,
        title=title or original,
        original_title=original,
        aka=aka[:20],
        poster_url=_poster_tmdb(data.get("poster_path")),
        year=_year_from(str(date) if date else None),
        rating=rating_f,
        overview=str(data.get("overview") or ""),
    )
    item["cast"] = cast
    if genres:
        item["genres"] = genres[:12]
    if runtime_i and runtime_i > 0:
        item["runtime"] = runtime_i
    if countries:
        item["countries"] = countries[:8]
    _cache_set(cache_key, item, ttl=_CACHE_TTL_S)
    return _wrap(item)


@router.get("/media/tmdb/{media_type}/{media_id}/related")
async def tmdb_related(media_type: str, media_id: str) -> dict[str, Any]:
    """相似 + 推荐（MoviePilot 详情相关推荐）。"""
    mt = (media_type or "").strip().lower()
    if mt not in {"movie", "tv"}:
        raise HTTPException(status_code=400, detail="media_type 须为 movie 或 tv")
    mid = str(media_id or "").strip()
    if not mid.isdigit():
        raise HTTPException(status_code=400, detail="无效 id")

    cache_key = f"tmdb:related:{mt}:{mid}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return _wrap(cached)

    key = _require_tmdb_key()
    params = {"api_key": key, "language": "zh-CN", "page": 1}
    async with httpx.AsyncClient(**_HTTPX_KW) as client:
        sim = await _tmdb_get(client, f"/3/{mt}/{mid}/similar", params)
        rec = await _tmdb_get(client, f"/3/{mt}/{mid}/recommendations", params)

    def _rows(data: dict[str, Any]) -> list[dict[str, Any]]:
        results = data.get("results") if isinstance(data.get("results"), list) else []
        return [
            _map_tmdb_list_item(x, mt)
            for x in results
            if isinstance(x, dict) and x.get("id")
        ][:16]

    payload = {
        "similar": _rows(sim),
        "recommendations": _rows(rec),
    }
    _cache_set(cache_key, payload, ttl=3600)
    return _wrap(payload)


@router.get("/media/search")
async def media_search(
    q: str = Query(..., min_length=1),
    source: str = Query("tmdb"),
    page: int = Query(1, ge=1, le=20),
) -> dict[str, Any]:
    """影视信息搜索（TMDB / 豆瓣）。

    多片名：用逗号/顿号/分号等分隔（中文片名也可用空格），逐条搜索后合并去重。
    英文片名含空格时请用逗号分隔多部作品，避免被拆碎。
    """
    src = (source or "tmdb").strip().lower()
    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="请输入关键词")
    if src not in {"tmdb", "douban"}:
        raise HTTPException(status_code=400, detail="未知数据源")

    terms = _split_media_query_terms(query)
    if not terms:
        raise HTTPException(status_code=400, detail="请输入关键词")

    # 多词：固定汇总第 1 页，避免分页语义混乱
    multi = len(terms) > 1
    use_page = 1 if multi else page
    cache_key = (
        f"search:{src}:multi:{'|'.join(t.lower() for t in terms)}"
        if multi
        else f"search:{src}:{query.lower()}:{use_page}"
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return _wrap(cached)

    if src == "tmdb":
        key = _require_tmdb_key()
        async with httpx.AsyncClient(**_HTTPX_KW) as client:
            if multi:
                batches = await asyncio.gather(
                    *[
                        _tmdb_search_one(client, key=key, query=t, page=1)
                        for t in terms
                    ]
                )
                items = _merge_media_items([b[0] for b in batches])
                total_pages = 1
            else:
                items, total_pages = await _tmdb_search_one(
                    client, key=key, query=terms[0], page=use_page
                )
        payload = {
            "source": "tmdb",
            "query": query,
            "terms": terms,
            "page": use_page,
            "totalPages": total_pages,
            "items": items,
        }
        _cache_set(cache_key, payload, ttl=1800)
        return _wrap(payload)

    # 豆瓣 subject_suggest
    try:
        async with httpx.AsyncClient(**_DOUBAN_HTTPX_KW) as client:
            if multi:
                batches = await asyncio.gather(
                    *[_douban_suggest_one(client, t) for t in terms]
                )
                items = _merge_media_items(list(batches))
            else:
                items = await _douban_suggest_one(client, terms[0])
    except httpx.ConnectError as e:
        raise HTTPException(
            status_code=502,
            detail="无法连接豆瓣（网络或系统代理异常）",
        ) from e
    payload = {
        "source": "douban",
        "query": query,
        "terms": terms,
        "page": 1,
        "totalPages": 1,
        "items": items,
    }
    _cache_set(cache_key, payload, ttl=1800 if items else 120)
    return _wrap(payload)


_MEDIA_QUERY_STRONG_SEP = re.compile(r"[,;，、；|｜/\n\r]+")
_MEDIA_QUERY_SPACE_SEP = re.compile(r"\s+")
_MEDIA_QUERY_HAS_LATIN = re.compile(r"[A-Za-z]")


def _split_media_query_terms(q: str, *, limit: int = 10) -> list[str]:
    """拆成多个片名：强分隔符优先；纯中文可用空格；英文含空格整段保留。"""
    s = (q or "").strip()
    if not s:
        return []
    if _MEDIA_QUERY_STRONG_SEP.search(s):
        parts = _MEDIA_QUERY_STRONG_SEP.split(s)
    elif _MEDIA_QUERY_HAS_LATIN.search(s):
        parts = [s]
    else:
        parts = _MEDIA_QUERY_SPACE_SEP.split(s)
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        t = str(part or "").strip()
        if not t:
            continue
        key = t.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
        if len(out) >= limit:
            break
    return out


def _merge_media_items(batches: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """按各词结果顺序交错合并，同 id 去重。"""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_len = max((len(b) for b in batches), default=0)
    for i in range(max_len):
        for batch in batches:
            if i >= len(batch):
                continue
            item = batch[i]
            if not isinstance(item, dict):
                continue
            sid = f"{item.get('source')}:{item.get('id')}"
            if sid in seen:
                continue
            seen.add(sid)
            merged.append(item)
    return merged


async def _tmdb_search_one(
    client: httpx.AsyncClient,
    *,
    key: str,
    query: str,
    page: int,
) -> tuple[list[dict[str, Any]], int]:
    data = await _tmdb_get(
        client,
        "/3/search/multi",
        {
            "api_key": key,
            "language": "zh-CN",
            "query": query,
            "page": page,
            "include_adult": "false",
        },
    )
    results = data.get("results") if isinstance(data.get("results"), list) else []
    items: list[dict[str, Any]] = []
    for raw in results:
        if not isinstance(raw, dict):
            continue
        mt = str(raw.get("media_type") or "").strip().lower()
        if mt not in {"movie", "tv"}:
            continue
        if not raw.get("id"):
            continue
        items.append(_map_tmdb_list_item(raw, mt))
    return items, max(1, int(data.get("total_pages") or 1))


async def _douban_suggest_one(
    client: httpx.AsyncClient, query: str
) -> list[dict[str, Any]]:
    r = await client.get(
        "https://movie.douban.com/j/subject_suggest",
        params={"q": query},
        headers={
            "User-Agent": _DOUBAN_UA,
            "Referer": "https://movie.douban.com/",
            "Accept": "application/json, text/plain, */*",
        },
    )
    if r.status_code in {403, 418, 429}:
        raise HTTPException(status_code=502, detail="豆瓣暂时拒绝访问（风控）")
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"豆瓣返回 {r.status_code}")
    try:
        rows = r.json() or []
    except Exception as e:
        raise HTTPException(status_code=502, detail="豆瓣响应非 JSON") from e
    if not isinstance(rows, list):
        rows = []
    items: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        typ = str(raw.get("type") or "movie").strip().lower()
        mt = "tv" if typ in {"tv", "drama", "show"} else "movie"
        cover = _normalize_douban_cover(
            str(raw.get("img") or raw.get("cover") or "").strip() or None
        )
        items.append(
            _norm_item(
                source="douban",
                id_=str(raw.get("id")),
                media_type=mt,
                title=str(raw.get("title") or "").strip(),
                original_title=str(raw.get("sub_title") or "").strip(),
                poster_url=cover,
                year=str(raw.get("year") or "").strip() or None,
            )
        )
    return items


# ─── 豆瓣 ─────────────────────────────────────────────


def _douban_tag_for(category: str, chart: str) -> tuple[str, str]:
    """返回 (type, tag) 给 j/search_subjects。"""
    if category == "movie":
        if chart == "new":
            return "movie", "最新"
        if chart == "top250":
            return "movie", "豆瓣高分"
        if chart == "cn":
            return "movie", "华语"
        if chart == "western":
            return "movie", "欧美"
        return "movie", "热门"
    if category == "tv":
        if chart == "new":
            return "tv", "国产剧"
        if chart == "jp":
            return "tv", "日剧"
        if chart == "kr":
            return "tv", "韩剧"
        if chart == "cn":
            return "tv", "国产剧"
        return "tv", "热门"
    if category == "anime":
        # 「动漫」标签已空；官网 TV 标签为「日本动画」
        return "tv", "日本动画"
    return "tv", "综艺"


async def _douban_search_subjects(
    client: httpx.AsyncClient,
    *,
    typ: str,
    tag: str,
    page_start: int = 0,
    page_limit: int = 20,
) -> list[dict[str, Any]]:
    r = await client.get(
        "https://movie.douban.com/j/search_subjects",
        params={
            "type": typ,
            "tag": tag,
            "sort": "recommend",
            "page_limit": page_limit,
            "page_start": page_start,
        },
        headers={
            "User-Agent": _DOUBAN_UA,
            "Referer": "https://movie.douban.com/",
            "Accept": "application/json, text/plain, */*",
        },
    )
    if r.status_code in {403, 418, 429}:
        raise HTTPException(
            status_code=502,
            detail="豆瓣暂时拒绝访问（风控），请稍后再试",
        )
    if not r.is_success:
        raise HTTPException(
            status_code=502, detail=f"豆瓣返回 {r.status_code}"
        )
    try:
        data = r.json() or {}
    except Exception as e:
        raise HTTPException(status_code=502, detail="豆瓣响应非 JSON") from e
    subjects = data.get("subjects") if isinstance(data, dict) else None
    if not isinstance(subjects, list):
        return []
    return [x for x in subjects if isinstance(x, dict)]


def _normalize_douban_cover(url: str | None) -> str | None:
    """豆瓣图床 img9 等常对桌面 Referer 返回挑战页；统一到较稳的 img3。"""
    s = str(url or "").strip()
    if not s:
        return None
    return re.sub(
        r"https?://img\d+\.doubanio\.com",
        "https://img3.doubanio.com",
        s,
        count=1,
        flags=re.I,
    )


def _map_douban_subject(raw: dict[str, Any], media_type: str) -> dict[str, Any]:
    sid = str(raw.get("id") or "").strip()
    title = str(raw.get("title") or "").strip()
    # rate 字段常为字符串
    rate_raw = raw.get("rate") or raw.get("rating") or raw.get("score")
    try:
        rating_f = float(rate_raw) if rate_raw not in (None, "") else None
    except (TypeError, ValueError):
        rating_f = None
    cover = _normalize_douban_cover(
        str(raw.get("cover") or raw.get("cover_url") or "").strip() or None
    )
    return _norm_item(
        source="douban",
        id_=sid,
        media_type=media_type,
        title=title,
        poster_url=cover,
        rating=rating_f,
    )


@router.get("/media/douban/charts")
async def douban_charts(
    category: str = Query("movie"),
    chart: str = Query("hot"),
    page: int = Query(1, ge=1, le=20),
) -> dict[str, Any]:
    cat = (category or "movie").strip().lower()
    ch = (chart or "hot").strip().lower()
    if cat not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"未知分类: {category}")
    if ch not in DOUBAN_CHARTS:
        raise HTTPException(status_code=400, detail=f"未知榜单: {chart}")

    cache_key = f"douban:charts:{cat}:{ch}:{page}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return _wrap(cached)

    typ, tag = _douban_tag_for(cat, ch)
    media_type = "movie" if typ == "movie" else "tv"
    start = (page - 1) * 20

    try:
        async with httpx.AsyncClient(**_DOUBAN_HTTPX_KW) as client:
            if cat == "movie" and ch == "top250":
                # Top250 专用页解析
                items = await _douban_top250(client, page=page)
            else:
                rows = await _douban_search_subjects(
                    client, typ=typ, tag=tag, page_start=start, page_limit=20
                )
                items = [_map_douban_subject(x, media_type) for x in rows if x.get("id")]
    except HTTPException:
        raise
    except httpx.ConnectError as e:
        log.warning("douban charts connect failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail="无法连接豆瓣（网络或系统代理异常），请检查代理设置后重试",
        ) from e
    except Exception as e:
        log.warning("douban charts failed: %s", e)
        msg = str(e).strip() or e.__class__.__name__
        raise HTTPException(status_code=502, detail=f"豆瓣拉取失败: {msg}") from e

    payload = {
        "source": "douban",
        "category": cat,
        "chart": ch,
        "page": page,
        "totalPages": 10 if ch == "top250" else 5,
        "items": items,
    }
    # 空结果不长缓存，避免错误标签把「暂无内容」锁住数小时
    _cache_set(cache_key, payload, ttl=120.0 if not items else _CACHE_TTL_S)
    return _wrap(payload)


async def _douban_top250(
    client: httpx.AsyncClient, *, page: int
) -> list[dict[str, Any]]:
    start = (page - 1) * 25
    r = await client.get(
        "https://movie.douban.com/top250",
        params={"start": start},
        headers={
            "User-Agent": _DOUBAN_UA,
            "Referer": "https://movie.douban.com/",
        },
    )
    if r.status_code in {403, 418, 429}:
        raise HTTPException(
            status_code=502, detail="豆瓣暂时拒绝访问（风控），请稍后再试"
        )
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"豆瓣 Top250 返回 {r.status_code}")
    html = r.text or ""
    items: list[dict[str, Any]] = []
    # <div class="item"> ... <a href="https://movie.douban.com/subject/1292052/">
    for m in re.finditer(
        r'href="https://movie\.douban\.com/subject/(\d+)/"[^>]*>\s*<img[^>]+alt="([^"]+)"[^>]+src="([^"]+)"',
        html,
    ):
        sid, title, cover = m.group(1), m.group(2), m.group(3)
        # rating nearby
        rating_f = None
        chunk = html[m.start() : m.start() + 800]
        rm = re.search(r'property="v:average">([\d.]+)<', chunk)
        if rm:
            try:
                rating_f = float(rm.group(1))
            except ValueError:
                pass
                items.append(
            _norm_item(
                source="douban",
                id_=sid,
                media_type="movie",
                title=title,
                poster_url=_normalize_douban_cover(cover),
                rating=rating_f,
            )
        )
    return items


@router.get("/media/douban/subject/{subject_id}")
async def douban_detail(subject_id: str) -> dict[str, Any]:
    sid = str(subject_id or "").strip()
    if not sid.isdigit():
        raise HTTPException(status_code=400, detail="无效豆瓣 id")

    cache_key = f"douban:detail:{sid}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return _wrap(cached)

    # 桌面站 subject HTML 常被 JS 挑战截断；走移动端 rexxar JSON。
    url = f"https://m.douban.com/rexxar/api/v2/subject/{sid}"
    try:
        async with httpx.AsyncClient(**_DOUBAN_HTTPX_KW) as client:
            r = await client.get(
                url,
                headers={
                    "User-Agent": _DOUBAN_MOBILE_UA,
                    "Referer": f"https://m.douban.com/movie/subject/{sid}/",
                    "Origin": "https://m.douban.com",
                    "Accept": "application/json, text/plain, */*",
                },
            )
    except httpx.ConnectError as e:
        raise HTTPException(
            status_code=502,
            detail="无法连接豆瓣（网络或系统代理异常），请检查代理设置后重试",
        ) from e
    except Exception as e:
        msg = str(e).strip() or e.__class__.__name__
        raise HTTPException(status_code=502, detail=f"豆瓣详情失败: {msg}") from e

    if r.status_code in {403, 418, 429}:
        raise HTTPException(
            status_code=502, detail="豆瓣暂时拒绝访问（风控），请稍后再试"
        )
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="作品不存在")
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"豆瓣返回 {r.status_code}")

    try:
        data = r.json() or {}
    except Exception as e:
        raise HTTPException(status_code=502, detail="豆瓣详情非 JSON") from e
    if not isinstance(data, dict) or not data.get("id"):
        raise HTTPException(status_code=502, detail="豆瓣详情无效")

    title = str(data.get("title") or "").strip()
    original = str(data.get("original_title") or "").strip()
    aka_raw = data.get("aka")
    aka: list[str] = []
    if isinstance(aka_raw, list):
        for part in aka_raw:
            s = str(part or "").strip()
            if s and s != title and s != original:
                aka.append(s)

    year = str(data.get("year") or "").strip() or None
    if year and not year.isdigit():
        year = _year_from(year)

    rating_f = None
    rating = data.get("rating")
    if isinstance(rating, dict):
        try:
            val = rating.get("value")
            rating_f = float(val) if val not in (None, "", 0, 0.0) else None
        except (TypeError, ValueError):
            rating_f = None

    poster = None
    pic = data.get("pic")
    if isinstance(pic, dict):
        poster = str(pic.get("large") or pic.get("normal") or "").strip() or None
    if not poster:
        poster = str(data.get("cover_url") or data.get("cover") or "").strip() or None
    poster = _normalize_douban_cover(poster)

    overview = str(data.get("intro") or "").strip()

    typ = str(data.get("type") or data.get("subtype") or "").strip().lower()
    if typ in {"tv", "show"} or data.get("is_tv") is True:
        media_type = "tv"
    else:
        media_type = "movie"

    cast: list[str] = []
    for key in ("directors", "actors"):
        rows = data.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                name = str(row.get("name") or "").strip()
            else:
                name = str(row or "").strip()
            if name and name not in cast:
                cast.append(name)

    item = _norm_item(
        source="douban",
        id_=sid,
        media_type=media_type,
        title=title or sid,
        original_title=original,
        aka=aka[:20],
        poster_url=poster,
        year=year,
        rating=rating_f,
        overview=overview,
    )
    if cast:
        item["cast"] = cast[:12]
    genres_db: list[str] = []
    for g in data.get("genres") or []:
        if isinstance(g, str) and g.strip():
            genres_db.append(g.strip())
        elif isinstance(g, dict) and g.get("name"):
            genres_db.append(str(g["name"]))
    if genres_db:
        item["genres"] = genres_db[:12]
    countries_db: list[str] = []
    for c in data.get("countries") or []:
        if isinstance(c, str) and c.strip():
            countries_db.append(c.strip())
    if countries_db:
        item["countries"] = countries_db[:8]
    _cache_set(cache_key, item)
    return _wrap(item)


@router.get("/media/meta")
def media_meta() -> dict[str, Any]:
    """前端 Hub 用的分类 / 榜单目录。"""
    tmdb_ok = bool(get_tmdb_api_key())
    return _wrap(
        {
            "tmdbConfigured": tmdb_ok,
            "categories": [
                {"id": "movie", "label": "电影"},
                {"id": "tv", "label": "电视剧"},
                {"id": "anime", "label": "动漫"},
                {"id": "variety", "label": "综艺"},
            ],
            "sources": [
                {
                    "id": "tmdb",
                    "label": "TMDB",
                    "charts": [
                        {"id": "trending", "label": "本周趋势"},
                        {"id": "now_playing", "label": "正在热映"},
                        {"id": "upcoming", "label": "即将上映"},
                        {"id": "popular", "label": "热门"},
                        {"id": "top_rated", "label": "高分"},
                        {"id": "on_the_air", "label": "播出中"},
                    ],
                },
                {
                    "id": "douban",
                    "label": "豆瓣",
                    "charts": [
                        {"id": "hot", "label": "热门"},
                        {"id": "top250", "label": "Top250"},
                        {"id": "new", "label": "新片/新剧"},
                        {"id": "cn", "label": "华语"},
                        {"id": "western", "label": "欧美"},
                        {"id": "jp", "label": "日剧"},
                        {"id": "kr", "label": "韩剧"},
                    ],
                },
            ],
        }
    )
