"""Browse / search / detail against Postgres resource DB."""

from __future__ import annotations

import json
import time
from typing import Any

from . import pg
from .resource_format import (
    FILTERED_CORE_COLS,
    FILTER_META_JOIN,
    HASH_RE,
    LIST_META_JOIN,
    PUBLIC_RESOURCE_FILTER,
    RESOURCE_SELECT,
    SOURCE_META_JOIN,
    format_resource,
    format_resources,
)
from .search_av import (
    apply_av_code_boundary_filter,
    build_av_code_continuation_reject,
    build_av_code_ilike_patterns,
    is_uncensored_maker_code,
)
from .search_constants import (
    MAX_SEARCH_OFFSET,
    escape_ilike,
    normalize_match_mode,
    normalize_sort_type,
    resolve_sort_type_for_query,
)
from .search_keywords import (
    build_keyword_filter,
    build_relevance_order_by,
    extract_keywords,
)
from .region_board_allowlist import (
    board_fid_allowed,
    normalize_region,
    region_allowlist_sql,
)
from .search_prefer import build_prefer_filter_sql

# Bitmagnet service.ts?1 week / 1 month / 1 year???? 7/31/365 day?
TIME_FILTERS = {
    "gt-1day": "AND r.created_at > now() - interval '1 day'",
    "gt-7day": "AND r.created_at > now() - interval '1 week'",
    "gt-31day": "AND r.created_at > now() - interval '1 month'",
    "gt-365day": "AND r.created_at > now() - interval '1 year'",
}

# Bitmagnet???? BETWEEN??? inclusive??gt5gb ? >
SIZE_FILTERS = {
    "lt100mb": "AND r.size < 100 * 1024 * 1024::bigint",
    "gt100mb-lt500mb": (
        "AND r.size BETWEEN 100 * 1024 * 1024::bigint "
        "AND 500 * 1024 * 1024::bigint"
    ),
    "gt500mb-lt1gb": (
        "AND r.size BETWEEN 500 * 1024 * 1024::bigint "
        "AND 1024 * 1024 * 1024::bigint"
    ),
    "gt1gb-lt5gb": (
        "AND r.size BETWEEN 1 * 1024 * 1024 * 1024::bigint "
        "AND 5 * 1024 * 1024 * 1024::bigint"
    ),
    "gt5gb": "AND r.size > 5 * 1024 * 1024 * 1024::bigint",
}

SORT_SQL = {
    "default": "r.created_at DESC",
    "size": "r.size DESC NULLS LAST, r.created_at DESC",
    # links_count ?? FILTER_META?????enrich ??? LIST_META ??? links
    "count": "coalesce(rs.links_count, 1) DESC, r.created_at DESC",
    "date": "r.created_at DESC",
}

# Bitmagnet UNION ?????????? rs?
_BM_ARM_ORDER = {
    "default": "r.created_at DESC",
    "date": "r.created_at DESC",
    "size": "r.size DESC NULLS LAST, r.created_at DESC",
}
_BM_OUTER_ORDER = {
    "default": "u.created_at DESC",
    "date": "u.created_at DESC",
    "size": "u.size DESC NULLS LAST, u.created_at DESC",
}

_ILIKE_ESC = "ESCAPE '\\'"

_trgm_ok: bool | None = None
_SEARCH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_SEARCH_CACHE_TTL = 30.0
_SEARCH_CACHE_MAX = 64
# 搜索 SQL 超时（毫秒）；超时后前端可重试/收窄时间范围
_SEARCH_STATEMENT_TIMEOUT_MS = 8000
# 精确 COUNT 上限：超过则返回 cap（列表不依赖精确总数）
_SEARCH_COUNT_CAP = 1000


def _search_cache_get(key: str) -> dict[str, Any] | None:
    hit = _SEARCH_CACHE.get(key)
    if not hit:
        return None
    ts, data = hit
    if time.monotonic() - ts > _SEARCH_CACHE_TTL:
        _SEARCH_CACHE.pop(key, None)
        return None
    return data


def _search_cache_set(key: str, data: dict[str, Any]) -> None:
    if len(_SEARCH_CACHE) >= _SEARCH_CACHE_MAX:
        oldest = min(_SEARCH_CACHE.items(), key=lambda kv: kv[1][0])[0]
        _SEARCH_CACHE.pop(oldest, None)
    _SEARCH_CACHE[key] = (time.monotonic(), data)


def pg_trgm_available() -> bool:
    global _trgm_ok
    if _trgm_ok is None:
        try:
            rows = pg.query(
                "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm' LIMIT 1"
            )
            _trgm_ok = bool(rows)
        except Exception:
            _trgm_ok = False
    return _trgm_ok


def _page_params(p: int, ps: int) -> tuple[int, int, int]:
    page = max(1, int(p or 1))
    # search pool may request up to 80; browse route still caps at 50
    page_size = min(max(int(ps or 10), 1), 80)
    offset = min((page - 1) * page_size, MAX_SEARCH_OFFSET)
    return page, page_size, offset


def _list_enrich_sql(from_filtered: str = "filtered") -> str:
    """Bitmagnet?CTE ????? LIST_META?????????"""
    return f"""
SELECT {RESOURCE_SELECT}
FROM {from_filtered} r
{LIST_META_JOIN}
"""


_browse_indexes_ready = False


def _ensure_browse_indexes() -> None:
    """?????? board_fid ??????????"""
    global _browse_indexes_ready
    if _browse_indexes_ready:
        return
    try:
        pg.query(
            "CREATE INDEX IF NOT EXISTS idx_resource_sources_board_fid "
            "ON resource_sources (board_fid)"
        )
    except Exception:
        pass
    _browse_indexes_ready = True


def browse_resources(
    *,
    p: int = 1,
    ps: int = 10,
    link_kind: str | None = None,
    board_fid: str | None = None,
    board: str | None = None,
    board_parent: str | None = None,
    keyword: str | None = None,
    with_total_count: bool = False,
) -> dict[str, Any]:
    """???? / ?????

    ? board_fid ?? resource_sources ???``fid`` ? ``fid:%``??
    ???? COUNT?``ps+1`` ? has_more???? 5?10s ?????
    """
    page, page_size, offset = _page_params(p, ps)
    kind = (link_kind or "").strip()
    link_sql = ""
    if kind == "magnet":
        link_sql = "AND lower(COALESCE(r.ed2k_link, '')) LIKE 'magnet:%%'"
    elif kind == "ed2k":
        link_sql = "AND lower(COALESCE(r.ed2k_link, '')) LIKE 'ed2k://%%'"

    kw = (keyword or "").strip()
    kw_sql = ""
    kw_params: list[Any] = []
    if len(kw) >= 2:
        pat = f"%{escape_ilike(kw)}%"
        kw_sql = (
            f"AND (r.filename ILIKE %s {_ILIKE_ESC} "
            f"OR COALESCE(rs.title, '') ILIKE %s {_ILIKE_ESC})"
        )
        kw_params = [pat, pat]

    fid = (board_fid or "").strip()
    board_name = (board or "").strip()
    parent = (board_parent or "").strip()
    fetch_limit = page_size if with_total_count else page_size + 1

    # ?? ????? board_fid???? fid:%???
    if fid:
        _ensure_browse_indexes()
        # ?? 141 ? 141 + 141:%??? 141:689 ? ?? + ?????
        fid_params: list[Any] = [fid, f"{fid}:%%", *kw_params]
        list_sql = f"""
WITH filtered AS (
  SELECT {FILTERED_CORE_COLS}
  FROM resource_sources rs
  JOIN ed2k_resources r ON r.hash = rs.hash
  WHERE (rs.board_fid = %s OR rs.board_fid LIKE %s)
  {PUBLIC_RESOURCE_FILTER}
  {link_sql}
  {kw_sql}
  ORDER BY r.created_at DESC
  LIMIT %s OFFSET %s
)
{_list_enrich_sql("filtered")}
"""
        rows = pg.query(list_sql, [*fid_params, fetch_limit, offset])
        if with_total_count:
            count_sql = f"""
SELECT COUNT(*)::int AS total_count
FROM resource_sources rs
JOIN ed2k_resources r ON r.hash = rs.hash
WHERE (rs.board_fid = %s OR rs.board_fid LIKE %s)
{PUBLIC_RESOURCE_FILTER}
{link_sql}
{kw_sql}
"""
            total = int(
                (pg.query(count_sql, fid_params) or [{}])[0].get(
                    "total_count", 0
                )
                or 0
            )
            rows = rows[:page_size]
            has_more = offset + len(rows) < total
        else:
            has_more = len(rows) > page_size
            rows = rows[:page_size]
            total = offset + len(rows) + (1 if has_more else 0)
        return {
            "resources": format_resources(rows, prefetch_torrents=False),
            "total_count": total,
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
        }

    # ?? ???????????????????? COUNT???
    where = ["TRUE", PUBLIC_RESOURCE_FILTER.strip()]
    params: list[Any] = []
    if link_sql:
        where.append(link_sql)
    need_meta = bool(board_name or parent or kw_sql)
    if parent:
        where.append(
            "AND (rs.board_name = %s OR rs.board_name LIKE %s OR rs.board_name LIKE %s)"
        )
        params.extend([parent, f"{parent} ? %", f"{parent}-%"])
    elif board_name:
        where.append(
            "AND replace(COALESCE(rs.board_name, ''), '-', ' ? ') = %s"
        )
        params.append(board_name.replace("-", " ? "))
    if kw_sql:
        where.append(kw_sql)
        params.extend(kw_params)

    where_sql = "\n".join(where)

    if need_meta:
        list_sql = f"""
WITH filtered AS (
  SELECT {FILTERED_CORE_COLS}
  FROM resource_sources rs
  JOIN ed2k_resources r ON r.hash = rs.hash
  WHERE {where_sql}
  ORDER BY r.created_at DESC
  LIMIT %s OFFSET %s
)
{_list_enrich_sql("filtered")}
"""
    else:
        list_sql = f"""
WITH filtered AS (
  SELECT {FILTERED_CORE_COLS}
  FROM ed2k_resources r
  WHERE {where_sql}
  ORDER BY r.created_at DESC
  LIMIT %s OFFSET %s
)
{_list_enrich_sql("filtered")}
"""

    rows = pg.query(list_sql, [*params, fetch_limit, offset])
    if with_total_count:
        if need_meta:
            count_sql = f"""
SELECT COUNT(*)::int AS total_count
FROM resource_sources rs
JOIN ed2k_resources r ON r.hash = rs.hash
WHERE {where_sql}
"""
        else:
            count_sql = f"""
SELECT COUNT(*)::int AS total_count
FROM ed2k_resources r
WHERE {where_sql}
"""
        total = int(
            (pg.query(count_sql, params) or [{}])[0].get("total_count", 0) or 0
        )
        rows = rows[:page_size]
        has_more = offset + len(rows) < total
    else:
        has_more = len(rows) > page_size
        rows = rows[:page_size]
        total = offset + len(rows) + (1 if has_more else 0)

    return {
        "resources": format_resources(rows, prefetch_torrents=False),
        "total_count": total,
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
    }


def resource_by_hash(hash_: str) -> dict[str, Any] | None:
    h = (hash_ or "").strip().upper()
    if not h:
        return None
    sql = f"""
SELECT {RESOURCE_SELECT}
FROM ed2k_resources r
{SOURCE_META_JOIN}
WHERE r.hash = %s
{PUBLIC_RESOURCE_FILTER}
LIMIT 1
"""
    rows = pg.query(sql, [h])
    if not rows:
        return None
    # 色花详情不拉外网 .torrent 补文件树（会卡住首屏）；文件列表前端也不再展示
    return format_resource(rows[0], enrich_magnets=False)


def _av_union_count(
    patterns: list[str], reject: str | None
) -> int:
    file_or = " OR ".join(
        [f"r.filename ILIKE %s {_ILIKE_ESC}"] * len(patterns)
    )
    title_or = " OR ".join(
        [f"rs.title ILIKE %s {_ILIKE_ESC}"] * len(patterns)
    )
    file_reject = " AND r.filename !~* %s" if reject else ""
    title_reject = " AND rs.title !~* %s" if reject else ""
    sql = f"""
SELECT COUNT(*)::int AS total FROM (
  SELECT r.hash FROM ed2k_resources r
  WHERE ({file_or}){file_reject}
  {PUBLIC_RESOURCE_FILTER}
  UNION
  SELECT r.hash FROM resource_sources rs
  JOIN ed2k_resources r ON r.hash = rs.hash
  WHERE ({title_or}){title_reject}
  {PUBLIC_RESOURCE_FILTER}
) t
"""
    params: list[Any] = [*patterns]
    if reject:
        params.append(reject)
    params.extend(patterns)
    if reject:
        params.append(reject)
    rows = pg.query(sql, params)
    return int(rows[0]["total"]) if rows else 0


def _filter_rows_by_region(
    rows: list[dict[str, Any]],
    region: str | None,
    *,
    include_optional: bool = True,
) -> list[dict[str, Any]]:
    """????????????????? board_fid SQL ?? AV/Bitmagnet??"""
    if not region:
        return rows
    return [
        r
        for r in rows
        if board_fid_allowed(
            r.get("board_fid"), region, include_optional=include_optional
        )
    ]


def _av_union_list(
    patterns: list[str],
    reject: str | None,
    *,
    fetch_limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    file_or = " OR ".join(
        [f"r.filename ILIKE %s {_ILIKE_ESC}"] * len(patterns)
    )
    title_or = " OR ".join(
        [f"rs.title ILIKE %s {_ILIKE_ESC}"] * len(patterns)
    )
    file_reject = " AND r.filename !~* %s" if reject else ""
    title_reject = " AND rs.title !~* %s" if reject else ""
    # ???? 480??? region ???????????
    arm_limit = min(max(fetch_limit + offset, fetch_limit), 480)
    sql = f"""
WITH hits AS (
  (
    SELECT r.hash, r.created_at FROM ed2k_resources r
    WHERE ({file_or}){file_reject}
    {PUBLIC_RESOURCE_FILTER}
    ORDER BY r.created_at DESC
    LIMIT %s
  )
  UNION
  (
    SELECT r.hash, r.created_at FROM resource_sources rs
    JOIN ed2k_resources r ON r.hash = rs.hash
    WHERE ({title_or}){title_reject}
    {PUBLIC_RESOURCE_FILTER}
    ORDER BY r.created_at DESC
    LIMIT %s
  )
),
uniq AS (
  SELECT hash, MAX(created_at) AS created_at FROM hits GROUP BY hash
),
filtered AS (
  SELECT {FILTERED_CORE_COLS}
  FROM uniq u
  JOIN ed2k_resources r ON r.hash = u.hash
  ORDER BY u.created_at DESC
  LIMIT %s OFFSET %s
)
{_list_enrich_sql("filtered")}
"""
    params: list[Any] = [*patterns]
    if reject:
        params.append(reject)
    params.append(arm_limit)
    params.extend(patterns)
    if reject:
        params.append(reject)
    params.extend([arm_limit, fetch_limit, offset])
    return pg.query(sql, params)


def _search_count_sql(where_sql: str, *, with_meta: bool) -> str:
    join = FILTER_META_JOIN if with_meta else ""
    return f"""
SELECT COUNT(*)::int AS total_count
FROM ed2k_resources r
{join}
WHERE {where_sql}
"""


def _search_list_sql(where_sql: str, order: str, *, with_meta: bool) -> str:
    """filtered CTE ? LIST_META enrich?with_meta ???? FILTER_META?prefer/count??"""
    join = FILTER_META_JOIN if with_meta else ""
    return f"""
WITH filtered AS (
  SELECT {FILTERED_CORE_COLS}
  FROM ed2k_resources r
  {join}
  WHERE {where_sql}
  ORDER BY {order}
  LIMIT %s OFFSET %s
)
{_list_enrich_sql("filtered")}
"""


def _bitmagnet_filename_count(
    file_sql: str,
    file_params: list[Any],
    extra_where: str,
) -> int:
    """Bitmagnet????????? list ???????"""
    sql = f"""
SELECT COUNT(*)::int AS total
FROM ed2k_resources r
WHERE ({file_sql})
{PUBLIC_RESOURCE_FILTER}
{extra_where}
"""
    rows = pg.query(sql, file_params)
    return int(rows[0]["total"]) if rows else 0


def _bitmagnet_union_count(
    file_sql: str,
    title_sql: str,
    file_params: list[Any],
    title_params: list[Any],
    extra_where: str,
) -> int:
    """filename ∪ title 命中数；封顶避免全库 COUNT 拖死。"""
    sql = f"""
SELECT COUNT(*)::int AS total FROM (
  SELECT hash FROM (
    SELECT r.hash FROM ed2k_resources r
    WHERE ({file_sql})
    {PUBLIC_RESOURCE_FILTER}
    {extra_where}
    UNION
    SELECT r.hash FROM resource_sources rs
    JOIN ed2k_resources r ON r.hash = rs.hash
    WHERE ({title_sql})
    {PUBLIC_RESOURCE_FILTER}
    {extra_where}
  ) u
  LIMIT %s
) t
"""
    rows = pg.query(
        sql,
        [*file_params, *title_params, _SEARCH_COUNT_CAP + 1],
        statement_timeout_ms=_SEARCH_STATEMENT_TIMEOUT_MS,
    )
    n = int(rows[0]["total"]) if rows else 0
    return min(n, _SEARCH_COUNT_CAP)


def _bitmagnet_filename_list(
    file_sql: str,
    file_params: list[Any],
    extra_where: str,
    *,
    sort_key: str,
    fetch_limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    """Bitmagnet ??????? name/filename?LIMIT ?? enrich?"""
    arm_order = _BM_ARM_ORDER.get(sort_key, _BM_ARM_ORDER["default"])
    sql = f"""
WITH filtered AS (
  SELECT {FILTERED_CORE_COLS}
  FROM ed2k_resources r
  WHERE ({file_sql})
  {PUBLIC_RESOURCE_FILTER}
  {extra_where}
  ORDER BY {arm_order}
  LIMIT %s OFFSET %s
)
{_list_enrich_sql("filtered")}
"""
    return pg.query(sql, [*file_params, fetch_limit, offset])


def _bitmagnet_union_list(
    file_sql: str,
    title_sql: str,
    file_params: list[Any],
    title_params: list[Any],
    extra_where: str,
    *,
    sort_key: str,
    fetch_limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    """Bitmagnet?filename ? title ??????

    ???? title????????????????????? SONE-996 ????
    ???????????? title?????
    """
    arm_order = _BM_ARM_ORDER.get(sort_key, _BM_ARM_ORDER["default"])
    outer_order = _BM_OUTER_ORDER.get(sort_key, _BM_OUTER_ORDER["default"])
    arm_limit = min(max(fetch_limit, 40), 240)
    sql = f"""
WITH hits AS (
  (
    SELECT r.hash, r.created_at, r.size FROM ed2k_resources r
    WHERE ({file_sql})
    {PUBLIC_RESOURCE_FILTER}
    {extra_where}
    ORDER BY {arm_order}
    LIMIT %s
  )
  UNION
  (
    SELECT r.hash, r.created_at, r.size FROM resource_sources rs
    JOIN ed2k_resources r ON r.hash = rs.hash
    WHERE ({title_sql})
    {PUBLIC_RESOURCE_FILTER}
    {extra_where}
    ORDER BY {arm_order}
    LIMIT %s
  )
),
uniq AS (
  SELECT hash, MAX(created_at) AS created_at, MAX(size) AS size
  FROM hits GROUP BY hash
),
filtered AS (
  SELECT {FILTERED_CORE_COLS}
  FROM uniq u
  JOIN ed2k_resources r ON r.hash = u.hash
  ORDER BY {outer_order}
  LIMIT %s OFFSET %s
)
{_list_enrich_sql("filtered")}
"""
    return pg.query(
        sql,
        [*file_params, arm_limit, *title_params, arm_limit, fetch_limit, offset],
        statement_timeout_ms=_SEARCH_STATEMENT_TIMEOUT_MS,
    )


def search_resources(
    *,
    keyword: str,
    p: int = 1,
    ps: int = 10,
    sort_type: str = "default",
    filter_time: str = "all",
    filter_size: str = "all",
    match_mode: str = "smart",
    with_total_count: bool = True,
    count_only: bool = False,
    prefer_chinese: bool = False,
    prefer_crack: bool = False,
    japan_censored: bool = False,
    exclude_uncensored: bool | None = None,
    region: str | None = None,
    include_optional_boards: bool = True,
) -> dict[str, Any]:
    global _trgm_ok

    kw = (keyword or "").strip()
    if len(kw) < 2:
        raise ValueError("????? 2 ???")

    page, page_size, offset = _page_params(p, ps)
    mode = normalize_match_mode(match_mode)
    sort_key = resolve_sort_type_for_query(normalize_sort_type(sort_type))
    use_trgm = pg_trgm_available()
    full_plain = kw.replace('"', "").strip()

    cache_key = json.dumps(
        {
            "kw": kw,
            "p": page,
            "ps": page_size,
            "sort": sort_type,
            "time": filter_time,
            "size": filter_size,
            "mode": mode,
            "wtc": with_total_count,
            "co": count_only,
            "cn": prefer_chinese,
            "ck": prefer_crack,
            "yc": japan_censored,
            "xu": exclude_uncensored,
            "region": region or "",
            "optb": include_optional_boards,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cached = _search_cache_get(cache_key)
    if cached is not None:
        return cached

    def _cached(payload: dict[str, Any]) -> dict[str, Any]:
        _search_cache_set(cache_key, payload)
        return payload

    if HASH_RE.match(kw):
        one = resource_by_hash(kw)
        items = [one] if one else []
        return _cached(
            {
                "keywords": [kw.upper()],
                "resources": [] if count_only else items,
                "total_count": len(items),
                "has_more": False,
                "page": 1,
                "page_size": page_size,
                "match_mode": mode,
            }
        )

    crack = prefer_crack and not is_uncensored_maker_code(kw)
    # ?????????????? AV/Bitmagnet ?????? count ? SQL
    resolved_region = normalize_region(region) or (
        "japan_censored" if japan_censored else None
    )
    prefer_sql = build_prefer_filter_sql(
        prefer_chinese=prefer_chinese,
        prefer_crack=crack,
    )
    region_sql = (
        region_allowlist_sql(
            resolved_region, include_optional=include_optional_boards
        )
        if resolved_region
        else ""
    )
    # ??????region ??? prefer_sql
    del exclude_uncensored

    kw_items = extract_keywords(kw, mode)
    kw_sql, kw_params, code_bound = build_keyword_filter(
        kw_items,
        mode,
        full_keyword=full_plain if mode == "fuzzy" else None,
        use_trgm=use_trgm,
    )

    time_sql = TIME_FILTERS.get(filter_time, "")
    size_sql = SIZE_FILTERS.get(filter_size, "")

    # count+region ?????????? SQL???????? + ?????
    av_fast = (
        bool(code_bound)
        and mode == "exact"
        and not prefer_sql.strip()
        and not time_sql
        and not size_sql
        and not (count_only and bool(region_sql))
    )

    # AV UNION fast path
    if av_fast and code_bound:
        patterns: list[str] = []
        seen: set[str] = set()
        for ck in code_bound:
            for pat in build_av_code_ilike_patterns(ck):
                if pat not in seen:
                    seen.add(pat)
                    patterns.append(pat)
        reject = (
            build_av_code_continuation_reject(code_bound[0])
            if len(code_bound) == 1
            else None
        )

        if count_only:
            total = _av_union_count(patterns, reject)
            return _cached(
                {
                    "keywords": [x["keyword"] for x in kw_items],
                    "resources": [],
                    "total_count": total,
                    "has_more": offset + page_size < total,
                    "page": page,
                    "page_size": page_size,
                    "match_mode": mode,
                }
            )

        base_fetch = page_size if with_total_count else page_size + 1
        # ? region ????????????????
        if resolved_region:
            fetch_limit = min(max(base_fetch * 16, base_fetch + 80), 400)
        else:
            fetch_limit = min(max(base_fetch * 8, base_fetch + 40), 240)
        raw_rows = _av_union_list(
            patterns, reject, fetch_limit=fetch_limit, offset=offset
        )
        # ???????????????????????????????
        window_full = len(raw_rows) >= fetch_limit
        rows = apply_av_code_boundary_filter(raw_rows, code_bound)
        rows = _filter_rows_by_region(
            rows,
            resolved_region,
            include_optional=include_optional_boards,
        )
        has_more = False
        total = 0
        if with_total_count and not resolved_region:
            total = _av_union_count(patterns, reject)
            has_more = offset + min(len(rows), page_size) < total
            rows = rows[:page_size]
        else:
            overflow = len(rows) > page_size
            # ???????/??????????????????
            maybe_more = window_full and len(rows) <= page_size
            has_more = overflow or maybe_more
            rows = rows[:page_size]
            total = offset + len(rows) + (1 if has_more else 0)
        return _cached(
            {
                "keywords": [x["keyword"] for x in kw_items],
                "resources": format_resources(rows, prefetch_torrents=False),
                "total_count": total,
                "has_more": has_more,
                "page": page,
                "page_size": page_size,
                "match_mode": mode,
            }
        )

    extra_filters = "\n".join(
        x for x in (time_sql, size_sql) if x
    )

    # Bitmagnet ??????/title ?? ILIKE ? UNION ? LIMIT ? enrich
    # ?? prefer?? count/relevance?? exact-???region ???????
    use_bitmagnet = (
        not prefer_sql.strip()
        and sort_key in _BM_ARM_ORDER
        and not (mode == "exact" and code_bound)
        and not (count_only and bool(region_sql))
    )

    if use_bitmagnet:
        file_sql, file_params, _ = build_keyword_filter(
            kw_items,
            mode,
            full_keyword=full_plain if mode == "fuzzy" else None,
            use_trgm=use_trgm and mode == "fuzzy",
            field="filename",
        )
        title_sql, title_params, _ = build_keyword_filter(
            kw_items,
            mode,
            full_keyword=full_plain if mode == "fuzzy" else None,
            use_trgm=use_trgm and mode == "fuzzy",
            field="title",
        )

        if count_only:
            try:
                total = _bitmagnet_union_count(
                    file_sql,
                    title_sql,
                    file_params,
                    title_params,
                    extra_filters,
                )
            except Exception as e:
                msg = str(e).lower()
                if use_trgm and ("similarity" in msg or "word_similarity" in msg):
                    _trgm_ok = False
                    file_sql, file_params, _ = build_keyword_filter(
                        kw_items, mode, field="filename"
                    )
                    title_sql, title_params, _ = build_keyword_filter(
                        kw_items, mode, field="title"
                    )
                    total = _bitmagnet_union_count(
                        file_sql,
                        title_sql,
                        file_params,
                        title_params,
                        extra_filters,
                    )
                else:
                    raise
            return _cached(
                {
                    "keywords": [x["keyword"] for x in kw_items],
                    "resources": [],
                    "total_count": total,
                    "has_more": offset + page_size < total,
                    "page": page,
                    "page_size": page_size,
                    "match_mode": mode,
                }
            )

        base_fetch = page_size if with_total_count else page_size + 1
        fetch_n = (
            min(max(base_fetch * 8, base_fetch + 40), 240)
            if resolved_region
            else base_fetch
        )
        try:
            rows = _bitmagnet_union_list(
                file_sql,
                title_sql,
                file_params,
                title_params,
                extra_filters,
                sort_key=sort_key,
                fetch_limit=fetch_n,
                offset=offset,
            )
        except Exception as e:
            msg = str(e).lower()
            if use_trgm and ("similarity" in msg or "word_similarity" in msg):
                _trgm_ok = False
                file_sql, file_params, _ = build_keyword_filter(
                    kw_items, mode, field="filename"
                )
                title_sql, title_params, _ = build_keyword_filter(
                    kw_items, mode, field="title"
                )
                rows = _bitmagnet_union_list(
                    file_sql,
                    title_sql,
                    file_params,
                    title_params,
                    extra_filters,
                    sort_key=sort_key,
                    fetch_limit=fetch_n,
                    offset=offset,
                )
            else:
                raise

        window_full = len(rows) >= fetch_n
        rows = _filter_rows_by_region(
            rows,
            resolved_region,
            include_optional=include_optional_boards,
        )

        total = 0
        has_more = False
        if with_total_count and not resolved_region:
            total = _bitmagnet_union_count(
                file_sql,
                title_sql,
                file_params,
                title_params,
                extra_filters,
            )
            has_more = offset + min(len(rows), page_size) < total
            rows = rows[:page_size]
        else:
            overflow = len(rows) > page_size
            maybe_more = bool(resolved_region) and window_full and len(rows) <= page_size
            has_more = overflow or maybe_more
            rows = rows[:page_size]
            total = offset + len(rows) + (1 if has_more else 0)

        return _cached(
            {
                "keywords": [x["keyword"] for x in kw_items],
                "resources": format_resources(rows, prefetch_torrents=False),
                "total_count": total,
                "has_more": has_more,
                "page": page,
                "page_size": page_size,
                "match_mode": mode,
            }
        )

    # prefer / count+region / exact-???????? JOIN meta
    where = [
        "TRUE",
        PUBLIC_RESOURCE_FILTER.strip(),
        f"AND ({kw_sql})",
    ]
    params: list[Any] = list(kw_params)
    if prefer_sql:
        where.append(prefer_sql)
    # ???? JOIN meta?region ??? SQL?count ???cn/ck ?????
    if region_sql:
        where.append(region_sql)
    if time_sql:
        where.append(time_sql)
    if size_sql:
        where.append(size_sql)
    where_sql = "\n".join(where)

    order_params: list[Any] = []
    if sort_key == "relevance":
        order, order_params = build_relevance_order_by(
            kw_items, full_plain, use_trgm=use_trgm
        )
    else:
        order = SORT_SQL.get(sort_key, SORT_SQL["default"])

    need_meta = (
        bool(prefer_sql.strip())
        or bool(region_sql)
        or sort_key == "count"
        or sort_key == "relevance"
    )

    if count_only:
        count_rows = pg.query(
            _search_count_sql(where_sql, with_meta=need_meta), params
        )
        total = int(count_rows[0]["total_count"]) if count_rows else 0
        return _cached(
            {
                "keywords": [x["keyword"] for x in kw_items],
                "resources": [],
                "total_count": total,
                "has_more": offset + page_size < total,
                "page": page,
                "page_size": page_size,
                "match_mode": mode,
            }
        )

    base_fetch = page_size if with_total_count else page_size + 1
    fetch_n = (
        min(max(base_fetch * 8, base_fetch + 40), 240)
        if code_bound
        else base_fetch
    )

    list_sql = _search_list_sql(where_sql, order, with_meta=need_meta)
    try:
        rows = pg.query(list_sql, [*params, *order_params, fetch_n, offset])
    except Exception as e:
        msg = str(e).lower()
        if use_trgm and ("similarity" in msg or "word_similarity" in msg):
            _trgm_ok = False
            if sort_key == "relevance":
                order, order_params = build_relevance_order_by(
                    kw_items, full_plain, use_trgm=False
                )
            kw_sql2, kw_params2, _ = build_keyword_filter(
                kw_items, mode, full_keyword=full_plain, use_trgm=False
            )
            where[2] = f"AND ({kw_sql2})"
            where_sql = "\n".join(where)
            list_sql = _search_list_sql(where_sql, order, with_meta=need_meta)
            rows = pg.query(
                list_sql, [*kw_params2, *order_params, fetch_n, offset]
            )
            params = list(kw_params2)
        else:
            raise

    if code_bound:
        rows = apply_av_code_boundary_filter(rows, code_bound)

    total = 0
    has_more = False
    if with_total_count:
        count_rows = pg.query(
            _search_count_sql(where_sql, with_meta=need_meta), params
        )
        total = int(count_rows[0]["total_count"]) if count_rows else 0
        has_more = offset + min(len(rows), page_size) < total
        rows = rows[:page_size]
    else:
        has_more = len(rows) > page_size
        rows = rows[:page_size]
        total = offset + len(rows) + (1 if has_more else 0)

    return _cached(
        {
            "keywords": [x["keyword"] for x in kw_items],
            "resources": format_resources(rows, prefetch_torrents=False),
            "total_count": total,
            "has_more": has_more,
            "page": page,
            "page_size": page_size,
            "match_mode": mode,
        }
    )
