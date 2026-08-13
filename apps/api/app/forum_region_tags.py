"""色花堂子板地区标签：只认论坛管理已保存的 regionByKey。

七区映射：
- 国产无码 ← 国产 + 混合
- 欧美无码 ← 欧美 + 混合
- 日本五区 ← 日本 + 混合
- 未配置 / 其他 ← 不参与
"""

from __future__ import annotations

import time
from typing import Any

from . import settings_store

ForumRegion = str  # japan|china|western|mixed|other

_FORUM_REGION_IDS = frozenset({"japan", "china", "western", "mixed", "other"})

# 七区 → 论坛粗地区
_SEARCH_TO_COARSE: dict[str, ForumRegion] = {
    "japan": "japan",
    "japan_censored": "japan",
    "japan_uncensored": "japan",
    "japan_amateur": "japan",
    "fc2": "japan",
    "china": "china",
    "western": "western",
}

_cache_at = 0.0
_cache_overrides: dict[str, ForumRegion] = {}
_CACHE_TTL = 5.0


def _norm_key(board_fid: str | None) -> str:
    s = str(board_fid or "").strip()
    if not s:
        return ""
    if ":" in s:
        root, _, rest = s.partition(":")
        typ = rest.split(":", 1)[0].strip()
        return f"{root.strip()}:{typ}" if typ else f"{root.strip()}:"
    return f"{s}:"


def _load_overrides() -> dict[str, ForumRegion]:
    global _cache_at, _cache_overrides
    now = time.monotonic()
    if now - _cache_at < _CACHE_TTL:
        return _cache_overrides
    out: dict[str, ForumRegion] = {}
    try:
        raw = settings_store.get_setting(settings_store.FORUM_SEHUATANG_KEY) or {}
    except Exception:
        raw = {}
    if isinstance(raw, dict):
        src = raw.get("regionByKey") or raw.get("region_by_key") or {}
        if isinstance(src, dict):
            for k, v in src.items():
                key = _norm_key(str(k))
                region = str(v or "").strip().lower()
                if key and region in _FORUM_REGION_IDS:
                    out[key] = region
    _cache_overrides = out
    _cache_at = now
    return out


def invalidate_forum_region_cache() -> None:
    global _cache_at, _cache_overrides
    _cache_at = 0.0
    _cache_overrides = {}


def coarse_forum_region(search_region: str | None) -> ForumRegion | None:
    key = str(search_region or "").strip().lower()
    return _SEARCH_TO_COARSE.get(key)


def resolve_forum_region(board_fid: str | None) -> ForumRegion:
    """只读已保存配置：精确 key → 整板 key；皆无则 other（不参与）。"""
    key = _norm_key(board_fid)
    if not key:
        return "other"
    overrides = _load_overrides()
    if key in overrides:
        return overrides[key]
    root = key.split(":", 1)[0]
    parent = f"{root}:"
    if parent != key and parent in overrides:
        return overrides[parent]
    return "other"


def forum_region_allows_search(
    board_fid: str | None,
    search_region: str | None,
) -> bool:
    """本区粗粒度 + mixed 放行；other / 未配置拒绝。"""
    coarse = coarse_forum_region(search_region)
    if not coarse:
        return True
    tag = resolve_forum_region(board_fid)
    if tag == "other":
        return False
    if tag == "mixed":
        return True
    return tag == coarse


def known_forum_leaf_keys() -> set[str]:
    """仅已保存的配置键。"""
    return set(_load_overrides().keys())


def forum_exclude_specs_for_search(search_region: str | None) -> list[str]:
    """对本区应排除的规格（已配置且非本区/非混合）。"""
    coarse = coarse_forum_region(search_region)
    if not coarse:
        return []
    out: list[str] = []
    for key in known_forum_leaf_keys():
        tag = resolve_forum_region(key)
        if tag == "mixed" or tag == coarse:
            continue
        if key.endswith(":"):
            out.append(key[:-1])
        else:
            out.append(key)
    return sorted(set(out))


def forum_allow_specs_for_search(search_region: str | None) -> list[str]:
    """已配置且为本区或混合的放行规格。"""
    coarse = coarse_forum_region(search_region)
    if not coarse:
        return []
    overrides = _load_overrides()
    typed_roots: set[str] = set()
    for key in overrides:
        if ":" in key and not key.endswith(":"):
            typed_roots.add(key.split(":", 1)[0])

    specs: list[str] = []
    for key, tag in overrides.items():
        if tag != coarse and tag != "mixed":
            continue
        if key.endswith(":"):
            root = key[:-1]
            # 同根下已有细分配置时不用整树，避免盖住 other 子板
            if root in typed_roots:
                continue
            if root:
                specs.append(root)
        else:
            specs.append(key)
    return sorted(set(specs))


def is_forum_driven_search(search_region: str | None) -> bool:
    key = str(search_region or "").strip().lower()
    return key in _SEARCH_TO_COARSE
