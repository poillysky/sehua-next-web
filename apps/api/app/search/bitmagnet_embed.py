"""Bitmagnet 磁力嵌入文本：种子名 + 内容标题/类型摘要。"""

from __future__ import annotations

import hashlib
import re
from typing import Any

_WS_RE = re.compile(r"\s+")
_MAX_EMBED_CHARS = 800


def _clip(s: str, n: int) -> str:
    t = _WS_RE.sub(" ", (s or "").strip())
    return t if len(t) <= n else t[: n - 1] + "…"


def build_source_text(row: dict[str, Any]) -> str:
    name = _clip(str(row.get("name") or ""), 200)
    title = _clip(str(row.get("title") or ""), 160)
    overview = _clip(str(row.get("overview") or ""), 280)
    ctype = _clip(str(row.get("content_type") or row.get("type") or ""), 40)
    res = _clip(str(row.get("video_resolution") or ""), 24)
    parts: list[str] = []
    if name:
        parts.append(name)
    if title and title.casefold() not in name.casefold():
        parts.append(f"标题 {title}")
    if ctype:
        parts.append(f"类型 {ctype}")
    if res:
        parts.append(res)
    if overview:
        parts.append(overview)
    text = " · ".join(parts) if parts else str(row.get("info_hash") or "")
    return _clip(text, _MAX_EMBED_CHARS)


def row_embed_payload(row: dict[str, Any]) -> dict[str, Any]:
    info_hash = str(row.get("info_hash") or "").strip().lower()
    source_text = build_source_text(row)
    sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    return {
        "info_hash": info_hash,
        "source_text": source_text,
        "content_sha": sha,
    }
