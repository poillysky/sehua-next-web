"""Format Postgres rows → API resource objects (aligned with sehua-search)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import unquote

from .pack_bleed import (
    gallery_preview_images,
    is_pack_bleed_item,
    is_public_download_link,
    links_for_resource_hash,
    parse_ed2k_link,
    pick_previews_for_resource,
    format_size_gb,
)

PUBLIC_RESOURCE_FILTER = """
  AND (
    lower(COALESCE(r.ed2k_link, '')) LIKE 'ed2k://%%'
    OR lower(COALESCE(r.ed2k_link, '')) LIKE 'magnet:%%'
    OR lower(COALESCE(r.ed2k_link, '')) LIKE '%%115cdn.com/s/%%'
    OR lower(COALESCE(r.ed2k_link, '')) LIKE '%%115.com/s/%%'
    OR lower(COALESCE(r.ed2k_link, '')) LIKE 'unavailable://%%'
  )
"""

SOURCE_META_JOIN = """
LEFT JOIN LATERAL (
  SELECT title, description, source_url, board_fid, board_name, forum_id,
         preview_images, ed2k_links, extract_password
  FROM resource_sources
  WHERE hash = r.hash
  ORDER BY
    CASE WHEN coalesce(array_length(ed2k_links, 1), 0) <= 1 THEN 0 ELSE 1 END,
    coalesce(array_length(preview_images, 1), 0) DESC,
    length(coalesce(description, '')) DESC,
    created_at DESC
  LIMIT 1
) rs ON true
"""

LIST_META_JOIN = """
LEFT JOIN LATERAL (
  SELECT title, description, source_url, board_fid, board_name, forum_id,
         preview_images, ed2k_links, extract_password
  FROM resource_sources
  WHERE hash = r.hash
  ORDER BY
    CASE WHEN coalesce(array_length(ed2k_links, 1), 0) <= 1 THEN 0 ELSE 1 END,
    created_at DESC
  LIMIT 1
) rs ON true
"""

# Bitmagnet：筛选 / COUNT 只用轻量 meta（title + 板块 + links_count），不含预览大字段
FILTER_META_JOIN = """
LEFT JOIN LATERAL (
  SELECT title, board_fid, board_name,
         coalesce(array_length(ed2k_links, 1), 1) AS links_count
  FROM resource_sources
  WHERE hash = r.hash
  ORDER BY
    CASE WHEN coalesce(array_length(ed2k_links, 1), 0) <= 1 THEN 0 ELSE 1 END,
    created_at DESC
  LIMIT 1
) rs ON true
"""

# CTE filtered 选出的主表列（外层再挂 LIST_META enrich）
FILTERED_CORE_COLS = """
    r.hash,
    r.filename,
    r.size,
    r.ed2k_link,
    r.extension,
    r.created_at,
    r.updated_at
"""

RESOURCE_SELECT = """
  r.hash,
  r.filename,
  r.size::text,
  r.ed2k_link,
  r.extension,
  r.created_at,
  r.updated_at,
  rs.title,
  rs.description,
  rs.source_url,
  rs.board_fid,
  rs.board_name,
  rs.forum_id,
  rs.preview_images,
  rs.ed2k_links,
  rs.extract_password
"""

HASH_RE = re.compile(r"^[0-9a-fA-F]{32,40}$")

ED2K_RE = re.compile(
    r"^ed2k://\|file\|([^|]+)\|(\d+)\|([0-9a-fA-F]{32})\|",
    re.I,
)


def to_epoch_seconds(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        n = float(value)
        return int(n / 1000) if n > 1_000_000_000_000 else int(n)
    if isinstance(value, datetime):
        return int(value.timestamp())
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def link_kind_of(link: str) -> str:
    low = (link or "").lower()
    if low.startswith("magnet:"):
        return "magnet"
    if low.startswith("ed2k://"):
        return "ed2k"
    if "115.com/s/" in low or "115cdn.com/s/" in low:
        return "share115"
    if low.startswith("unavailable://"):
        return "unavailable"
    return "other"


def parse_ed2k(link: str) -> dict[str, Any] | None:
    """Backward-compatible wrapper; prefers pack_bleed search parser."""
    parsed = parse_ed2k_link(link)
    if parsed:
        return {
            "filename": parsed["filename"],
            "size": parsed["size"],
            "hash": parsed["hash"],
        }
    m = ED2K_RE.match((link or "").strip())
    if not m:
        return None
    name = m.group(1)
    try:
        name = unquote(name)
    except Exception:
        pass
    return {"filename": name, "size": int(m.group(2)), "hash": m.group(3).upper()}


def format_resource(row: dict[str, Any]) -> dict[str, Any]:
    raw_title = (row.get("title") or "").strip() or None
    raw_desc = (row.get("description") or "").strip() or None
    raw_link = (row.get("ed2k_link") or "").strip()
    hash_ = str(row.get("hash") or "").upper()
    filename = row.get("filename") or ""
    is_stub = raw_link.lower().startswith("unavailable://")
    raw_ed2k_links = row.get("ed2k_links")

    # Detect packBleed BEFORE filtering links (raw meta hashes)
    pack_bleed = is_pack_bleed_item(
        raw_title,
        filename,
        raw_desc,
        hash_,
        raw_link,
        raw_ed2k_links,
    )

    ed2k_links = links_for_resource_hash(hash_, raw_ed2k_links, raw_link)
    primary = (
        (
            raw_link
            if is_public_download_link(raw_link) and raw_link in ed2k_links
            else ""
        )
        or (ed2k_links[0] if ed2k_links else "")
        or (raw_link if is_stub else "")
    )

    files = []
    for i, link in enumerate(ed2k_links):
        parsed = parse_ed2k(link)
        path = parsed["filename"] if parsed else filename
        size = int(parsed["size"] if parsed else (row.get("size") or 0) or 0)
        ext = row.get("extension") or (path.rsplit(".", 1)[-1] if "." in path else "")
        files.append({"index": i + 1, "path": path, "size": size, "extension": ext})

    try:
        display_size = int(float(row.get("size") or (files[0]["size"] if files else 0)))
    except Exception:
        display_size = 0

    previews_raw = row.get("preview_images") or []
    if not isinstance(previews_raw, list):
        previews_raw = []

    if pack_bleed:
        title = filename or raw_title
        size_text = format_size_gb(display_size)
        description = "\n".join(
            x
            for x in (
                f"【资源名称】：{filename or ''}",
                f"【资源大小】：{size_text}" if size_text else "",
            )
            if x
        )
        preview_images = pick_previews_for_resource(
            hash_,
            filename,
            raw_ed2k_links,
            raw_link,
            previews_raw,
            raw_title,
        )
        extract_password = None
    else:
        title = raw_title
        description = raw_desc
        preview_images = gallery_preview_images(previews_raw)
        extract_password = (row.get("extract_password") or "").strip() or None

    board = (row.get("board_name") or "").strip() or None
    if board and "-" in board and " · " not in board:
        board = board.replace("-", " · ", 1)

    return {
        "hash": hash_,
        "name": filename,
        "title": title,
        "description": description,
        "source_url": row.get("source_url") or None,
        "board_fid": row.get("board_fid") or None,
        "board_name": board,
        "forum_id": row.get("forum_id") or None,
        "forum_name": row.get("forum_id") or None,
        "extract_password": extract_password,
        "preview_images": [str(x) for x in preview_images if x],
        "ed2k_links": ed2k_links,
        "size": display_size,
        "ed2k_link": primary,
        "link_kind": link_kind_of(primary),
        "single_file": len(ed2k_links) <= 1,
        "files_count": len(ed2k_links),
        "files": files,
        "created_at": to_epoch_seconds(row.get("created_at")),
        "updated_at": to_epoch_seconds(row.get("updated_at")),
    }
