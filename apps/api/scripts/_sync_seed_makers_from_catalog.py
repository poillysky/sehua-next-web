# -*- coding: utf-8 -*-
"""Sync missing seed makers from runtime catalog."""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.region_meta import REGION_ORDER
from app.prefix import catalog_store as store

doc = store.load_catalog(force=True)
seed = store.load_seed()
synced = 0
for rid in REGION_ORDER:
    cprefs = doc["regions"][rid].get("prefixes") or {}
    sprefs = (seed.get("regions") or {}).get(rid, {}).get("prefixes") or {}
    for pref, cent in cprefs.items():
        sent = sprefs.get(pref)
        if not isinstance(sent, dict) or not isinstance(cent, dict):
            continue
        cm = str(cent.get("maker") or "").strip()
        sm = str(sent.get("maker") or "").strip()
        if not cm or sm:
            continue
        sent = dict(sent)
        sent["prefix"] = pref
        sent["maker"] = cm
        for k in ("maker_ja", "maker_en"):
            if cent.get(k):
                sent[k] = cent[k]
        srcs = set(sent.get("sources") or [])
        srcs.update(cent.get("sources") or [])
        srcs.add("catalog-sync")
        sent["sources"] = sorted(srcs)
        pe = store._normalize_prefix_entry(pref, sent)
        sprefs[pe["prefix"]] = pe
        synced += 1

store.SEED_PATH.write_text(
    json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

# re-audit seed
empty = 0
total = 0
for rid in REGION_ORDER:
    prefs = (seed.get("regions") or {}).get(rid, {}).get("prefixes") or {}
    total += len(prefs)
    empty += sum(
        1
        for e in prefs.values()
        if not str((e or {}).get("maker") or "").strip()
    )
print(f"synced makers into seed: {synced}")
print(f"seed after: prefixes={total} no_maker={empty}")

# seed-only prefixes still empty (exist in seed but not filled in catalog either, or catalog missing)
still = []
for rid in REGION_ORDER:
    cprefs = doc["regions"][rid].get("prefixes") or {}
    sprefs = (seed.get("regions") or {}).get(rid, {}).get("prefixes") or {}
    for p, e in sorted(sprefs.items()):
        if str((e or {}).get("maker") or "").strip():
            continue
        in_cat = p in cprefs
        still.append((rid, p, in_cat, str((cprefs.get(p) or {}).get("maker") or "")))
print(f"seed still empty: {len(still)}")
for rid, p, in_cat, cm in still[:30]:
    print(f"  {rid} {p} in_catalog={in_cat} catalog_maker={cm!r}")
