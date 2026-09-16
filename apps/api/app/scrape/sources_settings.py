"""全站数据源设置（对齐 mdcs providerSettings + siteMirror 缓存叠加）。"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse

import app.scrape.source_catalog as catalog
import app.core.settings_store as settings_store

SCRAPE_PROVIDERS_KEY = "scrape.providers"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _norm_url(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    try:
        u = urlparse(s)
        if not u.netloc:
            return ""
        path = u.path or ""
        if path in ("/", ""):
            return f"{u.scheme}://{u.netloc}"
        return f"{u.scheme}://{u.netloc}{path}".rstrip("/")
    except Exception:
        return ""


# `site_mirrors.json` 里 site_mirror 侧的键 → 目录侧 canonical id
# （`catalog.canonicalize_id()` 把 missav→miss_av、7mmtv→sevenmmtv）
_MIRROR_CANON = {"missav": "miss_av", "7mmtv": "sevenmmtv"}


def _live_cache() -> dict[str, Any]:
    """测通缓存（site-mirrors.json）的**只读**进程内视图。

    ⚠️ 本文件过去也是这个 JSON 的写者（自造 `{sid: {"base":..., "ttlMs":...}}`
    schema 后用 `write_text` 整份覆盖），与 `app.core.site_mirror` 的
    `{"version","mirrors"}` 互相覆盖 —— 两套 schema 互为对方读不懂的格式，
    并发时还会把文件写成「合法 JSON + 尾巴」→ `Extra data: line N column 1`。
    现在文件**只有** `site_mirror` 一个写者（原子替换），这里只做读适配。
    """
    try:
        import app.core.site_mirror as site_mirror

        snap = site_mirror.snapshot_live()
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, Any] = {}
    for sid, row in snap.items():
        out[sid] = row
        alias = _MIRROR_CANON.get(str(sid))
        if alias:
            out.setdefault(alias, row)
    return out


def _remember_live(
    source_id: str,
    base: str,
    *,
    discovered_from: str | None = None,
) -> None:
    """记录测通/跳转发现的生效地址（写入交给 site_mirror，唯一写者）。"""
    sid = catalog.canonicalize_id(source_id)
    base_n = _norm_url(base)
    if not base_n:
        return
    from_n = _norm_url(discovered_from or "") or base_n
    mirror_id = {"miss_av": "missav", "sevenmmtv": "7mmtv"}.get(sid, sid)
    try:
        import app.core.site_mirror as site_mirror

        site_mirror.remember(mirror_id, base_n, discovered_from=from_n)
    except Exception:  # noqa: BLE001
        pass


# ⚠️ 源配置读取是「每番号」路径上的固定税，不是启动一次：
# `enabled_enrich_sources`（被 `_fetch_detail` 每个番号调用）对每个源先来一次
# `provider_settings()`、`effective_display_url()` 里再来一次 → 单次调用读
# 20 遍 app_settings，每次 ~8ms ≈ 170ms。这里存一份进程内快照；
# 唯一写入点 `_persist_provider_row` 写完立即失效。
_providers_cache: dict[str, Any] | None = None


def _invalidate_providers_cache() -> None:
    global _providers_cache
    _providers_cache = None


def load_raw() -> dict[str, Any]:
    """源配置快照。**始终返回副本**——`_persist_provider_row` 会原地写入它。"""
    global _providers_cache
    if _providers_cache is None:
        raw = settings_store.get_setting(SCRAPE_PROVIDERS_KEY)
        _providers_cache = raw if isinstance(raw, dict) else {}
    return dict(_providers_cache)


def _normalize_last_probe(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    msg = str(raw.get("message") or "").strip()
    ms_raw = raw.get("ms")
    ms: int | None
    try:
        ms = int(ms_raw) if ms_raw is not None else None
    except (TypeError, ValueError):
        ms = None
    at_raw = raw.get("at")
    try:
        at = int(at_raw) if at_raw is not None else 0
    except (TypeError, ValueError):
        at = 0
    return {
        "ok": bool(raw.get("ok")),
        "ms": ms,
        "message": msg[:220],
        "at": at,
    }


def provider_settings(source_id: str, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    sid = catalog.canonicalize_id(source_id)
    data = raw if raw is not None else load_raw()
    # accept legacy makers keys
    block = data.get(sid) or data.get(source_id) or {}
    if not isinstance(block, dict):
        block = {}
    meta = catalog.catalog_by_id().get(sid) or {}
    enabled = block.get("enabled")
    if enabled is None:
        enabled = True
    base = _norm_url(str(block.get("baseUrl") or block.get("base") or ""))
    cookie = str(
        block.get("cookie")
        if block.get("cookie") is not None
        else (meta.get("defaultCookie") or "")
    ).strip()
    api_key = str(block.get("apiKey") or "").strip()
    return {
        "enabled": bool(enabled),
        "baseUrl": base,
        "cookie": cookie,
        "apiKey": api_key,
        "activeBase": str(block.get("activeBase") or "").strip(),
        "lastProbe": _normalize_last_probe(block.get("lastProbe")),
    }


def is_provider_enabled(source_id: str, raw: dict[str, Any] | None = None) -> bool:
    """数据源总开关：关则全局/字段优先级配置也不生效。"""
    sid = catalog.canonicalize_id(source_id)
    if not sid:
        return False
    return bool(provider_settings(sid, raw).get("enabled", True))


def _persist_provider_row(sid: str, cfg: dict[str, Any], *, raw: dict[str, Any] | None = None) -> None:
    data = raw if raw is not None else load_raw()
    row: dict[str, Any] = {
        "enabled": bool(cfg.get("enabled", True)),
        "baseUrl": str(cfg.get("baseUrl") or ""),
        "cookie": str(cfg.get("cookie") or ""),
        "apiKey": str(cfg.get("apiKey") or ""),
        "activeBase": str(cfg.get("activeBase") or ""),
    }
    last = _normalize_last_probe(cfg.get("lastProbe"))
    if last:
        row["lastProbe"] = last
    data[sid] = row
    settings_store.put_setting(SCRAPE_PROVIDERS_KEY, data)
    _invalidate_providers_cache()


def store_last_probe(result: dict[str, Any]) -> None:
    """写入最近一次测通结果，供列表展示（失败也会覆盖旧成功态）。"""
    sid = catalog.canonicalize_id(str(result.get("source") or ""))
    if not sid or sid not in catalog.catalog_by_id():
        return
    raw = load_raw()
    cur = dict(provider_settings(sid, raw))
    cur["lastProbe"] = {
        "ok": bool(result.get("ok")),
        "ms": result.get("ms"),
        "message": str(result.get("message") or "")[:220],
        "at": int(time.time() * 1000),
    }
    _persist_provider_row(sid, cur, raw=raw)
    _sync_legacy_makers(sid, cur)


def public_catalog() -> dict[str, Any]:
    raw = load_raw()
    live = _live_cache()
    # migrate hints from makers.catalog for the five legacy sources
    try:
        import app.makers.settings as makers_settings

        makers = makers_settings.resolve_makers_catalog()
        legacy_map = {
            "javbus": "javbus",
            "iqqtv": "iqqtv",
            "missav": "miss_av",
            "7mmtv": "sevenmmtv",
            "madou": "madou",
        }
        for old, new in legacy_map.items():
            if new in raw or old in raw:
                continue
            blk = makers.get(old) or {}
            urls = blk.get("bases") or blk.get("seeds") or []
            preferred = ""
            if blk.get("activeBase"):
                preferred = str(blk["activeBase"])
            elif urls:
                preferred = str(urls[0])
            raw.setdefault(
                new,
                {
                    "enabled": bool(blk.get("enabled", True)),
                    "baseUrl": _norm_url(preferred),
                    "cookie": str(blk.get("cookie") or ""),
                    "activeBase": str(blk.get("activeBase") or ""),
                },
            )
    except Exception:
        pass

    rows = []
    for meta in catalog.list_catalog_public():
        sid = str(meta["id"])
        cfg = provider_settings(sid, raw)
        live_row = live.get(sid) or live.get(catalog.LEGACY_ID_MAP.get(sid, "")) or {}
        live_base = ""
        if isinstance(live_row, dict):
            live_base = _norm_url(str(live_row.get("base") or ""))
        display = cfg.get("activeBase") or live_base or cfg.get("baseUrl") or meta.get("defaultUrl") or ""
        rows.append(
            {
                **meta,
                "enabled": cfg["enabled"],
                "baseUrl": cfg["baseUrl"],
                "cookie": cfg["cookie"],
                "apiKey": cfg["apiKey"] if meta.get("needsApiKey") else "",
                "activeBase": cfg.get("activeBase") or live_base,
                "displayUrl": display,
                "accessLabel": meta.get("accessLabel") or "",
                "lastProbe": cfg.get("lastProbe"),
            }
        )

    groups = []
    for g in catalog.SOURCE_GROUPS:
        gid = g["id"]
        groups.append(
            {
                "id": gid,
                "label": g["label"],
                "sources": [r for r in rows if r.get("group") == gid],
            }
        )
    return {
        "groups": groups,
        "sources": rows,
        "updatedAt": None,
    }


def save_provider(source_id: str, body: dict[str, Any]) -> dict[str, Any]:
    sid = catalog.canonicalize_id(source_id)
    if sid not in catalog.catalog_by_id():
        raise KeyError(f"unknown source: {source_id}")
    raw = load_raw()
    cur = dict(provider_settings(sid, raw))
    if "enabled" in body:
        cur["enabled"] = bool(body.get("enabled"))
    if "baseUrl" in body:
        cur["baseUrl"] = _norm_url(str(body.get("baseUrl") or ""))
    if "cookie" in body:
        cur["cookie"] = str(body.get("cookie") or "").strip()
    if "apiKey" in body:
        cur["apiKey"] = str(body.get("apiKey") or "").strip()
    if "activeBase" in body:
        cur["activeBase"] = _norm_url(str(body.get("activeBase") or ""))
    if "lastProbe" in body:
        cur["lastProbe"] = _normalize_last_probe(body.get("lastProbe"))
    _persist_provider_row(sid, cur, raw=raw)
    _sync_legacy_makers(sid, cur)
    return public_catalog()


def _sync_legacy_makers(sid: str, cfg: dict[str, Any]) -> None:
    """把 5 个旧 makers 源回写到 makers.catalog，供 site_mirror 等沿用。"""
    legacy_id = {
        "javbus": "javbus",
        "iqqtv": "iqqtv",
        "miss_av": "missav",
        "sevenmmtv": "7mmtv",
        "madou": "madou",
    }.get(sid)
    if not legacy_id:
        return
    try:
        import app.makers.settings as makers_settings

        preferred = _norm_url(str(cfg.get("baseUrl") or cfg.get("activeBase") or ""))
        block: dict[str, Any] = {
            "enabled": bool(cfg.get("enabled", True)),
            "activeBase": _norm_url(str(cfg.get("activeBase") or "")),
        }
        if preferred:
            if legacy_id == "javbus":
                block["bases"] = [preferred]
            else:
                block["seeds"] = [preferred]
        if legacy_id == "javbus" and "cookie" in cfg:
            block["cookie"] = str(cfg.get("cookie") or "")
        makers_settings.save_makers_catalog({legacy_id: block})
    except Exception:
        pass


def _homepage_url(sid: str, cfg: dict[str, Any], meta: dict[str, Any]) -> str:
    """只用主站地址：优先用户填写的网站地址，否则目录 defaultUrl。"""
    for raw in (cfg.get("baseUrl"), meta.get("defaultUrl")):
        u = _norm_url(str(raw or ""))
        if not u:
            continue
        if sid == "miss_av" and "missav.com" in u.replace("www.", ""):
            continue
        return u
    return ""


# 刮削库元数据补全：有详情拉页实现的数据源（catalog id → detail key）
# 与 scrape_details.registry 对齐；值为 detailKey（多数与 id 相同）
ENRICH_DETAIL_PROVIDERS: dict[str, str] = {
    "javbus": "javbus",
    "dmm": "dmm",
    "libredmm": "libredmm",
    "airav": "airav",
    "airav_io": "airav_io",
    "avmoo": "avmoo",
    "jav321": "jav321",
    "javlibrary": "javlibrary",
    "avbase": "avbase",
    "mgstage": "mgstage",
    "freejavbt": "freejavbt",
    "sevenmmtv": "7mmtv",
    "iqqtv": "iqqtv",
    "avsex": "avsex",
    "r18dev": "r18dev",
    "avwikidb": "avwikidb",
    "javday": "javday",
    "miss_av": "missav",
    "njav": "njav",
    "lulubar": "lulubar",
    "avsox": "avsox",
    "carib": "carib",
    "fc2": "fc2",
    "fd2ppv": "fd2ppv",
    "madou": "madou",
    "madouqu": "madouqu",
    "xiao_huang_shu": "xiao_huang_shu",
    "hscangku": "hscangku",
    "theporndb": "theporndb",
    "avheat": "avheat",
}

# 七区 → 可用数据源分组（仅开关打开的源会参与级联）
# 有码/写真/素人/无码 → 有码 AV + 无码 AV + 综合
# FC2 → FC2 + 综合；国产 → 国产 + 综合；欧美 → 欧美 + 综合
REGION_ENRICH_GROUPS: dict[str, tuple[str, ...]] = {
    "japan_censored": ("av", "uncensored", "general"),
    "japan_gravure": ("av", "uncensored", "general"),
    "japan_amateur": ("av", "uncensored", "general"),
    "japan_uncensored": ("av", "uncensored", "general"),
    "fc2": ("fc2", "general"),
    "china": ("chinese", "general"),
    "western": ("western", "general"),
}


def resolve_enrich_region_id(region: str | None) -> str | None:
    """刮削库 region / 七区 id / 中文标签 → 稳定七区 id。"""
    from app.core.region_meta import REGION_META, resolve_fs_region

    raw = str(region or "").strip()
    if not raw:
        return None
    rid = resolve_fs_region(raw)
    if rid:
        return rid
    low = raw.casefold()
    aliases = {
        "有码": "japan_censored",
        "日本有码": "japan_censored",
        "写真": "japan_gravure",
        "日本写真": "japan_gravure",
        "素人": "japan_amateur",
        "日本素人": "japan_amateur",
        "无码": "japan_uncensored",
        "日本无码": "japan_uncensored",
        "国产": "china",
        "国产无码": "china",
        "欧美": "western",
        "欧美无码": "western",
        "fc2": "fc2",
    }
    if raw in aliases:
        return aliases[raw]
    if low in aliases:
        return aliases[low]
    for kid, meta in REGION_META.items():
        label = str(meta.get("label") or "")
        if raw == kid or raw == label or low == label.casefold():
            return kid
    return None


def enrich_groups_for_region(region: str | None) -> tuple[str, ...]:
    rid = resolve_enrich_region_id(region)
    if not rid:
        return ()
    try:
        import app.scrap_library.enrich_strategy as strat

        override = strat.region_groups_override(rid)
        if override:
            return override
    except Exception:
        pass
    return REGION_ENRICH_GROUPS.get(rid, ())


def effective_display_url(
    source_id: str,
    *,
    cfg: dict[str, Any] | None = None,
    live: dict[str, Any] | None = None,
) -> str:
    """与数据源列表 displayUrl 一致：activeBase → 测通缓存 → baseUrl → defaultUrl。

    `cfg` / `live` 允许调用方注入，避免热路径重复取配置与重复取缓存：
    `enabled_enrich_sources()` 每个番号对每个源各调一次。
    """
    sid = catalog.canonicalize_id(source_id)
    meta = catalog.catalog_by_id().get(sid) or {}
    if cfg is None:
        cfg = provider_settings(sid)
    if live is None:
        live = _live_cache()
    live_row = live.get(sid) or {}
    if not isinstance(live_row, dict):
        live_row = {}
    # legacy mirror keys
    if not live_row:
        legacy = {"miss_av": "missav", "sevenmmtv": "7mmtv"}.get(sid)
        if legacy:
            live_row = live.get(legacy) if isinstance(live.get(legacy), dict) else {}
    live_base = _norm_url(str(live_row.get("base") or ""))
    for raw in (
        cfg.get("activeBase"),
        live_base,
        cfg.get("baseUrl"),
        meta.get("defaultUrl"),
    ):
        u = _norm_url(str(raw or ""))
        if u:
            return u
    return ""


def enabled_enrich_sources(*, region: str = "") -> list[dict[str, Any]]:
    """刮削池 =（番号类型全局有序源 ∪ 字段优先级源）∩ 已启用 ∩ 有详情。

    - regionSources：主列表，顺序即发车/合并全局序
    - fieldPriority：字段偏好站若不在全局列表，仍追加进池（否则配置了也刮不到）
    - 数据源总开关关闭：不进池
    """
    rid = resolve_enrich_region_id(region)
    # 测通缓存只取一次：`_live_cache()` 现在只是 site_mirror 进程内内存表的读适配
    # （不再读盘），但仍没必要每个源各取一次。
    live = _live_cache()
    # 策略只读一次：`get_strategy()` 要读 app_settings（~7ms），而本函数在
    # `_fetch_detail` 里**每个番号**都被调用，读两遍就是白扔 7ms。
    try:
        import app.scrap_library.enrich_strategy as strat

        strategy_cfg: dict[str, Any] = strat.get_strategy() or {}
    except Exception:  # noqa: BLE001
        strat = None  # type: ignore[assignment]
        strategy_cfg = {}

    ordered_ids: list[str] = []
    if rid and strat is not None:
        try:
            ordered_ids = list(strat.region_sources_for(rid, cfg=strategy_cfg) or [])
        except Exception:
            ordered_ids = []

    # 字段优先级里多出来的站：接到全局列表后，保证能被刮到
    extra_field_ids: list[str] = []
    try:
        fp = strategy_cfg.get("fieldPriority") or {}
        if isinstance(fp, dict):
            seen_ord = {catalog.canonicalize_id(s) for s in ordered_ids}
            seen_extra: set[str] = set()
            for sites in fp.values():
                if not isinstance(sites, list):
                    continue
                for raw in sites:
                    sid = catalog.canonicalize_id(str(raw or ""))
                    if not sid or sid in seen_ord or sid in seen_extra:
                        continue
                    seen_extra.add(sid)
                    extra_field_ids.append(sid)
    except Exception:
        extra_field_ids = []

    def _row(sid: str, meta: dict[str, Any]) -> dict[str, Any] | None:
        detail_key = ENRICH_DETAIL_PROVIDERS.get(sid)
        if not detail_key:
            return None
        cfg = provider_settings(sid)
        if not cfg.get("enabled", True):
            return None
        base = effective_display_url(sid, cfg=cfg, live=live)
        return {
            "id": sid,
            "detailKey": detail_key,
            "group": str(meta.get("group") or ""),
            "label": str(meta.get("label") or sid),
            "baseUrl": base,
            "cookie": str(cfg.get("cookie") or ""),
            "apiKey": str(cfg.get("apiKey") or ""),
            "access": catalog_access(sid),
            "region": rid,
        }

    # 这里只需要 id/group/label 等**目录字段**；`list_catalog_public()` 会为全部源
    # 再构造 seeds/trust/accessLabel 并逐源调 `source_trust`（内含 dict 重建），
    # 属于每番号白付的税 → 直接用静态索引表。
    by_meta = catalog.catalog_by_id()

    if ordered_ids or extra_field_ids:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_sid in list(ordered_ids) + extra_field_ids:
            sid = catalog.canonicalize_id(raw_sid)
            if not sid or sid in seen:
                continue
            meta = by_meta.get(sid) or catalog.catalog_by_id().get(sid) or {}
            if not meta:
                continue
            row = _row(sid, meta)
            if row:
                seen.add(sid)
                out.append(row)
        return out

    # 无有序配置时回落：分组 ∩ 目录顺序
    groups = enrich_groups_for_region(region)
    if region and not groups:
        return []
    allowed = set(groups) if groups else None
    out = []
    for meta in catalog.catalog_by_id().values():
        sid = str(meta.get("id") or "")
        group = str(meta.get("group") or "")
        if allowed is not None and group not in allowed:
            continue
        row = _row(sid, meta)
        if row:
            out.append(row)
    return out


def catalog_access(source_id: str) -> str:
    """与数据源测链相同的 access（来自 SOURCE_CATALOG）。"""
    sid = catalog.canonicalize_id(source_id)
    meta = catalog.catalog_by_id().get(sid) or {}
    a = str(meta.get("access") or "proxy_adaptive").strip().lower()
    if a == "proxy_flare":
        return "proxy_flare"
    if a in {"proxy_only", "proxy_curl", "curl", "direct"}:
        return "proxy_only"
    return "proxy_adaptive"


def resolve_fetch_context(source_id: str) -> dict[str, Any]:
    """写库拉页上下文：与数据源测链/列表链接逻辑对齐。

    - 仅已启用
    - 链接：displayUrl（activeBase → 测通缓存 → baseUrl → defaultUrl）
    - Cookie / API Key：数据源页配置
    - access：目录 access（自适应/过盾/代理）
    """
    sid = catalog.canonicalize_id(source_id)
    meta = catalog.catalog_by_id().get(sid) or {}
    if not meta:
        raise KeyError(f"unknown source: {sid}")
    cfg = provider_settings(sid)
    if not cfg.get("enabled", True):
        raise RuntimeError(f"{sid} 已禁用")
    home = _homepage_url(sid, cfg, meta)
    display = effective_display_url(sid)
    base = display or home
    if not base:
        raise RuntimeError(f"{sid} 无可用链接")
    return {
        "id": sid,
        "label": str(meta.get("label") or sid),
        "group": str(meta.get("group") or ""),
        "baseUrl": base,
        "homeUrl": home,
        "cookie": str(cfg.get("cookie") or ""),
        "apiKey": str(cfg.get("apiKey") or ""),
        "access": catalog_access(sid),
        "enabled": True,
    }


def apply_provider_link_for_fetch(source_id: str) -> dict[str, Any]:
    """把数据源页生效链接写入 makers.catalog + site_mirror，供 detail 拉页。"""
    ctx = resolve_fetch_context(source_id)
    sid = str(ctx["id"])
    base = str(ctx["baseUrl"])
    row = {
        "enabled": True,
        "baseUrl": _norm_url(str(provider_settings(sid).get("baseUrl") or "")) or base,
        "activeBase": base,
        "cookie": ctx["cookie"],
        "apiKey": ctx["apiKey"],
        "lastProbe": provider_settings(sid).get("lastProbe"),
    }
    if not row["baseUrl"]:
        row["baseUrl"] = base
    _sync_legacy_makers(sid, row)

    origin = base
    if sid in ("iqqtv", "miss_av", "njav", "airav_io"):
        origin = re.sub(r"/(cn|ja|en|zh)/?$", "", base, flags=re.I).rstrip("/") or base
    elif sid == "sevenmmtv":
        origin = re.sub(r"/zh/?$", "", base, flags=re.I).rstrip("/") or base
    _remember_live(sid, origin, discovered_from=origin)
    return {
        "id": sid,
        "baseUrl": base,
        "origin": origin,
        "detailKey": ENRICH_DETAIL_PROVIDERS.get(sid, sid),
        "cookie": ctx["cookie"],
        "apiKey": ctx["apiKey"],
        "access": ctx["access"],
        "label": ctx["label"],
        "group": ctx["group"],
    }


# 主页身份线索（host 子串 / 正文或 title 子串，满足其一即可）
_PROBE_MARKERS: dict[str, tuple[str, str]] = {
    "javbus": ("javbus", "javbus"),
    "dmm": ("dmm.co.jp", "dmm"),
    "libredmm": ("libredmm", "libre"),
    "airav": ("airav", "airav"),
    "airav_io": ("airav", "airav"),
    "avmoo": ("avmoo", "avmoo"),
    "jav321": ("jav321", "jav321"),
    "javlibrary": ("javlibrary", "javlibrary"),
    "avbase": ("avbase", "avbase"),
    "mgstage": ("mgstage", "mgstage"),
    "freejavbt": ("freejavbt", "freejav"),
    "sevenmmtv": ("7mm", "7mm"),
    "iqqtv": ("iqq", "iqq"),
    "avsex": ("avsex", "avsex"),
    "r18dev": ("r18.dev", "r18"),
    "avwikidb": ("avwikidb", "avwikidb"),
    "javday": ("javday", "javday"),
    "miss_av": ("missav", "missav"),
    "njav": ("123av", "123av"),
    "lulubar": ("lulubar", "lulu"),
    "avsox": ("avsox", "avsox"),
    "carib": ("caribbean", "caribbean"),
    "fc2": ("fc2.com", "fc2"),
    "fd2ppv": ("fd2ppv", "fd2"),
    "madou": ("madou", "madou"),
    "madouqu": ("madouqu", "madou"),
    "xiao_huang_shu": ("xchina", "xchina"),
    "hscangku": ("hsck", "hsck"),
    "theporndb": ("theporndb", "porndb"),
    "avheat": ("avheat", "avheat"),
}

_BLOCK_HINT = re.compile(
    r"just a moment[\s.]*\.\.\.|cf-browser-verification|"
    r"attention required!|checking your browser before|"
    r"enable javascript and cookies to continue|"
    r"cdn-cgi/challenge-platform/h/[a-z0-9]+/orchestrate|"
    r"cf-challenge-running|challenge-form|"
    r"why have i been blocked",
    re.I,
)


def _page_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()[:100]


def _landed_base(raw_url: str, home: str) -> str:
    landed = _norm_url(raw_url) or home
    try:
        u = urlparse(landed)
        path = (u.path or "").rstrip("/")
        keep_prefix = ""
        for prefix in ("/cn", "/zh", "/ja", "/en", "/tw"):
            if path == prefix or path.startswith(prefix + "/"):
                keep_prefix = prefix
                break
        return f"{u.scheme}://{u.netloc}{keep_prefix}"
    except Exception:
        return home


def _identity_ok(sid: str, final_url: str, html: str) -> tuple[bool, str]:
    title = _page_title(html)
    # 真·盾页标题
    if re.search(r"just a moment|attention required|access denied|cf-?ray", title, re.I):
        return False, "盾/拦截页"
    if sid == "dmm":
        low_u = (final_url or "").lower()
        if "age_check" in low_u or "年齢認証" in title or "年龄认证" in title:
            return False, "仍停在年龄认证页"
        if "age" in title.lower() and "認証" in title:
            return False, "仍停在年龄认证页"
    host_k, html_k = _PROBE_MARKERS.get(sid, (sid, sid))
    host = (urlparse(final_url).hostname or "").lower()
    blob = f"{host}\n{title}\n{(html or '')[:8000]}".lower()
    if host_k.lower() in host or html_k.lower() in blob:
        return True, title or host
    return False, f"未识别站点页 title={title[:40] or '无'}"


def _probe_dmm(
    *,
    home: str,
    cookie: str,
    persist: bool,
    proxy: str,
) -> dict[str, Any]:
    """DMM：用 GraphQL 验证可达，避免把年龄认证页当成成功。"""
    import app.core.outbound_http as outbound_http

    headers = {
        "User-Agent": _UA,
        "Accept": "application/json,text/html,*/*",
        "Content-Type": "application/json",
        "Origin": "https://video.dmm.co.jp",
        "Referer": "https://video.dmm.co.jp/",
    }
    if cookie:
        headers["Cookie"] = cookie
    else:
        headers["Cookie"] = "age_check_done=1; ckcy=1; cklg=ja; is_overseas=0"

    t0 = time.perf_counter()
    try:
        r = outbound_http.curl_request(
            "POST",
            "https://api.video.dmm.co.jp/graphql",
            headers=headers,
            json_body={
                "operationName": "ScrapDigitalContent",
                "variables": {"id": "ssis00123"},
                "query": (
                    "query ScrapDigitalContent($id: ID!){"
                    " ppvContent(id:$id){ id title }"
                    " }"
                ),
            },
            timeout=12.0,
            verify=False,
        )
        ms = int((time.perf_counter() - t0) * 1000)
        hit = None
        code = int(getattr(r, "status_code", 500) or 500)
        if code < 400:
            try:
                hit = ((r.json().get("data") or {}).get("ppvContent"))
            except Exception:
                hit = None
        ok = bool(hit and (hit.get("id") or hit.get("title")))
        if not ok:
            return {
                "ok": False,
                "source": "dmm",
                "ms": ms,
                "message": f"DMM API 不可用 · HTTP {code}",
            }
        landed = _norm_url(home) or "https://www.dmm.co.jp"
        if persist:
            _remember_live("dmm", landed, discovered_from=home)
            save_provider("dmm", {"activeBase": landed})
        title = str(hit.get("title") or hit.get("id") or "DMM")
        via = "curl+代理" if proxy else "curl"
        return {
            "ok": True,
            "source": "dmm",
            "ms": ms,
            "activeBase": landed,
            "seed": home,
            "discoveredFrom": home,
            "title": title,
            "message": f"已识别 · GraphQL · {via} · {ms}ms",
        }
    except Exception as e:  # noqa: BLE001
        err = str(e)[:160]
        low = err.lower()
        if "timed out" in low or "timeout" in low:
            err = (
                "超时：DMM 需代理，请先在「网络」启用出站代理"
                if not proxy
                else "超时：DMM 经代理仍不可达"
            )
        return {"ok": False, "source": "dmm", "message": err}


def probe_provider(source_id: str, *, persist: bool = True) -> dict[str, Any]:
    """测主站主页：走出站代理；校验非盾页且 host/正文像目标站。"""
    out = _probe_provider_impl(source_id, persist=persist)
    try:
        store_last_probe(out)
    except Exception:
        pass
    return out


def _probe_provider_impl(source_id: str, *, persist: bool = True) -> dict[str, Any]:
    """测主站主页：走出站代理；校验非盾页且 host/正文像目标站。"""
    import app.core.outbound_http as outbound_http

    sid = catalog.canonicalize_id(source_id)
    meta = catalog.catalog_by_id().get(sid)
    if not meta:
        return {"ok": False, "message": f"unknown source: {source_id}"}
    cfg = provider_settings(sid)
    if not cfg["enabled"]:
        return {"ok": False, "message": "已禁用", "source": sid}

    home = _homepage_url(sid, cfg, meta)
    if not home:
        return {"ok": False, "source": sid, "message": "无主站地址"}

    proxy = outbound_http.resolve_scrape_proxy_url()
    if sid == "dmm":
        return _probe_dmm(
            home=home,
            cookie=cfg["cookie"],
            persist=persist,
            proxy=proxy,
        )

    cookie = cfg["cookie"]
    url = home if home.endswith("/") else home + "/"
    access = str(meta.get("access") or "proxy_adaptive")
    t0 = time.perf_counter()
    html = ""
    landed_raw = home
    via = "代理" if proxy else "直连"

    def _still_blocked(body: str) -> bool:
        if not body or len(body) < 64:
            return True
        # 以 outbound 盾检测为准；再叠加真·挑战页特征（勿匹配 CF 统计脚本）
        if outbound_http.looks_blocked_html(body) and _BLOCK_HINT.search(body[:6000]):
            return True
        if _BLOCK_HINT.search(body[:6000]):
            return True
        # 仅极短/典型拦截：looks_blocked 且无站点身份线索时才拦
        if outbound_http.looks_blocked_html(body):
            title = _page_title(body)
            if re.search(r"just a moment|attention required|access denied", title, re.I):
                return True
            if len(body) < 400:
                return True
        return False

    try:
        had_clearance = bool(outbound_http.get_cached_clearance(url))
        # 与采集同一套阶梯：优先复用 cf_clearance（二次测通应走 curl 秒过）
        page = outbound_http.fetch_page(
            url,
            cookie=cookie or None,
            access=access,
            timeout=20.0,
            fresh_probe=False,
            source_id=sid,
        )
        html = page.html or ""
        landed_raw = page.final_url or home
        via = (
            "Flare"
            if page.via == "flare"
            else ("curl" if page.via == "curl" else ("代理" if proxy else "直连"))
        )
    except Exception as e:  # noqa: BLE001
        err = str(e)[:160] or "主页无法打开"
        low = err.lower()
        if "timed out" in low or "timeout" in low:
            err = (
                "超时：主站需代理，请先在「网络」启用出站代理"
                if not proxy
                else "超时：主站经代理仍不可达"
            )
        if not outbound_http.resolve_flaresolverr_url():
            return {"ok": False, "source": sid, "message": err}
        try:
            page = outbound_http.fetch_page(
                url,
                cookie=cookie or None,
                access="proxy_flare",
                timeout=35.0,
                fresh_probe=False,
                source_id=sid,
            )
            html = page.html or ""
            landed_raw = page.final_url or home
            via = "Flare"
        except Exception as e2:  # noqa: BLE001
            return {
                "ok": False,
                "source": sid,
                "message": f"过盾失败 · {str(e2)[:100] or err}",
            }

    # 已能识别站点则不必再烧 Flare（避免假阳性毁掉 curl 成功页）
    id_ok_early, _ = _identity_ok(sid, landed_raw or home, html)
    need_flare = _still_blocked(html) and not id_ok_early

    if need_flare and via != "Flare" and outbound_http.resolve_flaresolverr_url():
        try:
            page = outbound_http.fetch_page(
                url,
                cookie=cookie or None,
                access="proxy_flare",
                timeout=45.0,
                fresh_probe=False,
                source_id=sid,
            )
            html = page.html or ""
            landed_raw = page.final_url or landed_raw
            via = "Flare" if page.via == "flare" else via
            if via != "Flare":
                flare = outbound_http.flaresolverr_request_full(
                    url,
                    max_timeout_ms=45000,
                    cookie=cookie or None,
                    no_session_retry=False,
                )
                html = flare.html or ""
                landed_raw = flare.final_url or landed_raw
                via = "Flare"
        except Exception as e:  # noqa: BLE001
            return {
                "ok": False,
                "source": sid,
                "message": f"盾拦截 · 过盾失败 · {str(e)[:80]}",
            }

    ms = int((time.perf_counter() - t0) * 1000)
    if len(html) < 64:
        return {"ok": False, "source": sid, "ms": ms, "message": "主页无内容"}
    if _still_blocked(html):
        if via == "Flare":
            msg = "盾拦截 · Flare 未能解开"
        elif outbound_http.resolve_flaresolverr_url():
            msg = "盾拦截 · 未过盾"
        else:
            msg = "盾拦截 · 未配置 FlareSolverr"
        return {
            "ok": False,
            "source": sid,
            "ms": ms,
            "message": msg,
        }

    landed = _landed_base(landed_raw, home)
    ok_id, id_note = _identity_ok(sid, landed_raw or landed, html)
    if not ok_id:
        return {"ok": False, "source": sid, "ms": ms, "message": id_note}

    if persist:
        _remember_live(sid, landed, discovered_from=home)
        save_provider(sid, {"activeBase": landed})

    if had_clearance and via == "curl":
        via = "curl·凭证"
    elif had_clearance and via == "Flare":
        via = "Flare·凭证"

    same_host = False
    try:
        same_host = urlparse(landed).netloc == urlparse(home).netloc
    except Exception:
        same_host = landed == home
    title = _page_title(html)
    if same_host:
        if title:
            msg = f"已识别 · {via} · {ms}ms · {title[:24]}"
        else:
            msg = f"已识别 · {via} · {ms}ms"
    else:
        msg = f"已识别 · {via} · 发现 {urlparse(landed).netloc} · {ms}ms"
    return {
        "ok": True,
        "source": sid,
        "ms": ms,
        "activeBase": landed,
        "seed": home,
        "discoveredFrom": home,
        "title": title,
        "message": msg,
    }
