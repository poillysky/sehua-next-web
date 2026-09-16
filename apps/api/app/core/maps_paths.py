"""Committed map seeds live in ``apps/maps/<category>/``.

Layout::

    apps/maps/
      makers/     makers.json, av-makers.*.json
      prefixes/   prefixes.json, catalog.seed.json, code-*.json
      scrape/     actors / tags / code-titles / variant-fold（唯一完整表）
      regions/    regions.json
      sites/      DMM / R18 / ThePornDB / 色花堂

Runtime overlays (writable) for prefix catalog etc. stay under repo-root ``data/``.
Actors / tags / code-titles are NOT dual-homed under data/scrape_maps.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.db import ROOT, data_dir

MAPS_SEED_DIR = ROOT / "apps" / "maps"

# logical name (callers / load_json_map) → path under apps/maps/
_SEED_REL: dict[str, str] = {
    "makers.json": "makers/makers.json",
    "av-makers.japan.json": "makers/av-makers.japan.json",
    "av-makers.china.json": "makers/av-makers.china.json",
    "av-makers.western.json": "makers/av-makers.western.json",
    "prefixes.json": "prefixes/prefixes.json",
    "prefix-catalog.seed.json": "prefixes/catalog.seed.json",
    "prefix-code-ranges.json": "prefixes/code-ranges.json",
    "prefix-code-shapes.json": "prefixes/code-shapes.json",
    "prefix-code-read.json": "prefixes/code-read.json",
    "regions.json": "regions/regions.json",
    "dmm-series-digit.json": "sites/dmm-series-digit.json",
    "r18-content-id-prefixes.json": "sites/r18-content-id-prefixes.json",
    "western-studio-search-aliases.json": "sites/western-studio-search-aliases.json",
    "sehuatang-forum.json": "sites/sehuatang-forum.json",
    "sehuatang-forum-prefix-map.json": "sites/sehuatang-forum-prefix-map.json",
    "sehuatang-forum-skip-names.json": "sites/sehuatang-forum-skip-names.json",
    "tags.variant-fold.zh-CN.json": "scrape/tags.variant-fold.zh-CN.json",
    "code-titles.json": "scrape/code-titles.json",
}


def maps_seed(name: str) -> Path:
    """Resolve a map seed path.

    Accepts logical names (``makers.json``), relative paths
    (``makers/makers.json``), or scrape filenames (``actors.zh-CN.json``).
    """
    key = str(name or "").replace("\\", "/").lstrip("/")
    if key in _SEED_REL:
        return MAPS_SEED_DIR / _SEED_REL[key]
    if "/" in key:
        return MAPS_SEED_DIR / key
    if key.startswith("actors.") or key.startswith("tags."):
        return MAPS_SEED_DIR / "scrape" / key
    # fallback: flat under maps root (compat)
    return MAPS_SEED_DIR / key


def scrape_maps_seed_dir() -> Path:
    return MAPS_SEED_DIR / "scrape"


def actors_seed(lang: str = "zh-CN") -> Path:
    return maps_seed(f"actors.{lang}.json")


def tags_seed(lang: str = "zh-CN") -> Path:
    return maps_seed(f"tags.{lang}.json")


def prefix_code_ranges_seed() -> Path:
    return maps_seed("prefix-code-ranges.json")


def prefix_catalog_seed() -> Path:
    return maps_seed("prefix-catalog.seed.json")


def av_makers(region: str) -> Path:
    """region: japan | china | western"""
    return maps_seed(f"av-makers.{region}.json")


def av_makers_all() -> tuple[Path, Path, Path]:
    return av_makers("japan"), av_makers("china"), av_makers("western")


def sehuatang_forum_seed() -> Path:
    return maps_seed("sehuatang-forum.json")


def sehuatang_forum_prefix_map_seed() -> Path:
    return maps_seed("sehuatang-forum-prefix-map.json")


def sehuatang_forum_skip_names_seed() -> Path:
    return maps_seed("sehuatang-forum-skip-names.json")


def actors_runtime(lang: str = "zh-CN") -> Path:
    """Compat alias — actors live only in apps/maps/scrape/."""
    return actors_seed(lang)


def tags_runtime(lang: str = "zh-CN") -> Path:
    """Compat alias — tags live only in apps/maps/scrape/."""
    return tags_seed(lang)


def prefix_code_ranges_runtime() -> Path:
    from app.core.db import prefix_code_ranges_cache

    return prefix_code_ranges_cache()


def scrape_maps_runtime_dir() -> Path:
    """Deprecated dual-home; prefer scrape_maps_seed_dir()."""
    return scrape_maps_seed_dir()


def code_titles_seed() -> Path:
    return maps_seed("scrape/code-titles.json")


def code_titles_runtime() -> Path:
    """Compat alias — code-titles live in apps/maps/scrape/."""
    return code_titles_seed()


@lru_cache(maxsize=1)
def load_code_titles() -> dict[str, str]:
    path = code_titles_runtime()
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    return {str(k).strip().upper(): str(v).strip() for k, v in raw.items() if str(k).strip() and str(v).strip()}


def lookup_code_title(code: str) -> str:
    key = str(code or "").strip().upper()
    if not key:
        return ""
    table = load_code_titles()
    if key in table:
        return table[key]
    # 兼容无横杠 / 下划线
    compact = key.replace("_", "-")
    if compact in table:
        return table[compact]
    return ""


def code_actors_seed() -> Path:
    return maps_seed("scrape/code-actors.json")


def code_actors_runtime() -> Path:
    """Compat alias — code-actors live in apps/maps/scrape/."""
    return code_actors_seed()


@lru_cache(maxsize=1)
def load_code_actors() -> dict[str, tuple[str, ...]]:
    """番号 → 女优名单（原始日文名，展示前走演员映射链）。"""
    path = code_actors_runtime()
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for k, v in raw.items():
        key = str(k).strip().upper()
        names = tuple(
            str(n).strip() for n in (v if isinstance(v, list) else []) if str(n or "").strip()
        )
        if key and names:
            out[key] = names
    return out


def lookup_code_actors(code: str) -> tuple[str, ...]:
    key = str(code or "").strip().upper()
    if not key:
        return ()
    table = load_code_actors()
    if key in table:
        return table[key]
    compact = key.replace("_", "-")
    return table.get(compact, ())


@lru_cache(maxsize=64)
def load_json_map(name: str) -> Any:
    """Load a JSON document from ``apps/maps`` (cached)."""
    path = maps_seed(name)
    if not path.is_file():
        raise FileNotFoundError(f"missing map seed: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_str_map(name: str) -> dict[str, str]:
    raw = load_json_map(name)
    if not isinstance(raw, dict):
        raise TypeError(f"{name}: expected object, got {type(raw).__name__}")
    return {str(k): "" if v is None else str(v) for k, v in raw.items()}


def load_trip_map(name: str) -> dict[str, tuple[str, str, str]]:
    """str → (zh, ja, en) from JSON arrays (legacy flat files)."""
    raw = load_json_map(name)
    if not isinstance(raw, dict):
        raise TypeError(f"{name}: expected object, got {type(raw).__name__}")
    return _trip_from_flat(raw)


def _trip_from_flat(raw: dict[str, Any]) -> dict[str, tuple[str, str, str]]:
    out: dict[str, tuple[str, str, str]] = {}
    for k, v in raw.items():
        if isinstance(v, (list, tuple)):
            zh = str(v[0]) if len(v) > 0 else ""
            ja = str(v[1]) if len(v) > 1 else ""
            en = str(v[2]) if len(v) > 2 else ""
        elif isinstance(v, dict):
            trip = v.get("i18n")
            if isinstance(trip, (list, tuple)):
                zh = str(trip[0]) if len(trip) > 0 else ""
                ja = str(trip[1]) if len(trip) > 1 else ""
                en = str(trip[2]) if len(trip) > 2 else ""
            else:
                zh = str(v.get("zh") or "")
                ja = str(v.get("ja") or "")
                en = str(v.get("en") or "")
        else:
            zh, ja, en = str(v), "", ""
        out[str(k)] = (zh, ja, en)
    return out


def _trip_from_entry(entry: dict[str, Any] | None) -> tuple[str, str, str] | None:
    if not isinstance(entry, dict):
        return None
    trip = entry.get("i18n")
    if not isinstance(trip, (list, tuple)) or not trip:
        return None
    zh = str(trip[0]) if len(trip) > 0 else ""
    ja = str(trip[1]) if len(trip) > 1 else ""
    en = str(trip[2]) if len(trip) > 2 else ""
    return (zh, ja, en)


@lru_cache(maxsize=1)
def makers_doc() -> dict[str, Any]:
    return dict(load_json_map("makers.json") or {})


@lru_cache(maxsize=1)
def prefixes_doc() -> dict[str, Any]:
    return dict(load_json_map("prefixes.json") or {})


@lru_cache(maxsize=1)
def regions_doc() -> dict[str, Any]:
    return dict(load_json_map("regions.json") or {})


def maker_i18n_map() -> dict[str, tuple[str, str, str]]:
    out: dict[str, tuple[str, str, str]] = {}
    for key, entry in dict(makers_doc().get("makers") or {}).items():
        trip = _trip_from_entry(entry if isinstance(entry, dict) else None)
        if trip:
            out[str(key)] = trip
    return out


def maker_intro_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, entry in dict(makers_doc().get("makers") or {}).items():
        if not isinstance(entry, dict):
            continue
        intro = str(entry.get("intro") or "").strip()
        if intro:
            out[str(key)] = intro
    return out


def studio_card_label_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, entry in dict(makers_doc().get("makers") or {}).items():
        if not isinstance(entry, dict):
            continue
        card = str(entry.get("card") or "").strip()
        if card:
            out[str(key)] = card
    return out


def studio_alias_map() -> dict[str, str]:
    raw = makers_doc().get("aliases") or {}
    return {str(k): str(v) for k, v in dict(raw).items()}


def prefix_i18n_map() -> dict[str, tuple[str, str, str]]:
    out: dict[str, tuple[str, str, str]] = {}
    for key, entry in dict(prefixes_doc().get("prefixes") or {}).items():
        trip = _trip_from_entry(entry if isinstance(entry, dict) else None)
        if trip:
            out[str(key)] = trip
    return out


def prefix_intro_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, entry in dict(prefixes_doc().get("prefixes") or {}).items():
        if not isinstance(entry, dict):
            continue
        intro = str(entry.get("intro") or "").strip()
        if intro:
            out[str(key)] = intro
    return out


def prefix_studio_override_map() -> dict[str, str]:
    raw = prefixes_doc().get("studioOverrides") or {}
    return {str(k): str(v) for k, v in dict(raw).items()}


def clear_maps_cache() -> None:
    load_json_map.cache_clear()
    makers_doc.cache_clear()
    prefixes_doc.cache_clear()
    regions_doc.cache_clear()
    load_code_titles.cache_clear()
    load_code_actors.cache_clear()
