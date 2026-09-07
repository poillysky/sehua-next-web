"""片商目录数据源配置（对齐 mdcs source-catalog / providerSettings）。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from . import settings_store

MAKERS_CATALOG_KEY = "makers.catalog"

# mdcs: existmag=all; age=verified; dv=1 — 封面下载与年龄门需要
DEFAULT_JAVBUS_COOKIE = "existmag=all; age=verified; dv=1"
# mdcs SITE_MIRROR_PROFILES.javbus
DEFAULT_JAVBUS_BASES = (
    "https://www.javbus.com",
    "https://www.seejav.me",
    "https://seejav.me",
)
# mdcs iqqtvMirror ENTRY_SEEDS（root；UI/defaultUrl 拼 /cn）
DEFAULT_IQQTV_SEEDS = (
    "https://iqqk4.quest",
    "https://www.iqqk4.quest",
    "https://iqq5.xyz",
    "https://www.iqq5.xyz",
    "https://iqq6.xyz",
)
DEFAULT_SEVENMM_SEEDS = (
    "https://7mmtv.sx",
    "https://www.7mmtv.sx",
    "https://7mmtv.com",
    "https://7mm.tv",
)
DEFAULT_MADOU_SEEDS = (
    "https://madou.club",
    "https://www.madou.club",
)
# mdcs miss_av（不含已死 missav.com）
DEFAULT_MISSAV_SEEDS = (
    "https://missav123.com",
    "https://www.missav123.com",
    "https://missav.ws",
    "https://missav.live",
    "https://missav.ai",
    "https://missav.li",
)

_JAVBUS_HOST_RE = re.compile(r"(javbus|seejav)", re.I)
DEFAULT_SOURCE_ORDER = ("javbus", "iqqtv", "missav", "7mmtv", "madou")


def _normalize_source_order(raw: Any) -> list[str]:
    allowed = list(DEFAULT_SOURCE_ORDER)
    out: list[str] = []
    if isinstance(raw, str):
        parts = re.split(r"[\n,;]+", raw)
    elif isinstance(raw, (list, tuple)):
        parts = [str(x) for x in raw]
    else:
        parts = []
    for p in parts:
        sid = str(p or "").strip().lower()
        if sid in allowed and sid not in out:
            out.append(sid)
    for sid in allowed:
        if sid not in out:
            out.append(sid)
    return out


def _norm_url(raw: str) -> str:
    s = str(raw or "").strip().rstrip("/")
    if not s:
        return ""
    if not re.match(r"^https?://", s, re.I):
        s = "https://" + s
    try:
        u = urlparse(s)
        if not u.netloc:
            return ""
        return f"{u.scheme or 'https'}://{u.netloc}".rstrip("/")
    except Exception:
        return ""


def normalize_url_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[\n,;]+", raw)
    elif isinstance(raw, (list, tuple)):
        parts = [str(x) for x in raw]
    else:
        parts = [str(raw)]
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        u = _norm_url(p)
        if not u:
            continue
        key = u.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


def is_javbus_host(host: str | None) -> bool:
    return bool(_JAVBUS_HOST_RE.search(host or ""))


def _provider_block(
    raw: Any,
    *,
    default_enabled: bool,
    default_urls: tuple[str, ...],
    url_key: str,
    cookie_default: str | None = None,
) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    enabled = src.get("enabled")
    if enabled is None:
        enabled = default_enabled
    urls = normalize_url_list(
        src.get(url_key) or src.get("bases") or src.get("mirrors") or src.get("seeds")
    )
    # 显式写过 seeds/bases（含空列表）视为已配置，不再灌回默认镜像
    has_url_key = any(k in src for k in (url_key, "bases", "mirrors", "seeds"))
    if not urls and not has_url_key:
        urls = list(default_urls)
    out: dict[str, Any] = {
        "enabled": bool(enabled),
        url_key: urls,
    }
    if cookie_default is not None:
        cookie = str(src.get("cookie") if src.get("cookie") is not None else cookie_default)
        out["cookie"] = cookie.strip()
    active = str(src.get("activeBase") or "").strip().rstrip("/")
    if active:
        # iqqtv 展示常带 /cn
        out["activeBase"] = active
    return out


def resolve_makers_catalog(raw: Any | None = None) -> dict[str, Any]:
    if raw is None:
        raw = settings_store.get_setting(MAKERS_CATALOG_KEY)
    data = raw if isinstance(raw, dict) else {}
    jav = _provider_block(
        data.get("javbus"),
        default_enabled=True,
        default_urls=DEFAULT_JAVBUS_BASES,
        url_key="bases",
        cookie_default=DEFAULT_JAVBUS_COOKIE,
    )
    iqq = _provider_block(
        data.get("iqqtv"),
        default_enabled=True,
        default_urls=DEFAULT_IQQTV_SEEDS,
        url_key="seeds",
    )
    seven = _provider_block(
        data.get("7mmtv") if data.get("7mmtv") is not None else data.get("sevenmmtv"),
        default_enabled=True,
        default_urls=DEFAULT_SEVENMM_SEEDS,
        url_key="seeds",
    )
    madou = _provider_block(
        data.get("madou"),
        default_enabled=True,
        default_urls=DEFAULT_MADOU_SEEDS,
        url_key="seeds",
    )
    missav = _provider_block(
        data.get("missav") if data.get("missav") is not None else data.get("miss_av"),
        default_enabled=True,
        default_urls=DEFAULT_MISSAV_SEEDS,
        url_key="seeds",
    )
    order = _normalize_source_order(
        data.get("sourceOrder") if data.get("sourceOrder") is not None else data.get("source_order")
    )
    by_id = {
        "javbus": {
            "id": "javbus",
            "label": "JavBus",
            "defaultUrl": DEFAULT_JAVBUS_BASES[0],
            "access": "proxy_only",
            "notes": "有码/无码列表与详情 · 需年龄 Cookie · curl/代理不过盾",
            "enabled": jav["enabled"],
            "bases": jav["bases"],
            "cookie": jav["cookie"],
            "activeBase": jav.get("activeBase") or "",
        },
        "iqqtv": {
            "id": "iqqtv",
            "label": "iQQTV",
            "defaultUrl": f"{DEFAULT_IQQTV_SEEDS[0]}/cn",
            "access": "proxy_adaptive",
            "notes": "中文标题补充 · 镜像探测",
            "enabled": iqq["enabled"],
            "seeds": iqq["seeds"],
            "activeBase": iqq.get("activeBase") or "",
        },
        "missav": {
            "id": "missav",
            "label": "MissAV",
            "defaultUrl": f"{DEFAULT_MISSAV_SEEDS[0]}/cn",
            "access": "proxy_adaptive",
            "notes": "有码/无码/FC2/国产 · 代理自适应",
            "enabled": missav["enabled"],
            "seeds": missav["seeds"],
            "activeBase": missav.get("activeBase") or "",
        },
        "7mmtv": {
            "id": "7mmtv",
            "label": "7MMTV",
            "defaultUrl": f"{DEFAULT_SEVENMM_SEEDS[0]}/zh/",
            "access": "proxy_adaptive",
            "notes": "有码/无码/素人/国产/FC2 栏目",
            "enabled": seven["enabled"],
            "seeds": seven["seeds"],
            "activeBase": seven.get("activeBase") or "",
        },
        "madou": {
            "id": "madou",
            "label": "Madou",
            "defaultUrl": DEFAULT_MADOU_SEEDS[0],
            "access": "proxy_adaptive",
            "notes": "国产麻豆栏目",
            "enabled": madou["enabled"],
            "seeds": madou["seeds"],
            "activeBase": madou.get("activeBase") or "",
        },
    }
    return {
        "javbus": jav,
        "iqqtv": iqq,
        "missav": missav,
        "7mmtv": seven,
        "madou": madou,
        "sourceOrder": order,
        "sources": [by_id[sid] for sid in order if sid in by_id],
    }


def makers_catalog_public(raw: Any | None = None) -> dict[str, Any]:
    cfg = resolve_makers_catalog(raw)
    provider_ids = ("javbus", "iqqtv", "missav", "7mmtv", "madou")
    blocks = {sid: dict(cfg[sid]) for sid in provider_ids}
    ready = False
    for sid, block in blocks.items():
        urls = block.get("bases") or block.get("seeds") or []
        if block.get("enabled") and urls:
            ready = True
            break
    live_map: dict[str, dict[str, Any]] = {}
    try:
        from . import site_mirror

        for sid in provider_ids:
            live_map[sid] = site_mirror.active_public(sid)
    except Exception:
        live_map = {sid: {"activeBase": "", "cached": False} for sid in provider_ids}

    active_by_id: dict[str, str] = {}
    for sid, block in blocks.items():
        settings_active = str(block.get("activeBase") or "").strip()
        urls = block.get("bases") or block.get("seeds") or []
        live_active = str((live_map.get(sid) or {}).get("activeBase") or "").strip()
        # 测链清空后 seeds 为空：禁止用旧镜像缓存把「当前」复活
        if settings_active:
            active = settings_active
        elif urls:
            active = live_active
        else:
            active = ""
        block["activeBase"] = active
        active_by_id[sid] = active

    sources = []
    for s in cfg["sources"]:
        row = dict(s)
        sid = str(row.get("id") or "")
        if sid in active_by_id:
            row["activeBase"] = active_by_id[sid]
        sources.append(row)
    return {
        **blocks,
        "sourceOrder": cfg.get("sourceOrder") or list(DEFAULT_SOURCE_ORDER),
        "sources": sources,
        "live": live_map,
        "configured": ready,
        "hubStatus": "已就绪" if ready else "未启用",
    }


def save_makers_catalog(body: dict[str, Any]) -> dict[str, Any]:
    prev = settings_store.get_setting(MAKERS_CATALOG_KEY)
    prev_d = prev if isinstance(prev, dict) else {}

    def merge_provider(key: str, url_key: str, cookie: bool = False) -> dict[str, Any]:
        incoming = body.get(key)
        if not isinstance(incoming, dict):
            incoming = {}
        old = prev_d.get(key) if isinstance(prev_d.get(key), dict) else {}
        merged = dict(old)
        if "enabled" in incoming:
            merged["enabled"] = bool(incoming["enabled"])
        if (
            url_key in incoming
            or "bases" in incoming
            or "mirrors" in incoming
            or "seeds" in incoming
        ):
            # 优先显式字段，避免 seeds=[] 被 or 链吞掉后误用其它键
            if url_key in incoming:
                raw_urls = incoming.get(url_key)
            elif "bases" in incoming:
                raw_urls = incoming.get("bases")
            elif "mirrors" in incoming:
                raw_urls = incoming.get("mirrors")
            else:
                raw_urls = incoming.get("seeds")
            merged[url_key] = normalize_url_list(raw_urls)
        if cookie and "cookie" in incoming:
            merged["cookie"] = str(incoming.get("cookie") or "").strip()
        if "activeBase" in incoming:
            active = str(incoming.get("activeBase") or "").strip().rstrip("/")
            if active:
                merged["activeBase"] = active
            else:
                merged.pop("activeBase", None)
        return merged

    next_val = {
        "javbus": merge_provider("javbus", "bases", cookie=True),
        "iqqtv": merge_provider("iqqtv", "seeds"),
        "missav": merge_provider("missav", "seeds"),
        "7mmtv": merge_provider("7mmtv", "seeds"),
        "madou": merge_provider("madou", "seeds"),
    }
    if "sourceOrder" in body or "source_order" in body:
        next_val["sourceOrder"] = _normalize_source_order(
            body.get("sourceOrder")
            if body.get("sourceOrder") is not None
            else body.get("source_order")
        )
    else:
        prev_order = prev_d.get("sourceOrder")
        if prev_order is None:
            prev_order = prev_d.get("source_order")
        if prev_order is not None:
            next_val["sourceOrder"] = _normalize_source_order(prev_order)

    saved = settings_store.put_setting(MAKERS_CATALOG_KEY, next_val)

    # 同步全局镜像缓存，片商拉页立即用同一地址
    try:
        from . import site_mirror

        jav_ab = str((next_val.get("javbus") or {}).get("activeBase") or "")
        iqq_ab = str((next_val.get("iqqtv") or {}).get("activeBase") or "")
        miss_ab = str((next_val.get("missav") or {}).get("activeBase") or "")
        seven_ab = str((next_val.get("7mmtv") or {}).get("activeBase") or "")
        madou_ab = str((next_val.get("madou") or {}).get("activeBase") or "")
        if jav_ab:
            site_mirror.remember("javbus", jav_ab, discovered_from=jav_ab)
        else:
            site_mirror.invalidate("javbus")
        if iqq_ab:
            root = re.sub(r"/cn/?$", "", iqq_ab, flags=re.I)
            site_mirror.remember("iqqtv", root, discovered_from=root)
        else:
            site_mirror.invalidate("iqqtv")
        if miss_ab:
            root = re.sub(r"/cn/?$", "", miss_ab, flags=re.I)
            site_mirror.remember("missav", root, discovered_from=root)
        else:
            site_mirror.invalidate("missav")
        if seven_ab:
            site_mirror.remember("7mmtv", seven_ab, discovered_from=seven_ab)
        else:
            site_mirror.invalidate("7mmtv")
        if madou_ab:
            site_mirror.remember("madou", madou_ab, discovered_from=madou_ab)
        else:
            site_mirror.invalidate("madou")
    except Exception:
        pass

    public = makers_catalog_public(saved["value"])
    public["updatedAt"] = saved["updated_at"]
    return public


def javbus_bases() -> tuple[str, ...]:
    bases = resolve_makers_catalog()["javbus"]["bases"]
    return tuple(bases) if bases else DEFAULT_JAVBUS_BASES


def javbus_cookie() -> str:
    return str(resolve_makers_catalog()["javbus"].get("cookie") or DEFAULT_JAVBUS_COOKIE)


def javbus_enabled() -> bool:
    return bool(resolve_makers_catalog()["javbus"].get("enabled", True))


def iqqtv_seeds() -> tuple[str, ...]:
    seeds = resolve_makers_catalog()["iqqtv"]["seeds"]
    return tuple(seeds) if seeds else DEFAULT_IQQTV_SEEDS


def iqqtv_enabled() -> bool:
    return bool(resolve_makers_catalog()["iqqtv"].get("enabled", True))


def missav_seeds() -> tuple[str, ...]:
    seeds = resolve_makers_catalog()["missav"]["seeds"]
    return tuple(seeds) if seeds else DEFAULT_MISSAV_SEEDS


def missav_enabled() -> bool:
    return bool(resolve_makers_catalog()["missav"].get("enabled", True))


def sevenmm_seeds() -> tuple[str, ...]:
    seeds = resolve_makers_catalog()["7mmtv"]["seeds"]
    return tuple(seeds) if seeds else DEFAULT_SEVENMM_SEEDS


def sevenmm_enabled() -> bool:
    return bool(resolve_makers_catalog()["7mmtv"].get("enabled", True))


def madou_seeds() -> tuple[str, ...]:
    seeds = resolve_makers_catalog()["madou"]["seeds"]
    return tuple(seeds) if seeds else DEFAULT_MADOU_SEEDS


def madou_enabled() -> bool:
    return bool(resolve_makers_catalog()["madou"].get("enabled", True))


def provider_access(source_id: str | None) -> str:
    """片商源 access：proxy_adaptive | proxy_flare | proxy_only（默认 adaptive）。"""
    sid = str(source_id or "").strip().lower()
    if sid in ("miss_av", "miss-av"):
        sid = "missav"
    if sid in ("sevenmmtv", "7mm"):
        sid = "7mmtv"
    # JavBus 固定不过盾，即使配置里写了 adaptive/flare
    if sid == "javbus":
        return "proxy_only"
    for item in resolve_makers_catalog().get("sources") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip().lower() != sid:
            continue
        a = str(item.get("access") or "").strip().lower()
        if a == "proxy_flare":
            return "proxy_flare"
        if a in {"proxy_only", "proxy_curl", "curl", "direct"}:
            return "proxy_only"
        return "proxy_adaptive"
    return "proxy_adaptive"
