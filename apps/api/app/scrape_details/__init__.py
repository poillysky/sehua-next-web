# -*- coding: utf-8 -*-
"""详情写库统一入口：catalog id → scrape_detail(code)。"""

from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger(__name__)

DetailFn = Callable[..., dict[str, Any]]


def _legacy_javbus(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict[str, Any]:
    from ..makers_catalog_routes import _javbus_detail

    del api_key
    return _javbus_detail(code, base_url=base_url, cookie=cookie)


def _legacy_iqqtv(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict[str, Any]:
    from ..makers_catalog_routes import _iqqtv_detail

    del api_key
    return _iqqtv_detail(code, base_url=base_url, cookie=cookie)


def _legacy_sevenmm(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict[str, Any]:
    import re

    from .. import makers_providers_extra as extra
    from ..makers_catalog_routes import _fetch_html

    del cookie, api_key
    # apply_provider_link_for_fetch 已写入 mirror；base_url 再置顶
    if base_url:
        try:
            from .. import site_mirror

            o = str(base_url).rstrip("/")
            o = re.sub(r"/zh/?$", "", o, flags=re.I) or o
            site_mirror.remember("7mmtv", o, discovered_from=o)
        except Exception:
            pass
    return extra.sevenmm_detail(code, fetch_html=_fetch_html)


def _legacy_missav(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict[str, Any]:
    from .. import makers_providers_extra as extra
    from ..makers_catalog_routes import _fetch_html

    del cookie, api_key
    if base_url:
        try:
            from .. import site_mirror

            o = str(base_url).rstrip("/")
            site_mirror.remember("missav", o, discovered_from=o)
        except Exception:
            pass
    return extra.missav_detail(code, fetch_html=_fetch_html)


def _legacy_madou(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict[str, Any]:
    from .. import makers_providers_extra as extra
    from ..makers_catalog_routes import _fetch_html

    del cookie, api_key
    if base_url:
        try:
            from .. import site_mirror

            o = str(base_url).rstrip("/")
            site_mirror.remember("madou", o, discovered_from=o)
        except Exception:
            pass
    return extra.madou_detail(code, fetch_html=_fetch_html)


def _load_fn(module: str, attr: str = "scrape_detail") -> DetailFn:
    import importlib

    mod = importlib.import_module(f".{module}", __package__)
    fn = getattr(mod, attr)
    return fn  # type: ignore[no-any-return]


# catalog id → (lazy module name | legacy callable)
# module name means apps.api.app.scrape_details.<name>.scrape_detail
_PROVIDER_SPEC: dict[str, str | DetailFn] = {
    "javbus": _legacy_javbus,
    "iqqtv": _legacy_iqqtv,
    "sevenmmtv": _legacy_sevenmm,
    "miss_av": _legacy_missav,
    "madou": _legacy_madou,
    # ported modules (filled as files land)
    "r18dev": "r18dev",
    "libredmm": "libredmm",
    "javday": "javday",
    "carib": "carib",
    "theporndb": "theporndb",
    "njav": "njav",
    "jav321": "jav321",
    "mgstage": "mgstage",
    "dmm": "dmm",
    "javlibrary": "javlibrary",
    "airav_io": "airav_io",
    "airav": "airav",
    "avbase": "avbase",
    "freejavbt": "freejavbt",
    "javdb": "javdb",
    "fc2": "fc2",
    "fd2ppv": "fd2ppv",
    "fc2_hub": "fc2_hub",
    "madouqu": "madouqu",
    "xiao_huang_shu": "xiao_huang_shu",
    "hscangku": "hscangku",
    "avsex": "avsex",
    "avmoo": "avmoo",
    "avsox": "avsox",
    "avheat": "avheat",
    "lulubar": "lulubar",
}


def registered_detail_ids() -> list[str]:
    return list(_PROVIDER_SPEC.keys())


def resolve_detail_fn(source_id: str) -> DetailFn | None:
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
