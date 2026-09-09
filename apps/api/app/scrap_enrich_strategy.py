# -*- coding: utf-8 -*-
"""刮削库元数据补全 · 七区并发策略配置。"""

from __future__ import annotations

from typing import Any

from . import settings_store
from .region_meta import REGION_META, REGION_ORDER
from .scrape_source_catalog import SOURCE_GROUPS

ENRICH_STRATEGY_KEY = "scrap.enrich.strategy"

# 与 scrape_sources_settings.REGION_ENRICH_GROUPS 默认一致
_DEFAULT_REGION_GROUPS: dict[str, list[str]] = {
    "japan_censored": ["av", "uncensored", "general"],
    "japan_gravure": ["av", "uncensored", "general"],
    "japan_amateur": ["av", "uncensored", "general"],
    "japan_uncensored": ["av", "uncensored", "general"],
    "fc2": ["fc2", "general"],
    "china": ["chinese", "general"],
    "western": ["western", "general"],
}

VALID_MODES = ("parallel_all", "adaptive_first", "adaptive_only")
VALID_GROUP_IDS = {str(g.get("id") or "") for g in SOURCE_GROUPS if g.get("id")}

MODE_LABELS: dict[str, str] = {
    "parallel_all": "全部并发",
    "adaptive_first": "自适应优先",
    "adaptive_only": "仅自适应",
}


def default_strategy() -> dict[str, Any]:
    return {
        # parallel_all：番号匹配源一起并发（按配置并发数）
        "mode": "parallel_all",
        # 0 = 不限制，等于该批源数量
        "adaptiveWorkers": 0,
        "flareWorkers": 0,
        "includeFlare": True,
        "perSourceTimeoutSec": 45,
        "regionGroups": {
            rid: list(groups) for rid, groups in _DEFAULT_REGION_GROUPS.items()
        },
    }


def _clamp_int(raw: Any, *, lo: int, hi: int, default: int) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _norm_groups(raw: Any, *, fallback: list[str]) -> list[str]:
    if not isinstance(raw, list):
        return list(fallback)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        gid = str(item or "").strip().lower()
        if not gid or gid not in VALID_GROUP_IDS or gid in seen:
            continue
        seen.add(gid)
        out.append(gid)
    return out or list(fallback)


def normalize_strategy(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = default_strategy()
    if not isinstance(raw, dict):
        return base
    mode = str(raw.get("mode") or base["mode"]).strip().lower()
    if mode not in VALID_MODES:
        mode = str(base["mode"])
    region_in = raw.get("regionGroups") if isinstance(raw.get("regionGroups"), dict) else {}
    region_groups: dict[str, list[str]] = {}
    for rid in REGION_ORDER:
        fb = list(_DEFAULT_REGION_GROUPS.get(rid) or ["general"])
        region_groups[rid] = _norm_groups(region_in.get(rid), fallback=fb)
    return {
        "mode": mode,
        # 0 = 全开（等于源数）；上限放宽，避免「固定 8」
        "adaptiveWorkers": _clamp_int(
            raw.get("adaptiveWorkers"), lo=0, hi=64, default=int(base["adaptiveWorkers"])
        ),
        "flareWorkers": _clamp_int(
            raw.get("flareWorkers"), lo=0, hi=64, default=int(base["flareWorkers"])
        ),
        "includeFlare": bool(raw.get("includeFlare", base["includeFlare"])),
        "perSourceTimeoutSec": _clamp_int(
            raw.get("perSourceTimeoutSec"),
            lo=10,
            hi=120,
            default=int(base["perSourceTimeoutSec"]),
        ),
        "regionGroups": region_groups,
    }


def get_strategy() -> dict[str, Any]:
    raw = settings_store.get_setting(ENRICH_STRATEGY_KEY) or {}
    return normalize_strategy(raw if isinstance(raw, dict) else {})


def put_strategy(body: dict[str, Any] | None) -> dict[str, Any]:
    cfg = normalize_strategy(body if isinstance(body, dict) else {})
    settings_store.put_setting(ENRICH_STRATEGY_KEY, cfg)
    return cfg


def strategy_public(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """带标签与可选分组清单，供设置页渲染。"""
    data = normalize_strategy(cfg) if cfg is not None else get_strategy()
    regions = []
    for rid in REGION_ORDER:
        meta = REGION_META.get(rid) or {}
        regions.append(
            {
                "id": rid,
                "label": str(meta.get("label") or rid),
                "groups": list(data["regionGroups"].get(rid) or []),
            }
        )
    return {
        **data,
        "modeLabel": MODE_LABELS.get(str(data["mode"]), str(data["mode"])),
        "modes": [{"value": m, "label": MODE_LABELS[m]} for m in VALID_MODES],
        "groupOptions": [
            {"id": str(g.get("id")), "label": str(g.get("label") or g.get("id"))}
            for g in SOURCE_GROUPS
            if g.get("id")
        ],
        "regions": regions,
    }


def resolve_pool_workers(configured: int, batch_size: int) -> int:
    """配置并发：0=与批次数相同（全开）；否则 min(配置, 批次数)。"""
    n = int(batch_size or 0)
    if n <= 0:
        return 0
    cfg = int(configured)
    if cfg <= 0:
        return n
    return max(1, min(cfg, n))


def region_groups_override(region_id: str | None) -> tuple[str, ...] | None:
    """返回配置的七区分组（始终有值）。"""
    rid = str(region_id or "").strip()
    if not rid:
        return None
    cfg = get_strategy()
    groups = cfg.get("regionGroups") or {}
    hit = groups.get(rid)
    if not isinstance(hit, list) or not hit:
        fb = _DEFAULT_REGION_GROUPS.get(rid)
        return tuple(fb) if fb else None
    return tuple(str(x) for x in hit)
