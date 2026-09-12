"""小花助手：检索工具适配层。"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx

from app.ai.assistant_protocol import make_card, merge_cards, select_ui_cards
from app.ai.config import resolve_web_search_config
from app.search.sehua_embed import display_hit_label

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

_SOURCE_LABEL = {
    "sehua": "仓库",
    "magnet": "磁力",
    "scrap": "片商",
    "media": "影视",
    "web": "网络",
}

_WEB_META_LABELS = (
    "导演",
    "主演",
    "演员",
    "类型",
    "制片国家/地区",
    "制片国家",
    "地区",
    "上映日期",
    "片长",
    "年份",
    "评分",
    "评语",
)


def _web_host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except Exception:  # noqa: BLE001
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _format_web_meta(snippet: str) -> str:
    text = re.sub(r"\s+", " ", str(snippet or "")).strip()
    if not text:
        return ""
    # 结构化字段前加分隔，避免「导演主演类型」糊成一团
    for label in _WEB_META_LABELS:
        text = re.sub(
            rf"(?<![·\s])\s*({re.escape(label)})\s*[:：]",
            rf" · \1：",
            text,
        )
    text = re.sub(r"^(?:\s*·\s*)+", "", text)
    text = re.sub(r"(?:\s*·\s*){2,}", " · ", text)
    return text[:160].rstrip(" ·")


def tool_definitions(*, include_web: bool = True) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "sehua_keyword",
                "description": "在色花资源仓库用关键词搜索（标题/文件名）。适合番号、女优、片名。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索词"},
                        "region": {
                            "type": "string",
                            "description": "可选分区，如 japan_censored / 有码 / 无码",
                        },
                        "limit": {"type": "integer", "description": "条数 1-12，默认 6"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "sehua_semantic",
                "description": "色花仓库语义/向量检索。适合口语描述、相似推荐。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "scrap_search",
                "description": "片商刮削库语义搜索（女优/厂牌/番号/类型）。可指定 region。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "region": {
                            "type": "string",
                            "description": "如 有码 / 无码 / japan_censored",
                        },
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "scrap_list",
                "description": "片商库按关键词/女优/厂牌/标签筛选列表（非向量）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "actress": {"type": "string"},
                        "studio": {"type": "string"},
                        "genre": {"type": "string"},
                        "region": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "magnet_search",
                "description": "Bitmagnet 本地磁力库关键词搜索。适合电影/剧集种子、蓝光、infohash。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "magnet_semantic",
                "description": "Bitmagnet 磁力库语义/向量检索。适合口语描述、相似种子推荐。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "media_search",
                "description": (
                    "影视元数据搜索（TMDB/豆瓣/Bangumi/AniList）。"
                    "适合查片名、确认作品；会尽量带回主演供下一步推导。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "source": {
                            "type": "string",
                            "enum": ["tmdb", "douban", "bangumi", "anilist"],
                            "description": "默认 tmdb",
                        },
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "media_person_works",
                "description": (
                    "按影人姓名列出参演/相关电影电视剧作品。"
                    "适合「某某演过哪些」「某片女主演的其他电影」等多跳查询的第二步。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "影人姓名，如女主/男主/导演名",
                        },
                        "person_id": {
                            "type": "string",
                            "description": "可选：已知影人 id",
                        },
                        "source": {
                            "type": "string",
                            "enum": ["tmdb", "douban", "bangumi", "anilist"],
                            "description": "默认 tmdb",
                        },
                        "limit": {"type": "integer", "description": "条数 1-12，默认 8"},
                    },
                    "required": ["name"],
                },
            },
        },
    ]
    if include_web:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "搜索公开网络（SearXNG / Serper / Brave）。查演员资料、片名确认、网上热门等。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["query"],
                    },
                },
            }
        )
    return tools


def filter_tools_by_prefer(
    tools: list[dict[str, Any]],
    prefer: list[str] | None,
) -> list[dict[str, Any]]:
    if not prefer:
        return tools
    allow = {str(s).strip().lower() for s in prefer if str(s).strip()}
    if not allow:
        return tools
    name_map = {
        "sehua": {"sehua_keyword", "sehua_semantic"},
        "scrap": {"scrap_search", "scrap_list"},
        "magnet": {"magnet_search", "magnet_semantic"},
        "media": {"media_search", "media_person_works"},
        "web": {"web_search"},
        "warehouse": {"sehua_keyword", "sehua_semantic"},
        "makers": {"scrap_search", "scrap_list"},
    }
    names: set[str] = set()
    for p in allow:
        names |= name_map.get(p, set())
        if p in {
            "sehua_keyword",
            "sehua_semantic",
            "scrap_search",
            "scrap_list",
            "magnet_search",
            "magnet_semantic",
            "media_search",
            "media_person_works",
            "web_search",
        }:
            names.add(p)
    if not names:
        return tools
    return [t for t in tools if str((t.get("function") or {}).get("name") or "") in names]


def filter_tools_by_enabled(
    tools: list[dict[str, Any]],
    enabled: list[str] | set[str] | None,
) -> list[dict[str, Any]]:
    if enabled is None:
        return tools
    allow = {str(x).strip() for x in enabled if str(x).strip()}
    if not allow:
        return []
    return [t for t in tools if str((t.get("function") or {}).get("name") or "") in allow]


def _limit(raw: Any, default: int = 6, hi: int = 12) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = default
    return max(1, min(hi, n))


def _sehual_cards(resources: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in resources[:limit]:
        h = str(item.get("hash") or item.get("info_hash") or "").strip()
        if not h:
            continue
        title = display_hit_label(
            title=item.get("title"),
            description=item.get("description"),
            filename=item.get("name") or item.get("filename"),
        )
        board = str(item.get("board_name") or "").strip()
        size = item.get("size")
        meta_parts = [board]
        if isinstance(size, (int, float)) and size > 0:
            meta_parts.append(_fmt_size(int(size)))
        cover = ""
        previews = item.get("preview_images") or item.get("images") or []
        if isinstance(previews, list) and previews:
            cover = str(previews[0] or "")
        score = item.get("score")
        cards.append(
            make_card(
                source="sehua",
                title=title,
                subtitle=_guess_code(title),
                meta=" · ".join(p for p in meta_parts if p),
                cover=cover,
                score=float(score) if isinstance(score, (int, float)) else None,
                key=h.lower(),
                open_payload={"kind": "sehua", "hash": h},
            )
        )
    return cards


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n / 1024:.1f} KB"
    if n < 1024**3:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024**3:.2f} GB"


_CODE_RE = re.compile(
    r"(?:^|[^A-Za-z0-9])((?:\d{2,3})?[A-Za-z]{2,15}[-_\s]?\d{2,8}|FC2[-_\s]?PPV[-_\s]?\d{5,10})",
    re.I,
)


def _guess_code(text: str) -> str:
    m = _CODE_RE.search(text or "")
    if not m:
        return ""
    raw = re.sub(r"[\s_]+", "-", m.group(1).upper())
    return raw[:24]


async def run_sehua_keyword(args: dict[str, Any]) -> dict[str, Any]:
    import app.search.resource_service as resource_service

    q = str(args.get("query") or "").strip()
    if len(q) < 2:
        return {"ok": False, "error": "关键词太短", "cards": [], "total": 0}
    limit = _limit(args.get("limit"), 6)
    region = str(args.get("region") or "").strip() or None
    try:
        data = resource_service.search_resources(
            keyword=q,
            p=1,
            ps=limit,
            sort_type="default",
            match_mode="smart",
            with_total_count=True,
            region=region,
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "cards": [], "total": 0}
    resources = list(data.get("resources") or [])
    total = int(data.get("total_count") or len(resources))
    cards = _sehual_cards(resources, limit=limit)
    return {
        "ok": True,
        "source": "sehua",
        "mode": "keyword",
        "query": q,
        "total": total,
        "cards": cards,
        "summary": f"仓库关键词「{q}」{total} 条",
    }


async def run_sehua_semantic(args: dict[str, Any]) -> dict[str, Any]:
    from app.search.sehua_vector_search import search_semantic

    q = str(args.get("query") or "").strip()
    if not q:
        return {"ok": False, "error": "空查询", "cards": [], "total": 0}
    limit = _limit(args.get("limit"), 6)
    try:
        semantic = await search_semantic(q)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "cards": [], "total": 0}
    if not semantic.get("ok"):
        return {
            "ok": False,
            "error": str(semantic.get("reason") or "semantic-failed"),
            "cards": [],
            "total": 0,
            "summary": f"语义不可用：{semantic.get('reason') or 'unknown'}",
        }
    resources = list(semantic.get("resources") or [])[:limit]
    total = int(semantic.get("total") or len(resources))
    cards = _sehual_cards(resources, limit=limit)
    return {
        "ok": True,
        "source": "sehua",
        "mode": "semantic",
        "query": q,
        "total": total,
        "cards": cards,
        "summary": f"仓库语义「{q}」{total} 条",
    }


def _scrap_card(hit: dict[str, Any]) -> dict[str, Any]:
    code = str(hit.get("code") or "").strip()
    title = str(hit.get("title") or "").strip() or code or str(hit.get("itemId") or "")
    cover = str(
        hit.get("posterApi")
        or hit.get("thumbApi")
        or hit.get("coverUrl")
        or ""
    )
    region = str(hit.get("region") or "").strip()
    score = hit.get("score")
    item_id = str(hit.get("itemId") or "").strip()
    return make_card(
        source="scrap",
        title=title,
        subtitle=code,
        meta=region,
        cover=cover,
        score=float(score) if isinstance(score, (int, float)) else None,
        key=item_id or code or title,
        open_payload={"kind": "scrap", "item": hit},
    )


async def run_scrap_search(args: dict[str, Any]) -> dict[str, Any]:
    import app.scrap_library.embed as svc

    q = str(args.get("query") or "").strip()
    if not q:
        return {"ok": False, "error": "空查询", "cards": [], "total": 0}
    limit = _limit(args.get("limit"), 8)
    region = str(args.get("region") or "").strip()
    try:
        hits = svc.search(q, limit=limit, region=region)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "cards": [], "total": 0}
    cards = [_scrap_card(h) for h in hits if isinstance(h, dict)]
    return {
        "ok": True,
        "source": "scrap",
        "mode": "semantic",
        "query": q,
        "total": len(cards),
        "cards": cards,
        "summary": f"片商语义「{q}」{len(cards)} 条",
    }


async def run_scrap_list(args: dict[str, Any]) -> dict[str, Any]:
    import app.scrap_library.embed as svc

    limit = _limit(args.get("limit"), 8)
    q = str(args.get("query") or "").strip()
    actress = str(args.get("actress") or "").strip()
    studio = str(args.get("studio") or "").strip()
    genre = str(args.get("genre") or "").strip()
    region = str(args.get("region") or "").strip()
    tag = actress or ""
    try:
        page = svc.list_items(
            region=region,
            q=q,
            genre=genre,
            tag=tag,
            studio=studio,
            limit=limit,
            offset=0,
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "cards": [], "total": 0}
    items = list(page.get("items") or []) if isinstance(page, dict) else []
    total = int(page.get("total") or len(items)) if isinstance(page, dict) else len(items)
    cards = [_scrap_card(h) for h in items if isinstance(h, dict)]
    return {
        "ok": True,
        "source": "scrap",
        "mode": "list",
        "query": q or actress or studio or genre,
        "total": total,
        "cards": cards,
        "summary": f"片商列表 {total} 条",
    }


async def run_magnet_search(args: dict[str, Any]) -> dict[str, Any]:
    import app.search.bitmagnet_client as bitmagnet_client

    q = str(args.get("query") or "").strip()
    if not q:
        return {"ok": False, "error": "空查询", "cards": [], "total": 0}
    limit = _limit(args.get("limit"), 6)
    try:
        data = bitmagnet_client.search(q, page=1)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "cards": [], "total": 0}
    items = list(data.get("items") or [])[:limit]
    total = int(data.get("total") or len(items))
    cards: list[dict[str, Any]] = []
    for it in items:
        h = str(it.get("hash") or it.get("infoHash") or it.get("info_hash") or "").strip()
        if not h:
            continue
        title = str(it.get("name") or it.get("title") or h).strip()
        size = it.get("size") or it.get("totalSize")
        meta = _fmt_size(int(size)) if isinstance(size, (int, float)) and size else ""
        cards.append(
            make_card(
                source="magnet",
                title=title,
                subtitle=_guess_code(title),
                meta=meta,
                cover="",
                key=h.lower(),
                open_payload={"kind": "magnet", "hash": h},
            )
        )
    return {
        "ok": True,
        "source": "magnet",
        "mode": "keyword",
        "query": q,
        "total": total,
        "cards": cards,
        "summary": f"磁力「{q}」{total} 条",
    }


async def run_magnet_semantic(args: dict[str, Any]) -> dict[str, Any]:
    from app.search.bitmagnet_vector_search import search_semantic

    q = str(args.get("query") or "").strip()
    if not q:
        return {"ok": False, "error": "空查询", "cards": [], "total": 0}
    limit = _limit(args.get("limit"), 6)
    try:
        semantic = await search_semantic(q)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "cards": [], "total": 0}
    if not semantic.get("ok"):
        return {
            "ok": False,
            "error": str(semantic.get("reason") or "semantic-failed"),
            "cards": [],
            "total": 0,
            "summary": f"磁力语义不可用：{semantic.get('reason') or 'unknown'}",
        }
    items = list(semantic.get("items") or [])[:limit]
    total = int(semantic.get("total") or len(items))
    cards: list[dict[str, Any]] = []
    for it in items:
        h = str(it.get("hash") or it.get("infoHash") or it.get("info_hash") or "").strip()
        if not h:
            continue
        title = str(it.get("name") or it.get("title") or h).strip()
        size = it.get("size") or it.get("totalSize")
        score = it.get("score")
        meta_parts: list[str] = []
        if isinstance(size, (int, float)) and size:
            meta_parts.append(_fmt_size(int(size)))
        cards.append(
            make_card(
                source="magnet",
                title=title,
                subtitle=_guess_code(title),
                meta=" · ".join(meta_parts),
                cover="",
                score=float(score) if isinstance(score, (int, float)) else None,
                key=h.lower(),
                open_payload={"kind": "magnet", "hash": h},
            )
        )
    return {
        "ok": True,
        "source": "magnet",
        "mode": "semantic",
        "query": q,
        "total": total,
        "cards": cards,
        "summary": f"磁力语义「{q}」{total} 条",
    }


async def run_media_search(args: dict[str, Any]) -> dict[str, Any]:
    q = str(args.get("query") or "").strip()
    if not q:
        return {"ok": False, "error": "空查询", "cards": [], "total": 0}
    source = str(args.get("source") or "tmdb").strip().lower() or "tmdb"
    if source not in {"tmdb", "douban", "bangumi", "anilist"}:
        source = "tmdb"
    limit = _limit(args.get("limit"), 6)
    try:
        from app.media.routes import media_search

        wrapped = await media_search(q=q, source=source, page=1)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "cards": [], "total": 0}
    data = wrapped.get("data") if isinstance(wrapped, dict) else None
    if not isinstance(data, dict):
        return {"ok": False, "error": "影视搜索无数据", "cards": [], "total": 0}
    items = list(data.get("items") or [])[:limit]
    cards: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        mid = str(it.get("id") or "").strip()
        title = str(it.get("title") or "").strip() or mid
        year = str(it.get("year") or "").strip()
        media_type = str(it.get("mediaType") or it.get("media_type") or "").strip()
        rating = it.get("rating")
        meta_parts = [year, media_type]
        if isinstance(rating, (int, float)):
            meta_parts.append(f"{float(rating):.1f}")
        cover = str(it.get("posterUrl") or it.get("poster_url") or "")
        cards.append(
            make_card(
                source="media",
                title=title,
                subtitle=str(it.get("originalTitle") or "")[:40],
                meta=" · ".join(p for p in meta_parts if p),
                cover=cover,
                key=f"{source}:{mid}",
                open_payload={"kind": "media", "item": it},
            )
        )

    # 取头条详情主演，方便多跳（片名 → 演员 → 作品）
    facts: list[dict[str, Any]] = []
    if items:
        cast_names = await _media_top_cast(source, items[0])
        if cast_names:
            facts.append(
                {
                    "title": str(items[0].get("title") or q),
                    "year": str(items[0].get("year") or ""),
                    "cast": cast_names,
                    "hint": "若用户要该片主演的其他作品，下一步用 media_person_works(name=主演名)",
                }
            )

    return {
        "ok": True,
        "source": "media",
        "mode": source,
        "query": q,
        "total": len(cards),
        "cards": cards,
        "facts": facts,
        "summary": f"影视({source})「{q}」{len(cards)} 条"
        + (f"；头条主演 {', '.join(facts[0]['cast'][:3])}" if facts else ""),
    }


async def _media_top_cast(source: str, item: dict[str, Any]) -> list[str]:
    """尽量拉取作品主演名（失败则空，不影响主流程）。"""
    mid = str(item.get("id") or "").strip()
    if not mid:
        return []
    media_type = str(item.get("mediaType") or item.get("media_type") or "movie").strip() or "movie"
    try:
        if source == "tmdb":
            from app.media.routes import tmdb_detail

            mt = media_type if media_type in {"movie", "tv"} else "movie"
            wrapped = await tmdb_detail(mt, mid)
        elif source == "douban":
            from app.media.routes import douban_detail

            wrapped = await douban_detail(mid)
        else:
            return []
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(wrapped, dict):
        return []
    data = wrapped.get("data") if isinstance(wrapped.get("data"), dict) else wrapped
    cast = data.get("cast") if isinstance(data, dict) else None
    if not isinstance(cast, list):
        return []
    names: list[str] = []
    # tmdb_detail / 部分源会把导演排在 cast 前部，跳过前 1 位更易拿到主演
    start = 1 if len(cast) > 2 else 0
    for p in cast[start : start + 10]:
        if not isinstance(p, dict):
            continue
        role = str(p.get("role") or p.get("job") or "").strip().lower()
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        if role in {"director", "导演"}:
            continue
        if name not in names:
            names.append(name)
        if len(names) >= 5:
            break
    return names


async def run_media_person_works(args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name") or args.get("q") or "").strip()
    person_id = str(args.get("person_id") or args.get("personId") or "").strip()
    if not name and not person_id:
        return {"ok": False, "error": "需要影人姓名", "cards": [], "total": 0}
    source = str(args.get("source") or "tmdb").strip().lower() or "tmdb"
    if source not in {"tmdb", "douban", "bangumi", "anilist"}:
        source = "tmdb"
    limit = _limit(args.get("limit"), 8)
    try:
        from app.media.routes import media_person_works

        wrapped = await media_person_works(source=source, q=name, person_id=person_id)
    except Exception as e:  # noqa: BLE001
        err = str(getattr(e, "detail", None) or e)
        return {"ok": False, "error": err, "cards": [], "total": 0, "summary": err}
    data = wrapped.get("data") if isinstance(wrapped, dict) else None
    if not isinstance(data, dict):
        return {"ok": False, "error": "影人作品无数据", "cards": [], "total": 0}
    display = str(data.get("name") or name or person_id)
    items = list(data.get("items") or [])[:limit]
    cards: list[dict[str, Any]] = []
    titles: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        mid = str(it.get("id") or "").strip()
        title = str(it.get("title") or "").strip() or mid
        if title:
            titles.append(title)
        year = str(it.get("year") or "").strip()
        media_type = str(it.get("mediaType") or it.get("media_type") or "").strip()
        rating = it.get("rating")
        meta_parts = [year, media_type]
        if isinstance(rating, (int, float)):
            meta_parts.append(f"{float(rating):.1f}")
        cover = str(it.get("posterUrl") or it.get("poster_url") or "")
        cards.append(
            make_card(
                source="media",
                title=title,
                subtitle=display[:40],
                meta=" · ".join(p for p in meta_parts if p),
                cover=cover,
                key=f"person-work:{source}:{mid or title}",
                open_payload={"kind": "media", "item": it},
            )
        )
    facts = [{"person": display, "works": titles[:8]}]
    return {
        "ok": True,
        "source": "media",
        "mode": f"person_works:{source}",
        "query": name or person_id,
        "total": len(cards),
        "cards": cards,
        "facts": facts,
        "summary": f"影人「{display}」作品 {len(cards)} 部",
    }


async def run_web_search(args: dict[str, Any]) -> dict[str, Any]:
    cfg = resolve_web_search_config(include_secret=True)
    if not cfg.get("enabled"):
        return {
            "ok": False,
            "error": "网络搜索未启用",
            "cards": [],
            "total": 0,
            "summary": "请在 设置 → AI 模型 → 小花 中启用网络搜索",
        }
    provider = str(cfg.get("provider") or "serper").strip().lower()
    api_key = str(cfg.get("apiKey") or "").strip()
    base_url = str(cfg.get("baseUrl") or "").strip().rstrip("/")
    if provider == "searxng":
        if not base_url:
            return {
                "ok": False,
                "error": "未配置 SearXNG 地址",
                "cards": [],
                "total": 0,
                "summary": "请填写 SearXNG 服务地址，例如 http://192.168.2.38:8085",
            }
    elif not api_key:
        return {
            "ok": False,
            "error": "未配置网络搜索 API Key",
            "cards": [],
            "total": 0,
            "summary": "未配置网络搜索 API Key",
        }
    q = str(args.get("query") or "").strip()
    if not q:
        return {"ok": False, "error": "空查询", "cards": [], "total": 0}
    limit = _limit(args.get("limit"), 5, hi=8)
    try:
        if provider == "searxng":
            hits = await _searxng_search(q, base_url=base_url, limit=limit)
        elif provider == "brave":
            hits = await _brave_search(q, api_key=api_key, limit=limit)
        else:
            hits = await _serper_search(q, api_key=api_key, limit=limit)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "cards": [], "total": 0, "summary": f"网络搜索失败：{e}"}

    cards: list[dict[str, Any]] = []
    for h in hits:
        url = str(h.get("url") or "").strip()
        if not url:
            continue
        title = str(h.get("title") or url).strip()
        snippet = _format_web_meta(str(h.get("snippet") or ""))
        host = _web_host(url)
        cards.append(
            make_card(
                source="web",
                title=title,
                subtitle=host,
                meta=snippet,
                cover="",
                key=url,
                open_payload={"kind": "url", "url": url, "title": title},
            )
        )
    return {
        "ok": True,
        "source": "web",
        "mode": provider,
        "query": q,
        "total": len(cards),
        "cards": cards,
        "summary": f"网络({provider})「{q}」{len(cards)} 条",
    }


async def _searxng_search(query: str, *, base_url: str, limit: int) -> list[dict[str, str]]:
    root = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=8.0)) as client:
        r = await client.get(
            f"{root}/search",
            params={
                "q": query,
                "format": "json",
                "language": "zh-CN",
            },
        )
    if not r.is_success:
        raise RuntimeError(f"SearXNG {r.status_code}: {r.text[:160]}")
    data = r.json() or {}
    rows = data.get("results") or []
    out: list[dict[str, str]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        out.append(
            {
                "title": str(row.get("title") or url).strip(),
                "url": url,
                "snippet": str(row.get("content") or row.get("snippet") or "").strip(),
            }
        )
    return out


async def _serper_search(query: str, *, api_key: str, limit: int) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0)) as client:
        r = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": limit},
        )
    if r.status_code == 401:
        raise RuntimeError("Serper API Key 无效")
    if not r.is_success:
        raise RuntimeError(f"Serper {r.status_code}: {r.text[:160]}")
    data = r.json() or {}
    organic = data.get("organic") or []
    out: list[dict[str, str]] = []
    for row in organic[:limit]:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "title": str(row.get("title") or ""),
                "url": str(row.get("link") or ""),
                "snippet": str(row.get("snippet") or ""),
            }
        )
    return out


async def _brave_search(query: str, *, api_key: str, limit: int) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0)) as client:
        r = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
            params={"q": query, "count": limit},
        )
    if r.status_code == 401:
        raise RuntimeError("Brave API Key 无效")
    if not r.is_success:
        raise RuntimeError(f"Brave {r.status_code}: {r.text[:160]}")
    data = r.json() or {}
    web = (data.get("web") or {}).get("results") or []
    out: list[dict[str, str]] = []
    for row in web[:limit]:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "title": str(row.get("title") or ""),
                "url": str(row.get("url") or ""),
                "snippet": str(row.get("description") or ""),
            }
        )
    return out


TOOL_HANDLERS: dict[str, ToolHandler] = {
    "sehua_keyword": run_sehua_keyword,
    "sehua_semantic": run_sehua_semantic,
    "scrap_search": run_scrap_search,
    "scrap_list": run_scrap_list,
    "magnet_search": run_magnet_search,
    "magnet_semantic": run_magnet_semantic,
    "media_search": run_media_search,
    "media_person_works": run_media_person_works,
    "web_search": run_web_search,
}

TOOL_STATUS_LABEL: dict[str, str] = {
    "sehua_keyword": "正在仓库搜…",
    "sehua_semantic": "正在语义搜仓库…",
    "scrap_search": "正在片商库搜…",
    "scrap_list": "正在片商列表筛…",
    "magnet_search": "正在磁力库搜…",
    "magnet_semantic": "正在磁力语义搜…",
    "media_search": "正在影视库搜…",
    "media_person_works": "正在查影人作品…",
    "web_search": "正在搜网络…",
}


async def dispatch_tool(name: str, arguments: dict[str, Any] | str | None) -> dict[str, Any]:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {"ok": False, "error": f"未知工具 {name}", "cards": [], "total": 0}
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            args = {}
    elif isinstance(arguments, dict):
        args = arguments
    else:
        args = {}
    result = await handler(args)
    if "cards" not in result:
        result["cards"] = []
    return result


def tool_result_for_llm(result: dict[str, Any]) -> str:
    payload = {
        "ok": bool(result.get("ok")),
        "summary": result.get("summary") or result.get("error") or "",
        "total": result.get("total") or 0,
        "cards": [
            {
                "source": c.get("source"),
                "title": c.get("title"),
                "subtitle": c.get("subtitle"),
                "meta": c.get("meta"),
            }
            for c in (result.get("cards") or [])[:8]
        ],
    }
    facts = result.get("facts")
    if isinstance(facts, list) and facts:
        payload["facts"] = facts[:4]
    if result.get("error") and not result.get("ok"):
        payload["error"] = result["error"]
    return json.dumps(payload, ensure_ascii=False)


def collect_cards_from_results(results: list[dict[str, Any]], *, limit: int = 24) -> list[dict[str, Any]]:
    groups = [list(r.get("cards") or []) for r in results if isinstance(r, dict)]
    return merge_cards(*groups, limit=limit)


def collect_ui_cards(
    results: list[dict[str, Any]],
    *,
    message: str,
    limit: int = 24,
) -> list[dict[str, Any]]:
    from app.ai.assistant_protocol import user_wants_resource_cards

    return select_ui_cards(
        results,
        wants_cards=user_wants_resource_cards(message),
        limit=limit,
    )


def source_label(source: str) -> str:
    return _SOURCE_LABEL.get(source, source)


async def heuristic_local_search(
    message: str,
    *,
    prefer: list[str] | None = None,
    enabled_tools: list[str] | set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """无 LLM 时的降级：按 prefer 或启发式并行搜本地。"""
    q = message.strip()
    prefer_set = {str(s).strip().lower() for s in (prefer or []) if str(s).strip()}
    allow = (
        {str(x).strip() for x in enabled_tools if str(x).strip()}
        if enabled_tools is not None
        else None
    )
    jobs: list[tuple[str, dict[str, Any]]] = []

    def want(*keys: str) -> bool:
        if not prefer_set:
            return True
        return bool(prefer_set & set(keys))

    def tool_ok(name: str) -> bool:
        return allow is None or name in allow

    if want("sehua", "warehouse") and tool_ok("sehua_keyword"):
        jobs.append(("sehua_keyword", {"query": q, "limit": 5}))
    if want("scrap", "makers") and tool_ok("scrap_search"):
        jobs.append(("scrap_search", {"query": q, "limit": 5}))
    if want("magnet") and tool_ok("magnet_search"):
        jobs.append(("magnet_search", {"query": q, "limit": 5}))
    if want("magnet") and tool_ok("magnet_semantic"):
        jobs.append(("magnet_semantic", {"query": q, "limit": 5}))
    if want("media") and tool_ok("media_search"):
        jobs.append(("media_search", {"query": q, "limit": 5}))
    if not jobs and allow is not None:
        # 无 prefer 命中时，退到已启用工具
        for name in (
            "sehua_keyword",
            "sehua_semantic",
            "scrap_search",
            "magnet_search",
            "magnet_semantic",
            "media_search",
        ):
            if name in allow:
                jobs.append((name, {"query": q, "limit": 5}))
    elif not jobs:
        jobs = [
            ("sehua_keyword", {"query": q, "limit": 5}),
            ("scrap_search", {"query": q, "limit": 5}),
            ("magnet_search", {"query": q, "limit": 5}),
            ("media_search", {"query": q, "limit": 5}),
        ]

    results: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for name, args in jobs:
        r = await dispatch_tool(name, args)
        results.append(r)
        steps.append(
            {
                "tool": name,
                "status": "done",
                "ok": bool(r.get("ok")),
                "summary": r.get("summary") or r.get("error") or "",
            }
        )
    return collect_cards_from_results(results), steps
