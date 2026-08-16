"""刮削地基：七区方案（对齐 maker-fs）+ meta/cover 源优先级。

对齐 mdc-ng / sehuatang：各区独立源链；封面与元数据源可分开改；封面只需一张。
"""

from __future__ import annotations

import re
from typing import Any

# 刮削方案 = maker-fs 七区（路径与任务区一一对应）
KIND_ORDER = (
    "japan_censored",
    "japan_gravure",
    "japan_uncensored",
    "japan_amateur",
    "fc2",
    "china",
    "western",
)

KIND_LABELS: dict[str, str] = {
    "japan_censored": "日本有码",
    "japan_gravure": "日本写真",
    "japan_uncensored": "日本无码",
    "japan_amateur": "日本素人",
    "fc2": "FC2",
    "china": "国产无码",
    "western": "欧美无码",
}

# 与 apps/scrape / mdc-ng 源 id 对齐（色花堂不在刮削源目录，仅 maker-fs 种子兜底）
SOURCE_CATALOG: list[dict[str, str]] = [
    # access: direct=直连 | proxy=代理直连 | proxy_flare=代理过盾
    {"id": "airav_io", "name": "Airav_io", "group": "av", "defaultUrl": "https://airav.io/cn", "access": "proxy_adaptive"},
    {"id": "avbase", "name": "Avbase", "group": "av", "defaultUrl": "https://www.avbase.net", "access": "proxy_adaptive"},
    {"id": "avmoo", "name": "Avmoo", "group": "av", "defaultUrl": "https://avmoo.shop", "access": "proxy_flare"},
    {"id": "avsox", "name": "Avsox", "group": "uncensored", "defaultUrl": "https://avsox.click", "access": "proxy_flare"},
    {"id": "carib", "name": "Carib", "group": "uncensored", "defaultUrl": "https://www.caribbeancom.com", "access": "proxy"},
    {"id": "dmm", "name": "Dmm", "group": "av", "defaultUrl": "https://www.dmm.co.jp", "access": "proxy"},
    {"id": "fc2", "name": "Fc2", "group": "fc2", "defaultUrl": "https://adult.contents.fc2.com", "access": "proxy"},
    {"id": "fc2_hub", "name": "Fc2_hub", "group": "fc2", "defaultUrl": "https://javten.com", "access": "proxy_flare"},
    {"id": "fd2ppv", "name": "Fd2ppv", "group": "fc2", "defaultUrl": "https://fd2ppv.cc", "access": "proxy_flare"},
    {"id": "freejavbt", "name": "Freejavbt", "group": "av", "defaultUrl": "https://freejavbt.com", "access": "proxy"},
    {"id": "jav321", "name": "Jav321", "group": "av", "defaultUrl": "https://www.jav321.com", "access": "proxy"},
    {"id": "javbus", "name": "Javbus", "group": "av", "defaultUrl": "https://www.javbus.com", "access": "proxy"},
    {"id": "javdb", "name": "Javdb", "group": "av", "defaultUrl": "https://javdb.com", "access": "proxy_flare"},
    {"id": "javlibrary", "name": "Javlibrary", "group": "av", "defaultUrl": "https://www.javlibrary.com/cn", "access": "proxy_flare"},
    {"id": "madou", "name": "Madou", "group": "chinese", "defaultUrl": "https://madou.club", "access": "proxy"},
    {"id": "madouqu", "name": "Madouqu", "group": "chinese", "defaultUrl": "https://madouqu.com", "access": "proxy"},
    {"id": "xiao_huang_shu", "name": "Xiao_huang_shu", "group": "chinese", "defaultUrl": "https://xchina.co", "access": "proxy"},
    {"id": "mgstage", "name": "Mgstage", "group": "av", "defaultUrl": "https://www.mgstage.com", "access": "proxy_adaptive"},
    {"id": "libredmm", "name": "LibreDMM", "group": "av", "defaultUrl": "https://www.libredmm.com", "access": "proxy"},
    {"id": "miss_av", "name": "Miss_av", "group": "av", "defaultUrl": "https://missav123.com", "access": "proxy_flare"},
    {"id": "sevenmmtv", "name": "7mmtv", "group": "av", "defaultUrl": "https://7mmtv.sx/zh", "access": "proxy_adaptive"},
    {"id": "iqqtv", "name": "Iqqtv", "group": "av", "defaultUrl": "https://iqq5.xyz/cn", "access": "direct"},
    {"id": "theporndb", "name": "ThePornDB", "group": "western", "defaultUrl": "https://api.theporndb.net", "access": "proxy"},
    {"id": "airav", "name": "Airav", "group": "av", "defaultUrl": "https://www.airav.wiki", "access": "proxy_adaptive"},
]

# 色花堂不在刮削源目录；仅作 maker-fs 种子 / fieldSources 标记
FORUM_SEED_ID = "forum"

_KNOWN = {s["id"] for s in SOURCE_CATALOG}
_CATALOG_BY_ID = {s["id"]: s for s in SOURCE_CATALOG}

# 当前出口实测不可用 / 缺密钥：默认关闭，优先级链里也剔除；forum 永不进源链
_DEFAULT_DISABLED_SOURCES = frozenset({"mgstage", "fc2_hub", "theporndb", "forum"})

# 字段优先级：五项（空列表=该字段不用任何源）
FIELD_PRIORITY_KEYS = (
    "cover",
    "titleZh",
    "outline",
    "studio",
    "actors",
    "tags",
    "series",
)
# schema≥3：字段优先级嵌在七区 kindProfiles[*].fieldPriority
# schema=5：日本区 titleZh/outline 前置 iqqtv（不过盾中文标题快源）
# schema=6：freejavbt 移出封面源（截帧/推荐串号不可靠）
# schema=7：标题/简介锁中文快源；其它字段放开结构快源（速度优先，少过盾）
FIELD_PRIORITY_SCHEMA = 7
# 七区×字段默认：仅「从未配置过」时的出厂值；线上以设置页 kindProfiles.fieldPriority 为准，勿在业务里写死源序
# 快源靠前；titleZh/outline 中文站优先；其它字段可用日文结构源
_JP_CENSORED_FP: dict[str, list[str]] = {
    "titleZh": ["iqqtv", "airav_io", "sevenmmtv"],
    "outline": ["iqqtv", "airav_io", "jav321"],
    "studio": ["javbus", "jav321", "libredmm"],
    "cover": ["javbus", "jav321", "libredmm"],
    "actors": ["javbus", "jav321", "libredmm"],
    "tags": ["javbus", "freejavbt", "airav_io"],
    "series": ["javbus", "freejavbt", "jav321"],
}

_JP_UNCENSORED_FP: dict[str, list[str]] = {
    "titleZh": ["iqqtv", "sevenmmtv", "airav_io"],
    "outline": ["iqqtv", "carib", "jav321"],
    "studio": ["carib", "javbus", "jav321"],
    "cover": ["carib", "javbus", "jav321"],
    "actors": ["javbus", "carib", "jav321"],
    "tags": ["javbus", "carib", "freejavbt"],
    "series": ["javbus", "carib", "jav321"],
}

_JP_AMATEUR_FP: dict[str, list[str]] = {
    "titleZh": ["iqqtv", "airav_io", "sevenmmtv"],
    "outline": ["iqqtv", "airav_io", "libredmm"],
    "studio": ["libredmm", "javbus", "jav321"],
    "cover": ["javbus", "libredmm", "jav321"],
    "actors": ["javbus", "libredmm", "jav321"],
    "tags": ["javbus", "libredmm", "freejavbt"],
    "series": ["libredmm", "javbus", "jav321"],
}

# FC2：官方快；中文标题能刮到再补 iqqtv/airav
_FC2_FP: dict[str, list[str]] = {
    "titleZh": ["iqqtv", "airav_io", "fc2"],
    "outline": ["fc2", "iqqtv", "javbus"],
    "studio": ["fc2", "javbus"],
    "cover": ["fc2", "javbus"],
    "actors": ["fc2", "javbus"],
    "tags": ["fc2", "javbus"],
    "series": ["fc2", "javbus"],
}

# 国产：标题/简介中文站；封面 madou 更稳，小黄书作补充
_CHINA_FP: dict[str, list[str]] = {
    "titleZh": ["madouqu", "madou", "xiao_huang_shu"],
    "outline": ["madouqu", "madou", "xiao_huang_shu"],
    "studio": ["madouqu", "madou", "xiao_huang_shu"],
    "cover": ["madou", "xiao_huang_shu", "madouqu"],
    "actors": ["madouqu", "madou", "javbus"],
    "tags": ["madou", "madouqu", "javbus"],
    "series": ["madouqu", "madou"],
}

_WESTERN_FP: dict[str, list[str]] = {
    "titleZh": ["iqqtv", "airav_io", "sevenmmtv"],
    "outline": ["iqqtv", "airav_io", "libredmm"],
    "studio": ["javbus", "libredmm", "jav321"],
    "cover": ["javbus", "libredmm", "jav321"],
    "actors": ["javbus", "libredmm", "jav321"],
    "tags": ["javbus", "libredmm", "freejavbt"],
    "series": ["javbus", "libredmm", "jav321"],
}


def _fp_copy(src: dict[str, list[str]]) -> dict[str, list[str]]:
    return {k: list(src.get(k) or []) for k in FIELD_PRIORITY_KEYS}


DEFAULT_FIELD_PRIORITY: dict[str, list[str]] = _fp_copy(_JP_CENSORED_FP)

DEFAULT_FIELD_PRIORITY_BY_KIND: dict[str, dict[str, list[str]]] = {
    "japan_censored": _fp_copy(_JP_CENSORED_FP),
    "japan_gravure": _fp_copy(_JP_CENSORED_FP),
    "japan_uncensored": _fp_copy(_JP_UNCENSORED_FP),
    "japan_amateur": _fp_copy(_JP_AMATEUR_FP),
    "fc2": _fp_copy(_FC2_FP),
    "china": _fp_copy(_CHINA_FP),
    "western": _fp_copy(_WESTERN_FP),
}

# 兼容旧 meta/cover 链名（由 fieldPriority 推导）
_AV_CHAIN: list[str] = []
_UNCENSORED_CHAIN: list[str] = []
_AMATEUR_CHAIN: list[str] = []
_FC2_META: list[str] = []
_FC2_COVER: list[str] = []
_CHINA_CHAIN: list[str] = []
_WESTERN_CHAIN: list[str] = []

# 源序 schema：升版时按新区默认重配 fieldPriority（保留 library/write）
KIND_PRIORITY_SCHEMA = 20

# 海报裁剪：right=右侧 / none=不裁剪 / face=人脸(注意力)定位
POSTER_CROP_MODES = frozenset({"right", "none", "face"})
POSTER_CROP_RATIOS = frozenset({"full", "emby"})  # full=2.12/3, emby=2/3

# 七区默认裁剪（对齐 mdc-ng 建议）
DEFAULT_POSTER_CROP_BY_KIND: dict[str, str] = {
    "japan_censored": "right",
    "japan_gravure": "right",
    "japan_uncensored": "none",
    "japan_amateur": "face",
    "fc2": "face",
    "china": "none",
    "western": "none",
}

POSTER_CROP_KIND_HINTS: dict[str, str] = {
    "japan_censored": "缩略图多为光碟封面，海报部分出现在右侧，建议使用右侧裁剪",
    "japan_gravure": "写真封面多为横图，可按右侧裁剪出竖版海报",
    "japan_uncensored": "无码作品可以保留原图，也可以进行人脸识别，推荐不裁剪",
    "japan_amateur": "素人图片尺寸不规则，建议使用人脸识别，根据人脸位置裁剪",
    "fc2": "FC2图片尺寸不规则，建议使用人脸识别，根据人脸位置裁剪",
    "china": "国产作品一般有完整的宽图封面，建议不裁剪保留原样",
    "western": "欧美作品封面多为完整竖图或宽图，建议不裁剪保留原样",
}


def normalize_poster_crop(raw: Any) -> dict[str, Any]:
    """海报剪裁配置：七区模式 + 比例 + 两个增强开关。"""
    src = raw if isinstance(raw, dict) else {}
    by_raw = src.get("byKind") or src.get("by_kind") or {}
    if not isinstance(by_raw, dict):
        by_raw = {}
    by_kind: dict[str, str] = {}
    for kid in KIND_ORDER:
        v = str(by_raw.get(kid) or DEFAULT_POSTER_CROP_BY_KIND[kid]).strip().lower()
        if v in {"no", "skip", "keep", "original"}:
            v = "none"
        if v in {"face_detect", "ai", "attention"}:
            v = "face"
        if v in {"right_crop", "right-side", "side"}:
            v = "right"
        by_kind[kid] = v if v in POSTER_CROP_MODES else DEFAULT_POSTER_CROP_BY_KIND[kid]
    ratio = str(src.get("ratio") or "full").strip().lower()
    if ratio in {"2.12/3", "2.12:3", "complete", "poster"}:
        ratio = "full"
    if ratio in {"2/3", "2:3", "emby_ratio"}:
        ratio = "emby"
    if ratio not in POSTER_CROP_RATIOS:
        ratio = "full"
    return {
        "byKind": by_kind,
        "ratio": ratio,
        "cropDownloadedPoster": bool(
            src.get("cropDownloadedPoster", src.get("crop_downloaded_poster", False))
        ),
        "preferCropIfBetter": bool(
            src.get("preferCropIfBetter", src.get("prefer_crop_if_better", False))
        ),
        "kindHints": dict(POSTER_CROP_KIND_HINTS),
    }


def _clean_field_list(raw: Any) -> list[str]:
    """字段优先级：只过滤非法/重复/默认关闭源，不补默认站点。"""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        sid = str(item or "").strip().lower()
        if (
            not sid
            or sid not in _KNOWN
            or sid in seen
            or sid in _DEFAULT_DISABLED_SOURCES
        ):
            continue
        seen.add(sid)
        out.append(sid)
    return out


def _clean_sources(raw: Any, fallback: list[str]) -> list[str]:
    """保留用户顺序；剔除默认关闭源。有配置则不补默认源（设置页为准）。"""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        sid = str(item or "").strip().lower()
        if (
            not sid
            or sid not in _KNOWN
            or sid in seen
            or sid in _DEFAULT_DISABLED_SOURCES
        ):
            continue
        seen.add(sid)
        out.append(sid)
    if out:
        return out
    return [s for s in fallback if s not in _DEFAULT_DISABLED_SOURCES]


def normalize_field_priority(raw: Any) -> dict[str, list[str]]:
    src = raw if isinstance(raw, dict) else {}
    # 旧版「发行方」槽位 → 简介
    if "outline" not in src and isinstance(src.get("publisher"), list):
        src = {**src, "outline": list(src.get("publisher") or [])}
    # genres 别名 → tags
    if "tags" not in src and isinstance(src.get("genres"), list):
        src = {**src, "tags": list(src.get("genres") or [])}
    out: dict[str, list[str]] = {}
    for key in FIELD_PRIORITY_KEYS:
        fb = list(DEFAULT_FIELD_PRIORITY.get(key) or [])
        if key not in src:
            # 旧配置缺新字段：用默认链补齐（标签/系列）
            out[key] = fb
            continue
        if isinstance(src.get(key), list) and len(src.get(key) or []) == 0:
            out[key] = []
        else:
            out[key] = _clean_field_list(src.get(key))
    return out


def default_field_priority_for_kind(kind: str) -> dict[str, list[str]]:
    """新区默认四字段。"""
    base = DEFAULT_FIELD_PRIORITY_BY_KIND.get(kind) or DEFAULT_FIELD_PRIORITY_BY_KIND[
        "japan_censored"
    ]
    fp = {k: list(base.get(k) or []) for k in FIELD_PRIORITY_KEYS}
    return normalize_field_priority(fp)


def normalize_export_fields(raw: Any) -> list[str]:
    """任务/导出字段列表；空或全无效时默认全开。"""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        key = _TASK_FIELD_CANON.get(str(item or "").strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out or list(DEFAULT_SCRAPE_TASK_FIELDS)


def filter_field_priority_for_export(
    fp: dict[str, list[str]] | None,
    export_fields: list[str] | None,
) -> dict[str, list[str]]:
    """按任务勾选字段裁剪 fieldPriority；未选字段对应空列表。"""
    fields = normalize_field_priority(fp)
    want = set(normalize_export_fields(export_fields))
    return {
        k: (list(fields.get(k) or []) if k in want else [])
        for k in FIELD_PRIORITY_KEYS
    }


def derive_sources_from_fields(
    fp: dict[str, list[str]] | None,
) -> tuple[list[str], list[str]]:
    """由字段优先级推导抓取队列：cover 单独；meta 去重合并。

    顺序与 scrape.ts deriveCollectPlan 对齐：快源（封面/系列）靠前，
    中文过盾源（标题/简介）垫后，避免日志/兜底链先打 Flare。
    """
    fields = normalize_field_priority(fp)
    cover = list(fields.get("cover") or [])
    meta: list[str] = []
    seen: set[str] = set()
    for key in ("cover", "series", "studio", "tags", "actors", "titleZh", "outline"):
        for sid in fields.get(key) or []:
            if sid in seen:
                continue
            seen.add(sid)
            meta.append(sid)
    if not meta:
        meta = list(cover)
    if not cover:
        cover = list(meta)
    return meta, cover


def _profile(kind: str) -> dict[str, Any]:
    fp = default_field_priority_for_kind(kind)
    meta_d, cover_d = derive_sources_from_fields(fp)
    return {
        "libraryRoot": "",
        "writeTree": None,
        "writeEmby": None,
        "metaSources": meta_d,
        "coverSources": cover_d,
        "fieldPriority": fp,
    }


DEFAULT_KIND_PROFILES: dict[str, dict[str, Any]] = {
    kid: _profile(kid) for kid in KIND_ORDER
}


# 兼容旧字段名
DEFAULT_REGION_PROFILES = DEFAULT_KIND_PROFILES
REGION_ORDER = KIND_ORDER
REGION_LABELS = KIND_LABELS

_FC2_RE = re.compile(r"^FC2", re.I)


def is_fc2_code(code: str) -> bool:
    return bool(_FC2_RE.match(str(code or "").strip()))


def detect_scrape_kind(code: str, region: str | None = None) -> str:
    """番号 + maker-fs 区 → 刮削方案。FC2 优先；区与 KIND_ORDER 一一对应。"""
    if is_fc2_code(code):
        return "fc2"
    rid = (region or "").strip()
    if rid in KIND_ORDER:
        return rid
    return "japan_censored"


def _field_priority_from_raw(
    raw: dict[str, Any],
    base: dict[str, Any],
    *,
    global_field_priority: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    fp_raw = raw.get("fieldPriority") or raw.get("field_priority")
    if isinstance(fp_raw, dict) and any(k in fp_raw for k in FIELD_PRIORITY_KEYS):
        return normalize_field_priority(fp_raw)
    gfp = normalize_field_priority(global_field_priority)
    if any(gfp.get(k) for k in FIELD_PRIORITY_KEYS):
        return gfp
    base_fp = base.get("fieldPriority")
    if isinstance(base_fp, dict) and any(base_fp.get(k) for k in FIELD_PRIORITY_KEYS):
        return normalize_field_priority(base_fp)
    return {k: [] for k in FIELD_PRIORITY_KEYS}


def _merge_profile(
    kind: str,
    raw: Any,
    *,
    global_field_priority: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    base = dict(DEFAULT_KIND_PROFILES.get(kind) or DEFAULT_KIND_PROFILES["japan_censored"])
    if not isinstance(raw, dict):
        return dict(base)
    lib = str(raw.get("libraryRoot") or raw.get("library_root") or "").strip()
    wt = raw.get("writeTree", raw.get("write_tree", base.get("writeTree")))
    we = raw.get("writeEmby", raw.get("write_emby", base.get("writeEmby")))
    if wt is not None:
        wt = bool(wt)
    if we is not None:
        we = bool(we)
    fp = _field_priority_from_raw(raw, base, global_field_priority=global_field_priority)
    meta_d, cover_d = derive_sources_from_fields(fp)
    return {
        "libraryRoot": lib,
        "writeTree": wt,
        "writeEmby": we,
        "metaSources": meta_d,
        "coverSources": cover_d,
        "fieldPriority": fp,
    }


def _legacy_raw_table(raw: Any) -> dict[str, Any]:
    """合并 kindProfiles / regionProfiles。"""
    src: dict[str, Any] = {}
    if isinstance(raw, dict):
        src.update(raw)
    return src


def normalize_kind_profiles(
    raw: Any,
    *,
    priority_schema: int | None = None,
    global_field_priority: dict[str, list[str]] | None = None,
) -> dict[str, dict[str, Any]]:
    src = _legacy_raw_table(raw)
    # 五类 → 七区：缺写真/素人键时整表按新默认源序重配
    upgrade_kinds = not (
        isinstance(src, dict)
        and "japan_amateur" in src
        and "japan_gravure" in src
    )
    try:
        schema = int(priority_schema) if priority_schema is not None else 0
    except (TypeError, ValueError):
        schema = 0
    upgrade_order = schema < KIND_PRIORITY_SCHEMA
    gfp = (
        normalize_field_priority(global_field_priority)
        if global_field_priority is not None
        else None
    )
    if upgrade_kinds:
        return {
            kid: _merge_profile(kid, None, global_field_priority=gfp)
            for kid in KIND_ORDER
        }
    if upgrade_order:
        # 刷新默认源序；已保存的 fieldPriority 必须保留（勿被默认覆盖）
        out: dict[str, dict[str, Any]] = {}
        for kid in KIND_ORDER:
            cur = src.get(kid) if isinstance(src, dict) else None
            merged = _merge_profile(
                kid, cur if isinstance(cur, dict) else None, global_field_priority=gfp
            )
            fresh = _merge_profile(kid, None, global_field_priority=gfp)
            saved_fp = merged.get("fieldPriority") or {}
            has_saved = any(saved_fp.get(k) for k in FIELD_PRIORITY_KEYS)
            if has_saved:
                fp = normalize_field_priority(saved_fp)
                meta_d, cover_d = derive_sources_from_fields(fp)
                merged["fieldPriority"] = fp
                merged["metaSources"] = meta_d
                merged["coverSources"] = cover_d
            else:
                merged["fieldPriority"] = dict(fresh["fieldPriority"])
                merged["metaSources"] = list(fresh["metaSources"])
                merged["coverSources"] = list(fresh["coverSources"])
            out[kid] = merged
        return out
    return {
        kid: _merge_profile(
            kid, src.get(kid), global_field_priority=gfp
        )
        for kid in KIND_ORDER
    }


def normalize_region_profiles(raw: Any) -> dict[str, dict[str, Any]]:
    """兼容旧 API 名。"""
    return normalize_kind_profiles(raw)


def resolve_kind_profile(
    kind: str | None,
    *,
    profiles: dict[str, dict[str, Any]] | None = None,
    global_library: str = "",
    global_write_tree: bool = True,
    global_write_emby: bool = True,
) -> dict[str, Any]:
    kid = (kind or "").strip()
    table = profiles or normalize_kind_profiles(None)
    prof = table.get(kid) or _merge_profile(
        kid if kid in DEFAULT_KIND_PROFILES else "japan_censored", None
    )
    lib = str(prof.get("libraryRoot") or "").strip() or str(global_library or "").strip()
    wt = prof.get("writeTree")
    we = prof.get("writeEmby")
    return {
        "kind": kid,
        "region": kid,  # 兼容旧字段
        "libraryRoot": lib,
        "writeTree": global_write_tree if wt is None else bool(wt),
        "writeEmby": global_write_emby if we is None else bool(we),
        "metaSources": list(prof.get("metaSources") or []),
        "coverSources": list(prof.get("coverSources") or []),
        "fieldPriority": normalize_field_priority(prof.get("fieldPriority")),
    }


def resolve_region_profile(
    region: str | None,
    *,
    profiles: dict[str, dict[str, Any]] | None = None,
    global_library: str = "",
    global_write_tree: bool = True,
    global_write_emby: bool = True,
    code: str | None = None,
) -> dict[str, Any]:
    kind = detect_scrape_kind(code or "", region)
    return resolve_kind_profile(
        kind,
        profiles=profiles,
        global_library=global_library,
        global_write_tree=global_write_tree,
        global_write_emby=global_write_emby,
    )


def default_cookie_for(sid: str) -> str:
    if sid == "javbus":
        return "existmag=all; age=verified; dv=1"
    if sid == "mgstage":
        return "adc=1"
    return ""


def default_source_config(sid: str) -> dict[str, Any]:
    defn = _CATALOG_BY_ID.get(sid) or {"defaultUrl": "", "name": sid, "group": "other"}
    access = str(defn.get("access") or "proxy").strip().lower()
    if access not in ("direct", "proxy", "proxy_flare", "proxy_adaptive"):
        access = "proxy"
    return {
        "id": sid,
        "name": defn.get("name") or sid,
        "group": defn.get("group") or "other",
        "access": access,
        "enabled": sid not in _DEFAULT_DISABLED_SOURCES,
        "baseUrl": str(defn.get("defaultUrl") or ""),
        "cookie": default_cookie_for(sid),
        "status": "unknown",
        "lastCheckedAt": None,
        "lastError": None,
        "lastProbeVia": None,
        "retry": 0,
        "cooldownUntil": None,
        "cooldownRemainingSec": 0,
    }


def _cooldown_remaining_sec(raw: Any) -> tuple[str | None, int]:
    """返回 (cooldownUntil iso, remainingSec)。"""
    from datetime import datetime, timezone

    s = str(raw or "").strip()
    if not s:
        return None, 0
    try:
        # 支持 ...Z
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        rem = int((dt - now).total_seconds())
        if rem <= 0:
            return None, 0
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), rem
    except Exception:
        return None, 0


def normalize_sources_map(raw: Any) -> dict[str, dict[str, Any]]:
    src = raw if isinstance(raw, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for defn in SOURCE_CATALOG:
        sid = defn["id"]
        base = default_source_config(sid)
        cur = src.get(sid) if isinstance(src.get(sid), dict) else {}
        base["enabled"] = bool(cur.get("enabled", base["enabled"]))
        # 目录名始终覆盖
        base["name"] = str(defn.get("name") or sid)
        url = str(cur.get("baseUrl") or cur.get("base_url") or "").strip()
        if url:
            base["baseUrl"] = url
        cookie = str(cur.get("cookie") or "").strip()
        if cookie:
            base["cookie"] = cookie
        st = str(cur.get("status") or "unknown").lower()
        if st not in ("ok", "error", "unknown"):
            st = "unknown"
        base["status"] = st
        base["lastCheckedAt"] = cur.get("lastCheckedAt") or cur.get("last_checked_at")
        base["lastError"] = cur.get("lastError") or cur.get("last_error")
        via = str(cur.get("lastProbeVia") or cur.get("last_probe_via") or "").strip().lower()
        base["lastProbeVia"] = via if via in ("direct", "curl", "flare") else None
        try:
            base["retry"] = max(0, min(8, int(cur.get("retry") or 0)))
        except (TypeError, ValueError):
            base["retry"] = 0
        until, rem = _cooldown_remaining_sec(
            cur.get("cooldownUntil") or cur.get("cooldown_until")
        )
        base["cooldownUntil"] = until
        base["cooldownRemainingSec"] = rem
        out[sid] = base
    return out


def sources_public_list(raw: Any) -> list[dict[str, Any]]:
    m = normalize_sources_map(raw)
    return [m[s["id"]] for s in SOURCE_CATALOG]


def normalize_retry(raw: Any) -> dict[str, int]:
    n = 0
    if isinstance(raw, dict):
        try:
            n = int(raw.get("defaultRetry") or raw.get("default_retry") or 0)
        except (TypeError, ValueError):
            n = 0
    elif isinstance(raw, (int, float)):
        n = int(raw)
    return {"defaultRetry": max(0, min(8, n))}


def apply_source_probe(
    sources: dict[str, dict[str, Any]],
    sid: str,
    *,
    status: str,
    last_error: str | None = None,
    cooldown_sec: int | None = None,
    resolved_base_url: str | None = None,
    probe_via: str | None = None,
) -> dict[str, dict[str, Any]]:
    out = normalize_sources_map(sources)
    if sid not in out:
        return out
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    out[sid]["status"] = status if status in ("ok", "error", "unknown") else "unknown"
    out[sid]["lastCheckedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    out[sid]["lastError"] = last_error
    via = str(probe_via or "").strip().lower()
    out[sid]["lastProbeVia"] = via if via in ("direct", "curl", "flare") else None
    # 探测跟到可用镜像时回写 baseUrl（iqqtv / airav_io / javbus 等）
    resolved = str(resolved_base_url or "").strip().rstrip("/")
    if status == "ok" and resolved and resolved.startswith("http"):
        prev = str(out[sid].get("baseUrl") or "").strip().rstrip("/")
        if resolved != prev:
            out[sid]["baseUrl"] = resolved
    if status == "error":
        sec = 10 if cooldown_sec is None else max(0, min(120, int(cooldown_sec)))
        if sec > 0:
            until = now + timedelta(seconds=sec)
            out[sid]["cooldownUntil"] = until.strftime("%Y-%m-%dT%H:%M:%SZ")
            out[sid]["cooldownRemainingSec"] = sec
        else:
            out[sid]["cooldownUntil"] = None
            out[sid]["cooldownRemainingSec"] = 0
    else:
        out[sid]["cooldownUntil"] = None
        out[sid]["cooldownRemainingSec"] = 0
    return out


def enabled_source_ids(sources: dict[str, dict[str, Any]] | None) -> list[str]:
    m = normalize_sources_map(sources)
    return [
        sid
        for sid, cfg in m.items()
        if cfg.get("enabled") and int(cfg.get("cooldownRemainingSec") or 0) <= 0
    ]


def filter_sources_by_enabled(order: list[str], enabled: set[str] | list[str]) -> list[str]:
    allow = set(enabled)
    return [
        s
        for s in order
        if s in allow and s != FORUM_SEED_ID and s not in _DEFAULT_DISABLED_SOURCES
    ]


SCRAPE_TASK_FIELDS = (
    "cover",
    "titleZh",
    "outline",
    "studio",
    "actors",
    "tags",
    "series",
)
DEFAULT_SCRAPE_TASK_FIELDS = list(SCRAPE_TASK_FIELDS)
# 可从索引物化复用的字段（封面永远走网络）
LOCAL_REUSE_FIELDS = (
    "titleZh",
    "outline",
    "studio",
    "actors",
    "tags",
    "series",
)
_TASK_FIELD_CANON = {f.lower(): f for f in SCRAPE_TASK_FIELDS}
_TASK_FIELD_CANON["title"] = "titleZh"
_TASK_FIELD_CANON["plot"] = "outline"
_TASK_FIELD_CANON["publisher"] = "outline"  # 旧任务字段兼容
_TASK_FIELD_CANON["genres"] = "tags"
_TASK_FIELD_CANON["tag"] = "tags"


def normalize_local_fields(raw: Any) -> list[str]:
    """任务「本地可复用字段」；允许空（空=不从索引读内容字段）。不含封面。"""
    out: list[str] = []
    seen: set[str] = set()
    allow = set(LOCAL_REUSE_FIELDS)
    for item in raw if isinstance(raw, list) else []:
        key = _TASK_FIELD_CANON.get(str(item or "").strip().lower())
        if not key or key not in allow or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def normalize_scrape_tasks(raw: Any) -> list[dict[str, Any]]:
    """Emby 式刮削任务列表。"""
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("id") or "").strip()
        if not tid or tid in seen:
            continue
        seen.add(tid)
        regions: list[str] = []
        for r in item.get("regions") or []:
            s = str(r or "").strip()
            if s and s not in regions:
                regions.append(s)
        mode = str(item.get("mode") or "incremental").strip().lower()
        if mode not in ("incremental", "force"):
            mode = "incremental"
        # 任务字段：未配置或全空时默认全开
        raw_fields = item.get("fields") or []
        fields: list[str] = []
        seen_f: set[str] = set()
        for f in raw_fields:
            key = _TASK_FIELD_CANON.get(str(f or "").strip().lower())
            if not key or key in seen_f:
                continue
            seen_f.add(key)
            fields.append(key)
        if not fields:
            fields = list(DEFAULT_SCRAPE_TASK_FIELDS)
        # 本地可复用：显式列表，缺省为空（不读索引脏数据）
        local_raw = item.get("localFields")
        if local_raw is None:
            local_raw = item.get("local_fields")
        local_fields = normalize_local_fields(local_raw)
        # 仅保留也在刮削字段里的项（封面本来就不在 LOCAL_REUSE）
        field_set = set(fields)
        local_fields = [f for f in local_fields if f in field_set]

        def _int(key: str, *alts: str) -> int:
            for k in (key, *alts):
                if item.get(k) is None:
                    continue
                try:
                    return max(0, int(item.get(k) or 0))
                except (TypeError, ValueError):
                    continue
            return 0

        def _code_list(raw_codes: Any) -> list[str]:
            out_codes: list[str] = []
            seen_c: set[str] = set()
            if not isinstance(raw_codes, list):
                return out_codes
            for x in raw_codes:
                c = str(x or "").strip()
                if not c or c in seen_c:
                    continue
                seen_c.add(c)
                out_codes.append(c)
                if len(out_codes) >= 20000:
                    break
            return out_codes

        watch_raw = item.get("watchEnabled")
        if watch_raw is None:
            watch_raw = item.get("watch_enabled")
        # 仅当用户手动「开始」并完整跑完一轮后，监控才允许自动入队
        armed_raw = item.get("watchArmed")
        if armed_raw is None:
            armed_raw = item.get("watch_armed")
        done_v = _int("done")
        empty_v = _int("empty")
        skipped_v = _int("skipped")
        failed_v = _int("failed")
        total_v = _int("total")
        done_codes = _code_list(item.get("doneCodes") or item.get("done_codes"))
        empty_codes = _code_list(item.get("emptyCodes") or item.get("empty_codes"))
        skipped_codes = _code_list(
            item.get("skippedCodes") or item.get("skipped_codes")
        )
        failed_codes = _code_list(
            item.get("failedCodes") or item.get("failed_codes")
        )
        # 有番号列表时以列表长度为准，并钳制成功>合计的历史脏数据
        if done_codes:
            done_v = min(done_v, len(done_codes)) if done_v else len(done_codes)
            done_v = len(done_codes)
        if empty_codes:
            empty_v = len(empty_codes)
        if skipped_codes:
            skipped_v = len(skipped_codes)
        if failed_codes:
            failed_v = len(failed_codes)
        processed = done_v + empty_v + skipped_v + failed_v
        # 任务卡是终身累计：合计不够时抬高合计，绝不压低成功数
        if processed > total_v:
            total_v = processed
        last_status = str(
            item.get("lastStatus") or item.get("last_status") or ""
        ).strip()
        if last_status.startswith("完成") and total_v >= 0:
            last_status = (
                f"完成 · 成功 {done_v} · 空号 {empty_v} · 失败 {failed_v}"
            )
        out.append(
            {
                "id": tid,
                "name": str(item.get("name") or "").strip(),
                "regions": regions,
                "maker": str(item.get("maker") or "").strip(),
                "prefix": str(item.get("prefix") or "").strip(),
                "code": str(item.get("code") or "").strip(),
                "mode": mode,
                "fields": fields,
                "localFields": local_fields,
                "watchEnabled": bool(watch_raw),
                # 仅用户手动「开始」并正常跑完一轮后为 True；暂停/取消后清掉
                "watchArmed": bool(armed_raw),
                "lastStatus": last_status,
                "updatedAt": str(
                    item.get("updatedAt") or item.get("updated_at") or ""
                ).strip(),
                "done": done_v,
                "empty": empty_v,
                "skipped": skipped_v,
                "failed": failed_v,
                "total": total_v,
                "doneCodes": done_codes,
                "emptyCodes": empty_codes,
                "skippedCodes": skipped_codes,
                "failedCodes": failed_codes,
            }
        )
    return out


def _prepend_iqqtv_field_lists(
    kinds: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """schema 升级：日本/欧美区 titleZh、outline 前置 iqqtv（不过盾中文快源）。"""
    target_kinds = {
        "japan_censored",
        "japan_gravure",
        "japan_uncensored",
        "japan_amateur",
        "western",
    }
    out: dict[str, dict[str, Any]] = {}
    for kid, prof in kinds.items():
        merged = dict(prof or {})
        if kid not in target_kinds:
            out[kid] = merged
            continue
        fp_raw = merged.get("fieldPriority")
        if not isinstance(fp_raw, dict):
            out[kid] = merged
            continue
        fp = {k: list(v) if isinstance(v, list) else [] for k, v in fp_raw.items()}
        changed = False
        for key in ("titleZh", "outline"):
            lst = [str(x or "").strip().lower() for x in (fp.get(key) or [])]
            lst = [x for x in lst if x]
            if not lst:
                continue
            if "iqqtv" in lst:
                rest = [x for x in lst if x != "iqqtv"]
                nxt = ["iqqtv", *rest]
            else:
                nxt = ["iqqtv", *lst]
            # 每字段最多 3 个网络源
            nxt = nxt[:3]
            if nxt != lst:
                fp[key] = nxt
                changed = True
        if changed:
            fp_n = normalize_field_priority(fp)
            meta_d, cover_d = derive_sources_from_fields(fp_n)
            merged["fieldPriority"] = fp_n
            merged["metaSources"] = meta_d
            merged["coverSources"] = cover_d
        out[kid] = merged
    return out


def _strip_freejavbt_from_cover(
    kinds: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """schema≥6：freejavbt 不得作封面源。"""
    out: dict[str, dict[str, Any]] = {}
    for kid, prof in kinds.items():
        merged = dict(prof or {})
        fp_raw = merged.get("fieldPriority")
        if not isinstance(fp_raw, dict):
            out[kid] = merged
            continue
        fp = {k: list(v) if isinstance(v, list) else [] for k, v in fp_raw.items()}
        cover = [str(x or "").strip().lower() for x in (fp.get("cover") or [])]
        cover = [x for x in cover if x and x != "freejavbt"]
        old = [str(x or "").strip().lower() for x in (fp.get("cover") or []) if str(x or "").strip()]
        if cover == old:
            # 仍可能 coverSources 里残留
            cs = [
                str(x or "").strip().lower()
                for x in (merged.get("coverSources") or [])
                if str(x or "").strip()
            ]
            if "freejavbt" not in cs:
                out[kid] = merged
                continue
            merged["coverSources"] = [x for x in cs if x != "freejavbt"]
            out[kid] = merged
            continue
        fp["cover"] = cover[:3]
        fp_n = normalize_field_priority(fp)
        meta_d, cover_d = derive_sources_from_fields(fp_n)
        merged["fieldPriority"] = fp_n
        merged["metaSources"] = meta_d
        merged["coverSources"] = [x for x in cover_d if x != "freejavbt"]
        out[kid] = merged
    return out


def _apply_speed_zh_title_field_defaults(
    kinds: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """schema≥7：按出厂「标题/简介中文 + 其它字段放开快源」重配各区 fieldPriority。"""
    out: dict[str, dict[str, Any]] = {}
    for kid, prof in kinds.items():
        merged = dict(prof or {})
        base = DEFAULT_FIELD_PRIORITY_BY_KIND.get(kid)
        if not base:
            out[kid] = merged
            continue
        fp_n = normalize_field_priority(base)
        meta_d, cover_d = derive_sources_from_fields(fp_n)
        merged["fieldPriority"] = fp_n
        merged["metaSources"] = meta_d
        merged["coverSources"] = cover_d
        out[kid] = merged
    return out


def profiles_public(
    raw_profiles: Any,
    *,
    raw_sources: Any = None,
    raw_field_priority: Any = None,
    raw_retry: Any = None,
    raw_tasks: Any = None,
    priority_schema: int | None = None,
    field_priority_schema: int | None = None,
) -> dict[str, Any]:
    try:
        schema = int(priority_schema) if priority_schema is not None else 0
    except (TypeError, ValueError):
        schema = 0
    try:
        fp_schema = (
            int(field_priority_schema) if field_priority_schema is not None else 0
        )
    except (TypeError, ValueError):
        fp_schema = 0
    upgrade_order = schema < KIND_PRIORITY_SCHEMA
    upgrade_fields = fp_schema < FIELD_PRIORITY_SCHEMA
    gfp = (
        normalize_field_priority(raw_field_priority)
        if upgrade_fields
        else None
    )
    kinds = normalize_kind_profiles(
        raw_profiles,
        priority_schema=priority_schema,
        global_field_priority=gfp,
    )
    if upgrade_fields:
        kinds = _prepend_iqqtv_field_lists(kinds)
        kinds = _strip_freejavbt_from_cover(kinds)
        if fp_schema < 7:
            kinds = _apply_speed_zh_title_field_defaults(kinds)
    # 顶层 fieldPriority 仅兼容旧前端；schema≥3 以各区 kindProfiles.fieldPriority 为准
    ref = kinds.get("japan_censored") or {}
    fields = normalize_field_priority(ref.get("fieldPriority"))
    tasks = normalize_scrape_tasks(raw_tasks)
    # 预览 codes 可能截断；对外返回的计数以 SQLite 为准抬高
    try:
        from . import scrape_export_log_store

        enriched: list[dict[str, Any]] = []
        for t in tasks:
            tid = str(t.get("id") or "").strip()
            if not tid:
                enriched.append(t)
                continue
            dbc = scrape_export_log_store.count_result_codes(tid)
            nt = dict(t)
            nt["done"] = max(int(t.get("done") or 0), int(dbc.get("done") or 0))
            nt["empty"] = max(int(t.get("empty") or 0), int(dbc.get("empty") or 0))
            nt["skipped"] = max(
                int(t.get("skipped") or 0), int(dbc.get("skipped") or 0)
            )
            nt["failed"] = max(
                int(t.get("failed") or 0), int(dbc.get("failed") or 0)
            )
            processed = (
                int(nt["done"])
                + int(nt["empty"])
                + int(nt["skipped"])
                + int(nt["failed"])
            )
            nt["total"] = max(int(t.get("total") or 0), processed)
            enriched.append(nt)
        tasks = enriched
    except Exception:
        pass
    sources = sources_public_list(raw_sources)
    return {
        "sourceCatalog": SOURCE_CATALOG,
        "sources": sources,
        "kindLabels": KIND_LABELS,
        "kindProfiles": kinds,
        "fieldPriority": fields,
        "retry": normalize_retry(raw_retry),
        "scrapeTasks": tasks,
        "kindPrioritySchema": KIND_PRIORITY_SCHEMA,
        "fieldPrioritySchema": FIELD_PRIORITY_SCHEMA,
        "posterCropModes": sorted(POSTER_CROP_MODES),
        "posterCropRatios": sorted(POSTER_CROP_RATIOS),
        # 兼容旧前端字段
        "regionLabels": KIND_LABELS,
        "regionProfiles": kinds,
        "_upgradedPriority": upgrade_order,
        "_upgradedFieldPriority": upgrade_fields,
    }
