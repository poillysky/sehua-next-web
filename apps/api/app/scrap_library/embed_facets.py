# -*- coding: utf-8 -*-
"""embed_facets —— 自 scrap_library/embed.py 拆出（机械搬移，行为不变）。"""

from __future__ import annotations
import json
import logging
import os
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
import app.core.settings_store as settings_store
from app.ai.config import resolve_embed_config
from app.ai.embed import encode_texts_sync
from app.core.db import data_dir, media_dir, get_meta_pool, init_db, meta_dsn_label
from app.scrap_library.nfo import (
    build_nfo_embed_text,
    content_sha,
    item_id_from_rel,
    normalize_source_text_for_diff,
    parse_nfo,
    polish_source_text_actresses,
    preserve_actress_line,
)
from app.core.ttl_cache import enforce_max, prune_by_age

import app.scrap_library.embed as _embed
import app.scrap_library.embed_catalog as _embed_catalog
import app.scrap_library.embed_poster as _embed_poster
import app.scrap_library.embed_recommend as _embed_recommend
from app.scrap_library.embed import (_CODEISH_RE, _FACETS_SNAP_DIR, _FACETS_SNAP_VERSION, _FACET_LINE_RE, _append_prefix_clause, _append_studio_clause, _prefix_blurb, _recommend_snap_path, _split_tokens, _studio_blurb, _studio_display_name, _studio_match_key, log)
from app.scrap_library.embed_runtime import (_FACETS_CACHE, _ITEMS_HUB_CACHE, _facets_snap_lock)


_DISPLAY_READY_SQL = (
    f"{_embed_catalog._NOT_SKELETON_SQL} AND coalesce(poster_path, '') <> ''"
)


def list_regions() -> list[dict[str, Any]]:
    """向量库中实际存在的分区及条数。"""
    from app.core.region_meta import REGION_META, REGION_ORDER

    _embed.ensure_schema()
    pool = get_meta_pool()
    counts: dict[str, int] = {}
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT region, count(*)::int AS n
                FROM {_embed.TABLE}
                GROUP BY region
                """
            )
            for row in cur.fetchall():
                if not isinstance(row, dict):
                    continue
                counts[str(row.get("region") or "")] = int(row.get("n") or 0)

    # 按六区顺序输出；库内孤儿区追加在后
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rid in REGION_ORDER:
        label = str(REGION_META[rid].get("label") or rid)
        n = int(counts.get(label) or 0) + int(counts.get(rid) or 0)
        out.append({"id": rid, "label": label, "count": n})
        seen.add(label)
        seen.add(rid)
    for name, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        if not name or name in seen:
            continue
        out.append({"id": name, "label": name, "count": int(n)})
    return out


def list_prefixes(
    *, region: str = "", studio: str = "", q: str = "", limit: int | None = None
) -> list[dict[str, Any]]:
    """厂牌下的前缀夹列表。

    计数含骨架（否则仅空壳的 FC2-PPV 等前缀会消失）；封面优先磁盘现行路径。
    """
    _embed.ensure_schema()
    pool = get_meta_pool()
    clauses: list[str] = ["coalesce(prefix,'') <> ''"]
    params: list[Any] = []
    match = _embed._region_match_values(region)
    if match:
        clauses.append("region = ANY(%s)")
        params.append(match)
    studio_q = str(studio or "").strip()
    if studio_q:
        _append_studio_clause(clauses, params, studio_q, region=region)
    query = str(q or "").strip()
    if query:
        like = f"%{query}%"
        clauses.append("prefix ILIKE %s")
        params.append(like)
    where = " AND ".join(clauses)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                       prefix,
                       count(*)::int AS n,
                       max(code) AS latest_code,
                       max(
                         NULLIF(
                           substring(source_text from '年份：([0-9]{{4}})'),
                           ''
                         )
                       ) AS latest_year,
                       max(updated_at) AS latest_at,
                       array_agg(
                         COALESCE(
                           NULLIF(poster_path, ''),
                           NULLIF(thumb_path, ''),
                           NULLIF(cover_url, '')
                         )
                         ORDER BY
                           CASE
                             WHEN content_sha NOT LIKE '{_embed_catalog.SKELETON_SHA_PREFIX}:%%'
                                  AND coalesce(poster_path, '') <> '' THEN 0
                             WHEN coalesce(poster_path, '') <> '' THEN 1
                             ELSE 2
                           END,
                           NULLIF(
                             substring(source_text from '年份：([0-9]{{4}})'),
                             ''
                           ) DESC NULLS LAST,
                           code DESC
                       ) FILTER (
                         WHERE coalesce(poster_path,'') <> ''
                            OR coalesce(thumb_path,'') <> ''
                            OR coalesce(cover_url,'') <> ''
                       ) AS posters
                FROM {_embed.TABLE}
                WHERE {where}
                GROUP BY 1
                ORDER BY
                  max(
                    NULLIF(
                      substring(source_text from '年份：([0-9]{{4}})'),
                      ''
                    )
                  ) DESC NULLS LAST,
                  max(updated_at) DESC NULLS LAST,
                  prefix ASC
                """,
                params,
            )
            rows = list(cur.fetchall())
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("posters") or []
        candidates: list[str] = []
        pref = str(row.get("prefix") or "")
        for s in _embed_poster._sample_prefix_disk_posters(region, pref, limit=8):
            if s and s not in candidates:
                candidates.append(s)
        if isinstance(raw, (list, tuple)):
            for p in raw:
                s = _embed_catalog.resolve_existing_media_rel(str(p or "").strip())
                if s and s not in candidates:
                    candidates.append(s)
                if len(candidates) >= 8:
                    break
        # 列表页单封面：优先本地，否则外链 coverUrl
        poster_api, poster_apis, cover_url = _facet_media_refs(candidates[:4])
        primary = ""
        for c in candidates:
            if c and not str(c).startswith(("http://", "https://")):
                primary = str(c)
                break
        year_raw = row.get("latest_year")
        try:
            latest_year = int(year_raw) if year_raw not in (None, "") else 0
        except (TypeError, ValueError):
            latest_year = 0
        latest_at = row.get("latest_at")
        latest_at_s = ""
        if latest_at is not None:
            try:
                latest_at_s = latest_at.isoformat()  # datetime
            except AttributeError:
                latest_at_s = str(latest_at)
        blurb = _prefix_blurb(pref)
        from app.prefix.maker_names import prefix_line_rank
        from app.core.region_meta import fc2_fs_prefix
        from app.scrap_library.studio_display_names import resolve_studio_for_prefix

        studio_name = resolve_studio_for_prefix(pref, region=region) or ""
        display_pref = (
            fc2_fs_prefix(pref) if str(region or "").strip() == "fc2" else pref
        ) or pref
        out.append(
            {
                "prefix": display_pref,
                "count": int(row.get("n") or 0),
                "latestCode": str(row.get("latest_code") or "").strip().upper(),
                "latestYear": latest_year,
                "latestAt": latest_at_s,
                "lineRank": prefix_line_rank(pref, blurb),
                "posterPath": primary,
                "posterApi": poster_api,
                "posterApis": poster_apis,
                "coverUrl": cover_url,
                "blurb": blurb,
                "studio": studio_name,
            }
        )

    def _at_ts(raw: Any) -> float:
        s = str(raw or "").strip()
        if not s:
            return 0.0
        try:
            from datetime import datetime

            return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except Exception:  # noqa: BLE001
            return 0.0

    # 主力线优先，同档再按发行年 / 入库时间新→旧
    out.sort(
        key=lambda r: (
            int(r.get("lineRank") or 99),
            -int(r.get("latestYear") or 0),
            -_at_ts(r.get("latestAt")),
            str(r.get("prefix") or ""),
        )
    )
    if limit is not None:
        lim = max(1, min(100, int(limit)))
        out = out[:lim]
    return out


_STUDIO_LINE_SQL = "NULLIF(substring(source_text from '片商：(.+?)(?:\\n|$)'), '')"


_ACTRESS_LINE_SQL = "NULLIF(substring(source_text from '女优：(.+?)(?:\\n|$)'), '')"


_TOKEN_SPLIT_SQL = "[[:space:]/|、，,]+"


def _build_studio_facets_by_prefix(*, region: str = "") -> list[dict[str, Any]]:
    """厂牌货架：按库内 prefix 汇总，再用标准「前缀→厂牌」表归位（不读 NFO 片商）。

    计数含骨架行（否则仅空壳的前缀如 FC2-PPV 不会出现在厂牌墙）；
    封面优先磁盘前缀夹取样，再补库内海报。
    合并后无任何封面的厂牌会被丢掉（避免「奢华TV」这类仅骨架空壳卡）。
    """
    from app.scrap_library.studio_display_names import resolve_studio_for_prefix

    _embed.ensure_schema()
    match = _embed._region_match_values(region)
    clauses = ["coalesce(prefix, '') <> ''"]
    params: list[Any] = []
    if match:
        clauses.append("region = ANY(%s)")
        params.append(match)
    where = " AND ".join(clauses)
    pool = get_meta_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT upper(prefix) AS pref, count(*)::int AS n,
                       array_agg(
                         COALESCE(
                           NULLIF(poster_path, ''),
                           NULLIF(thumb_path, ''),
                           NULLIF(cover_url, '')
                         )
                         ORDER BY
                           CASE
                             WHEN content_sha NOT LIKE '{_embed_catalog.SKELETON_SHA_PREFIX}:%%'
                                  AND coalesce(poster_path, '') <> '' THEN 0
                             WHEN coalesce(poster_path, '') <> '' THEN 1
                             ELSE 2
                           END,
                           code ASC
                       ) FILTER (
                         WHERE coalesce(poster_path, '') <> ''
                            OR coalesce(thumb_path, '') <> ''
                            OR coalesce(cover_url, '') <> ''
                       ) AS posters
                FROM {_embed.TABLE}
                WHERE {where}
                GROUP BY upper(prefix)
                """,
                params,
            )
            rows = list(cur.fetchall())

    buckets: dict[str, dict[str, Any]] = {}
    unknown_n = 0
    unknown_paths: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pref = str(row.get("pref") or "").strip().upper()
        n = int(row.get("n") or 0)
        if not pref or n <= 0:
            continue
        paths: list[str] = []
        # 优先磁盘现行路径（FC2 三层），再补库内仍有效的海报
        for s in _embed_poster._sample_prefix_disk_posters(region, pref, limit=8):
            if s and s not in paths:
                paths.append(s)
            if len(paths) >= 8:
                break
        for p in row.get("posters") or []:
            s = _embed_catalog.resolve_existing_media_rel(str(p or "").strip())
            if s and s not in paths:
                paths.append(s)
            if len(paths) >= 8:
                break
        studio = resolve_studio_for_prefix(pref, region=region)
        if not studio:
            unknown_n += n
            unknown_paths.extend(paths)
            continue
        key = _studio_match_key(studio) or studio.casefold()
        cur = buckets.get(key)
        if not cur:
            buckets[key] = _facet_row(
                name=studio,
                count=n,
                kind="studio",
                poster_paths=paths,
                validate_covers=False,
            )
        else:
            cur["count"] = int(cur.get("count") or 0) + n
            _absorb_facet_media(cur, paths)

    out = list(buckets.values())
    if unknown_n > 0:
        out.append(
            _facet_row(
                name="未标注厂牌",
                count=unknown_n,
                kind="studio",
                poster_paths=unknown_paths,
                validate_covers=False,
            )
        )
    return out


def _merge_studio_facets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """合并厂牌别名，展示名走映射表。"""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        raw_name = str(row.get("name") or "").strip()
        if raw_name in {"未标注厂牌", "未标注", "(unknown)"}:
            key = f"__unknown__:{raw_name}"
        else:
            key = _studio_match_key(raw_name) or f"__raw__:{raw_name.casefold()}"
        groups.setdefault(key, []).append(row)

    out: list[dict[str, Any]] = []
    for items in groups.values():
        items_sorted = sorted(
            items,
            key=lambda r: (
                -int(r.get("count") or 0),
                0 if " " in str(r.get("name") or "") else 1,
                -len(str(r.get("name") or "")),
            ),
        )
        primary = dict(items_sorted[0])
        total = sum(int(i.get("count") or 0) for i in items_sorted)
        display = _studio_display_name(str(primary.get("name") or ""))
        # 合并封面候选：优先主条目，再补其它
        poster_api = str(primary.get("posterApi") or "")
        cover_url = str(primary.get("coverUrl") or "")
        poster_apis = list(primary.get("posterApis") or [])
        for extra in items_sorted[1:]:
            if not poster_api and extra.get("posterApi"):
                poster_api = str(extra.get("posterApi") or "")
            if not cover_url and extra.get("coverUrl"):
                cover_url = str(extra.get("coverUrl") or "")
            for p in extra.get("posterApis") or []:
                s = str(p or "")
                if s and s not in poster_apis:
                    poster_apis.append(s)
                if len(poster_apis) >= 4:
                    break
        primary.update(
            {
                "name": display or str(primary.get("name") or ""),
                "count": total,
                "posterApi": poster_api,
                "posterApis": poster_apis[:4],
                "coverUrl": cover_url,
                "blurb": _studio_blurb(display or str(primary.get("name") or "")),
            }
        )
        out.append(primary)
    # 无封面的纯骨架厂牌不进墙（如仅有目录号、本地未刮的「奢华TV」「Dogma」）
    return [
        r
        for r in out
        if str(r.get("posterApi") or "").strip()
        or list(r.get("posterApis") or [])
        or str(r.get("coverUrl") or "").strip()
    ]


def _null_studio_prefix_buckets(region: str) -> list[dict[str, Any]]:
    """无片商条目按前缀汇总（用于归位到厂牌）。"""
    _embed.ensure_schema()
    match = _embed._region_match_values(region)
    clauses = [f"({_STUDIO_LINE_SQL} IS NULL)", "coalesce(prefix,'') <> ''"]
    params: list[Any] = []
    if match:
        clauses.append("region = ANY(%s)")
        params.append(match)
    where = " AND ".join(clauses)
    pool = get_meta_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT prefix, count(*)::int AS n,
                       array_agg(
                         COALESCE(
                           NULLIF(poster_path, ''),
                           NULLIF(thumb_path, ''),
                           NULLIF(cover_url, '')
                         )
                         ORDER BY code ASC
                       ) FILTER (
                         WHERE coalesce(poster_path,'') <> ''
                            OR coalesce(thumb_path,'') <> ''
                            OR coalesce(cover_url,'') <> ''
                       ) AS posters
                FROM {_embed.TABLE}
                WHERE {where}
                GROUP BY prefix
                """,
                params,
            )
            rows = list(cur.fetchall())
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        paths: list[str] = []
        for p in row.get("posters") or []:
            s = str(p or "").strip()
            if s and s not in paths:
                paths.append(s)
            if len(paths) >= 8:
                break
        out.append(
            {
                "prefix": str(row.get("prefix") or "").strip().upper(),
                "count": int(row.get("n") or 0),
                "paths": paths,
            }
        )
    return out


def _absorb_facet_media(dst: dict[str, Any], paths: list[str]) -> None:
    api, apis, cover = _facet_media_refs(paths)
    if api and not dst.get("posterApi"):
        dst["posterApi"] = api
    if cover and not dst.get("coverUrl"):
        dst["coverUrl"] = cover
    existing = list(dst.get("posterApis") or [])
    for a in apis:
        if a and a not in existing:
            existing.append(a)
        if len(existing) >= 4:
            break
    dst["posterApis"] = existing[:4]
    if api and not dst.get("posterPath"):
        # 仅作占位；真实路径由 list 侧再解析
        dst["posterPath"] = str(dst.get("posterPath") or "")


def _reattribute_unlabeled_studios(
    rows: list[dict[str, Any]], *, region: str
) -> list[dict[str, Any]]:
    """把缺片商但前缀可识别的条目归入对应厂牌 facet。"""
    from app.scrap_library.studio_display_names import resolve_studio_for_prefix

    buckets = _null_studio_prefix_buckets(region)
    if not buckets:
        return rows

    by_canon: dict[str, dict[str, Any]] = {}
    unknown: dict[str, Any] | None = None
    for row in rows:
        name = str(row.get("name") or "").strip()
        if name in {"未标注厂牌", "未标注", "(unknown)"}:
            unknown = dict(row)
            continue
        key = _studio_match_key(name) or name.casefold()
        existing = by_canon.get(key)
        if not existing:
            by_canon[key] = dict(row)
            continue
        existing["count"] = int(existing.get("count") or 0) + int(
            row.get("count") or 0
        )
        _absorb_facet_media(
            existing,
            [
                str(row.get("posterPath") or ""),
                str(row.get("coverUrl") or ""),
                *list(row.get("posterApis") or []),
            ],
        )

    leftover = 0
    leftover_paths: list[str] = []
    for b in buckets:
        pref = str(b.get("prefix") or "")
        n = int(b.get("count") or 0)
        paths = list(b.get("paths") or [])
        if n <= 0:
            continue
        studio_disp = resolve_studio_for_prefix(pref, region=region)
        if not studio_disp:
            leftover += n
            leftover_paths.extend(paths)
            continue
        key = _studio_match_key(studio_disp) or studio_disp.casefold()
        target = by_canon.get(key)
        if not target:
            by_canon[key] = _facet_row(
                name=studio_disp,
                count=n,
                kind="studio",
                poster_paths=paths,
                validate_covers=False,
            )
        else:
            target["count"] = int(target.get("count") or 0) + n
            _absorb_facet_media(target, paths)

    out = list(by_canon.values())
    if leftover > 0:
        if unknown:
            unknown["count"] = leftover
            _absorb_facet_media(unknown, leftover_paths)
            out.append(unknown)
        else:
            out.append(
                _facet_row(
                    name="未标注厂牌",
                    count=leftover,
                    kind="studio",
                    poster_paths=leftover_paths,
                    validate_covers=False,
                )
            )
    return out


_FACETS_CACHE_TTL_S = 600.0


_FACETS_CACHE_MAX = 48


def _normalize_facet_kind(kind: str) -> str:
    key = str(kind or "genre").strip().lower()
    if key in {"genres", "类型"}:
        return "genre"
    if key in {"tags", "标签"}:
        return "tag"
    if key in {"studios", "maker", "片商", "合集"}:
        return "studio"
    if key in {"actress", "actor", "女优"}:
        return "actress"
    if key not in {"genre", "tag", "studio", "actress"}:
        raise ValueError("kind 仅支持 genre / tag / studio / actress")
    return key


def _facet_media_refs(paths: list[str]) -> tuple[str, list[str], str]:
    """本地路径 → posterApi；coverUrl 仅供前端触发落盘，不直接展示。"""
    apis: list[str] = []
    cover = ""
    for raw in paths:
        s = str(raw or "").strip()
        if not s:
            continue
        if s.startswith(("http://", "https://")):
            if not cover:
                cover = s
            continue
        api = _embed.local_file_api(s.replace("\\", "/").lstrip("/"))
        if api and api not in apis:
            apis.append(api)
    return (apis[0] if apis else ""), apis[:4], cover


def _facet_row(
    *,
    name: str,
    count: int,
    kind: str,
    poster_paths: list[str],
    validate_covers: bool = False,
) -> dict[str, Any]:
    if validate_covers:
        paths = _embed_poster._pick_collage_posters(poster_paths, limit=4)
    else:
        locals_: list[str] = []
        covers_: list[str] = []
        seen: set[str] = set()
        for raw in poster_paths or []:
            s = str(raw or "").strip()
            if not s or s in seen:
                continue
            seen.add(s)
            if s.startswith(("http://", "https://")):
                if len(covers_) < 4:
                    covers_.append(s)
            elif len(locals_) < 4:
                locals_.append(s)
        paths = locals_ + covers_
    poster_api, poster_apis, cover_url = _facet_media_refs(paths)
    primary = next(
        (p for p in paths if not p.startswith(("http://", "https://"))),
        "",
    )
    return {
        "name": name,
        "count": count,
        "kind": kind,
        "posterPath": primary,
        "posterApi": poster_api,
        "posterApis": poster_apis,
        "coverUrl": cover_url,
    }


def _build_facets_sql_line_tokens(
    *,
    region: str,
    line_label: str,
    unknown_name: str,
    out_kind: str,
    studio: str = "",
    prefix: str = "",
    split_tokens: bool = True,
) -> list[dict[str, Any]]:
    """用 Postgres 抽取「女优：/片商：」行并汇总（比 Python 扫表快一个数量级）。"""
    _embed.ensure_schema()
    match = _embed._region_match_values(region)
    clauses = ["TRUE", _DISPLAY_READY_SQL]
    params: list[Any] = []
    if match:
        clauses.append("region = ANY(%s)")
        params.append(match)
    studio_q = str(studio or "").strip()
    pref = str(prefix or "").strip().upper()
    if studio_q:
        _append_studio_clause(clauses, params, studio_q, region=region)
    if pref:
        _append_prefix_clause(clauses, params, pref)
    where = " AND ".join(clauses)
    # 与 _split_tokens / list_items 一致
    split_re = _TOKEN_SPLIT_SQL
    label_re = f"{re.escape(line_label)}：(.+?)(?:\\n|$)"

    pool = get_meta_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            if split_tokens:
                cur.execute(
                    f"""
                    WITH base AS (
                      SELECT
                        ctid,
                        NULLIF(
                          substring(source_text from %s),
                          ''
                        ) AS line,
                        COALESCE(
                          NULLIF(poster_path, ''),
                          NULLIF(thumb_path, '')
                        ) AS local_poster,
                        NULLIF(cover_url, '') AS cover
                      FROM {_embed.TABLE}
                      WHERE {where}
                    ),
                    tokens AS (
                      SELECT DISTINCT ON (b.ctid, trim(tok))
                        trim(tok) AS name,
                        b.local_poster,
                        b.cover
                      FROM base b
                      CROSS JOIN LATERAL unnest(
                        regexp_split_to_array(b.line, %s)
                      ) AS tok
                      WHERE b.line IS NOT NULL AND trim(tok) <> ''
                    )
                    SELECT
                      name,
                      count(*)::int AS cnt,
                      (array_agg(local_poster) FILTER (
                        WHERE local_poster IS NOT NULL AND local_poster <> ''
                      ))[1:16] AS posters,
                      (array_agg(cover) FILTER (
                        WHERE cover IS NOT NULL AND cover <> ''
                      ))[1:8] AS covers
                    FROM tokens
                    GROUP BY name
                    """,
                    [label_re, *params, split_re],
                )
            else:
                cur.execute(
                    f"""
                    SELECT
                      trim(line) AS name,
                      count(*)::int AS cnt,
                      (array_agg(local_poster) FILTER (
                        WHERE local_poster IS NOT NULL AND local_poster <> ''
                      ))[1:16] AS posters,
                      (array_agg(cover) FILTER (
                        WHERE cover IS NOT NULL AND cover <> ''
                      ))[1:8] AS covers
                    FROM (
                      SELECT
                        NULLIF(
                          substring(source_text from %s),
                          ''
                        ) AS line,
                        COALESCE(
                          NULLIF(poster_path, ''),
                          NULLIF(thumb_path, '')
                        ) AS local_poster,
                        NULLIF(cover_url, '') AS cover
                      FROM {_embed.TABLE}
                      WHERE {where}
                    ) base
                    WHERE line IS NOT NULL AND trim(line) <> ''
                    GROUP BY trim(line)
                    """,
                    [label_re, *params],
                )
            rows = list(cur.fetchall())
            cur.execute(
                f"""
                SELECT count(*)::int AS n,
                       (array_agg(local_poster) FILTER (
                         WHERE local_poster IS NOT NULL AND local_poster <> ''
                       ))[1:16] AS posters,
                       (array_agg(cover) FILTER (
                         WHERE cover IS NOT NULL AND cover <> ''
                       ))[1:8] AS covers
                FROM (
                  SELECT
                    COALESCE(
                      NULLIF(poster_path, ''),
                      NULLIF(thumb_path, '')
                    ) AS local_poster,
                    NULLIF(cover_url, '') AS cover
                  FROM {_embed.TABLE}
                  WHERE {where}
                    AND (
                      source_text !~ %s
                      OR NULLIF(
                        substring(source_text from %s),
                        ''
                      ) IS NULL
                    )
                ) missing
                """,
                [*params, re.escape(line_label) + "：", label_re],
            )
            unknown = cur.fetchone() or {}

    def _merge_paths(row: dict[str, Any]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for key in ("posters", "covers"):
            for p in row.get(key) or []:
                s = str(p or "").strip()
                if not s or s in seen:
                    continue
                seen.add(s)
                out.append(s)
        return out

    out: list[dict[str, Any]] = []
    clean_actress = line_label in {"女优", "女優"}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        if clean_actress:
            from app.scrap_library.enrich import _clean_actors

            kept = _clean_actors([name])
            if not kept:
                continue
            name = kept[0]
        out.append(
            _facet_row(
                name=name,
                count=int(row.get("cnt") or 0),
                kind=out_kind,
                poster_paths=_merge_paths(row),
                validate_covers=False,
            )
        )
    unknown_n = int(unknown.get("n") or 0) if isinstance(unknown, dict) else 0
    if unknown_n > 0:
        out.append(
            _facet_row(
                name=unknown_name,
                count=unknown_n,
                kind=out_kind,
                poster_paths=_merge_paths(
                    unknown if isinstance(unknown, dict) else {}
                ),
                validate_covers=False,
            )
        )
    return out


def _build_facets_all(
    *,
    region: str = "",
    kind: str = "genre",
    studio: str = "",
    prefix: str = "",
) -> list[dict[str, Any]]:
    """从 source_text 汇总流派 / 标签 / 片商（全量，未排序切片）。"""
    key = _normalize_facet_kind(kind)
    if key == "actress":
        return _build_facets_sql_line_tokens(
            region=region,
            line_label="女优",
            unknown_name="未标注女优",
            out_kind="tag",
            studio=studio,
            prefix=prefix,
            split_tokens=True,
        )
    if key == "studio":
        # 标准前缀→厂牌表；不依赖 NFO「片商：」
        return _build_studio_facets_by_prefix(region=region)

    _embed.ensure_schema()
    match = _embed._region_match_values(region)
    clauses = ["TRUE", _DISPLAY_READY_SQL]
    params: list[Any] = []
    if match:
        clauses.append("region = ANY(%s)")
        params.append(match)
    studio_q = str(studio or "").strip()
    pref = str(prefix or "").strip().upper()
    if studio_q:
        _append_studio_clause(clauses, params, studio_q, region=region)
    if pref:
        _append_prefix_clause(clauses, params, pref)
    where = " AND ".join(clauses)

    pool = get_meta_pool()
    counts: dict[str, int] = {}
    posters: dict[str, list[str]] = {}
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT source_text, poster_path, thumb_path, cover_url, prefix
                FROM {_embed.TABLE}
                WHERE {where}
                """,
                params,
            )
            for row in cur.fetchall():
                if not isinstance(row, dict):
                    continue
                text = str(row.get("source_text") or "")
                poster = (
                    str(row.get("poster_path") or "").strip()
                    or str(row.get("thumb_path") or "").strip()
                    or str(row.get("cover_url") or "").strip()
                )
                prefix_val = str(row.get("prefix") or "").strip().upper()
                actress_m = _FACET_LINE_RE["actress"].search(text)
                actresses = set(
                    _split_tokens(actress_m.group(1)) if actress_m else []
                )
                # 标签：无独立字段时回退女优，便于 Emby 式浏览
                if key == "tag":
                    m_tag = _FACET_LINE_RE["tag"].search(text)
                    names = (
                        _split_tokens(m_tag.group(1))
                        if m_tag
                        else list(actresses)
                    )
                else:
                    m = _FACET_LINE_RE["genre"].search(text)
                    names = []
                    if m:
                        genre_raw = m.group(1)
                        genre_raw = re.split(
                            r"\s*(?:片商|发行|系列)\s*[:：]",
                            genre_raw,
                            maxsplit=1,
                        )[0]
                        for token in _split_tokens(genre_raw):
                            if token in actresses:
                                continue
                            if prefix_val and token.upper() == prefix_val:
                                continue
                            if _CODEISH_RE.match(token):
                                continue
                            if token.upper() in {"NO.1", "STYLE", "4K", "8K", "VR"}:
                                continue
                            if len(token) > 24:
                                continue
                            names.append(token)

                for name in names:
                    if not name:
                        continue
                    counts[name] = counts.get(name, 0) + 1
                    if poster:
                        bucket = posters.setdefault(name, [])
                        if poster not in bucket and len(bucket) < 24:
                            bucket.append(poster)

    out_kind = key
    return [
        _facet_row(
            name=name,
            count=n,
            kind=out_kind,
            poster_paths=posters.get(name) or [],
            validate_covers=False,
        )
        for name, n in counts.items()
    ]


def _sort_facets(
    rows: list[dict[str, Any]],
    *,
    sort: str = "count",
    order: str = "desc",
) -> list[dict[str, Any]]:
    sort_key = str(sort or "count").strip().lower()
    ascending = str(order or "desc").strip().lower() not in {
        "desc",
        "descending",
        "down",
    }

    def name_of(row: dict[str, Any]) -> str:
        return str(row.get("name") or "")

    if sort_key == "name":
        return sorted(rows, key=name_of, reverse=not ascending)

    if sort_key in {"age", "birthday"}:
        # 年龄越小越前（asc）；无年龄沉底
        def age_key(row: dict[str, Any]) -> tuple[int, int, str]:
            raw = row.get("age")
            try:
                age_i = int(raw) if raw is not None and str(raw).strip() != "" else None
            except (TypeError, ValueError):
                age_i = None
            has = age_i is not None and age_i > 0
            if ascending:
                return (0 if has else 1, age_i if has else 0, name_of(row))
            return (0 if has else 1, -(age_i if has else 0), name_of(row))

        return sorted(rows, key=age_key)

    def count_name(row: dict[str, Any]) -> tuple[int, str]:
        c = int(row.get("count") or 0)
        return (c if ascending else -c, name_of(row))

    return sorted(rows, key=count_name)


def _facets_snap_region_key(region: str) -> str:
    raw = str(region or "").strip() or "_all"
    return re.sub(r"[^\w.\-]+", "_", raw)[:96] or "_all"


def _facets_snap_path(region: str, kind: str) -> Path:
    d = data_dir().joinpath(*_FACETS_SNAP_DIR) / _facets_snap_region_key(region)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{kind}.json"


def _load_facets_snapshot(region: str, kind: str) -> list[dict[str, Any]] | None:
    path = _facets_snap_path(region, kind)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("facets snapshot read failed %s: %s", path, e)
        return None
    if int(data.get("v") or 0) != _FACETS_SNAP_VERSION:
        return None
    rows = data.get("rows")
    if not isinstance(rows, list):
        return None
    return [r for r in rows if isinstance(r, dict)]


def _save_facets_snapshot(
    region: str, kind: str, rows: list[dict[str, Any]]
) -> Path:
    path = _facets_snap_path(region, kind)
    tmp = path.with_suffix(".tmp")
    payload = {
        "v": _FACETS_SNAP_VERSION,
        "region": str(region or ""),
        "kind": kind,
        "updatedAt": time.time(),
        "count": len(rows),
        "rows": rows,
    }
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def _purge_facets_memory_cache(*, region: str = "", kind: str = "") -> None:
    kind_q = str(kind or "").strip()
    region_s = str(region or "")
    dead: list[str] = []
    for k in _FACETS_CACHE:
        # key: v8|{region}|{kind}|{studio}|{pref}
        parts = k.split("|")
        if len(parts) < 3:
            continue
        if parts[1] != region_s:
            continue
        if kind_q and parts[2] != kind_q:
            continue
        dead.append(k)
    for k in dead:
        _FACETS_CACHE.pop(k, None)


def facets_snapshot_meta(*, region: str = "") -> dict[str, Any]:
    """单区或全部区的快照元信息。"""
    from app.core.region_meta import REGION_ORDER

    rid = str(region or "").strip()
    if rid:
        return _facets_snapshot_meta_one(rid)
    regions: dict[str, Any] = {}
    for r in REGION_ORDER:
        regions[r] = _facets_snapshot_meta_one(r)
    rec_path = _recommend_snap_path()
    recommend: dict[str, Any] = {"exists": False}
    if rec_path.is_file():
        try:
            raw = json.loads(rec_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                recommend = {
                    "exists": True,
                    "shelves": len(raw.get("shelves") or []),
                    "total": int(raw.get("total") or 0),
                    "updatedAt": float(raw.get("updatedAt") or 0),
                }
            else:
                recommend = {"exists": True, "shelves": 0, "total": 0, "updatedAt": 0}
        except Exception:  # noqa: BLE001
            recommend = {"exists": True, "shelves": 0, "total": 0, "updatedAt": 0}
    return {"regions": regions, "recommend": recommend}


def _facets_snapshot_meta_one(region: str) -> dict[str, Any]:
    kinds: dict[str, Any] = {}
    for kind in ("genre", "actress", "studio", "tag"):
        path = _facets_snap_path(region, kind)
        if not path.is_file():
            kinds[kind] = {"exists": False}
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            kinds[kind] = {
                "exists": True,
                "count": int(data.get("count") or 0),
                "updatedAt": float(data.get("updatedAt") or 0),
            }
        except Exception:  # noqa: BLE001
            kinds[kind] = {"exists": True, "count": 0, "updatedAt": 0}
    return {"region": str(region or ""), "kinds": kinds}


def refresh_facets_snapshot(
    *,
    region: str = "",
    kinds: list[str] | None = None,
    all_regions: bool = False,
) -> dict[str, Any]:
    """重建分面磁盘快照。

    默认策略：
    - 种类：studio / genre / actress（片商页三个分面）
    - 范围：all_regions 或 region 为空 → 六区全量；否则仅指定区
    - 附带：推荐货架快照 + 影片一级首页（发行日期）内存预热
    全量约数秒，可同步完成。
    """
    from app.core.region_meta import REGION_ORDER

    if kinds:
        want = [_normalize_facet_kind(k) for k in kinds]
    else:
        want = ["studio", "genre", "actress"]
    seen: set[str] = set()
    ordered: list[str] = []
    for k in want:
        if k in seen:
            continue
        seen.add(k)
        ordered.append(k)

    rid = str(region or "").strip()
    if all_regions or not rid:
        regions = list(REGION_ORDER)
    else:
        regions = [rid]

    by_region: dict[str, dict[str, int]] = {}
    with _facets_snap_lock:
        for reg in regions:
            built: dict[str, int] = {}
            for key in ordered:
                rows = _build_facets_all(
                    region=reg, kind=key, studio="", prefix=""
                )
                _save_facets_snapshot(reg, key, rows)
                built[key] = len(rows)
            _purge_facets_memory_cache(region=reg)
            now = time.monotonic()
            for key in ordered:
                hit_rows = _load_facets_snapshot(reg, key) or []
                _FACETS_CACHE[f"v8|{reg}|{key}||"] = (now, list(hit_rows))
            enforce_max(_FACETS_CACHE, _FACETS_CACHE_MAX)
            by_region[reg] = built

    recommend: dict[str, Any] = {}
    try:
        rec = _embed_recommend.refresh_recommend_snapshot()
        recommend = {
            "shelves": int(rec.get("shelves") or 0),
            "total": int(rec.get("total") or 0),
        }
    except Exception as e:  # noqa: BLE001
        log.warning("recommend snapshot refresh failed: %s", e)

    warmed = 0
    try:
        _ITEMS_HUB_CACHE.clear()
        for reg in regions:
            _embed.list_items(
                region=reg,
                sort="year",
                order="desc",
                offset=0,
                limit=45,
            )
            warmed += 1
    except Exception as e:  # noqa: BLE001
        log.warning("movies hub warm failed: %s", e)

    flat: dict[str, int] = {}
    if len(regions) == 1:
        flat = dict(by_region.get(regions[0]) or {})
    else:
        for built in by_region.values():
            for k, n in built.items():
                flat[k] = int(flat.get(k) or 0) + int(n)
    if recommend:
        flat["recommend"] = int(recommend.get("shelves") or 0)
    if warmed:
        flat["moviesWarm"] = warmed

    return {
        "region": "" if len(regions) > 1 else regions[0],
        "regions": list(regions),
        "byRegion": by_region,
        "kinds": flat,
        "recommend": recommend,
        "updatedAt": time.time(),
    }
