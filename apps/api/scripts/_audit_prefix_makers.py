# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, ".")
from app.core.region_meta import REGION_META, REGION_ORDER
from app.prefix import catalog_store as store

doc = store.load_catalog(force=True)
seed = store.load_seed()

print("=== runtime catalog ===")
total = empty = 0
for rid in REGION_ORDER:
    prefs = doc["regions"][rid].get("prefixes") or {}
    miss = [
        p
        for p, e in sorted(prefs.items())
        if not str((e or {}).get("maker") or "").strip()
    ]
    n = len(prefs)
    total += n
    empty += len(miss)
    label = REGION_META[rid]["label"]
    print(f"{label} ({rid}): prefixes={n} no_maker={len(miss)}")
    for p in miss:
        print(f"  - {p}")

print(f"TOTAL prefixes={total} no_maker={empty}")

print()
print("=== seed ===")
st = se = 0
for rid in REGION_ORDER:
    prefs = (seed.get("regions") or {}).get(rid, {}).get("prefixes") or {}
    miss = [
        p
        for p, e in sorted(prefs.items())
        if not str((e or {}).get("maker") or "").strip()
    ]
    st += len(prefs)
    se += len(miss)
    label = REGION_META[rid]["label"]
    print(f"{label} ({rid}): prefixes={len(prefs)} no_maker={len(miss)}")
    for p in miss:
        print(f"  - {p}")
print(f"SEED prefixes={st} no_maker={se}")

print()
print("=== suspect maker values ===")
suspect = 0
for rid in REGION_ORDER:
    prefs = doc["regions"][rid].get("prefixes") or {}
    for p, e in sorted(prefs.items()):
        m = str((e or {}).get("maker") or "").strip()
        if m in ("不明", "未知", "unknown", "-", "N/A", "n/a", "?", "？"):
            print(f"suspect {rid} {p}: {m!r}")
            suspect += 1
print(f"suspect markers: {suspect}")

# maker present but maker_ja empty — informational
no_ja = 0
for rid in REGION_ORDER:
    prefs = doc["regions"][rid].get("prefixes") or {}
    for p, e in prefs.items():
        if str((e or {}).get("maker") or "").strip() and not str(
            (e or {}).get("maker_ja") or ""
        ).strip():
            no_ja += 1
print(f"has maker but no maker_ja: {no_ja}")
