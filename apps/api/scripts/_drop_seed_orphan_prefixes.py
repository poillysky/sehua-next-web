# -*- coding: utf-8 -*-
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.core.region_meta import REGION_ORDER
from app.prefix import catalog_store as store

ORPHANS = {
    "japan_censored": ["HKG", "IPBD", "NMS", "SAMA", "SAO", "SMD", "YM"],
    "japan_amateur": ["DA"],
}
doc = store.load_catalog(force=True)
seed = store.load_seed()
deleted = []
for rid, prefs_list in ORPHANS.items():
    sprefs = (seed.get("regions") or {}).get(rid, {}).get("prefixes") or {}
    cprefs = doc["regions"][rid].get("prefixes") or {}
    for p in prefs_list:
        if p in cprefs:
            print(f"SKIP {rid}/{p} still in catalog")
            continue
        if p in sprefs:
            del sprefs[p]
            deleted.append(f"{rid}/{p}")
            print(f"DEL seed {rid}/{p}")
store.SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# final audit both
for name, source in [("catalog", store.load_catalog(force=True)), ("seed", store.load_seed())]:
    total = empty = 0
    for rid in REGION_ORDER:
        prefs = (source.get("regions") or {}).get(rid, {}).get("prefixes") or {}
        total += len(prefs)
        empty += sum(1 for e in prefs.values() if not str((e or {}).get("maker") or "").strip())
    print(f"{name}: prefixes={total} no_maker={empty}")
print(f"deleted orphans: {len(deleted)}")
