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
        "id": "javdb",
        "label": "JavDB",
        "group": "av",
        "defaultUrl": "https://javdb.com",
        "probePath": "/",
        "access": "proxy_flare",
        "defaultCooldownSec": 10,
        "defaultCookie": "over18=1; locale=zh",
        "implemented": True,
        "notes": "强 CF；批量易超时 · 换出口或稳 Flare",
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
        "defaultUrl": "https://www.javlibrary.com",
        "probePath": "/cn/vl_searchbyid.php?keyword=SONE-001",
        "access": "proxy_adaptive",
        "implemented": True,
        "notes": "仅日本有码 · 镜像 CN 搜索 · adaptive（镜像须 Flare）",
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
        "access": "proxy_flare",
        "implemented": True,
        "notes": "强 CF；Flare 凭证不可 curl 复用 · 复用 FS 会话",
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
        "id": "fc2_hub",
        "label": "FC2 Hub",
        "group": "fc2",
        "defaultUrl": "https://javten.com",
        "probePath": "/en",
        "access": "proxy_flare",
        "implemented": True,
        "notes": "封面仅 fancybox；旧片 storage 可能 404",
    },
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
    "javdb": [
        "https://javdb.com",
        "https://www.javdb.com",
        "https://javdb368.com",
    ],
    "javlibrary": [
        "https://www.f101w.com",
        "https://www.c97k.com",
        "https://www.b47w.com",
        "https://www.javlibrary.com",
    ],
    "avbase": ["https://www.avbase.net", "https://avbase.net"],
    "fc2_hub": ["https://javten.com", "https://www.javten.com"],
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
}


def catalog_by_id() -> dict[str, dict[str, Any]]:
    return {str(e["id"]): e for e in SOURCE_CATALOG}


def canonicalize_id(source_id: str) -> str:
    sid = str(source_id or "").strip().lower()
    return LEGACY_ID_MAP.get(sid, sid)


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
        row["accessLabel"] = ACCESS_LABEL.get(str(e.get("access") or ""), "")
        row["seeds"] = mirror_seeds_for(str(e["id"]))
        out.append(row)
    return out
