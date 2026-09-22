# -*- coding: utf-8 -*-
"""Inventory all prefixes needing intro work (catalog + scrap + weak/stale)."""
from __future__ import annotations
import json, re, sys, importlib
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core import maps_paths
for fn in ("prefixes_doc", "prefix_intro_map", "makers_doc", "maker_intro_map", "maker_i18n_map"):
    f = getattr(maps_paths, fn, None)
    if hasattr(f, "cache_clear"):
        f.cache_clear()
import app.prefix.maker_names as mn
importlib.reload(mn)

from app.core.region_meta import REGION_ORDER, REGION_META
from app.prefix import catalog_store as store
from app.core.db import ROOT as API_ROOT

# --- catalog ---
doc = store.load_catalog(force=True)
catalog: dict[str, tuple[str, str]] = {}  # pref -> (rid, maker)
for rid in REGION_ORDER:
    for pref, e in (doc["regions"][rid].get("prefixes") or {}).items():
        catalog[pref] = (rid, str((e or {}).get("maker") or ""))

# --- scrap library prefixes (from FS) ---
scrap_roots = []
for cand in (
    ROOT / "data" / "scrap-library",
    Path(r"E:/Project/sehua-next-web/data/scrap-library"),
):
    if cand.is_dir():
        scrap_roots.append(cand)
        break

# also try config
try:
    from app.core.config_loader import get_config
    cfg = get_config() or {}
    # common keys
    for k in ("scrap_library_root", "scrap_library", "SCRAP_LIBRARY"):
        v = cfg.get(k) if isinstance(cfg, dict) else None
        if v and Path(v).is_dir():
            scrap_roots = [Path(v)]
            break
except Exception:
    pass

scrap_prefs: dict[str, list[str]] = defaultdict(list)  # pref -> region folder names
REGION_DIRS = {
    "日本有码": "japan_censored",
    "日本无码": "japan_uncensored",
    "日本素人": "japan_amateur",
    "FC2": "fc2",
    "国产无码": "china",
    "欧美无码": "western",
    "日本写真": "japan_censored",  # merged
}

if scrap_roots:
    root = scrap_roots[0]
    print(f"scrap root: {root}")
    for region_dir in root.iterdir():
        if not region_dir.is_dir():
            continue
        rname = region_dir.name
        for pref_dir in region_dir.iterdir():
            if not pref_dir.is_dir():
                continue
            name = pref_dir.name.strip()
            if not name or name.startswith(".") or name.startswith("_"):
                continue
            # skip non-prefix-looking? keep all folder names that look like prefixes
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,20}", name):
                scrap_prefs[name.upper()].append(rname)
else:
    print("NO scrap root found — will use DB facets if available")

# try DB prefix list from embed if scrap empty
if not scrap_prefs:
    try:
        from app.core.db import connect
        con = connect()
        rows = con.execute(
            "SELECT DISTINCT prefix FROM scrap_library_items WHERE prefix IS NOT NULL AND prefix != ''"
        ).fetchall()
        for (p,) in rows:
            scrap_prefs[str(p).strip().upper()].append("(db)")
        print(f"from DB prefixes: {len(scrap_prefs)}")
    except Exception as e:
        print("DB fallback fail", e)

WEAK_RE = re.compile(
    r"公开资料有限|简介待核实|小众独立系|小众企划系|厂牌 .{1,12}（前缀|旗下番号前缀"
)

def intro_of(pref: str) -> str:
    return (mn.PREFIX_INTRO.get(pref) or mn.resolve_maker_intro_for_prefix(pref) or "").strip()

# buckets
A_scrap_not_catalog = []  # scrap exists, not in catalog
B_scrap_no_intro = []     # scrap + catalog or not, no usable intro
C_weak_intro = []         # has intro but weak
D_catalog_no_prefix_intro = []  # in catalog, no PREFIX_INTRO (may have maker fb)

for pref, regions in sorted(scrap_prefs.items()):
    in_cat = pref in catalog
    intro = intro_of(pref)
    specific = (mn.PREFIX_INTRO.get(pref) or "").strip()
    maker = catalog.get(pref, ("", ""))[1]
    row = {
        "pref": pref,
        "scrap_regions": ",".join(sorted(set(regions))),
        "in_catalog": in_cat,
        "maker": maker,
        "intro": intro,
        "specific": specific,
    }
    if not in_cat:
        A_scrap_not_catalog.append(row)
    if not intro or WEAK_RE.search(intro):
        if not intro:
            B_scrap_no_intro.append(row)
        else:
            C_weak_intro.append(row)

for pref, (rid, maker) in catalog.items():
    specific = (mn.PREFIX_INTRO.get(pref) or "").strip()
    intro = intro_of(pref)
    if not specific:
        D_catalog_no_prefix_intro.append({
            "pref": pref, "region": rid, "maker": maker, "intro": intro
        })

# unique todo for user: scrap-visible needing info
# Prefer: scrap folders that need intro (empty or weak), plus catalog weak
todo_map = {}
for row in B_scrap_no_intro + C_weak_intro + A_scrap_not_catalog:
    p = row["pref"]
    if p not in todo_map:
        todo_map[p] = row
    else:
        # merge flags
        pass

# Also catalog-only weak from PREFIX_INTRO
for pref, intro in mn.PREFIX_INTRO.items():
    if WEAK_RE.search(intro):
        if pref not in todo_map:
            rid, maker = catalog.get(pref, ("", ""))
            todo_map[pref] = {
                "pref": pref,
                "scrap_regions": "(catalog-only)" if pref in catalog else "(stale-intro)",
                "in_catalog": pref in catalog,
                "maker": maker,
                "intro": intro,
                "specific": intro,
            }

todo = sorted(todo_map.values(), key=lambda r: (0 if not r.get("intro") else 1, r["pref"]))

print("\n===== SUMMARY =====")
print(f"scrap prefixes: {len(scrap_prefs)}")
print(f"catalog prefixes: {len(catalog)}")
print(f"A scrap但不在catalog: {len(A_scrap_not_catalog)}")
print(f"B scrap无介绍: {len(B_scrap_no_intro)}")
print(f"C scrap弱介绍: {len(C_weak_intro)}")
print(f"D catalog无专属介绍(可有厂牌回退): {len(D_catalog_no_prefix_intro)}")
print(f"待补充 UNIQUE: {len(todo)}")

# split for display
no_intro = [r for r in todo if not r.get("intro") or WEAK_RE.search(r.get("intro") or "")]
only_empty = [r for r in todo if not (r.get("intro") or "").strip()]
only_weak = [r for r in todo if (r.get("intro") or "").strip() and WEAK_RE.search(r["intro"])]
scrap_orphan = [r for r in todo if not r.get("in_catalog")]

print(f"  其中 完全无介绍: {len(only_empty)}")
print(f"  其中 弱/占位介绍: {len(only_weak)}")
print(f"  其中 不在catalog(刮削库残留): {len(scrap_orphan)}")

out = ROOT / "data/debug/prefix-intros-scrap-todo.tsv"
lines = ["#\tprefix\tin_catalog\tscrap_regions\tmaker\tstatus\tcurrent_intro\n"]
print("\n=== 待补充清单（全部）===")
for i, r in enumerate(todo, 1):
    intro = (r.get("intro") or "").strip()
    if not intro:
        status = "无介绍"
    elif WEAK_RE.search(intro):
        status = "弱介绍"
    else:
        status = "OK?"
    if not r.get("in_catalog"):
        status = "库残留+" + status
    maker = r.get("maker") or "-"
    print(f"{i:3d}. {r['pref']}  [{status}] maker={maker[:36]}  scrap={r.get('scrap_regions')}")
    if intro:
        print(f"      现: {intro[:55]}")
    lines.append(
        f"{i}\t{r['pref']}\t{int(bool(r.get('in_catalog')))}\t{r.get('scrap_regions')}\t{maker}\t{status}\t{intro}\n"
    )
out.write_text("".join(lines), encoding="utf-8")
print(f"\nwrote {out}")
