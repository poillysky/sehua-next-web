# -*- coding: utf-8 -*-
"""刮削库元数据补全 · 七区并发策略配置。"""

from __future__ import annotations

from typing import Any

import app.core.settings_store as settings_store
from app.core.region_meta import REGION_META, REGION_ORDER
from app.scrape.source_catalog import SOURCE_GROUPS

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
VALID_FILL_MODES = ("incremental", "overwrite")
VALID_GROUP_IDS = {str(g.get("id") or "") for g in SOURCE_GROUPS if g.get("id")}

MODE_LABELS: dict[str, str] = {
    "parallel_all": "全部并发",
    "adaptive_first": "自适应优先",
    "adaptive_only": "仅自适应",
}


def default_strategy() -> dict[str, Any]:
    from app.scrap_library.cover_scrape import default_cover_settings

    return {
        # parallel_all：番号匹配源一起并发（按配置并发数）
        "mode": "parallel_all",
        # 0 = 不限制，等于该批源数量
        "adaptiveWorkers": 0,
        "flareWorkers": 0,
        "includeFlare": True,
        "perSourceTimeoutSec": 60,
        "regionGroups": {
            rid: list(groups) for rid, groups in _DEFAULT_REGION_GROUPS.items()
        },
        # 刮削库页七区开关：关则批量补齐跳过该区
        "regionsEnabled": {rid: True for rid in REGION_ORDER},
        # 增量 = 只补缺；覆盖 = 全量覆盖
        "fillMode": "incremental",
        # 无可用中文 / 机翻过烂时：大模型译中（失败再回落机翻级联）
        "llmTranslateOnJunk": True,
        # 字段站点优先级覆盖：{ title: [airav, iqqtv, ...], overview: [...] }
        # 空 = 用 scrape_source_catalog.field_priority_chain 默认
        "fieldPriority": {},
        # 刮削封面：画质 + 七区裁剪
        "cover": default_cover_settings(),
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


def normalize_strategy(
    raw: dict[str, Any] | None, *, prev: dict[str, Any] | None = None
) -> dict[str, Any]:
    base = default_strategy()
    prior = prev if isinstance(prev, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    mode = str(raw.get("mode") or prior.get("mode") or base["mode"]).strip().lower()
    if mode not in VALID_MODES:
        mode = str(base["mode"])
    region_in = (
        raw.get("regionGroups")
        if isinstance(raw.get("regionGroups"), dict)
        else prior.get("regionGroups")
        if isinstance(prior.get("regionGroups"), dict)
        else {}
    )
    region_groups: dict[str, list[str]] = {}
    for rid in REGION_ORDER:
        fb = list(_DEFAULT_REGION_GROUPS.get(rid) or ["general"])
        region_groups[rid] = _norm_groups(region_in.get(rid), fallback=fb)

    if "regionsEnabled" in raw and isinstance(raw.get("regionsEnabled"), dict):
        enabled_in = dict(raw.get("regionsEnabled") or {})
        prior_en = (
            prior.get("regionsEnabled")
            if isinstance(prior.get("regionsEnabled"), dict)
            else {}
        )
        for rid in REGION_ORDER:
            if rid not in enabled_in and rid in prior_en:
                enabled_in[rid] = prior_en[rid]
    elif isinstance(prior.get("regionsEnabled"), dict):
        enabled_in = dict(prior.get("regionsEnabled") or {})
    else:
        enabled_in = {}
    regions_enabled: dict[str, bool] = {}
    for rid in REGION_ORDER:
        if rid in enabled_in:
            regions_enabled[rid] = bool(enabled_in[rid])
        else:
            regions_enabled[rid] = True

    fill_raw = raw.get("fillMode", prior.get("fillMode", base["fillMode"]))
    fill_mode = str(fill_raw or base["fillMode"]).strip().lower()
    if fill_mode not in VALID_FILL_MODES:
        fill_mode = str(base["fillMode"])

    from app.scrap_library.cover_scrape import (
        COVER_CROP_LABELS,
        COVER_CROP_MODES,
        normalize_cover_settings,
    )

    cover = normalize_cover_settings(
        raw.get("cover"),
        prev=prior.get("cover") if isinstance(prior.get("cover"), dict) else base["cover"],
    )

    fp_raw = (
        raw.get("fieldPriority")
        if isinstance(raw.get("fieldPriority"), dict)
        else prior.get("fieldPriority")
        if isinstance(prior.get("fieldPriority"), dict)
        else {}
    )
    field_priority: dict[str, list[str]] = {}
    if isinstance(fp_raw, dict):
        from app.scrape.source_catalog import canonicalize_id

        for fk, sites in fp_raw.items():
            key = str(fk or "").strip()
            if not key or not isinstance(sites, list):
                continue
            chain: list[str] = []
            seen: set[str] = set()
            for s in sites:
                sid = canonicalize_id(str(s or ""))
                if sid and sid not in seen:
                    seen.add(sid)
                    chain.append(sid)
            if chain:
                field_priority[key] = chain

    return {
        "mode": mode,
        # 0 = 全开（等于源数）；上限放宽，避免「固定 8」
        "adaptiveWorkers": _clamp_int(
            raw.get("adaptiveWorkers", prior.get("adaptiveWorkers")),
            lo=0,
            hi=64,
            default=int(base["adaptiveWorkers"]),
        ),
        "flareWorkers": _clamp_int(
            raw.get("flareWorkers", prior.get("flareWorkers")),
            lo=0,
            hi=64,
            default=int(base["flareWorkers"]),
        ),
        "includeFlare": bool(
            raw.get(
                "includeFlare",
                prior.get("includeFlare", base["includeFlare"]),
            )
        ),
        "perSourceTimeoutSec": _clamp_int(
            raw.get("perSourceTimeoutSec", prior.get("perSourceTimeoutSec")),
            lo=5,
            hi=180,
            default=int(base["perSourceTimeoutSec"]),
        ),
        "regionGroups": region_groups,
        "regionsEnabled": regions_enabled,
        "fillMode": fill_mode,
        "llmTranslateOnJunk": bool(
            raw.get(
                "llmTranslateOnJunk",
                prior.get("llmTranslateOnJunk", base["llmTranslateOnJunk"]),
            )
        ),
        "fieldPriority": field_priority,
        "cover": cover,
    }


def get_strategy() -> dict[str, Any]:
    raw = settings_store.get_setting(ENRICH_STRATEGY_KEY) or {}
    return normalize_strategy(raw if isinstance(raw, dict) else {})


def put_strategy(body: dict[str, Any] | None) -> dict[str, Any]:
    prev = get_strategy()
    cfg = normalize_strategy(body if isinstance(body, dict) else {}, prev=prev)
    settings_store.put_setting(ENRICH_STRATEGY_KEY, cfg)
    return cfg


def strategy_public(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """带标签与可选分组清单，供设置页渲染。"""
    from app.scrap_library.cover_scrape import COVER_CROP_LABELS, COVER_CROP_MODES, COVER_CROP_HINTS

    data = normalize_strategy(cfg) if cfg is not None else get_strategy()
    regions = []
    enabled = data.get("regionsEnabled") or {}
    for rid in REGION_ORDER:
        meta = REGION_META.get(rid) or {}
        regions.append(
            {
                "id": rid,
                "label": str(meta.get("label") or rid),
                "groups": list(data["regionGroups"].get(rid) or []),
                "enabled": bool(enabled.get(rid, True)),
                "coverHint": COVER_CROP_HINTS.get(rid, ""),
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
        "coverCropOptions": [
            {"id": m, "label": COVER_CROP_LABELS.get(m, m)} for m in COVER_CROP_MODES
        ],
        "coverQualityOptions": [
            {"id": "high", "label": "高画质"},
            {"id": "low", "label": "低画质"},
        ],
        "coverRatioOptions": [
            {"id": "full", "label": "完整海报（2.12:3）"},
            {"id": "emby", "label": "Emby 比例（2:3）"},
        ],
    }


def enabled_region_ids(cfg: dict[str, Any] | None = None) -> list[str]:
    data = normalize_strategy(cfg) if cfg is not None else get_strategy()
    enabled = data.get("regionsEnabled") or {}
    return [rid for rid in REGION_ORDER if bool(enabled.get(rid, True))]


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
