"""Bounded in-memory TTL helpers（防进程级 dict 无限涨）。"""

from __future__ import annotations

import time
from typing import Any, MutableMapping

CacheMap = MutableMapping[str, tuple[float, Any]]


def prune_by_expiry(cache: CacheMap, *, now: float | None = None) -> int:
    """删除已过期条目；tuple[0] = absolute expires_at。"""
    t = time.time() if now is None else now
    dead = [k for k, (exp, _) in cache.items() if exp <= t]
    for k in dead:
        cache.pop(k, None)
    return len(dead)


def prune_by_age(cache: CacheMap, ttl: float, *, now: float | None = None) -> int:
    """删除超龄条目；tuple[0] = created_at。"""
    t = time.time() if now is None else now
    dead = [k for k, (ts, _) in cache.items() if t - ts >= ttl]
    for k in dead:
        cache.pop(k, None)
    return len(dead)


def enforce_max(cache: CacheMap, max_size: int) -> None:
    """超上限时按 tuple[0] 升序淘汰（更早过期 / 更早写入先丢）。"""
    if max_size <= 0 or len(cache) <= max_size:
        return
    overflow = len(cache) - max_size
    victims = sorted(cache.items(), key=lambda kv: kv[1][0])[:overflow]
    for k, _ in victims:
        cache.pop(k, None)


def cache_get(cache: CacheMap, key: str) -> Any | None:
    """读一条；已过期则顺手删除并返回 None。

    ``media.routes`` 与 ``makers.catalog_routes`` 曾各写一份逐字节相同的 ``_cache_get``；
    这里收敛为唯一实现，两个模块各自传自己的 ``_cache``（缓存仍是各自独立的 dict）。
    """
    hit = cache.get(key)
    if not hit:
        return None
    exp, payload = hit
    if time.time() > exp:
        cache.pop(key, None)
        return None
    return payload
