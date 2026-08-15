"""Bitmagnet Postgres 搜索：对齐 Bitmagnet-Next-Web + 官方 FilesStatus 语义。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import quote

from . import bitmagnet_pg

log = logging.getLogger(__name__)

PAGE_SIZE = 10
SEARCH_FILES_MAX = 8
SEARCH_FILES_FETCH = 80
DETAIL_FILES_MAX = 2000
HASH_RE = re.compile(r"^[a-fA-F0-9]{40}$")
_ALIAS_QUERY_SEP = re.compile(r"[,;，、；|｜/\n\r]+")
PADDING_RE = re.compile(r"(_____padding_file_|\.pad/\d+)", re.I)
JUNK_EXTS = frozenset(
    {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "bmp",
        "nfo",
        "txt",
        "url",
        "html",
        "htm",
        "srt",
        "ass",
        "ssa",
        "vtt",
        "ico",
    }
)
VIDEO_EXTS = (
    "mp4",
    "mkv",
    "avi",
    "wmv",
    "rmvb",
    "m2ts",
    "ts",
    "mov",
    "flv",
    "mpeg",
    "mpg",
    "m4v",
    "webm",
    "rm",
)
CORE_EXTS = VIDEO_EXTS + ("iso", "zip", "rar", "7z")
JUNK_PATH_RE = re.compile(
    r"\.(png|jpe?g|gif|webp|bmp|nfo|txt|url|html?|srt|ass|ssa|vtt|ico)$",
    re.I,
)

_SORT_SQL = {
    "default": "t.created_at DESC",
    "size": "t.size DESC",
    "count": "COALESCE(t.files_count, 0) DESC",
    "date": "t.created_at ASC",
}
_TIME_SQL = {
    "gt-1day": "AND t.created_at > now() - interval '1 day'",
    "gt-7day": "AND t.created_at > now() - interval '1 week'",
    "gt-31day": "AND t.created_at > now() - interval '1 month'",
    "gt-365day": "AND t.created_at > now() - interval '1 year'",
}
_SIZE_SQL = {
    "lt100mb": "AND t.size < 100 * 1024 * 1024::bigint",
    "gt100mb-lt500mb": (
        "AND t.size BETWEEN 100 * 1024 * 1024::bigint"
        " AND 500 * 1024 * 1024::bigint"
    ),
    "gt500mb-lt1gb": (
        "AND t.size BETWEEN 500 * 1024 * 1024::bigint"
        " AND 1024 * 1024 * 1024::bigint"
    ),
    "gt1gb-lt5gb": (
        "AND t.size BETWEEN 1 * 1024 * 1024 * 1024::bigint"
        " AND 5 * 1024 * 1024 * 1024::bigint"
    ),
    "gt5gb": "AND t.size > 5 * 1024 * 1024 * 1024::bigint",
}


class BitmagnetError(RuntimeError):
    pass


def magnet_uri(*, info_hash_hex: str, name: str, size: int) -> str:
    h = (info_hash_hex or "").strip().lower()
    return (
        f"magnet:?xt=urn:btih:{h}"
        f"&dn={quote(name or h, safe='')}"
        f"&xl={int(size or 0)}"
    )


def _format_size(n: int | None) -> str:
    if n is None or n < 0:
        return ""
    units = ("B", "KB", "MB", "GB", "TB")
    v = float(n)
    for u in units:
        if v < 1024 or u == units[-1]:
            if u == "B":
                return f"{int(v)} {u}"
            return f"{v:.1f} {u}"
        v /= 1024
    return f"{n} B"


def _like_pattern(keyword: str) -> str:
    raw = (keyword or "").strip()
    escaped = (
        raw.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def _split_alias_terms(q: str, *, limit: int = 8) -> list[str]:
    s = (q or "").strip()
    if not s:
        return []
    if not _ALIAS_QUERY_SEP.search(s):
        return [s]
    out: list[str] = []
    seen: set[str] = set()
    for part in _ALIAS_QUERY_SEP.split(s):
        t = str(part or "").strip()
        if len(t) < 2:
            continue
        key = t.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
        if len(out) >= limit:
            break
    return out or [s]


def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _unix(v: Any) -> int:
    if v is None:
        return 0
    if hasattr(v, "timestamp"):
        try:
            return int(v.timestamp())
        except Exception:
            return 0
    n = _as_int(v, 0)
    if n > 1_000_000_000_000:
        return n // 1000
    return n


def _file_ext(f: dict[str, Any]) -> str:
    ext = str(f.get("extension") or "").strip().lstrip(".").lower()
    if ext and " " not in ext and len(ext) <= 8 and ext.isascii():
        return ext
    path = str(f.get("path") or "")
    path = (
        path.replace("\uFF0E", ".")
        .replace("\u3002", ".")
        .replace("\\", "/")
    )
    base = path.rsplit("/", 1)[-1].strip()
    m = re.search(r"\.([a-z0-9]{2,5})\s*$", base, re.I)
    if m:
        return m.group(1).lower()
    if "." in base:
        tail = base.rsplit(".", 1)[-1].strip().lower()
        if tail and " " not in tail and len(tail) <= 8 and tail.isascii():
            return tail
    return ""


def _is_padding(path: str) -> bool:
    p = (path or "").replace("\\", "/")
    base = p.rsplit("/", 1)[-1]
    return bool(PADDING_RE.search(base) or PADDING_RE.search(p))


def _is_junk_file(f: dict[str, Any]) -> bool:
    path = str(f.get("path") or "")
    if _is_padding(path):
        return True
    ext = _file_ext(f)
    if ext in JUNK_EXTS:
        return True
    if JUNK_PATH_RE.search(path.replace("\\", "/")):
        return True
    return False


def _normalize_files(raw: Any) -> list[dict[str, Any]]:
    """解析 json_agg / JOIN 结果；丢掉 null 元素。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path or path.lower() == "null":
            continue
        ext = _file_ext(item)
        rows.append(
            {
                "index": _as_int(item.get("index")),
                "path": path,
                "size": _as_int(item.get("size")),
                "extension": ext,
            }
        )
    return rows


def _sort_files_bm(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对齐 Bitmagnet-Next-Web formatTorrent：padding 最末 → 无后缀其次 → index。"""

    def _key(f: dict[str, Any]) -> tuple[int, int, int]:
        path = str(f.get("path") or "")
        pad = 1 if _is_padding(path) else 0
        no_ext = 1 if not _file_ext(f) else 0
        return (pad, no_ext, _as_int(f.get("index")))

    return sorted(files, key=_key)


def _single_from_torrent_name(
    *,
    name: str,
    size: int,
    torrent_ext: str | None,
    require_ext: bool,
) -> dict[str, Any] | None:
    """
    对齐官方 protobuf：
    - single: 始终用 torrents.name (+ extension)
    - no_info: 仅当 name 能解析出后缀时才生成
    """
    path = (name or "").strip()
    if not path:
        return None
    ext = (torrent_ext or "").strip().lstrip(".").lower()
    if not ext:
        ext = _file_ext({"path": path, "extension": ""})
    if require_ext and not ext:
        return None
    return {
        "index": 0,
        "path": path,
        "size": size,
        "extension": ext,
    }


def _resolve_files(
    row: dict[str, Any],
    *,
    files_cap: int | None,
) -> tuple[list[dict[str, Any]], int, bool]:
    """
    按 FilesStatus 解析文件列表（对齐 bitmagnet internal/protobuf/transformer.go
    + Bitmagnet-Next-Web formatTorrent）。
    """
    name = str(row.get("name") or "")
    size = _as_int(row.get("size"))
    status = str(row.get("files_status") or "").strip().lower()
    torrent_ext = str(row.get("extension") or "").strip().lstrip(".").lower() or None
    files_count = _as_int(row.get("files_count"))
    db_files = _normalize_files(row.get("files"))

    # LEFT JOIN + json_agg 无行时可能得到 [null] → 已在 normalize 滤掉
    files = list(db_files)

    if status == "single":
        # 官方：单文件一定是 torrents.name，即使 torrent_files 也有行也以 name 为准
        one = _single_from_torrent_name(
            name=name,
            size=size,
            torrent_ext=torrent_ext,
            require_ext=False,
        )
        files = [one] if one else files
        files_count = max(files_count, 1)
    elif status == "no_info":
        if not files:
            one = _single_from_torrent_name(
                name=name,
                size=size,
                torrent_ext=torrent_ext,
                require_ext=True,
            )
            files = [one] if one else []
        files_count = files_count or len(files) or 0
    elif status in ("multi", "over_threshold"):
        # 必须用 torrent_files；空则保持空（over_threshold 可能裁剪）
        files = db_files
        if not files_count:
            files_count = len(files)
    else:
        # 未知状态：有库文件用库文件；否则 BM-Next-Web：files_count<=0 时用 name
        if files:
            files_count = files_count or len(files)
        elif files_count <= 0:
            one = _single_from_torrent_name(
                name=name,
                size=size,
                torrent_ext=torrent_ext,
                require_ext=False,
            )
            files = [one] if one else []
            files_count = 1 if files else 0
        else:
            # files_count>0 但 JOIN 为空：仍不要用无后缀 name 冒充（多文件未入库）
            files = []

    files = _sort_files_bm(files)

    if files_cap is not None:
        # 列表卡片：在已排序结果上挑视频/大文件
        files = _pick_core_files(files, files_cap)

    single = status == "single" or (files_count <= 1 and len(files) <= 1)
    return files, max(files_count, len(files)), single


def _pick_core_files(files: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    """列表：≥100MB 且尽量有真实后缀；输入应已按 BM 规则排过序。"""
    min_size = 100 * 1024 * 1024
    usable = [f for f in files if not _is_junk_file(f)]
    with_ext = [
        f
        for f in usable
        if _file_ext(f) in CORE_EXTS and _as_int(f.get("size")) >= min_size
    ]
    large = [
        f
        for f in usable
        if f not in with_ext
        and _as_int(f.get("size")) >= min_size
        and _file_ext(f)
    ]
    pool = with_ext or large
    if not pool:
        return []

    def _rank(f: dict[str, Any]) -> tuple[int, int]:
        ext = _file_ext(f)
        pri = 0 if ext in VIDEO_EXTS else (1 if ext in CORE_EXTS else 2)
        return (pri, -_as_int(f.get("size")))

    pool.sort(key=_rank)
    return [dict(f) for f in pool[: max(1, cap)]]


def _item_from_row(row: dict[str, Any], *, files_cap: int | None) -> dict[str, Any]:
    info_hash = str(row.get("info_hash") or "").lower()
    name = str(row.get("name") or info_hash)
    size = _as_int(row.get("size"))
    files, files_count, single = _resolve_files(row, files_cap=files_cap)
    created = _unix(row.get("created_at"))
    magnet = magnet_uri(info_hash_hex=info_hash, name=name, size=size)
    return {
        "hash": info_hash,
        "name": name,
        "title": name,
        "path": info_hash,
        "infoHash": info_hash,
        "detailUrl": "",
        "size": size,
        "sizeText": _format_size(size),
        "fileCount": files_count,
        "files_count": files_count,
        "files": files,
        "files_status": str(row.get("files_status") or ""),
        "single_file": single,
        "seeders": None,
        "leechers": None,
        "created_at": created,
        "updated_at": _unix(row.get("updated_at")),
        "createdAt": "",
        "magnet": magnet,
        "magnet_uri": magnet,
        "magnets": [magnet],
    }


def get(hash_hex: str) -> dict[str, Any]:
    """详情：对齐 Bitmagnet-Next-Web torrentByHash — LEFT JOIN 全量文件。"""
    h = (hash_hex or "").strip().lower()
    if not HASH_RE.match(h):
        raise BitmagnetError("无效 infoHash")
    try:
        rows = bitmagnet_pg.query(
            """
            SELECT
              encode(t.info_hash, 'hex') AS info_hash,
              t.name,
              t.size,
              t.files_count,
              t.files_status::text AS files_status,
              t.extension,
              t.created_at,
              t.updated_at,
              COALESCE(
                (
                  SELECT json_agg(json_build_object(
                    'index', f.index,
                    'path', f.path,
                    'size', f.size,
                    'extension', f.extension
                  ) ORDER BY f.index)
                  FROM (
                    SELECT index, path, size, extension
                    FROM torrent_files
                    WHERE info_hash = t.info_hash
                    ORDER BY index
                    LIMIT %s
                  ) f
                ),
                '[]'::json
              ) AS files
            FROM torrents t
            WHERE t.info_hash = decode(%s, 'hex')
            LIMIT 1
            """,
            [DETAIL_FILES_MAX, h],
        )
    except bitmagnet_pg.BitmagnetDbUnavailable as e:
        raise BitmagnetError(str(e)) from e
    except Exception as e:
        log.warning("bitmagnet detail failed: %s", e)
        raise BitmagnetError(f"Bitmagnet 详情失败: {e}") from e
    if not rows:
        raise BitmagnetError("未找到该种子")
    return _item_from_row(rows[0], files_cap=None)


def search(
    keyword: str,
    *,
    page: int = 1,
    sort_type: str = "default",
    filter_time: str = "all",
    filter_size: str = "all",
) -> dict[str, Any]:
    kw = (keyword or "").strip()
    if not kw:
        raise BitmagnetError("请输入关键词")
    page = max(1, int(page or 1))
    offset = (page - 1) * PAGE_SIZE
    t0 = time.perf_counter()

    if HASH_RE.match(kw):
        try:
            item = get(kw)
        except BitmagnetError:
            item = None
        cost_ms = int((time.perf_counter() - t0) * 1000)
        items = [item] if item else []
        return {
            "keyword": kw,
            "keywords": [kw],
            "page": 1,
            "source": "bitmagnet",
            "baseUrl": "",
            "openUrl": "",
            "items": items,
            "total": len(items),
            "hasMore": False,
            "costMs": cost_ms,
        }

    order_sql = _SORT_SQL.get(sort_type) or _SORT_SQL["default"]
    time_sql = _TIME_SQL.get(filter_time) or ""
    size_sql = _SIZE_SQL.get(filter_size) or ""
    terms = _split_alias_terms(kw)
    patterns = [_like_pattern(t) for t in terms]
    name_where = " OR ".join(["t.name ILIKE %s ESCAPE '\\'"] * len(patterns))
    ext_list = ", ".join(f"'{e}'" for e in CORE_EXTS)

    try:
        count_rows = bitmagnet_pg.query(
            f"""
            SELECT COUNT(*)::int AS total
            FROM torrents t
            WHERE ({name_where})
            {time_sql}
            {size_sql}
            """,
            patterns,
        )
        total = int(count_rows[0]["total"]) if count_rows else 0

        # 对齐 BM-Next-Web：先 filtered 分页，再按 info_hash 拉文件（优先有后缀/大文件）
        rows = bitmagnet_pg.query(
            f"""
            WITH filtered AS (
              SELECT
                t.info_hash,
                t.name,
                t.size,
                t.files_count,
                t.files_status,
                t.extension,
                t.created_at,
                t.updated_at
              FROM torrents t
              WHERE ({name_where})
              {time_sql}
              {size_sql}
              ORDER BY {order_sql}
              LIMIT %s OFFSET %s
            )
            SELECT
              encode(filtered.info_hash, 'hex') AS info_hash,
              filtered.name,
              filtered.size,
              filtered.files_count,
              filtered.files_status::text AS files_status,
              filtered.extension,
              filtered.created_at,
              filtered.updated_at,
              COALESCE(
                (
                  SELECT json_agg(json_build_object(
                    'index', f.index,
                    'path', f.path,
                    'size', f.size,
                    'extension', f.extension
                  ) ORDER BY
                    CASE WHEN lower(COALESCE(f.extension, '')) IN ({ext_list}) THEN 0 ELSE 1 END,
                    COALESCE(f.size, 0) DESC,
                    f.index
                  )
                  FROM (
                    SELECT index, path, size, extension
                    FROM torrent_files
                    WHERE info_hash = filtered.info_hash
                      AND path !~* '_____padding_file_|\\.pad/'
                    ORDER BY
                      CASE WHEN lower(COALESCE(extension, '')) IN ({ext_list}) THEN 0 ELSE 1 END,
                      COALESCE(size, 0) DESC NULLS LAST,
                      index
                    LIMIT {int(SEARCH_FILES_FETCH)}
                  ) f
                ),
                '[]'::json
              ) AS files
            FROM filtered
            """,
            [*patterns, PAGE_SIZE, offset],
        )
    except bitmagnet_pg.BitmagnetDbUnavailable as e:
        raise BitmagnetError(str(e)) from e
    except Exception as e:
        log.warning("bitmagnet search failed: %s", e)
        raise BitmagnetError(f"Bitmagnet 查询失败: {e}") from e

    items = [_item_from_row(r, files_cap=SEARCH_FILES_MAX) for r in rows]
    cost_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "keyword": kw,
        "keywords": terms,
        "page": page,
        "source": "bitmagnet",
        "baseUrl": "",
        "openUrl": "",
        "items": items,
        "total": total,
        "hasMore": offset + len(items) < total,
        "costMs": cost_ms,
    }


def meta() -> dict[str, Any]:
    configured = bitmagnet_pg.is_configured()
    return {
        "source": "bitmagnet",
        "configured": configured,
        "baseUrl": "",
        "openUrl": "",
    }
