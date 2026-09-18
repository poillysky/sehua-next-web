"""Rebuild / expand prefix catalog from network sources."""

from __future__ import annotations

import logging
from typing import Any, Callable

import httpx

import app.prefix.catalog_dmm as dmm
import app.prefix.catalog_store as store
from app.core.region_meta import REGION_ORDER, std_prefix

log = logging.getLogger(__name__)

ProgressCb = Callable[[str], None]


def _progress(cb: ProgressCb | None, msg: str) -> None:
    if cb:
        cb(msg)
    else:
        log.info("%s", msg)


def rebuild_from_seed(*, clear: bool = True) -> dict[str, Any]:
    """用种子重建运行时表（可先清空）。"""
    if clear:
        store.rebuild_empty()
    seed = store.load_seed()
    # merge seed prefixes into catalog
    doc = store.load_catalog(force=True)
    for rid in REGION_ORDER:
        seed_prefs = (seed.get("regions") or {}).get(rid, {}).get("prefixes") or {}
        bucket = doc["regions"][rid]["prefixes"]
        for key, ent in seed_prefs.items():
            pe = store._normalize_prefix_entry(key, ent)
            if pe["prefix"] in bucket and bucket[pe["prefix"]].get("serials"):
                # keep existing harvested serials when not clearing
                if not clear:
                    continue
            bucket[pe["prefix"]] = pe
    store.save_catalog(doc)
    return store.public_summary(doc)


def harvest_japan_censored(
    *,
    prefixes: list[str] | None = None,
    hi_cap: int = 800,
    full_scan_limit: int = 80,
    limit: int = 0,
    mode: str = "quick",
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """对日本有码前缀走 DMM GraphQL，写入真实 serials。

    mode=quick（默认）：每前缀约十几次请求，确认真实样本号 + 上限。
    mode=dense：慢，尽量铺满流水号（容易「卡住」）。
    """
    doc = store.load_catalog(force=True)
    region = doc["regions"]["japan_censored"]
    all_prefs = region["prefixes"]
    keys = [std_prefix(p) for p in prefixes] if prefixes else sorted(all_prefs.keys())
    if limit and limit > 0:
        keys = keys[:limit]

    ok = miss = err = 0
    with httpx.Client(trust_env=False, follow_redirects=True, timeout=5.0) as http:
        # smoke
        smoke = dmm.gql_ppv(http, "ssis00123")
        if not smoke:
            raise RuntimeError("DMM GraphQL unreachable")
        _progress(on_progress, f"dmm smoke ok · {smoke.get('maker_ja')} · mode={mode}")

        for i, pref in enumerate(keys, 1):
            ent = all_prefs.get(pref) or store._normalize_prefix_entry(pref, {"maker": ""})
            _progress(on_progress, f"[{i}/{len(keys)}] {pref} …")
            try:
                digit = str(ent.get("dmm_digit") or "")
                hit_meta = None
                if digit:
                    hit_meta = dmm.probe_serial(http, pref, 1, digit) or dmm.probe_serial(
                        http, pref, 100, digit
                    )
                if not hit_meta:
                    resolved = dmm.resolve_digit(http, pref)
                    if not resolved:
                        ent["status"] = "miss"
                        ent["integrity"] = "dmm_miss"
                        ent["verified_at"] = store._now()
                        all_prefs[pref] = store._normalize_prefix_entry(pref, ent)
                        miss += 1
                        _progress(on_progress, f"[{i}/{len(keys)}] -- {pref}")
                        continue
                    digit, hit_meta = resolved

                serial_max = dmm.find_max_serial(http, pref, digit, hi_cap=hi_cap)
                if mode == "dense":
                    serials, integrity = dmm.harvest_serials_dense(
                        http,
                        pref,
                        digit,
                        serial_max,
                        full_scan_limit=full_scan_limit,
                    )
                else:
                    serials, integrity = dmm.harvest_serials_quick(
                        http, pref, digit, serial_max
                    )
                ent.update(
                    {
                        "dmm_digit": digit,
                        "maker_ja": hit_meta.get("maker_ja") or ent.get("maker_ja") or "",
                        "label_ja": hit_meta.get("label_ja") or ent.get("label_ja") or "",
                        "serials": serials,
                        "serial_max_hint": serial_max,
                        "sources": sorted(
                            set(list(ent.get("sources") or []) + ["dmm"])
                        ),
                        "status": "active" if serials else "empty",
                        "integrity": integrity,
                        "verified_at": store._now(),
                    }
                )
                all_prefs[pref] = store._normalize_prefix_entry(pref, ent)
                # preserve hint outside normalize
                all_prefs[pref]["serial_max_hint"] = serial_max
                ok += 1
                _progress(
                    on_progress,
                    f"[{i}/{len(keys)}] OK {pref} max={serial_max} "
                    f"codes={len(serials)} ({integrity})",
                )
            except Exception as e:  # noqa: BLE001
                err += 1
                ent["status"] = "error"
                ent["notes"] = str(e)[:200]
                ent["verified_at"] = store._now()
                all_prefs[pref] = store._normalize_prefix_entry(pref, ent)
                _progress(on_progress, f"[{i}/{len(keys)}] ERR {pref} {e}")

            # checkpoint every prefix in quick mode
            if mode == "quick" or i % 5 == 0 or i == len(keys):
                store.save_catalog(doc)

    store.save_catalog(doc)
    return {
        "region": "japan_censored",
        "ok": ok,
        "miss": miss,
        "error": err,
        "mode": mode,
        "summary": store.public_summary(doc),
    }


def harvest_dmm_prefix(prefix: str, *, hi_cap: int = 1200, full_scan_limit: int = 200) -> dict[str, Any]:
    """单前缀深度收获（写入 japan_censored）。"""
    return harvest_japan_censored(
        prefixes=[prefix],
        hi_cap=hi_cap,
        full_scan_limit=full_scan_limit,
    )


def _httpx_client() -> httpx.Client:
    from app.core.outbound_http import resolve_scrape_proxy_url

    proxy = resolve_scrape_proxy_url() or None
    kw: dict[str, Any] = {
        "trust_env": False,
        "follow_redirects": True,
        "timeout": 6.0,
    }
    if proxy:
        kw["proxy"] = proxy
        kw["verify"] = False
    return httpx.Client(**kw)


def harvest_latest_via_search(
    region_id: str,
    *,
    prefixes: list[str] | None = None,
    pages: int = 2,
    limit: int = 0,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """综合站搜索前缀 → 抽番号 → 排序取最大（约 1 次请求/前缀）。

    - 有码（含原写真前缀）：MissAV ``/search/{prefix}``
    - 素人：MGStage 搜索（MissAV 对 200GANA 等数字前缀较弱）
    """
    import re
    from urllib.parse import quote

    from app.core.outbound_http import fetch_page

    if region_id not in {
        "japan_censored",
        "japan_amateur",
        "china",
        "western",
    }:
        raise ValueError(f"search-latest 暂不支持 {region_id}")

    doc = store.load_catalog(force=True)
    region = doc["regions"][region_id]
    all_prefs = region["prefixes"]
    keys = [std_prefix(p) for p in prefixes] if prefixes else sorted(all_prefs.keys())
    if limit and limit > 0:
        keys = keys[:limit]

    ok = miss = err = 0
    latest: dict[str, str] = {}
    use_mgs = region_id == "japan_amateur"

    def _nums_from_html(pref: str, html: str) -> list[int]:
        rx = re.compile(
            rf"(?<![A-Z0-9]){re.escape(pref)}-(\d{{2,5}})(?![A-Z0-9])",
            re.I,
        )
        return sorted({int(m.group(1)) for m in rx.finditer(html or "")})

    def _search_missav(pref: str) -> int:
        best = 0
        for page in range(1, max(1, pages) + 1):
            q = quote(pref, safe="")
            url = (
                f"https://missav.ws/cn/search/{q}"
                if page == 1
                else f"https://missav.ws/cn/search/{q}?page={page}"
            )
            try:
                html = fetch_page(url, timeout=18.0).html or ""
            except Exception:
                continue
            nums = _nums_from_html(pref, html)
            if nums:
                best = max(best, nums[-1])
        return best

    def _search_mgs(pref: str) -> int:
        return _mgs_search_max(pref)

    _progress(on_progress, f"search-latest · {region_id} · pages={pages}")

    for i, pref in enumerate(keys, 1):
        ent = all_prefs.get(pref) or store._normalize_prefix_entry(pref, {"maker": ""})
        _progress(on_progress, f"[{i}/{len(keys)}] {pref} …")
        try:
            serial_max = 0
            source = "missav"
            if use_mgs:
                serial_max = _search_mgs(pref)
                source = "mgstage"
                if serial_max <= 0:
                    serial_max = _search_missav(pref)
                    source = "missav"
            else:
                serial_max = _search_missav(pref)
                if serial_max <= 0 and re.match(r"^\d{2,3}[A-Z]", pref):
                    serial_max = _search_mgs(pref)
                    source = "mgstage"

            if serial_max <= 0:
                ent["status"] = "miss"
                ent["integrity"] = "search_miss"
                ent["verified_at"] = store._now()
                all_prefs[pref] = store._normalize_prefix_entry(pref, ent)
                miss += 1
                _progress(on_progress, f"[{i}/{len(keys)}] -- {pref}")
                continue

            code = store.format_code(
                {
                    "prefix": pref,
                    "pad": ent.get("pad") or 3,
                    "format": ent.get("format") or "{prefix}-{num}",
                },
                serial_max,
            )
            ent.update(
                {
                    "serials": [serial_max],
                    "serial_max_hint": serial_max,
                    "latest_code": code,
                    "sources": sorted(set(list(ent.get("sources") or []) + [source])),
                    "status": "active",
                    "integrity": "latest_search",
                    "verified_at": store._now(),
                }
            )
            pe = store._normalize_prefix_entry(pref, ent)
            pe["serial_max_hint"] = serial_max
            pe["latest_code"] = code
            all_prefs[pref] = pe
            latest[pref] = code
            ok += 1
            _progress(on_progress, f"[{i}/{len(keys)}] OK {code} ({source})")
        except Exception as e:  # noqa: BLE001
            err += 1
            ent["status"] = "error"
            ent["notes"] = str(e)[:200]
            ent["verified_at"] = store._now()
            all_prefs[pref] = store._normalize_prefix_entry(pref, ent)
            _progress(on_progress, f"[{i}/{len(keys)}] ERR {pref} {e}")

        if i % 5 == 0 or i == len(keys):
            store.save_catalog(doc)

    store.save_catalog(doc)
    return {
        "region": region_id,
        "ok": ok,
        "miss": miss,
        "error": err,
        "mode": "latest_search",
        "latest": latest,
        "summary": store.public_summary(doc),
    }


def _mgs_product_exists(prefix: str, n: int) -> bool:
    from app.core.outbound_http import fetch_page, is_r18_safe_shell

    code = f"{prefix}-{n}"
    # MGStage pads vary; try unpadded and zfill 4
    candidates = [code]
    if n < 10000:
        candidates.append(f"{prefix}-{str(n).zfill(4)}")
    for c in candidates:
        url = f"https://www.mgstage.com/product/product_detail/{c}/"
        try:
            page = fetch_page(
                url,
                cookie="adc=1",
                referer="https://www.mgstage.com/",
                timeout=16.0,
            )
            html = page.html or ""
        except Exception:
            continue
        if is_r18_safe_shell(html) or len(html) < 4000:
            continue
        if "お探しのページ" in html or "404" in (html[:2000]):
            continue
        title_m = __import__("re").search(r"<title>(.*?)</title>", html, __import__("re").I | __import__("re").S)
        t = (title_m.group(1) if title_m else "")
        if "404" in t or "見つかり" in t:
            continue
        if "product" in html.lower():
            return True
    return False


def _mgs_search_max(prefix: str) -> int:
    import re

    from app.core.outbound_http import fetch_page

    url = f"https://www.mgstage.com/search/cSearch.php?search_word={prefix}"
    try:
        page = fetch_page(url, cookie="adc=1", timeout=22.0)
        html = page.html or ""
    except Exception:
        return 0
    rx = re.compile(
        rf"/product_detail/({re.escape(prefix)}-(\d+))/",
        re.I,
    )
    nums = [int(m.group(2)) for m in rx.finditer(html)]
    return max(nums) if nums else 0


def harvest_latest_mgstage_amateur(
    *,
    prefixes: list[str] | None = None,
    hi_cap: int = 9000,
    limit: int = 0,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """日本素人：MGStage 搜索 + 向上探最大流水号，每前缀留最新一条。"""
    doc = store.load_catalog(force=True)
    region = doc["regions"]["japan_amateur"]
    all_prefs = region["prefixes"]
    keys = [std_prefix(p) for p in prefixes] if prefixes else sorted(all_prefs.keys())
    if limit and limit > 0:
        keys = keys[:limit]

    ok = miss = err = 0
    latest: dict[str, str] = {}

    for i, pref in enumerate(keys, 1):
        ent = all_prefs.get(pref) or store._normalize_prefix_entry(pref, {"maker": ""})
        _progress(on_progress, f"[{i}/{len(keys)}] {pref} …")
        try:
            seed = _mgs_search_max(pref)
            if seed <= 0:
                # try low probes
                for n in (1, 100, 1000):
                    if _mgs_product_exists(pref, n):
                        seed = n
                        break
            if seed <= 0:
                ent["status"] = "miss"
                ent["integrity"] = "mgs_miss"
                ent["verified_at"] = store._now()
                all_prefs[pref] = store._normalize_prefix_entry(pref, ent)
                miss += 1
                _progress(on_progress, f"[{i}/{len(keys)}] -- {pref}")
                continue

            # 搜索首页通常已是新作；再向上轻探几档
            serial_max = seed
            for delta in (1, 2, 5, 10, 20, 50, 100):
                n = seed + delta
                if n > hi_cap:
                    break
                if _mgs_product_exists(pref, n):
                    serial_max = n
            # 若 +100 仍命中，二分到 hi_cap
            if serial_max >= seed + 100 and serial_max < hi_cap:
                left, right = serial_max + 1, min(hi_cap, serial_max * 2)
                while left <= right:
                    mid = (left + right) // 2
                    if _mgs_product_exists(pref, mid):
                        serial_max = mid
                        left = mid + 1
                    else:
                        right = mid - 1
            code = store.format_code(
                {
                    "prefix": pref,
                    "pad": ent.get("pad") or 3,
                    "format": ent.get("format") or "{prefix}-{num}",
                },
                serial_max,
            )
            ent.update(
                {
                    "serials": [serial_max],
                    "serial_max_hint": serial_max,
                    "latest_code": code,
                    "sources": sorted(set(list(ent.get("sources") or []) + ["mgstage"])),
                    "status": "active",
                    "integrity": "latest",
                    "verified_at": store._now(),
                }
            )
            pe = store._normalize_prefix_entry(pref, ent)
            pe["serial_max_hint"] = serial_max
            pe["latest_code"] = code
            all_prefs[pref] = pe
            latest[pref] = code
            ok += 1
            _progress(on_progress, f"[{i}/{len(keys)}] OK {code}")
        except Exception as e:  # noqa: BLE001
            err += 1
            ent["status"] = "error"
            ent["notes"] = str(e)[:200]
            ent["verified_at"] = store._now()
            all_prefs[pref] = store._normalize_prefix_entry(pref, ent)
            _progress(on_progress, f"[{i}/{len(keys)}] ERR {pref} {e}")

        if i % 2 == 0 or i == len(keys):
            store.save_catalog(doc)

    store.save_catalog(doc)
    return {
        "region": "japan_amateur",
        "ok": ok,
        "miss": miss,
        "error": err,
        "mode": "latest",
        "latest": latest,
        "summary": store.public_summary(doc),
    }
