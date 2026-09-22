"""六区前缀/番号目录：网络校验真相源（不依赖资源仓库）。

运行时：`data/prefix/catalog/catalog.json`
种子：`apps/maps/prefixes/catalog.seed.json`
"""

from __future__ import annotations

import json
import logging
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.db import ROOT, prefix_catalog_dir
from app.core.maps_paths import prefix_catalog_seed
from app.core.region_meta import REGION_META, REGION_ORDER, std_prefix
import app.prefix.maker_names as maker_names

log = logging.getLogger(__name__)

SEED_PATH = prefix_catalog_seed()
CATALOG_VERSION = 1

_lock = threading.RLock()
_cache: dict[str, Any] | None = None
_cache_mtime: float | None = None

# 刮削库「实际有番号」前缀数缓存（按区）
_scrap_prefix_counts_cache: dict[str, int] | None = None
_scrap_prefix_counts_at: float = 0.0
_SCRAP_PREFIX_COUNTS_TTL_SEC = 60.0


def catalog_dir() -> Path:
    return prefix_catalog_dir()


def catalog_path() -> Path:
    return catalog_dir() / "catalog.json"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def empty_catalog() -> dict[str, Any]:
    regions: dict[str, Any] = {}
    for rid in REGION_ORDER:
        meta = REGION_META[rid]
        regions[rid] = {
            "id": rid,
            "label": meta["label"],
            "prefixes": {},
        }
    return {
        "version": CATALOG_VERSION,
        "updated_at": _now(),
        "principle": "network-verified prefixes/codes; not warehouse-derived",
        "regions": regions,
    }


def _normalize_prefix_entry(prefix: str, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.prefix.code_read import (
        CODE_READ_PRESETS,
        VALID_CODE_READ_IDS,
        infer_code_read,
        resolve_code_read,
    )

    p = std_prefix(prefix)
    src = dict(raw or {})
    serials = sorted(
        {
            int(x)
            for x in (src.get("serials") or [])
            if str(x).isdigit() and int(x) > 0
        }
    )
    codes = sorted(
        {
            str(x).strip().upper()
            for x in (src.get("codes") or [])
            if str(x).strip()
        }
    )
    pad = int(src.get("pad") or 3)
    pad = max(1, min(8, pad))
    had_code_read = str(src.get("code_read") or "").strip() in VALID_CODE_READ_IDS
    code_read = (
        str(src.get("code_read") or "").strip()
        if had_code_read
        else infer_code_read(p, src)
    )
    if not had_code_read:
        preset_pad = int((CODE_READ_PRESETS.get(code_read) or {}).get("pad") or 0)
        if preset_pad > 0:
            pad = max(1, min(8, preset_pad))
    code_read_max = src.get("code_read_max")
    code_read_cid = src.get("code_read_cid")
    if code_read_max is not None and str(code_read_max).strip() == "":
        code_read_max = None
    if code_read_cid is not None and str(code_read_cid).strip() == "":
        code_read_cid = None
    latest_code = str(src.get("latest_code") or "").strip().upper() or ""
    hint = int(src.get("serial_max_hint") or 0)
    if not hint and serials:
        hint = serials[-1]
    profile = resolve_code_read(
        p,
        {
            **src,
            "code_read": code_read,
            "pad": pad,
            "code_read_max": code_read_max,
            "code_read_cid": code_read_cid,
        },
    )
    max_serial = profile.get("max_serial")
    if max_serial is not None:
        try:
            cap = int(max_serial)
            if hint > cap:
                hint = cap
        except (TypeError, ValueError):
            pass
    if codes:
        code_count = len(codes)
    else:
        code_count = len(serials) if serials else (1 if latest_code else 0)
    out: dict[str, Any] = {
        "prefix": p,
        "maker": str(src.get("maker") or "").strip(),
        "maker_zh": str(src.get("maker_zh") or "").strip(),
        "maker_ja": str(src.get("maker_ja") or "").strip(),
        "maker_en": str(src.get("maker_en") or "").strip(),
        "label_ja": str(src.get("label_ja") or "").strip(),
        "sources": list(src.get("sources") or []),
        "pad": pad,
        "format": str(src.get("format") or "{prefix}-{num}"),
        "dmm_digit": str(src.get("dmm_digit") or ""),
        "code_read": code_read,
        "serials": serials,
        "codes": codes,
        "serial_min": int(serials[0]) if serials else int(src.get("serial_min") or 0),
        "serial_max": int(serials[-1]) if serials else int(src.get("serial_max") or 0),
        "serial_max_hint": hint,
        "latest_code": latest_code,
        "code_count": code_count,
        "status": str(src.get("status") or "active"),
        "integrity": str(src.get("integrity") or "unknown"),
        "verified_at": str(src.get("verified_at") or ""),
        "notes": str(src.get("notes") or ""),
    }
    if code_read_max is not None:
        try:
            out["code_read_max"] = int(code_read_max)
        except (TypeError, ValueError):
            pass
    if code_read_cid is not None:
        try:
            out["code_read_cid"] = max(0, min(8, int(code_read_cid)))
        except (TypeError, ValueError):
            pass
    return out


def effective_code_count(entry: dict[str, Any] | None) -> int:
    """番号条数：优先 codes（库内真实串），再 serials。"""
    if not entry:
        return 0
    codes = entry.get("codes") or []
    if codes:
        return len(codes)
    serials = entry.get("serials") or []
    if serials:
        return len(serials)
    if str(entry.get("latest_code") or "").strip():
        return 1
    return int(entry.get("code_count") or 0)


def format_code(entry: dict[str, Any], n: int) -> str:
    p = entry.get("prefix") or ""
    pad = int(entry.get("pad") or 3)
    fmt = str(entry.get("format") or "{prefix}-{num}")
    num = str(int(n)).zfill(pad)
    return (
        fmt.replace("{prefix}", p)
        .replace("{num}", num)
        .replace("{n}", num)
    )


def codes_of(entry: dict[str, Any], *, offset: int = 0, limit: int = 0) -> list[str]:
    """本前缀番号列表。优先库内真实 codes；异前缀 latest 忽略。"""
    raw_codes = [
        str(x).strip().upper() for x in (entry.get("codes") or []) if str(x).strip()
    ]
    if raw_codes:
        try:
            from app.search.av import code_sort_key

            raw_codes = sorted(set(raw_codes), key=code_sort_key)
        except Exception:
            raw_codes = sorted(set(raw_codes))
        if limit and limit > 0:
            return raw_codes[offset : offset + limit]
        if offset:
            return raw_codes[offset:]
        return raw_codes

    latest = str(entry.get("latest_code") or "").strip()
    pref = std_prefix(entry.get("prefix") or "")
    if latest:
        latest_pref = std_prefix(latest.split("-", 1)[0])
        if latest_pref and latest_pref != pref:
            latest = ""

    serials = [int(x) for x in (entry.get("serials") or [])]
    if serials:
        if limit and limit > 0:
            serials = serials[offset : offset + limit]
        elif offset:
            serials = serials[offset:]
        return [format_code(entry, n) for n in serials]
    if not latest:
        return []
    if offset > 0:
        return []
    return [latest] if (not limit or limit > 0) else []


def load_seed() -> dict[str, Any]:
    if not SEED_PATH.exists():
        return empty_catalog()
    raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    doc = empty_catalog()
    doc["updated_at"] = str(raw.get("updated_at") or doc["updated_at"])
    for rid, region in (raw.get("regions") or {}).items():
        if rid not in doc["regions"]:
            continue
        prefixes = {}
        for key, ent in (region.get("prefixes") or {}).items():
            pe = _normalize_prefix_entry(key, ent)
            prefixes[pe["prefix"]] = pe
        doc["regions"][rid]["prefixes"] = prefixes
    return doc


def load_catalog(*, force: bool = False) -> dict[str, Any]:
    """读目录；磁盘被外部脚本改写后按 mtime 自动失效内存缓存。"""
    global _cache, _cache_mtime
    with _lock:
        path = catalog_path()
        mtime: float | None = None
        if path.exists():
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = None
        if (
            _cache is not None
            and not force
            and mtime is not None
            and mtime == _cache_mtime
        ):
            return deepcopy(_cache)
        if path.exists():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(doc.get("regions"), dict):
                    raise ValueError("bad catalog")
                _cache = doc
                _cache_mtime = mtime
                return deepcopy(doc)
            except Exception:
                log.exception("prefix catalog load failed; rebuilding from seed")
        doc = load_seed()
        save_catalog(doc)
        return deepcopy(doc)


def save_catalog(doc: dict[str, Any]) -> Path:
    global _cache, _cache_mtime
    with _lock:
        out = deepcopy(doc)
        out["version"] = CATALOG_VERSION
        out["updated_at"] = _now()
        # ensure all regions exist
        base = empty_catalog()
        for rid in REGION_ORDER:
            out.setdefault("regions", {}).setdefault(rid, base["regions"][rid])
        path = catalog_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
        _cache = deepcopy(out)
        try:
            _cache_mtime = path.stat().st_mtime
        except OSError:
            _cache_mtime = None
        try:
            from app.scrap_library.studio_display_names import invalidate_region_prefix_maps

            invalidate_region_prefix_maps()
        except Exception:  # noqa: BLE001
            pass
        return path


def upsert_prefix(region_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        doc = load_catalog()
        if region_id not in doc["regions"]:
            raise KeyError(f"unknown region: {region_id}")
        pe = _normalize_prefix_entry(entry.get("prefix") or "", entry)
        doc["regions"][region_id]["prefixes"][pe["prefix"]] = pe
        save_catalog(doc)
        return pe


def delete_prefix(region_id: str, prefix: str) -> bool:
    with _lock:
        doc = load_catalog()
        key = std_prefix(prefix)
        prefs = doc["regions"].get(region_id, {}).get("prefixes") or {}
        if key not in prefs:
            return False
        del prefs[key]
        save_catalog(doc)
        return True


def rebuild_empty() -> dict[str, Any]:
    """清空运行时表，仅保留六区壳。"""
    doc = empty_catalog()
    save_catalog(doc)
    return doc


def scrap_library_prefix_counts(*, force: bool = False) -> dict[str, int]:
    """刮削库磁盘上「实际有番号夹」的前缀数（按六区 id）。

    六区统一区/前缀/番号；FC2 现行 ``FC2/FC2/FC2-*``（扫描仍认旧 FC2-PPV）。结果短缓存。
    """
    import time

    global _scrap_prefix_counts_cache, _scrap_prefix_counts_at
    now = time.monotonic()
    if (
        not force
        and _scrap_prefix_counts_cache is not None
        and (now - _scrap_prefix_counts_at) < _SCRAP_PREFIX_COUNTS_TTL_SEC
    ):
        return dict(_scrap_prefix_counts_cache)

    out: dict[str, int] = {rid: 0 for rid in REGION_ORDER}
    try:
        from app.scrap_library.embed import resolve_root

        root = resolve_root(None)
    except Exception:  # noqa: BLE001
        root = None
    if root is None or not root.is_dir():
        _scrap_prefix_counts_cache = dict(out)
        _scrap_prefix_counts_at = now
        return dict(out)

    for rid in REGION_ORDER:
        label = str(REGION_META.get(rid, {}).get("label") or rid).strip()
        region_dir = root / label
        if not region_dir.is_dir():
            alt = root / rid
            region_dir = alt if alt.is_dir() else region_dir
        if not region_dir.is_dir():
            continue
        try:
            count = 0
            for pref_dir in region_dir.iterdir():
                if not pref_dir.is_dir() or pref_dir.name.startswith("_"):
                    continue
                name_u = pref_dir.name.strip().upper().replace("_", "-")
                # FC2 前缀夹：FC2 / FC2-PPV / 旧 FC2PPV
                if rid == "fc2" and name_u in {"FC2", "FC2-PPV", "FC2PPV"}:
                    pass  # 正常前缀夹，继续往下数番号
                elif rid == "fc2" and name_u.startswith("FC2") and any(
                    ch.isdigit() for ch in name_u
                ):
                    # 扁平残留 FC2-{num}，不算前缀夹
                    continue
                try:
                    has_code = any(
                        c.is_dir() and not c.name.startswith("_")
                        for c in pref_dir.iterdir()
                    )
                except OSError:
                    has_code = False
                if has_code:
                    count += 1
            # 若仍是纯扁平（无前缀夹），按番号形态估 1~2
            if rid == "fc2" and count == 0:
                from app.core.region_meta import fc2_prefix_from_code

                seen: set[str] = set()
                for code_dir in region_dir.iterdir():
                    if not code_dir.is_dir() or code_dir.name.startswith("_"):
                        continue
                    nu = code_dir.name.strip().upper().replace("_", "-")
                    if nu in {"FC2", "FC2PPV", "FC2-PPV"}:
                        continue
                    if any(ch.isdigit() for ch in code_dir.name):
                        seen.add(fc2_prefix_from_code(code_dir.name))
                count = len(seen)
            out[rid] = count
        except OSError:
            out[rid] = 0

    _scrap_prefix_counts_cache = dict(out)
    _scrap_prefix_counts_at = now
    return dict(out)


def public_summary(doc: dict[str, Any] | None = None) -> dict[str, Any]:
    d = doc or load_catalog()
    regions = []
    for rid in REGION_ORDER:
        reg = d["regions"].get(rid) or {}
        prefs = reg.get("prefixes") or {}
        code_total = sum(effective_code_count(p) for p in prefs.values())
        # 有片 = 目录扫描后实际有番号的前缀，不看刮削库磁盘
        coded = sum(1 for p in prefs.values() if effective_code_count(p) > 0)
        regions.append(
            {
                "id": rid,
                "label": reg.get("label") or REGION_META.get(rid, {}).get("label"),
                "prefix_count": len(prefs),
                "scrap_prefix_count": coded,
                "code_count": code_total,
            }
        )
    return {
        "version": d.get("version"),
        "updated_at": d.get("updated_at"),
        "principle": d.get("principle"),
        "regions": regions,
        "prefix_total": sum(r["prefix_count"] for r in regions),
        "scrap_prefix_total": sum(r["scrap_prefix_count"] for r in regions),
        "code_total": sum(r["code_count"] for r in regions),
    }


def list_prefixes(
    region_id: str,
    *,
    q: str = "",
) -> list[dict[str, Any]]:
    doc = load_catalog()
    reg = doc["regions"].get(region_id)
    if not reg:
        return []
    needle = std_prefix(q)
    out = []
    for pref, ent in sorted((reg.get("prefixes") or {}).items()):
        if needle and needle not in pref and needle not in std_prefix(
            f"{ent.get('maker') or ''} {ent.get('maker_zh') or ''} {ent.get('maker_ja') or ''} {ent.get('maker_en') or ''}"
        ):
            continue
        row = {
            "prefix": ent["prefix"],
            "maker": maker_names.clamp_maker_label(str(ent.get("maker") or "")),
            "maker_zh": ent.get("maker_zh") or "",
            "maker_ja": ent.get("maker_ja") or "",
            "maker_en": ent.get("maker_en") or "",
            "sources": ent.get("sources") or [],
            "code_count": effective_code_count(ent),
            "serial_min": ent.get("serial_min") or 0,
            "serial_max": ent.get("serial_max") or 0,
            "serial_max_hint": int(ent.get("serial_max_hint") or 0),
            "pad": ent.get("pad") or 3,
            "status": ent.get("status") or "",
            "integrity": ent.get("integrity") or "",
            "verified_at": ent.get("verified_at") or "",
        }
        out.append(row)
    return out


def list_makers(region_id: str, *, q: str = "") -> list[dict[str, Any]]:
    """按厂牌聚合前缀（与文件夹归位同一套 catalog 映射）。"""
    from app.scrap_library.studio_display_names import (
        preferred_studio_label,
        resolve_studio_canon_key,
        resolve_studio_display,
        resolve_studio_for_prefix,
    )

    doc = load_catalog()
    reg = doc["regions"].get(region_id)
    if not reg:
        return []
    needle = str(q or "").strip().casefold()
    buckets: dict[str, dict[str, Any]] = {}
    for pref, ent in (reg.get("prefixes") or {}).items():
        p = std_prefix(pref)
        if not p:
            continue
        label = resolve_studio_for_prefix(p, region=region_id)
        if not label:
            raw = str(ent.get("maker") or ent.get("maker_en") or p).strip()
            label = (
                resolve_studio_display(raw)
                or preferred_studio_label(raw)
                or raw
                or p
            )
        canon = resolve_studio_canon_key(label) or label.casefold()
        cur = buckets.get(canon)
        code_n = effective_code_count(ent)
        if not cur:
            buckets[canon] = {
                "maker": label,
                "label": label,
                "canon": canon,
                "prefixes": [p],
                "prefix_count": 1,
                "catalog_code_count": code_n,
                "maker_zh": str(ent.get("maker_zh") or ""),
                "maker_ja": str(ent.get("maker_ja") or ""),
                "maker_en": str(ent.get("maker_en") or ""),
            }
        else:
            cur["prefixes"].append(p)
            cur["prefix_count"] = len(cur["prefixes"])
            cur["catalog_code_count"] = int(cur["catalog_code_count"] or 0) + code_n
            if not cur.get("maker_zh") and ent.get("maker_zh"):
                cur["maker_zh"] = ent["maker_zh"]
            if not cur.get("maker_ja") and ent.get("maker_ja"):
                cur["maker_ja"] = ent["maker_ja"]
            if not cur.get("maker_en") and ent.get("maker_en"):
                cur["maker_en"] = ent["maker_en"]

    out: list[dict[str, Any]] = []
    for row in buckets.values():
        row["prefixes"] = sorted(set(row["prefixes"]))
        row["prefix_count"] = len(row["prefixes"])
        blob = " ".join(
            [
                str(row.get("maker") or ""),
                str(row.get("maker_zh") or ""),
                str(row.get("maker_ja") or ""),
                str(row.get("maker_en") or ""),
                " ".join(row["prefixes"]),
            ]
        ).casefold()
        if needle and needle not in blob:
            continue
        out.append(row)
    out.sort(key=lambda r: (-int(r.get("catalog_code_count") or 0), str(r.get("maker") or "")))
    return out


def get_prefix(region_id: str, prefix: str) -> dict[str, Any] | None:
    doc = load_catalog()
    ent = (doc["regions"].get(region_id) or {}).get("prefixes", {}).get(std_prefix(prefix))
    return deepcopy(ent) if ent else None
