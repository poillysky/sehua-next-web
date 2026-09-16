"""MDCS sourceMaster + SITE_MIRROR_PROFILES 移植（数据源目录与镜像种子）。"""

from __future__ import annotations

from typing import Any

# UI 分组（对齐 mdcs PROVIDER_UI_GROUPS）
SOURCE_GROUPS: list[dict[str, str]] = [
    {"id": "av", "label": "有码 AV"},
    {"id": "uncensored", "label": "无码 AV"},
    {"id": "fc2", "label": "FC2"},
    {"id": "chinese", "label": "国产"},
    {"id": "western", "label": "欧美"},
    {"id": "general", "label": "综合"},
]

ACCESS_LABEL: dict[str, str] = {
    "proxy_adaptive": "自适应",
    "proxy_flare": "过盾",
    "proxy": "代理",
    "direct": "直连",
}

# 对齐 .refs/mdcs/.../sourceMaster.ts SOURCE_CATALOG
SOURCE_CATALOG: list[dict[str, Any]] = [
    # —— 有码 AV ——
    {
        "id": "javbus",
        "label": "JavBus",
        "group": "av",
        "defaultUrl": "https://www.javbus.com",
        "probePath": "/",
        "access": "proxy_adaptive",
        "defaultCookie": "existmag=all; age=verified; dv=1",
        "implemented": True,
        "notes": "有码/无码列表与详情 · 需年龄 Cookie",
    },
    {
        "id": "dmm",
        "label": "DMM",
        "group": "av",
        "defaultUrl": "https://www.dmm.co.jp",
        "probePath": "/",
        "access": "proxy_adaptive",
        "defaultCookie": "age_check_done=1; ckcy=1; cklg=ja; is_overseas=0",
        "implemented": True,
    },
    {
        "id": "libredmm",
        "label": "LibreDMM",
        "group": "av",
        "defaultUrl": "https://www.libredmm.com",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
    },
    {
        "id": "airav",
        "label": "AirAV",
        "group": "av",
        "defaultUrl": "https://www.airav.wiki",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
        "notes": "wiki 入口 · 优先委托 airav_io",
    },
    {
        "id": "airav_io",
        "label": "AirAV.io",
        "group": "av",
        "defaultUrl": "https://airav.io/cn",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
    },
    {
        "id": "avmoo",
        "label": "Avmoo",
        "group": "av",
        "defaultUrl": "https://avmoo.shop",
        "probePath": "/cn",
        "access": "proxy_flare",
        "implemented": True,
        "notes": "AIO 家族 · 详情须 Flare 等 SPA 渲染",
    },
    {
        "id": "jav321",
        "label": "Jav321",
        "group": "av",
        "defaultUrl": "https://www.jav321.com",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
    },
    {
        "id": "javlibrary",
        "label": "JavLibrary",
        "group": "av",
        "defaultUrl": "https://www.javlibrary.com/tw/main.php",
        "probePath": "/tw/main.php",
        "access": "proxy_adaptive",
        "implemented": True,
        "notes": "仅日本有码 · 默认 tw 繁体站 · adaptive（镜像须 Flare）",
    },
    {
        "id": "avbase",
        "label": "AVBase",
        "group": "av",
        "defaultUrl": "https://www.avbase.net",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
    },
    {
        "id": "mgstage",
        "label": "MGStage",
        "group": "av",
        "defaultUrl": "https://www.mgstage.com",
        "probePath": "/",
        "access": "proxy_adaptive",
        "defaultCookie": "adc=1",
        "implemented": True,
    },
    {
        "id": "freejavbt",
        "label": "FreeJavBT",
        "group": "av",
        "defaultUrl": "https://www.freejavbt.com",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
    },
    {
        "id": "sevenmmtv",
        "label": "7MMTV",
        "group": "av",
        "defaultUrl": "https://7mmtv.sx/zh",
        "probePath": "/zh/",
        "access": "proxy_adaptive",
        "implemented": True,
        "aliasOf": "7mmtv",
    },
    {
        "id": "iqqtv",
        "label": "iQQTV",
        "group": "av",
        "defaultUrl": "https://iqq5.xyz/cn",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
    },
    {
        "id": "avsex",
        "label": "AVSex",
        "group": "av",
        "defaultUrl": "https://avsex.cc",
        "probePath": "/tw/search?query=sone-001",
        "access": "proxy_flare",
        "implemented": True,
        "notes": "仅中文元数据；封面/剧照不做（CDN 不稳定）",
    },
    {
        "id": "r18dev",
        "label": "R18.dev",
        "group": "av",
        "defaultUrl": "https://r18.dev",
        "probePath": "/videos/vod/movies/detail/-/dvd_id=sone00001/json",
        "access": "proxy_adaptive",
        "implemented": True,
        "notes": "JSON API · 番号补零 · 免 CF",
    },
    {
        "id": "avwikidb",
        "label": "AVWikiDB",
        "group": "av",
        "defaultUrl": "https://avwikidb.com",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
        "notes": "FANZA 索引 · 厂牌/品番映射强 · 自适应（curl 优先）",
    },
    # —— 综合 ——
    {
        "id": "javday",
        "label": "JavDay",
        "group": "general",
        "defaultUrl": "https://javday.app",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
        "notes": "繁中聚合 · 日/无/国产 · URL 去横杠",
    },
    {
        "id": "miss_av",
        "label": "MissAV",
        "group": "general",
        "defaultUrl": "https://missav123.com",
        "probePath": "/cn/sone-001",
        "access": "proxy_adaptive",
        "implemented": True,
        "notes": "播放聚合 · 日/无/国产 · 自适应",
        "aliasOf": "missav",
    },
    {
        "id": "njav",
        "label": "NJAV",
        "group": "general",
        "defaultUrl": "https://123av.com/ja",
        "probePath": "/v/sone-001",
        "access": "proxy_adaptive",
        "implemented": True,
        "notes": "123AV（原 njav.tv）· 自适应",
    },
    {
        "id": "lulubar",
        "label": "LuluBar",
        "group": "general",
        "defaultUrl": "https://lulubar.co",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
        "notes": "强 CF；自适应 curl→Flare；封面 CDN 常须 Referer",
    },
    # —— 无码 ——
    {
        "id": "avsox",
        "label": "AvSox",
        "group": "uncensored",
        "defaultUrl": "https://avsox.click",
        "probePath": "/cn",
        "access": "proxy_flare",
        "implemented": True,
    },
    {
        "id": "carib",
        "label": "Caribbean",
        "group": "uncensored",
        "defaultUrl": "https://www.caribbeancom.com",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
    },
    # —— FC2 ——
    {
        "id": "fc2",
        "label": "FC2",
        "group": "fc2",
        "defaultUrl": "https://adult.contents.fc2.com",
        "probePath": "/",
        "access": "proxy_adaptive",
        "defaultCookie": "adult_check=1",
        "implemented": True,
    },
    {
        "id": "fd2ppv",
        "label": "FC2-PPV",
        "group": "fc2",
        "defaultUrl": "https://fd2ppv.cc",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
    },
    # —— 国产 ——
    {
        "id": "madou",
        "label": "Madou",
        "group": "chinese",
        "defaultUrl": "https://madou.club",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
    },
    {
        "id": "madouqu",
        "label": "Madouqu",
        "group": "chinese",
        "defaultUrl": "https://madouqu.com",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
    },
    {
        "id": "xiao_huang_shu",
        "label": "小黄书",
        "group": "chinese",
        "defaultUrl": "https://xchina.co",
        "probePath": "/search.html",
        "access": "proxy_adaptive",
        "implemented": True,
        "notes": "全局代理易 403；详情须 Referer",
    },
    {
        "id": "hscangku",
        "label": "黄色仓库",
        "group": "chinese",
        "defaultUrl": "http://hsck.net",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
    },
    # —— 欧美 ——
    {
        "id": "theporndb",
        "label": "ThePornDB",
        "group": "western",
        "defaultUrl": "https://theporndb.net",
        "probePath": "/",
        "access": "proxy_adaptive",
        "implemented": True,
        "needsApiKey": True,
        "notes": "REST API · 须填 API Key",
    },
    {
        "id": "avheat",
        "label": "AVHeat",
        "group": "western",
        "defaultUrl": "https://avheat.shop",
        "probePath": "/cn",
        "access": "proxy_flare",
        "implemented": True,
        "notes": "AIO 家族 · 详情须 Flare",
    },
]

# 对齐 mdcs SITE_MIRROR_PROFILES.seeds + iqqtv ENTRY_SEEDS
MIRROR_SEEDS: dict[str, list[str]] = {
    "javbus": [
        "https://www.javbus.com",
        "https://www.seejav.me",
        "https://seejav.me",
    ],
    "miss_av": [
        "https://missav123.com",
        "https://www.missav123.com",
        "https://missav.ws",
        "https://missav.live",
        "https://missav.ai",
        "https://missav.li",
    ],
    "njav": [
        "https://123av.com/ja",
        "https://www.123av.com/ja",
        "https://njav.tv/ja",
        "https://www.njav.tv/ja",
    ],
    "sevenmmtv": [
        "https://7mmtv.sx",
        "https://www.7mmtv.sx",
        "https://7mmtv.com",
        "https://7mm.tv",
    ],
    "avmoo": ["https://avmoo.shop", "https://www.avmoo.shop"],
    "avsox": ["https://avsox.click", "https://www.avsox.click"],
    "javlibrary": [
        "https://www.f101w.com",
        "https://www.c97k.com",
        "https://www.b47w.com",
        "https://www.javlibrary.com",
    ],
    "avbase": ["https://www.avbase.net", "https://avbase.net"],
    "fd2ppv": ["https://fd2ppv.cc", "https://www.fd2ppv.cc"],
    "freejavbt": ["https://freejavbt.com", "https://www.freejavbt.com"],
    "madou": ["https://madou.club", "https://www.madou.club"],
    "madouqu": ["https://madouqu.com", "https://www.madouqu.com"],
    "xiao_huang_shu": ["https://xchina.co", "https://www.xchina.co"],
    "jav321": ["https://www.jav321.com", "https://jav321.com"],
    "dmm": ["https://www.dmm.co.jp"],
    "mgstage": ["https://www.mgstage.com"],
    "carib": ["https://www.caribbeancom.com"],
    "fc2": ["https://adult.contents.fc2.com"],
    "libredmm": ["https://www.libredmm.com"],
    "airav": ["https://www.airav.wiki", "https://airav.wiki"],
    "airav_io": ["https://airav.io/cn", "https://airav.io/", "https://www.airav.io/cn"],
    "iqqtv": [
        "https://iqqk4.quest",
        "https://www.iqqk4.quest",
        "https://iqq5.xyz",
        "https://www.iqq5.xyz",
        "https://iqq6.xyz",
    ],
    "javday": ["https://javday.app"],
    "lulubar": ["https://lulubar.co"],
    "avsex": ["https://avsex.cc"],
    "r18dev": ["https://r18.dev"],
    "avwikidb": ["https://avwikidb.com", "https://www.avwikidb.com"],
    "hscangku": ["http://hsck.net"],
    "theporndb": ["https://theporndb.net"],
    "avheat": ["https://avheat.shop"],
}

# 旧 makers id ↔ catalog id
LEGACY_ID_MAP: dict[str, str] = {
    "missav": "miss_av",
    "7mmtv": "sevenmmtv",
    "mmtv": "sevenmmtv",
    "fc2_hub": "fd2ppv",
    "fc2hub": "fd2ppv",
}

# 源基础可信度（0–100）：合并字段时 + 值质量分 选最优
SOURCE_TRUST: dict[str, int] = {
    # 官方 / 准官方
    "dmm": 96,
    "mgstage": 95,
    "r18dev": 93,
    "carib": 95,
    "fc2": 92,
    "theporndb": 90,
    # 元数据强
    "libredmm": 88,
    "javlibrary": 86,
    "javbus": 84,
    "avwikidb": 82,
    "jav321": 78,
    "avbase": 76,
    "avmoo": 74,
    "avsox": 72,
    # 中文聚合（剧情/标题偏置另加）
    "airav_io": 70,
    "airav": 68,
    "iqqtv": 68,
    "avsex": 62,
    # 厂牌/国产
    "madou": 78,
    "madouqu": 72,
    # 综合镜像
    "freejavbt": 62,
    "sevenmmtv": 60,
    "javday": 56,
    "miss_av": 55,
    "njav": 55,
    "fd2ppv": 64,
    "lulubar": 52,
    "xiao_huang_shu": 58,
    "hscangku": 54,
    "avheat": 58,
}

# 字段偏置：每源每字段加成 → field_trust = SOURCE_TRUST + bias
# 合并时：标题/剧情/片商/日期/封面/标签 各取该字段得分最高的源入库
#
# 封面优先级约定（高→低）：
#   官方 CDN（DMM / MGStage / Carib）> R18/LibreDMM > JavBus 等镜像
#   > 综合站；中文聚合站封面常水印/CDN 差，大幅降权
SOURCE_FIELD_BIAS: dict[str, dict[str, int]] = {
    # 官方：片商 / 日期 / 封面最强
    "dmm": {
        "studio": 14,
        "maker": 14,
        "date": 12,
        "year": 10,
        "poster": 32,
        "title": 4,
        "tags": -4,
        "overview": -6,
    },
    "mgstage": {
        "studio": 14,
        "maker": 14,
        "date": 12,
        "year": 10,
        "title": 5,
        "actors": 4,
        "poster": 28,
        "tags": 2,
        "overview": -4,
    },
    "r18dev": {
        "studio": 12,
        "maker": 12,
        "date": 12,
        "year": 10,
        "actors": 10,
        "title": 4,
        "poster": 20,
        "tags": 4,
    },
    "libredmm": {
        "studio": 10,
        "maker": 10,
        "title": 6,
        "date": 8,
        "poster": 18,
        "tags": 2,
    },
    # 女优强；封面中等（常转 DMM 图，但不如官方直链稳）
    "javlibrary": {"actors": 16, "title": 8, "studio": 4, "tags": 6, "poster": 2},
    "javbus": {"actors": 14, "studio": 8, "maker": 8, "title": 6, "tags": 8, "poster": 6},
    "avwikidb": {"studio": 12, "maker": 12, "title": 4, "tags": 4, "poster": 2},
    "jav321": {"actors": 8, "title": 6, "tags": 10, "poster": 2},
    "avbase": {"actors": 6, "title": 4, "tags": 6, "poster": 2},
    "avmoo": {"actors": 4, "tags": 4, "poster": 0},
    "avsox": {"actors": 4, "tags": 4, "poster": 0},
    "carib": {
        "studio": 12,
        "overview": 8,
        "actors": 8,
        "poster": 26,
        "date": 8,
        "tags": 4,
    },
    "fc2": {"title": 10, "overview": 8, "date": 8, "poster": 8, "tags": 2},
    # 中文聚合：剧情/标题/标签强；封面大幅降权
    "airav": {"overview": 32, "title": 28, "tags": 34, "actors": 8, "poster": -24},
    "airav_io": {"overview": 32, "title": 28, "tags": 34, "actors": 8, "poster": -24},
    "iqqtv": {"overview": 28, "title": 24, "tags": 30, "actors": 6, "poster": -20},
    "avsex": {"overview": 28, "title": 22, "tags": 28, "actors": 4, "poster": -30},
    "miss_av": {"title": 14, "tags": 22, "overview": 12, "poster": -8, "actors": 4},
    "sevenmmtv": {"title": 10, "tags": 18, "overview": 8, "poster": -10},
    "freejavbt": {"title": 6, "tags": 14, "poster": -8},
    "njav": {"title": 6, "tags": 8, "poster": -10},
    "javday": {"title": 4, "tags": 6, "poster": -10},
    "theporndb": {"actors": 12, "studio": 10, "title": 8, "date": 8, "tags": 6, "poster": 8},
    "madou": {"title": 10, "overview": 8, "studio": 6, "tags": 8, "poster": 6},
    "madouqu": {"title": 8, "overview": 6, "tags": 6, "poster": 2},
}


# SOURCE_CATALOG 是模块级静态常量（无运行时修改），索引在导入时建一次即可。
# 本函数落在合并/设置热路径上：`field_priority_chain` 排序、`source_trust`、
# `provider_settings`、`effective_display_url`、`mirror_seeds_for` 每源各调一次，
# 原先每次重建整表（~90 项）纯属浪费；批量刮削时是每番号数百次。
# 调用方一律只读（`.get()` / `in`），返回共享表。
_CATALOG_BY_ID: dict[str, dict[str, Any]] = {str(e["id"]): e for e in SOURCE_CATALOG}


def catalog_by_id() -> dict[str, dict[str, Any]]:
    return _CATALOG_BY_ID


def canonicalize_id(source_id: str) -> str:
    sid = str(source_id or "").strip().lower()
    return LEGACY_ID_MAP.get(sid, sid)


def source_trust(source_id: str) -> int:
    sid = canonicalize_id(source_id)
    if sid in SOURCE_TRUST:
        return int(SOURCE_TRUST[sid])
    meta = catalog_by_id().get(sid) or {}
    group = str(meta.get("group") or "")
    # 未表列：按分组给保守默认
    defaults = {
        "av": 60,
        "uncensored": 62,
        "fc2": 60,
        "chinese": 58,
        "western": 60,
        "general": 52,
    }
    return int(defaults.get(group, 55))


def field_trust(source_id: str, field: str) -> int:
    """源可信 + 字段偏置（合并打分基数）。"""
    sid = canonicalize_id(source_id)
    fid = str(field or "").strip()
    base = source_trust(sid)
    bias = int((SOURCE_FIELD_BIAS.get(sid) or {}).get(fid) or 0)
    return base + bias


# 设置页预填 / 策略默认（对齐用户参考配置；短链，合并时仍会接全局补充）
FIELD_PRIORITY_PREFILL: dict[str, list[str]] = {
    "title": ["airav_io", "iqqtv", "javbus"],
    "overview": ["airav_io", "iqqtv"],
    "actors": ["javbus", "airav_io", "iqqtv"],
    "poster": ["dmm", "libredmm", "r18dev", "javbus", "mgstage"],
    "tags": ["javbus", "avbase", "freejavbt"],
}

# 对齐 Amane：显式字段优先级（高→低）。未列出的字段按 field_trust 推导。
# title/overview 中文源前置；poster/studio/date 官方前置。
DEFAULT_FIELD_PRIORITY: dict[str, list[str]] = {
    "title": [
        "airav_io",
        "airav",
        "iqqtv",
        "avsex",
        "miss_av",
        "sevenmmtv",
        "madou",
        "madouqu",
        "libredmm",
        "javlibrary",
        "javbus",
        "mgstage",
        "dmm",
        "r18dev",
        "jav321",
        "avbase",
        "avmoo",
        "freejavbt",
        "njav",
        "theporndb",
    ],
    "overview": [
        "airav_io",
        "airav",
        "iqqtv",
        "avsex",
        "miss_av",
        "sevenmmtv",
        "carib",
        "madou",
        "libredmm",
        "dmm",
        "mgstage",
        "javbus",
        "javlibrary",
        "r18dev",
    ],
    "poster": [
        "dmm",
        "libredmm",
        "r18dev",
        "javbus",
        "mgstage",
        "carib",
        "theporndb",
        "fc2",
        "javlibrary",
        "avmoo",
        "avsox",
    ],
    "studio": [
        "dmm",
        "mgstage",
        "r18dev",
        "avwikidb",
        "libredmm",
        "javbus",
        "carib",
        "theporndb",
        "javlibrary",
    ],
    "maker": [
        "dmm",
        "mgstage",
        "r18dev",
        "avwikidb",
        "libredmm",
        "javbus",
        "theporndb",
    ],
    "date": [
        "dmm",
        "mgstage",
        "r18dev",
        "libredmm",
        "javbus",
        "carib",
        "fc2",
        "theporndb",
    ],
    "year": [
        "dmm",
        "mgstage",
        "r18dev",
        "libredmm",
        "javbus",
        "theporndb",
    ],
    "tags": [
        "javbus",
        "avbase",
        "freejavbt",
        "airav",
        "airav_io",
        "iqqtv",
        "avsex",
        "miss_av",
        "sevenmmtv",
        "jav321",
        "javlibrary",
        "mgstage",
    ],
}

_FIELD_PRIORITY_CACHE: dict[str, list[str]] = {}


def field_priority_chain(field: str, *, override: list[str] | None = None) -> list[str]:
    """返回字段站点优先级链（高→低）。

    override 非空：配置源按填写顺序排最前（如 DMM → MGStage），其余按 trust 接上。
    NFO 合并：配置源有数据即用；都没有才用全局补充。
    """
    fid = str(field or "").strip()
    ids = set(SOURCE_TRUST) | set(SOURCE_FIELD_BIAS) | {
        str(e.get("id") or "") for e in SOURCE_CATALOG if e.get("id")
    }
    ids.discard("")

    def _rest_after(preferred: list[str]) -> list[str]:
        seen = set(preferred)
        return sorted(
            (s for s in ids if s not in seen),
            key=lambda s: field_trust(s, fid),
            reverse=True,
        )

    if override:
        out: list[str] = []
        seen: set[str] = set()
        for raw in override:
            sid = canonicalize_id(str(raw or ""))
            if sid and sid not in seen:
                seen.add(sid)
                out.append(sid)
        return out + _rest_after(out)

    if fid in _FIELD_PRIORITY_CACHE:
        return list(_FIELD_PRIORITY_CACHE[fid])

    preferred = [canonicalize_id(s) for s in (DEFAULT_FIELD_PRIORITY.get(fid) or [])]
    preferred = [s for s in preferred if s]
    ranked = preferred + _rest_after(preferred)
    _FIELD_PRIORITY_CACHE[fid] = ranked
    return list(ranked)


def mirror_seeds_for(source_id: str) -> list[str]:
    sid = canonicalize_id(source_id)
    seeds = list(MIRROR_SEEDS.get(sid) or [])
    meta = catalog_by_id().get(sid)
    if meta and meta.get("defaultUrl"):
        du = str(meta["defaultUrl"]).rstrip("/")
        if du and du not in seeds:
            seeds.insert(0, du)
    return seeds


def list_catalog_public() -> list[dict[str, Any]]:
    out = []
    for e in SOURCE_CATALOG:
        row = dict(e)
        sid = str(e["id"])
        row["accessLabel"] = ACCESS_LABEL.get(str(e.get("access") or ""), "")
        row["seeds"] = mirror_seeds_for(sid)
        row["trust"] = source_trust(sid)
        out.append(row)
    return out
