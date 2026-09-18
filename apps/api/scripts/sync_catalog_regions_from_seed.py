# -*- coding: utf-8 -*-
"""Sync runtime catalog region membership from seed; preserve harvested serials/codes."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # sehua-next-web
SEED = ROOT / "apps" / "maps" / "prefixes" / "catalog.seed.json"
RUNTIME = ROOT / "data" / "prefix" / "catalog" / "catalog.json"

REGION_ORDER = [
    "japan_censored",
    "japan_uncensored",
    "japan_amateur",
    "fc2",
    "china",
    "western",
]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def counts(doc: dict) -> dict[str, int]:
    return {
        rid: len((doc.get("regions") or {}).get(rid, {}).get("prefixes") or {})
        for rid in REGION_ORDER
    }


def main() -> None:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    rt = json.loads(RUNTIME.read_text(encoding="utf-8"))

    # Backup
    bak = RUNTIME.with_suffix(".json.bak-before-seed-region-sync")
    bak.write_text(json.dumps(rt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # seed: prefix -> set of regions (MKY can be multi)
    seed_locs: dict[str, set[str]] = {}
    seed_meta: dict[tuple[str, str], dict] = {}
    for rid in REGION_ORDER:
        for pref, ent in ((seed.get("regions") or {}).get(rid, {}).get("prefixes") or {}).items():
            p = str(pref).strip().upper()
            seed_locs.setdefault(p, set()).add(rid)
            seed_meta[(rid, p)] = ent

    # Collect all runtime entries by (region, prefix)
    rt_entries: dict[tuple[str, str], dict] = {}
    for rid in REGION_ORDER:
        for pref, ent in ((rt.get("regions") or {}).get(rid, {}).get("prefixes") or {}).items():
            p = str(pref).strip().upper()
            rt_entries[(rid, p)] = deepcopy(ent)

    # Also index any location of a prefix for harvest merge
    by_pref: dict[str, list[tuple[str, dict]]] = {}
    for (rid, p), ent in rt_entries.items():
        by_pref.setdefault(p, []).append((rid, ent))

    def best_harvest(p: str) -> dict:
        """Pick entry with most serials/codes among current runtime copies."""
        cands = by_pref.get(p) or []
        if not cands:
            return {}
        def score(ent: dict) -> tuple[int, int]:
            return (len(ent.get("serials") or []), len(ent.get("codes") or []))
        return deepcopy(max((e for _, e in cands), key=score))

    new_regions: dict[str, dict] = {}
    for rid in REGION_ORDER:
        label = ((rt.get("regions") or {}).get(rid) or {}).get("label") or (
            (seed.get("regions") or {}).get(rid) or {}
        ).get("label") or rid
        new_regions[rid] = {"id": rid, "label": label, "prefixes": {}}

    moved = []
    added = []
    kept_runtime_only = []

    # 1) Place every seed prefix into its seed region(s), merging harvest from runtime
    for p, rids in seed_locs.items():
        harvest = best_harvest(p)
        for rid in rids:
            base = deepcopy(seed_meta[(rid, p)])
            # overlay harvest fields if present
            for k in (
                "serials",
                "codes",
                "serial_min",
                "serial_max",
                "serial_max_hint",
                "latest_code",
                "code_count",
                "verified_at",
                "integrity",
                "dmm_digit",
            ):
                if harvest.get(k) not in (None, "", [], 0):
                    # prefer non-empty harvest
                    if k in ("serials", "codes") and harvest.get(k):
                        base[k] = harvest[k]
                    elif k not in ("serials", "codes") and harvest.get(k) not in (None, ""):
                        if not base.get(k):
                            base[k] = harvest[k]
            # keep richer serials always from harvest when available
            if harvest.get("serials"):
                base["serials"] = harvest["serials"]
            if harvest.get("codes"):
                base["codes"] = harvest["codes"]
            if harvest.get("latest_code"):
                base["latest_code"] = harvest["latest_code"]
            if harvest.get("serial_max"):
                base["serial_max"] = harvest["serial_max"]
            if harvest.get("serial_min"):
                base["serial_min"] = harvest["serial_min"]
            if harvest.get("serial_max_hint"):
                base["serial_max_hint"] = harvest["serial_max_hint"]
            if harvest.get("code_count"):
                base["code_count"] = harvest["code_count"]
            base["prefix"] = p
            new_regions[rid]["prefixes"][p] = base

            old_rids = {r for r, _ in by_pref.get(p, [])}
            if old_rids and old_rids != {rid} and rid not in old_rids:
                moved.append((p, sorted(old_rids), rid))
            elif not old_rids:
                added.append((p, rid))

    # 2) Keep runtime-only prefixes (not in seed) in their current region
    for (rid, p), ent in rt_entries.items():
        if p in seed_locs:
            continue  # already placed per seed
        new_regions[rid]["prefixes"][p] = ent
        kept_runtime_only.append((p, rid))

    out = {
        "version": rt.get("version") or 1,
        "updated_at": _now(),
        "principle": rt.get("principle")
        or "network-verified prefixes/codes; not warehouse-derived",
        "regions": new_regions,
    }

    before = counts(rt)
    after = counts(out)
    RUNTIME.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("backup:", bak)
    print("before:", before, "total", sum(before.values()))
    print("after: ", after, "total", sum(after.values()))
    print("seed:  ", counts(seed), "total", sum(counts(seed).values()))
    print(f"moved_cross_region: {len(moved)}")
    for item in moved[:30]:
        print(" ", item)
    if len(moved) > 30:
        print(f"  ... +{len(moved)-30}")
    print(f"added_from_seed: {len(added)}")
    print(f"kept_runtime_only: {len(kept_runtime_only)}")
    # spot checks
    for pref in ("OKB", "CWPBD", "NNPJ", "SDNM", "SABA", "LUXU"):
        locs = [rid for rid in REGION_ORDER if pref in new_regions[rid]["prefixes"]]
        print(f"  {pref} -> {locs}")


if __name__ == "__main__":
    main()
