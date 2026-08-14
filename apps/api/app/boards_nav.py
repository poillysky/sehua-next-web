"""Static board navigation tree — 与 maker-fs 共用 web 侧 boards.nav.json。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# monorepo: apps/api/app → parents[3] = repo root
_ROOT = Path(__file__).resolve().parents[3]
_PATH = _ROOT / "apps" / "web" / "src" / "config" / "boards.nav.json"
# Docker / 旧布局兜底
_FALLBACK = Path(__file__).with_name("boards.nav.json")
_cache: tuple[float, list[dict[str, Any]]] | None = None


def _nav_path() -> Path:
    if _PATH.is_file():
        return _PATH
    return _FALLBACK


def load_board_nav() -> list[dict[str, Any]]:
    """按文件 mtime 缓存；改 boards.nav.json 后无需重启即生效。"""
    global _cache
    path = _nav_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    if _cache and _cache[0] == mtime:
        return _cache[1]
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    data = raw if isinstance(raw, list) else []
    _cache = (mtime, data)
    return data
