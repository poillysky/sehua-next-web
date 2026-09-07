"""Bangumi / AniList 公开 API（动漫向；无需 Key）。"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from fastapi import HTTPException

log = logging.getLogger(__name__)

_BGM_UA = "sehua-next-web/1.0 (media hub; contact: local-dev)"
_BGM_BASE = "https://api.bgm.tv"
_ANILIST_URL = "https://graphql.anilist.co"

_HTTPX_KW: dict[str, Any] = {
    "timeout": httpx.Timeout(12.0, connect=5.0),
    "trust_env": False,
    "follow_redirects": True,
}

# Bangumi SubjectType
_BGM_ANIME = 2
_BGM_REAL = 6

BANGUMI_CHARTS = ("rank", "heat", "score", "calendar", "real")
ANILIST_CHARTS = (
    "trending",
    "popular",
    "top_rated",
    "airing",
    "upcoming",
    "movies",
)


def _year_from(date_s: str | None) -> str | None:
    s = str(date_s or "").strip()
    if len(s) >= 4 and s[:4].isdigit():
        return s[:4]
    return None


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
    titles: list[str] = []
    for t in [title, original_title, *(aka or [])]:
        s = str(t or "").strip()
        if s and s not in titles:
            titles.append(s)
    return {
        "source": source,
        "id": str(id_),
        "mediaType": media_type if media_type in {"movie", "tv"} else "tv",
        "title": titles[0] if titles else str(id_),
        "originalTitle": original_title or None,
        "aka": titles[1:],
        "posterUrl": poster_url or None,
        "year": year or None,
        "rating": rating,
        "overview": (overview or "").strip() or None,
    }


def _bgm_headers() -> dict[str, str]:
    return {
        "User-Agent": _BGM_UA,
        "Accept": "application/json",
    }


def _map_bangumi_subject(raw: dict[str, Any]) -> dict[str, Any] | None:
    sid = raw.get("id")
    if sid is None:
        return None
    name = str(raw.get("name") or "").strip()
    name_cn = str(raw.get("name_cn") or "").strip()
    title = name_cn or name
    original = name if name_cn and name and name != name_cn else ""
    images = raw.get("images") if isinstance(raw.get("images"), dict) else {}
    poster = (
        str(images.get("large") or images.get("common") or images.get("medium") or "")
        .strip()
        or None
    )
    date_s = str(raw.get("date") or raw.get("air_date") or "").strip()
    score = None
    rating = raw.get("rating") if isinstance(raw.get("rating"), dict) else {}
    if rating.get("score") not in (None, "", 0):
        try:
            score = float(rating["score"])
        except (TypeError, ValueError):
            score = None
    summary = str(raw.get("summary") or "").strip()
    # Bangumi 动画/三次元都按剧集展示
    return _norm_item(
        source="bangumi",
        id_=str(sid),
        media_type="tv",
        title=title,
        original_title=original,
        poster_url=poster,
        year=_year_from(date_s),
        rating=score,
        overview=summary,
    )


async def bangumi_browse(
    client: httpx.AsyncClient,
    *,
    chart: str,
    page: int,
) -> tuple[list[dict[str, Any]], int]:
    limit = 20
    offset = (page - 1) * limit
    ch = (chart or "rank").strip().lower()

    if ch == "calendar":
        r = await client.get(f"{_BGM_BASE}/calendar", headers=_bgm_headers())
        if not r.is_success:
            raise HTTPException(status_code=502, detail=f"Bangumi 返回 {r.status_code}")
        days = r.json() if isinstance(r.json(), list) else []
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for day in days:
            if not isinstance(day, dict):
                continue
            for row in day.get("items") or []:
                if not isinstance(row, dict):
                    continue
                mapped = _map_bangumi_subject(row)
                if not mapped or mapped["id"] in seen:
                    continue
                seen.add(mapped["id"])
                items.append(mapped)
        # 简单分页
        total_pages = max(1, (len(items) + limit - 1) // limit)
        slice_ = items[offset : offset + limit]
        return slice_, total_pages

    if ch == "real":
        typ = _BGM_REAL
        sort = "rank"
    elif ch == "heat":
        typ = _BGM_ANIME
        # browse API sort 仅 date|rank；热门用 search
        return await bangumi_search_page(
            client, keyword="", page=page, sort="heat", typ=_BGM_ANIME
        )
    elif ch == "score":
        typ = _BGM_ANIME
        return await bangumi_search_page(
            client, keyword="", page=page, sort="score", typ=_BGM_ANIME
        )
    else:
        typ = _BGM_ANIME
        sort = "rank"

    r = await client.get(
        f"{_BGM_BASE}/v0/subjects",
        params={"type": typ, "sort": sort, "limit": limit, "offset": offset},
        headers=_bgm_headers(),
    )
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"Bangumi 返回 {r.status_code}")
    data = r.json() if isinstance(r.json(), dict) else {}
    rows = data.get("data") if isinstance(data.get("data"), list) else []
    total = int(data.get("total") or 0)
    items = []
    for row in rows:
        if isinstance(row, dict):
            m = _map_bangumi_subject(row)
            if m:
                items.append(m)
    total_pages = max(1, (total + limit - 1) // limit) if total else max(1, page)
    return items, total_pages


async def bangumi_search_page(
    client: httpx.AsyncClient,
    *,
    keyword: str,
    page: int,
    sort: str = "match",
    typ: int = _BGM_ANIME,
) -> tuple[list[dict[str, Any]], int]:
    limit = 20
    offset = (page - 1) * limit
    # 空关键词时用通配热度/评分榜
    kw = (keyword or "").strip() or ("动画" if typ == _BGM_ANIME else "剧集")
    body: dict[str, Any] = {
        "keyword": kw,
        "sort": sort if sort in {"match", "heat", "rank", "score"} else "match",
        "filter": {"type": [typ]},
    }
    r = await client.post(
        f"{_BGM_BASE}/v0/search/subjects",
        params={"limit": limit, "offset": offset},
        json=body,
        headers=_bgm_headers(),
    )
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"Bangumi 搜索返回 {r.status_code}")
    data = r.json() if isinstance(r.json(), dict) else {}
    rows = data.get("data") if isinstance(data.get("data"), list) else []
    total = int(data.get("total") or 0)
    items = []
    for row in rows:
        if isinstance(row, dict):
            m = _map_bangumi_subject(row)
            if m:
                items.append(m)
    total_pages = max(1, (total + limit - 1) // limit) if total else 1
    return items, total_pages


async def bangumi_detail(client: httpx.AsyncClient, subject_id: str) -> dict[str, Any]:
    r = await client.get(
        f"{_BGM_BASE}/v0/subjects/{subject_id}",
        headers=_bgm_headers(),
    )
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Bangumi 条目不存在")
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"Bangumi 返回 {r.status_code}")
    raw = r.json() if isinstance(r.json(), dict) else {}
    mapped = _map_bangumi_subject(raw)
    if not mapped:
        raise HTTPException(status_code=404, detail="Bangumi 条目无效")
    # 补充详情字段
    tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
    genres = []
    for t in tags[:12]:
        if isinstance(t, dict) and t.get("name"):
            genres.append(str(t["name"]))
        elif isinstance(t, str):
            genres.append(t)
    if genres:
        mapped["genres"] = genres
    cast = await bangumi_subject_cast(client, subject_id)
    if cast:
        mapped["cast"] = cast
    return mapped


def _bgm_person_avatar(images: Any) -> str | None:
    if not isinstance(images, dict):
        return None
    for key in ("large", "medium", "common", "small", "grid"):
        url = str(images.get(key) or "").strip()
        if url:
            return url
    return None


def _map_bgm_cast_person(raw: dict[str, Any]) -> dict[str, Any] | None:
    pid = raw.get("id")
    name_cn = str(raw.get("name_cn") or "").strip()
    name = str(raw.get("name") or "").strip()
    title = name_cn or name
    if not title:
        return None
    person: dict[str, Any] = {"name": title}
    if pid is not None:
        person["id"] = str(pid)
    avatar = _bgm_person_avatar(raw.get("images"))
    if avatar:
        person["avatarUrl"] = avatar
    return person


async def bangumi_subject_cast(
    client: httpx.AsyncClient, subject_id: str
) -> list[dict[str, Any]]:
    """优先角色配音 / 演员；不足时补人物表。"""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _push(raw: dict[str, Any] | None) -> None:
        if not isinstance(raw, dict):
            return
        mapped = _map_bgm_cast_person(raw)
        if not mapped:
            return
        key = mapped.get("id") or mapped["name"]
        if key in seen:
            return
        seen.add(str(key))
        items.append(mapped)

    # 角色 → 声优 / 演员
    try:
        cr = await client.get(
            f"{_BGM_BASE}/v0/subjects/{subject_id}/characters",
            headers=_bgm_headers(),
        )
        if cr.is_success:
            rows = cr.json() if isinstance(cr.json(), list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                actors = row.get("actors") if isinstance(row.get("actors"), list) else []
                if actors and isinstance(actors[0], dict):
                    _push(actors[0])
                else:
                    # 无声优时用角色脸（无人物 id，仅展示）
                    mapped = _map_bgm_cast_person(row)
                    if mapped:
                        mapped.pop("id", None)
                        key = f"char:{mapped['name']}"
                        if key not in seen:
                            seen.add(key)
                            items.append(mapped)
                if len(items) >= 12:
                    return items
    except Exception:
        pass

    # 人物关系表（导演 / 主演等）
    try:
        pr = await client.get(
            f"{_BGM_BASE}/v0/subjects/{subject_id}/persons",
            headers=_bgm_headers(),
        )
        if pr.is_success:
            rows = pr.json() if isinstance(pr.json(), list) else []
            prefer = ("主演", "演员", "主角", "配音", "声优", "导演")
            preferred_rows: list[dict[str, Any]] = []
            other_rows: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                rel = str(row.get("relation") or "")
                if any(p in rel for p in prefer):
                    preferred_rows.append(row)
                else:
                    other_rows.append(row)
            for row in preferred_rows + other_rows:
                _push(row)
                if len(items) >= 12:
                    break
    except Exception:
        pass

    return items[:12]


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _map_anilist_media(raw: dict[str, Any]) -> dict[str, Any] | None:
    mid = raw.get("id")
    if mid is None:
        return None
    title_obj = raw.get("title") if isinstance(raw.get("title"), dict) else {}
    native = str(title_obj.get("native") or "").strip()
    romaji = str(title_obj.get("romaji") or "").strip()
    english = str(title_obj.get("english") or "").strip()
    title = native or romaji or english or str(mid)
    original = romaji if native and romaji and romaji != native else (english or "")
    aka = []
    for t in (romaji, english, native):
        if t and t != title and t not in aka:
            aka.append(t)
    cover = raw.get("coverImage") if isinstance(raw.get("coverImage"), dict) else {}
    poster = str(cover.get("large") or cover.get("medium") or "").strip() or None
    start = raw.get("startDate") if isinstance(raw.get("startDate"), dict) else {}
    year = str(start.get("year") or "") if start.get("year") else None
    score = None
    if raw.get("averageScore") not in (None, ""):
        try:
            score = float(raw["averageScore"]) / 10.0  # 百分制 → 十分制
        except (TypeError, ValueError):
            score = None
    fmt = str(raw.get("format") or "").upper()
    media_type = "movie" if fmt in {"MOVIE", "MUSIC"} else "tv"
    overview = _strip_html(str(raw.get("description") or ""))
    item = _norm_item(
        source="anilist",
        id_=str(mid),
        media_type=media_type,
        title=title,
        original_title=original,
        aka=aka,
        poster_url=poster,
        year=year,
        rating=score,
        overview=overview,
    )
    genres = raw.get("genres") if isinstance(raw.get("genres"), list) else []
    if genres:
        item["genres"] = [str(g) for g in genres if g][:12]
    if raw.get("episodes"):
        try:
            item["runtime"] = int(raw["episodes"])
        except (TypeError, ValueError):
            pass
    return item


_ANILIST_PAGE_QUERY = """
query (
  $page: Int
  $perPage: Int
  $sort: [MediaSort]
  $search: String
  $type: MediaType
  $status: MediaStatus
  $format: MediaFormat
) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { total lastPage currentPage }
    media(
      sort: $sort
      search: $search
      type: $type
      status: $status
      format: $format
      isAdult: false
    ) {
      id
      title { romaji english native }
      coverImage { large medium }
      startDate { year }
      averageScore
      description(asHtml: false)
      format
      episodes
      genres
      status
    }
  }
}
"""


async def anilist_page(
    client: httpx.AsyncClient,
    *,
    page: int,
    chart: str = "trending",
    search: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    ch = (chart or "trending").strip().lower()
    variables: dict[str, Any] = {
        "page": page,
        "perPage": 20,
        "type": "ANIME",
    }
    if search:
        variables["search"] = search
        variables["sort"] = ["SEARCH_MATCH"]
    elif ch == "popular":
        variables["sort"] = ["POPULARITY_DESC"]
    elif ch == "top_rated":
        variables["sort"] = ["SCORE_DESC"]
    elif ch == "airing":
        variables["sort"] = ["POPULARITY_DESC"]
        variables["status"] = "RELEASING"
    elif ch == "upcoming":
        variables["sort"] = ["POPULARITY_DESC"]
        variables["status"] = "NOT_YET_RELEASED"
    elif ch == "movies":
        variables["sort"] = ["POPULARITY_DESC"]
        variables["format"] = "MOVIE"
    else:
        variables["sort"] = ["TRENDING_DESC"]

    r = await client.post(
        _ANILIST_URL,
        json={"query": _ANILIST_PAGE_QUERY, "variables": variables},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"AniList 返回 {r.status_code}")
    try:
        payload = r.json() or {}
    except Exception as e:
        raise HTTPException(status_code=502, detail="AniList 响应非 JSON") from e
    if payload.get("errors"):
        msg = payload["errors"][0].get("message") if payload["errors"] else "AniList 错误"
        raise HTTPException(status_code=502, detail=str(msg))
    page_data = ((payload.get("data") or {}).get("Page")) or {}
    media = page_data.get("media") if isinstance(page_data.get("media"), list) else []
    info = page_data.get("pageInfo") if isinstance(page_data.get("pageInfo"), dict) else {}
    last = int(info.get("lastPage") or 1)
    items = []
    for row in media:
        if isinstance(row, dict):
            m = _map_anilist_media(row)
            if m:
                items.append(m)
    return items, max(1, last)


async def anilist_detail(client: httpx.AsyncClient, media_id: str) -> dict[str, Any]:
    query = """
    query ($id: Int) {
      Media(id: $id, type: ANIME) {
        id
        title { romaji english native }
        coverImage { large medium }
        startDate { year }
        averageScore
        description(asHtml: false)
        format
        episodes
        genres
        countryOfOrigin
        duration
        characters(page: 1, perPage: 12, sort: [ROLE, RELEVANCE, ID]) {
          edges {
            role
            node {
              id
              name { full native }
              image { large medium }
            }
            voiceActors(language: JAPANESE, sort: [RELEVANCE]) {
              id
              name { full native }
              image { large medium }
            }
          }
        }
      }
    }
    """
    try:
        mid = int(media_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="无效 AniList id") from e
    r = await client.post(
        _ANILIST_URL,
        json={"query": query, "variables": {"id": mid}},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"AniList 返回 {r.status_code}")
    payload = r.json() if isinstance(r.json(), dict) else {}
    if payload.get("errors"):
        raise HTTPException(status_code=404, detail="AniList 条目不存在")
    raw = ((payload.get("data") or {}).get("Media")) or None
    if not isinstance(raw, dict):
        raise HTTPException(status_code=404, detail="AniList 条目不存在")
    mapped = _map_anilist_media(raw)
    if not mapped:
        raise HTTPException(status_code=404, detail="AniList 条目无效")
    if raw.get("duration"):
        try:
            mapped["runtime"] = int(raw["duration"])
        except (TypeError, ValueError):
            pass
    if raw.get("countryOfOrigin"):
        mapped["countries"] = [str(raw["countryOfOrigin"])]
    cast = _anilist_cast_from_characters(raw.get("characters"))
    if cast:
        mapped["cast"] = cast
    return mapped


def _anilist_cast_from_characters(characters: Any) -> list[dict[str, Any]]:
    if not isinstance(characters, dict):
        return []
    edges = characters.get("edges") if isinstance(characters.get("edges"), list) else []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        vas = edge.get("voiceActors") if isinstance(edge.get("voiceActors"), list) else []
        node = edge.get("node") if isinstance(edge.get("node"), dict) else {}
        # 优先声优（可点进人物作品）；无声优则用角色脸
        person_raw = vas[0] if vas and isinstance(vas[0], dict) else node
        if not isinstance(person_raw, dict):
            continue
        name_obj = person_raw.get("name") if isinstance(person_raw.get("name"), dict) else {}
        name = str(
            name_obj.get("native") or name_obj.get("full") or ""
        ).strip()
        if not name:
            continue
        pid = person_raw.get("id")
        key = str(pid) if pid is not None else name
        if key in seen:
            continue
        seen.add(key)
        person: dict[str, Any] = {"name": name}
        # 仅声优带 staff id，角色 id 点进作品会错
        if vas and isinstance(vas[0], dict) and vas[0].get("id") is not None:
            person["id"] = str(vas[0]["id"])
        img = person_raw.get("image") if isinstance(person_raw.get("image"), dict) else {}
        avatar = str(img.get("large") or img.get("medium") or "").strip()
        if avatar:
            person["avatarUrl"] = avatar
        items.append(person)
        if len(items) >= 12:
            break
    return items


async def bangumi_related(
    client: httpx.AsyncClient, subject_id: str
) -> list[dict[str, Any]]:
    r = await client.get(
        f"{_BGM_BASE}/v0/subjects/{subject_id}/subjects",
        headers=_bgm_headers(),
    )
    if r.status_code == 404:
        return []
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"Bangumi 相关返回 {r.status_code}")
    data = r.json()
    rows = data if isinstance(data, list) else []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        sub = row.get("subject") if isinstance(row.get("subject"), dict) else row
        if not isinstance(sub, dict):
            continue
        mapped = _map_bangumi_subject(sub)
        if not mapped or mapped["id"] == str(subject_id) or mapped["id"] in seen:
            continue
        seen.add(mapped["id"])
        items.append(mapped)
        if len(items) >= 16:
            break
    return items


async def anilist_related(
    client: httpx.AsyncClient, media_id: str
) -> list[dict[str, Any]]:
    query = """
    query ($id: Int) {
      Media(id: $id, type: ANIME) {
        recommendations(page: 1, perPage: 16, sort: [RATING_DESC]) {
          nodes {
            mediaRecommendation {
              id
              title { romaji english native }
              coverImage { large medium }
              startDate { year }
              averageScore
              description(asHtml: false)
              format
              episodes
              genres
            }
          }
        }
        relations {
          edges {
            relationType
            node {
              id
              title { romaji english native }
              coverImage { large medium }
              startDate { year }
              averageScore
              description(asHtml: false)
              format
              episodes
              genres
              type
            }
          }
        }
      }
    }
    """
    try:
        mid = int(media_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="无效 AniList id") from e
    r = await client.post(
        _ANILIST_URL,
        json={"query": query, "variables": {"id": mid}},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"AniList 返回 {r.status_code}")
    payload = r.json() if isinstance(r.json(), dict) else {}
    if payload.get("errors"):
        return []
    media = ((payload.get("data") or {}).get("Media")) or {}
    if not isinstance(media, dict):
        return []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _push(raw: dict[str, Any] | None) -> None:
        if not isinstance(raw, dict):
            return
        typ = str(raw.get("type") or "ANIME").upper()
        if typ and typ != "ANIME":
            return
        mapped = _map_anilist_media(raw)
        if not mapped or mapped["id"] == str(media_id) or mapped["id"] in seen:
            return
        seen.add(mapped["id"])
        items.append(mapped)

    rec = media.get("recommendations") if isinstance(media.get("recommendations"), dict) else {}
    for node in rec.get("nodes") or []:
        if isinstance(node, dict):
            _push(node.get("mediaRecommendation") if isinstance(node.get("mediaRecommendation"), dict) else None)
        if len(items) >= 16:
            return items

    rel = media.get("relations") if isinstance(media.get("relations"), dict) else {}
    for edge in rel.get("edges") or []:
        if isinstance(edge, dict):
            _push(edge.get("node") if isinstance(edge.get("node"), dict) else None)
        if len(items) >= 16:
            break
    return items


async def bangumi_person_works(
    client: httpx.AsyncClient,
    *,
    name: str = "",
    person_id: str = "",
) -> tuple[str, str, list[dict[str, Any]]]:
    """返回 (personId, displayName, items)。"""
    pid = str(person_id or "").strip()
    display = (name or "").strip()
    if not pid.isdigit():
        # POST /v0/search/persons
        r = await client.post(
            f"{_BGM_BASE}/v0/search/persons",
            params={"limit": 5, "offset": 0},
            json={"keyword": display or name},
            headers=_bgm_headers(),
        )
        if not r.is_success:
            raise HTTPException(status_code=502, detail=f"Bangumi 人物搜索返回 {r.status_code}")
        data = r.json() if isinstance(r.json(), dict) else {}
        rows = data.get("data") if isinstance(data.get("data"), list) else []
        if not rows or not isinstance(rows[0], dict) or rows[0].get("id") is None:
            raise HTTPException(status_code=404, detail=f"未找到人物「{name}」")
        pid = str(rows[0]["id"])
        display = str(rows[0].get("name") or display or pid).strip()

    r = await client.get(
        f"{_BGM_BASE}/v0/persons/{pid}/subjects",
        headers=_bgm_headers(),
    )
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Bangumi 人物不存在")
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"Bangumi 人物作品返回 {r.status_code}")
    rows = r.json() if isinstance(r.json(), list) else []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        # shape: { id, name, name_cn, ... } or nested subject
        sub = row.get("subject") if isinstance(row.get("subject"), dict) else row
        if not isinstance(sub, dict):
            continue
        mapped = _map_bangumi_subject(sub)
        if not mapped or mapped["id"] in seen:
            continue
        seen.add(mapped["id"])
        items.append(mapped)
        if len(items) >= 40:
            break

    if not display:
        pr = await client.get(f"{_BGM_BASE}/v0/persons/{pid}", headers=_bgm_headers())
        if pr.is_success:
            pdata = pr.json() if isinstance(pr.json(), dict) else {}
            display = str(pdata.get("name") or pdata.get("name_cn") or pid).strip()

    return pid, display or pid, items


async def anilist_staff_works(
    client: httpx.AsyncClient,
    *,
    name: str = "",
    staff_id: str = "",
) -> tuple[str, str, list[dict[str, Any]]]:
    sid = str(staff_id or "").strip()
    display = (name or "").strip()
    query = """
    query ($id: Int, $search: String) {
      Staff(id: $id, search: $search) {
        id
        name { full native }
        staffMedia(page: 1, perPage: 40, sort: [POPULARITY_DESC]) {
          edges {
            node {
              id
              type
              title { romaji english native }
              coverImage { large medium }
              startDate { year }
              averageScore
              description(asHtml: false)
              format
              episodes
              genres
            }
          }
        }
        characters(page: 1, perPage: 25, sort: [FAVOURITES_DESC]) {
          edges {
            node { id name { full } }
            media {
              id
              type
              title { romaji english native }
              coverImage { large medium }
              startDate { year }
              averageScore
              description(asHtml: false)
              format
              episodes
              genres
            }
          }
        }
      }
    }
    """
    variables: dict[str, Any] = {}
    if sid.isdigit():
        variables["id"] = int(sid)
    elif display:
        variables["search"] = display
    else:
        raise HTTPException(status_code=400, detail="请提供影人姓名或 id")

    r = await client.post(
        _ANILIST_URL,
        json={"query": query, "variables": variables},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"AniList 返回 {r.status_code}")
    payload = r.json() if isinstance(r.json(), dict) else {}
    if payload.get("errors"):
        raise HTTPException(status_code=404, detail=f"未找到人物「{name or sid}」")
    staff = ((payload.get("data") or {}).get("Staff")) or None
    if not isinstance(staff, dict):
        raise HTTPException(status_code=404, detail=f"未找到人物「{name or sid}」")

    out_id = str(staff.get("id") or sid)
    name_obj = staff.get("name") if isinstance(staff.get("name"), dict) else {}
    display = (
        str(name_obj.get("native") or name_obj.get("full") or display or out_id).strip()
    )

    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _push_media(raw: Any) -> None:
        if not isinstance(raw, dict):
            return
        if str(raw.get("type") or "ANIME").upper() != "ANIME":
            return
        mapped = _map_anilist_media(raw)
        if not mapped or mapped["id"] in seen:
            return
        seen.add(mapped["id"])
        items.append(mapped)

    staff_media = staff.get("staffMedia") if isinstance(staff.get("staffMedia"), dict) else {}
    for edge in staff_media.get("edges") or []:
        if isinstance(edge, dict):
            _push_media(edge.get("node"))
        if len(items) >= 40:
            break

    if len(items) < 12:
        chars = staff.get("characters") if isinstance(staff.get("characters"), dict) else {}
        for edge in chars.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            media_list = edge.get("media")
            if isinstance(media_list, list):
                for m in media_list:
                    _push_media(m)
                    if len(items) >= 40:
                        break
            elif isinstance(media_list, dict):
                _push_media(media_list)
            if len(items) >= 40:
                break

    return out_id, display, items


def client_kwargs(proxy: str = "") -> dict[str, Any]:
    kw = dict(_HTTPX_KW)
    if proxy:
        kw["trust_env"] = False
        kw["proxy"] = proxy
    return kw
