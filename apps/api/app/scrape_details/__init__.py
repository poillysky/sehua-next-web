# -*- coding: utf-8 -*-
"""详情写库统一入口：catalog id → scrape_detail(code)。"""

from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger(__name__)

DetailFn = Callable[..., dict[str, Any]]


def _legacy_javbus(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict[str, Any]:
    from app.makers.catalog_routes import _javbus_detail

    del api_key
    return _javbus_detail(code, base_url=base_url, cookie=cookie)


def _load_fn(module: str, attr: str = "scrape_detail") -> DetailFn:
    import importlib

    mod = importlib.import_module(f".{module}", __package__)
    fn = getattr(mod, attr)
    return fn  # type: ignore[no-any-return]


# catalog id → (lazy module name | legacy callable)
_PROVIDER_SPEC: dict[str, str | DetailFn] = {
    "javbus": _legacy_javbus,  # 仍走 makers 桥；其余已迁 scrape_details.<id>
    "iqqtv": "iqqtv",
    "sevenmmtv": "sevenmmtv",
    "miss_av": "miss_av",
    "madou": "madou",
    "r18dev": "r18dev",
    "libredmm": "libredmm",
    "javday": "javday",
    "carib": "carib",
    "10musume": "tenmusume",
    "heyzo": "heyzo",
    "1pondo": "onespondo",
    "pacopacomama": "pacopacomama",
    "kin8": "kin8",
    "h0930": "h0930",
    "h4610": "h4610",
    "c0930": "c0930",
    "tokyohot": "tokyohot",
    "nyoshin": "nyoshin",
    "heydouga": "heydouga",
    "theporndb": "theporndb",
    "njav": "njav",
    "jav321": "jav321",
    "mgstage": "mgstage",
    "dmm": "dmm",
    "airav_io": "airav_io",
    "avbase": "avbase",
    "freejavbt": "freejavbt",
    "fc2": "fc2",
    "fd2ppv": "fd2ppv",
    "madouqu": "madouqu",
    "xiao_huang_shu": "xiao_huang_shu",
    "hscangku": "hscangku",
    "avmoo": "avmoo",
    "avsox": "avsox",
    "avheat": "avheat",
}


def registered_detail_ids() -> list[str]:
    return list(_PROVIDER_SPEC.keys())


def resolve_detail_fn(source_id: str) -> DetailFn | None:
    try:
        from app.scrape.source_catalog import canonicalize_id

        sid = canonicalize_id(str(source_id or "").strip().lower())
    except Exception:  # noqa: BLE001
        sid = str(source_id or "").strip().lower()
    spec = _PROVIDER_SPEC.get(sid)
    if spec is None:
        return None
    if callable(spec):
        return spec
    try:
        return _load_fn(str(spec))
    except Exception as e:  # noqa: BLE001
        log.warning("scrape_details load %s failed: %s", sid, e)
        return None


def fetch_detail_for_source(
    source_id: str,
    code: str,
    *,
    base_url: str = "",
    cookie: str = "",
    api_key: str = "",
) -> dict[str, Any]:
    """按数据源拉详情；失败抛异常。对齐 MDCS prepareProviderFetch → scrape。"""
    from .common import prepare_provider_site

    try:
        from app.scrape.source_catalog import canonicalize_id

        sid = canonicalize_id(str(source_id or "").strip().lower())
    except Exception:  # noqa: BLE001
        sid = str(source_id or "").strip().lower()
    site = prepare_provider_site(sid, fallback_base=base_url)
    base = str(base_url or site.get("baseUrl") or "").strip()
    ck = str(cookie or site.get("cookie") or "").strip()
    key = str(api_key or site.get("apiKey") or "").strip()

    fn = resolve_detail_fn(sid)
    if not fn:
        raise RuntimeError(f"no detail provider: {source_id}")
    return fn(
        str(code or "").strip(),
        base_url=base,
        cookie=ck,
        api_key=key,
    )
