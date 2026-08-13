"""Static board navigation tree (aligned with sehua-search boards.nav.json)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_path = Path(__file__).with_name("boards.nav.json")
_cache: tuple[float, list[dict[str, Any]]] | None = None


def load_board_nav() -> list[dict[str, Any]]:
    """按文件 mtime 缓存；改 boards.nav.json 后无需重启即生效。"""
    global _cache
    try:
        mtime = _path.stat().st_mtime
    except OSError:
        return []
    if _cache and _cache[0] == mtime:
        return _cache[1]
    raw = json.loads(_path.read_text(encoding="utf-8"))
    data = raw if isinstance(raw, list) else []
    _cache = (mtime, data)
    return data
