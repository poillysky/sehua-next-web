# -*- coding: utf-8 -*-
"""刮削库元数据补全 · 七区并发策略配置。"""

from __future__ import annotations

from typing import Any

import app.core.settings_store as settings_store
from app.core.region_meta import REGION_META, REGION_ORDER
from app.scrape.source_catalog import SOURCE_GROUPS

ENRICH_STRATEGY_KEY = "scrap.enrich.strategy"

# 与 scrape_sources_settings.REGION_ENRICH_GROUPS 默认一致（由 regionSources 反推同步）
_DEFAULT_REGION_GROUPS: dict[str, list[str]] = {
    "japan_censored": ["av", "uncensored", "general"],
    "japan_gravure": ["av", "uncensored", "general"],
    "japan_amateur": ["av", "uncensored", "general"],
    "japan_uncensored": ["av", "uncensored", "general"],
    "fc2": ["fc2", "general"],
    "china": ["chinese", "general"],
    "western": ["western", "general"],
}

# 全局优先级（番号类型 → 有序源）：对齐 COVER_LOGIC.md §1.2
# 低质量源（MissAV / NJAV / FreeJavBT / 7MMTV 等）不进默认；需要时用户可手加。
# 目录无站（hbox_jp / javdb）已跳过；fc2_hub → fd2ppv
REGION_SOURCES_LOGIC_VERSION = 5
_DEFAULT_REGION_SOURCES: dict[str, list[str]] = {
    # 有码：DMM → LibreDMM → R18.dev → JavBus → Jav321 → AVBase → MGStage
    "japan_censored": [
        "dmm",
        "libredmm",
        "r18dev",
        "javbus",
        "jav321",
        "avbase",
        "mgstage",
    ],
    # 写真：DMM → LibreDMM → R18.dev → JavBus → MGStage → Jav321
    "japan_gravure": [
        "dmm",
        "libredmm",
        "r18dev",
        "javbus",
        "mgstage",
        "jav321",
    ],
    # 无码：Caribbean → JavBus → AVBase
    "japan_uncensored": ["carib", "javbus", "avbase"],
    # 素人：MGStage → JavBus → Caribbean → AirAV.io
    "japan_amateur": ["mgstage", "javbus", "carib", "airav_io"],
    # FC2 → FC2-PPV → AirAV.io
    "fc2": ["fc2", "fd2ppv", "airav_io"],
    # 国产：Madouqu → Madou → 小黄书
    "china": ["madouqu", "madou", "xiao_huang_shu"],
    # 欧美
    "western": ["theporndb"],
}

# 设置页展示顺序（对齐 MDCX；写真殿后）
REGION_PRIORITY_UI_ORDER: list[str] = [
    "japan_censored",
    "japan_uncensored",
    "japan_amateur",
    "fc2",
    "china",
    "western",
    "japan_gravure",
]

# 设置页番号类型标签（与七区目录 label 可不同）
REGION_PRIORITY_LABELS: dict[str, str] = {
    "japan_censored": "有码番号",
    "japan_gravure": "写真番号",
    "japan_uncensored": "无码番号",
    "japan_amateur": "素人番号",
    "fc2": "FC2 番号",
    "china": "国产番号",
    "western": "欧美影片",
}

VALID_MODES = ("parallel_all", "adaptive_first", "adaptive_only")
# incremental=只补缺；refresh_weak=缺口队列但强制重写弱字段；overwrite=全量覆盖
VALID_FILL_MODES = ("incremental", "refresh_weak", "overwrite")
VALID_AVATAR_MODES = ("incremental", "overwrite")
VALID_GROUP_IDS = {str(g.get("id") or "") for g in SOURCE_GROUPS if g.get("id")}
VALID_FIELD_LANG = ("prefer_zh", "prefer_ja", "zh_or_translate")
VALID_COVER_ENHANCE = ("off", "official")
VALID_OUTLINE_SHOW = ("zh", "zh_jp", "jp_zh")
# 本地映射表：关 / 优选（源站先出再比分） / 兜底（仅缺省） / 强制（命中即覆盖）
VALID_LOCAL_MAP_MODES = ("off", "prefer", "fallback", "force")
LOCAL_MAP_MODE_LABELS = {
    "off": "关",
    "prefer": "优选",
    "fallback": "兜底",
    "force": "强制",
}
VALID_FORCE_FIELDS = (
    "title",
    "overview",
    "actors",
    "studio",
    "poster",
    "tags",
    "badges",
)
FORCE_FIELD_LABELS: dict[str, str] = {
    "title": "标题",
    "overview": "剧情",
    "actors": "女优",
    "studio": "片商",
    "poster": "海报",
    "tags": "标签",
    "badges": "角标",
}

MODE_LABELS: dict[str, str] = {
    "parallel_all": "全部并发",
    "adaptive_first": "自适应优先",
    "adaptive_only": "仅自适应",
}

FILL_MODE_LABELS: dict[str, str] = {
    "incremental": "增量",
    "refresh_weak": "弱项重刮",
    "overwrite": "覆盖",
}


def default_strategy() -> dict[str, Any]:
    from app.scrap_library.cover_scrape import default_cover_settings

    return {
        # 增量默认自适应优先：缺口齐早停，不过盾拖尾（准确度靠合并投票）
        "mode": "adaptive_first",
        # 同时处理的番号数（批量补齐）；封面另有独立 job 池
        "itemWorkers": 6,
        # 0 = 不限制（等于该番号命中源数）
        "adaptiveWorkers": 0,
        "flareWorkers": 0,
        "includeFlare": True,
        # 单源超时（秒）；批量任务同样遵守，不再另压封顶
        "perSourceTimeoutSec": 28,
        "regionGroups": {
            rid: list(groups) for rid, groups in _DEFAULT_REGION_GROUPS.items()
        },
        # 全局源优先级：番号类型 → 有序站点（刮削与 NFO 全局回落按此顺序）
        "regionSources": {
            rid: list(sites) for rid, sites in _DEFAULT_REGION_SOURCES.items()
        },
        "regionSourcesLogicVersion": REGION_SOURCES_LOGIC_VERSION,
        # 刮削库页七区开关：关则批量补齐跳过该区
        "regionsEnabled": {rid: True for rid in REGION_ORDER},
        # 增量 = 只补缺；覆盖 = 全量覆盖
        "fillMode": "incremental",
        # 女优头像：增量 = 只缺头像；覆盖 = 已有也重下
        "actressAvatarMode": "incremental",
        # 无可用中文 / 机翻过烂时：大模型译中（失败再回落机翻级联）
        "llmTranslateOnJunk": True,
        # I41：字段语言偏好
        "fieldLanguage": {"title": "prefer_zh", "overview": "prefer_zh"},
        # I43：定稿后标题后处理（默认关，避免与尾名补演员打架）
        "stripTitleActorSuffix": False,
        "stripTitleCodePrefix": False,
        # I44：FC2 无女优时用卖家占位
        "fc2SellerAsActor": True,
        # I46：封面升清（默认 off；official=优先官方 CDN 大图）
        "coverEnhance": "off",
        # I48：详情双语展示偏好（列表仍单语）
        "outlineShow": "zh",
        # I49：增量模式下仍强制写回的字段（空=不额外强制）
        "forceFields": [],
        # 字段站点优先级：默认预填参考配置（设置页可见 tag）
        "fieldPriority": {
            "title": ["airav_io", "iqqtv", "javbus"],
            "overview": ["airav_io", "iqqtv"],
            # 女优：JavBus 与中文源并列择优（避免脏中文名独占）
            "actors": ["javbus", "airav_io", "iqqtv"],
            # 海报：DMM → LibreDMM → R18.dev → JavBus → MGStage
            "poster": ["dmm", "libredmm", "r18dev", "javbus", "mgstage"],
            "tags": ["javbus", "avbase", "freejavbt"],
        },
        # 字段优先级页：隐藏未配置行
        "fieldPriorityHideEmpty": False,
        # 元数据优化：标题/女优/标签映射 + 简介换行
        "localMaps": {
            "title": "prefer",
            "actors": "fallback",
            "tags": "fallback",
            "compactOutlineNewlines": True,
        },
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


def _norm_region_sources(
    raw: Any, *, fallback: list[str], keep_empty: bool = False
) -> list[str]:
    from app.scrape.source_catalog import canonicalize_id, catalog_by_id

    known = catalog_by_id()
    fb = [canonicalize_id(s) for s in fallback if canonicalize_id(s) in known]
    if not isinstance(raw, list):
        return list(fb)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        sid = canonicalize_id(str(item or ""))
        if not sid or sid not in known or sid in seen:
            continue
        seen.add(sid)
        out.append(sid)
    if keep_empty:
        return out
    return out or list(fb)


def _groups_from_sources(sids: list[str]) -> list[str]:
    from app.scrape.source_catalog import catalog_by_id

    by = catalog_by_id()
    out: list[str] = []
    seen: set[str] = set()
    for sid in sids:
        g = str((by.get(sid) or {}).get("group") or "").strip().lower()
        if not g or g not in VALID_GROUP_IDS or g in seen:
            continue
        seen.add(g)
        out.append(g)
    return out


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

    # 番号类型有序源（主配置）。客户端显式传入（含空列表）一律按传入落库。
    rs_key_present = isinstance(raw.get("regionSources"), dict)
    prior_rs = (
        prior.get("regionSources")
        if isinstance(prior.get("regionSources"), dict)
        else {}
    )
    rs_in = raw.get("regionSources") if rs_key_present else prior_rs
    if not isinstance(rs_in, dict):
        rs_in = {}
    region_sources: dict[str, list[str]] = {}
    for rid in REGION_ORDER:
        fb = list(_DEFAULT_REGION_SOURCES.get(rid) or [])
        if rid in rs_in and isinstance(rs_in.get(rid), list):
            region_sources[rid] = _norm_region_sources(
                rs_in.get(rid), fallback=fb, keep_empty=True
            )
        elif rid in prior_rs and isinstance(prior_rs.get(rid), list):
            region_sources[rid] = _norm_region_sources(
                prior_rs.get(rid), fallback=fb, keep_empty=True
            )
        else:
            region_sources[rid] = list(fb)

    # 兼容旧 regionGroups：由有序源反推；若无源则回落旧分组输入
    region_in = (
        raw.get("regionGroups")
        if isinstance(raw.get("regionGroups"), dict)
        else prior.get("regionGroups")
        if isinstance(prior.get("regionGroups"), dict)
        else {}
    )
    region_groups: dict[str, list[str]] = {}
    for rid in REGION_ORDER:
        derived = _groups_from_sources(region_sources.get(rid) or [])
        if derived:
            region_groups[rid] = derived
            continue
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

    avatar_raw = raw.get(
        "actressAvatarMode",
        prior.get("actressAvatarMode", base["actressAvatarMode"]),
    )
    actress_avatar_mode = str(
        avatar_raw or base["actressAvatarMode"]
    ).strip().lower()
    if actress_avatar_mode not in VALID_AVATAR_MODES:
        actress_avatar_mode = str(base["actressAvatarMode"])

    from app.scrap_library.cover_scrape import normalize_cover_settings

    cover = normalize_cover_settings(
        raw.get("cover"),
        prev=prior.get("cover") if isinstance(prior.get("cover"), dict) else base["cover"],
    )

    fp_key_present = isinstance(raw.get("fieldPriority"), dict)
    fp_raw = (
        raw.get("fieldPriority")
        if fp_key_present
        else prior.get("fieldPriority")
        if isinstance(prior.get("fieldPriority"), dict)
        else None
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
    # 仅从未配置过时预填默认；客户端显式传 {} / 清空则保留空
    if not field_priority and not fp_key_present and not isinstance(
        prior.get("fieldPriority"), dict
    ):
        field_priority = {
            str(k): list(v)
            for k, v in (base.get("fieldPriority") or {}).items()
            if isinstance(v, list) and v
        }

    def _pick_lang(field: str) -> str:
        blob = (
            raw.get("fieldLanguage")
            if isinstance(raw.get("fieldLanguage"), dict)
            else prior.get("fieldLanguage")
            if isinstance(prior.get("fieldLanguage"), dict)
            else base["fieldLanguage"]
        )
        v = str((blob or {}).get(field) or base["fieldLanguage"].get(field) or "prefer_zh")
        v = v.strip().lower()
        return v if v in VALID_FIELD_LANG else "prefer_zh"

    enhance = str(
        raw.get(
            "coverEnhance",
            prior.get("coverEnhance", base["coverEnhance"]),
        )
        or "off"
    ).strip().lower()
    if enhance not in VALID_COVER_ENHANCE:
        enhance = "off"

    outline = str(
        raw.get(
            "outlineShow",
            prior.get("outlineShow", base["outlineShow"]),
        )
        or "zh"
    ).strip().lower()
    if outline not in VALID_OUTLINE_SHOW:
        outline = "zh"

    def _bool_opt(key: str) -> bool:
        return bool(raw.get(key, prior.get(key, base[key])))

    def _local_map_mode(kind: str) -> str:
        blob = (
            raw.get("localMaps")
            if isinstance(raw.get("localMaps"), dict)
            else prior.get("localMaps")
            if isinstance(prior.get("localMaps"), dict)
            else base.get("localMaps")
        )
        base_m = (base.get("localMaps") or {}).get(kind) or (
            "prefer" if kind == "title" else "fallback"
        )
        v = str((blob or {}).get(kind) or base_m).strip().lower()
        # 标题：旧「兜底」升为「优选」（源站先出再比分，非缺省才补）
        if kind == "title" and v == "fallback":
            v = "prefer"
        # 标签无单独强制表：force 视同兜底（开映射）
        if kind == "tags" and v == "force":
            v = "fallback"
        return v if v in VALID_LOCAL_MAP_MODES else str(base_m)

    def _local_map_bool(key: str, *, default: bool = True) -> bool:
        blob = (
            raw.get("localMaps")
            if isinstance(raw.get("localMaps"), dict)
            else prior.get("localMaps")
            if isinstance(prior.get("localMaps"), dict)
            else base.get("localMaps")
        )
        base_blob = base.get("localMaps") if isinstance(base.get("localMaps"), dict) else {}
        if isinstance(blob, dict) and key in blob and blob[key] is not None:
            return bool(blob[key])
        if key in (base_blob or {}) and (base_blob or {}).get(key) is not None:
            return bool((base_blob or {}).get(key))
        return default

    return {
        "mode": mode,
        # 番号并发：1–16；默认 5
        "itemWorkers": _clamp_int(
            raw.get("itemWorkers", prior.get("itemWorkers")),
            lo=1,
            hi=16,
            default=int(base["itemWorkers"]),
        ),
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
        "regionSources": region_sources,
        "regionsEnabled": regions_enabled,
        "fillMode": fill_mode,
        "actressAvatarMode": actress_avatar_mode,
        "llmTranslateOnJunk": bool(
            raw.get(
                "llmTranslateOnJunk",
                prior.get("llmTranslateOnJunk", base["llmTranslateOnJunk"]),
            )
        ),
        "fieldLanguage": {
            "title": _pick_lang("title"),
            "overview": _pick_lang("overview"),
        },
        "stripTitleActorSuffix": _bool_opt("stripTitleActorSuffix"),
        "stripTitleCodePrefix": _bool_opt("stripTitleCodePrefix"),
        "fc2SellerAsActor": _bool_opt("fc2SellerAsActor"),
        "coverEnhance": enhance,
        "outlineShow": outline,
        "forceFields": [
            str(x).strip().lower()
            for x in (
                raw.get("forceFields")
                if isinstance(raw.get("forceFields"), list)
                else prior.get("forceFields")
                if isinstance(prior.get("forceFields"), list)
                else base["forceFields"]
            )
            if str(x).strip().lower() in VALID_FORCE_FIELDS
        ],
        "fieldPriority": field_priority,
        "fieldPriorityHideEmpty": bool(
            raw.get(
                "fieldPriorityHideEmpty",
                prior.get(
                    "fieldPriorityHideEmpty",
                    base.get("fieldPriorityHideEmpty", False),
                ),
            )
        ),
        "localMaps": {
            "title": _local_map_mode("title"),
            "actors": _local_map_mode("actors"),
            "tags": _local_map_mode("tags"),
            "compactOutlineNewlines": _local_map_bool(
                "compactOutlineNewlines", default=True
            ),
        },
        "cover": cover,
        "regionSourcesLogicVersion": REGION_SOURCES_LOGIC_VERSION,
    }


def local_map_mode(kind: str, cfg: dict[str, Any] | None = None) -> str:
    """title | actors | tags → off | prefer | fallback | force。"""
    data = normalize_strategy(cfg) if cfg is not None else get_strategy()
    maps = data.get("localMaps") if isinstance(data.get("localMaps"), dict) else {}
    k = str(kind or "").strip().lower()
    if k in ("actors", "actor", "actress"):
        key = "actors"
    elif k in ("tags", "tag"):
        key = "tags"
    else:
        key = "title"
    default = "prefer" if key == "title" else "fallback"
    v = str((maps or {}).get(key) or default).strip().lower()
    if key == "title" and v == "fallback":
        v = "prefer"
    if key == "tags" and v == "force":
        v = "fallback"
    return v if v in VALID_LOCAL_MAP_MODES else default


def local_map_bool(key: str, cfg: dict[str, Any] | None = None) -> bool:
    data = normalize_strategy(cfg) if cfg is not None else get_strategy()
    maps = data.get("localMaps") if isinstance(data.get("localMaps"), dict) else {}
    if key in (maps or {}) and (maps or {}).get(key) is not None:
        return bool((maps or {}).get(key))
    return True


def _resolve_strategy() -> tuple[dict[str, Any], bool]:
    """返回 (规范化后的策略, 是否需要把迁移结果落库)。**纯计算，不写库。**"""
    raw = settings_store.get_setting(ENRICH_STRATEGY_KEY) or {}
    raw_dict = raw if isinstance(raw, dict) else {}
    cfg = normalize_strategy(raw_dict)
    # 持久化 coverLogicVersion / 分区裁切恢复 / 省盘
    stored_cover = (
        raw_dict.get("cover") if isinstance(raw_dict.get("cover"), dict) else {}
    )
    new_cover = cfg.get("cover") if isinstance(cfg.get("cover"), dict) else {}
    need_persist = False
    if int(stored_cover.get("coverLogicVersion") or 0) < 9 or stored_cover.get(
        "regionCrop"
    ) != new_cover.get("regionCrop") or stored_cover.get("quality") != "compact":
        need_persist = True
    # 迁移：旧配置无 regionSources / 逻辑版落后 → 写入最终版默认有序源 + 海报字段优先
    stored_rs_ver = int(raw_dict.get("regionSourcesLogicVersion") or 0)
    if (
        not isinstance(raw_dict.get("regionSources"), dict)
        or stored_rs_ver < REGION_SOURCES_LOGIC_VERSION
    ):
        cfg["regionSources"] = {
            rid: list(sites) for rid, sites in _DEFAULT_REGION_SOURCES.items()
        }
        cfg["regionGroups"] = {
            rid: _groups_from_sources(cfg["regionSources"].get(rid) or [])
            or list(_DEFAULT_REGION_GROUPS.get(rid) or ["general"])
            for rid in REGION_ORDER
        }
        cfg["regionSourcesLogicVersion"] = REGION_SOURCES_LOGIC_VERSION
        fp = dict(cfg.get("fieldPriority") or {})
        fp["poster"] = ["dmm", "libredmm", "r18dev", "javbus", "mgstage"]
        cfg["fieldPriority"] = fp
        need_persist = True
    if int(stored_cover.get("coverLogicVersion") or 0) < 11:
        from app.scrap_library.cover_scrape import default_cover_settings

        cfg["cover"] = default_cover_settings()
        need_persist = True
    return cfg, need_persist


def get_strategy() -> dict[str, Any]:
    """读策略（纯读，**绝不写库**）。

    ⚠️ 不要在函数体里加 `put_setting`：本函数在 `enabled_enrich_sources()` 里
    **每个番号**都会被调一次，也挂在 `GET /embed/enrich/status` 这类纯读接口上。
    旧实现把「旧配置迁移」的 `put_setting` 直接内联在这里 —— 于是一次 GET 状态
    也会写 `app_settings`，且触发设置缓存失效 + 派生缓存失效（读放大成写风暴）。
    迁移现在由 `migrate_strategy_settings()` 承担，只在启动期与 `put_strategy()` 跑。
    内存里始终应用迁移结果，因此不落库也不影响任何读取方的语义。
    """
    return _resolve_strategy()[0]


def migrate_strategy_settings() -> bool:
    """把内存迁移结果落库一次（幂等）。返回本次是否真的写了。

    入口：应用启动（`main.lifespan`）。迁移完成后再调用不会产生写
    （`need_persist` 已为 False）。`put_strategy()` 自己就会写全量配置，
    因此不需要额外调用。
    """
    cfg, need = _resolve_strategy()
    if not need:
        return False
    try:
        settings_store.put_setting(ENRICH_STRATEGY_KEY, cfg)
    except Exception:  # noqa: BLE001
        return False
    return True


def put_strategy(body: dict[str, Any] | None) -> dict[str, Any]:
    prev = get_strategy()
    cfg = normalize_strategy(body if isinstance(body, dict) else {}, prev=prev)
    cfg["regionSourcesLogicVersion"] = REGION_SOURCES_LOGIC_VERSION
    settings_store.put_setting(ENRICH_STRATEGY_KEY, cfg)
    # 暂停中的任务立刻挂上新策略（续跑/展示）；源优先级与封面本就按 get_strategy 热读
    try:
        from app.scrap_library import enrich as enrich_svc

        enrich_svc.apply_live_strategy(cfg)
    except Exception:  # noqa: BLE001
        pass
    return cfg


def strategy_public(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """带标签与可选分组清单，供设置页渲染。"""
    from app.scrap_library.cover_scrape import (
        COVER_CROP_HINTS,
        COVER_CROP_LABELS,
        COVER_CROP_MODES,
        COVER_QUALITIES,
        COVER_QUALITY_LABELS,
    )
    from app.scrape.source_catalog import (
        SOURCE_CATALOG,
    )
    from app.scrape.sources_settings import is_provider_enabled

    data = normalize_strategy(cfg) if cfg is not None else get_strategy()
    regions = []
    enabled = data.get("regionsEnabled") or {}
    ui_order = [rid for rid in REGION_PRIORITY_UI_ORDER if rid in REGION_ORDER]
    for rid in ui_order + [r for r in REGION_ORDER if r not in ui_order]:
        meta = REGION_META.get(rid) or {}
        regions.append(
            {
                "id": rid,
                "label": str(
                    REGION_PRIORITY_LABELS.get(rid)
                    or meta.get("label")
                    or rid
                ),
                "folderLabel": str(meta.get("label") or rid),
                "groups": list(data["regionGroups"].get(rid) or []),
                "sources": list((data.get("regionSources") or {}).get(rid) or []),
                "enabled": bool(enabled.get(rid, True)),
                "coverHint": COVER_CROP_HINTS.get(rid, ""),
            }
        )
    return {
        **data,
        "modeLabel": MODE_LABELS.get(str(data["mode"]), str(data["mode"])),
        "modes": [{"value": m, "label": MODE_LABELS[m]} for m in VALID_MODES],
        "fillModeLabel": FILL_MODE_LABELS.get(
            str(data.get("fillMode") or "incremental"),
            str(data.get("fillMode") or "incremental"),
        ),
        "fillModes": [
            {"value": m, "label": FILL_MODE_LABELS[m]} for m in VALID_FILL_MODES
        ],
        "groupOptions": [
            {"id": str(g.get("id")), "label": str(g.get("label") or g.get("id"))}
            for g in SOURCE_GROUPS
            if g.get("id")
        ],
        "regions": regions,
        "regionSourceDefaults": {
            rid: list(sites)
            for rid, sites in _DEFAULT_REGION_SOURCES.items()
        },
        "coverCropOptions": [
            {"id": m, "label": COVER_CROP_LABELS.get(m, m)} for m in COVER_CROP_MODES
        ],
        "coverQualityOptions": [
            {"id": m, "label": COVER_QUALITY_LABELS.get(m, m)} for m in COVER_QUALITIES
        ],
        "coverRatioOptions": [
            {"id": "full", "label": "完整海报（2.12:3）"},
            {"id": "emby", "label": "Emby 比例（2:3）"},
        ],
        "fieldLanguageOptions": [
            {"id": "prefer_zh", "label": "中文优先"},
            {"id": "prefer_ja", "label": "日文优先"},
            {"id": "zh_or_translate", "label": "中文或译中"},
        ],
        "coverEnhanceOptions": [
            {"id": "off", "label": "关闭"},
            {"id": "official", "label": "官网/官方CDN"},
        ],
        "outlineShowOptions": [
            {"id": "zh", "label": "仅中文"},
            {"id": "zh_jp", "label": "中日"},
            {"id": "jp_zh", "label": "日中"},
        ],
        "forceFieldOptions": [
            {"id": fid, "label": FORCE_FIELD_LABELS.get(fid, fid)}
            for fid in VALID_FORCE_FIELDS
        ],
        # 字段站点优先级（设置页）：空链 = 用 catalog 默认；有配置 = 配置源第一优先，链上首个合格即停
        "fieldPriorityFields": [
            {"id": "title", "label": "标题"},
            {"id": "overview", "label": "简介"},
            {"id": "poster", "label": "海报"},
            {"id": "actors", "label": "女优"},
            {"id": "studio", "label": "片商"},
            {"id": "maker", "label": "制作商"},
            {"id": "date", "label": "发行日"},
            {"id": "year", "label": "年份"},
            {"id": "tags", "label": "标签"},
        ],
        "sourceOptions": [
            {
                "id": str(e.get("id")),
                "label": str(e.get("label") or e.get("id")),
                "group": str(e.get("group") or ""),
                "enabled": is_provider_enabled(str(e.get("id") or "")),
            }
            for e in SOURCE_CATALOG
            if e.get("id") and e.get("implemented", True)
        ],
        "fieldPriorityDefaults": {
            fid: list(chain)
            for fid, chain in default_strategy()["fieldPriority"].items()
        },
        "localMapModeOptions": [
            {"id": m, "label": LOCAL_MAP_MODE_LABELS.get(m, m)}
            for m in VALID_LOCAL_MAP_MODES
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
    """返回配置的七区分组（始终有值；通常由 regionSources 反推）。"""
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


def region_sources_for(
    region: str | None, *, cfg: dict[str, Any] | None = None
) -> list[str]:
    """番号类型有序源列表（高→低）；空 region 返回 []。

    cfg：复用调用方已读到的策略快照（热路径上省掉一次 app_settings 读取）。
    """
    from app.scrape.sources_settings import resolve_enrich_region_id
    from app.scrape.source_catalog import canonicalize_id

    rid = resolve_enrich_region_id(region) or str(region or "").strip()
    if not rid:
        return []
    if not isinstance(cfg, dict) or not cfg:
        cfg = get_strategy()
    raw = (cfg.get("regionSources") or {}).get(rid)
    if isinstance(raw, list) and raw:
        out: list[str] = []
        seen: set[str] = set()
        for s in raw:
            sid = canonicalize_id(str(s or ""))
            if sid and sid not in seen:
                seen.add(sid)
                out.append(sid)
        if out:
            return out
    return list(_DEFAULT_REGION_SOURCES.get(rid) or [])
