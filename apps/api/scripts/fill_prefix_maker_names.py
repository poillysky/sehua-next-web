# -*- coding: utf-8 -*-
"""为 catalog 每个前缀写入中文/日文（英文）厂牌名。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.prefix import catalog_store as store  # noqa: E402
from app.prefix import maker_names as names  # noqa: E402


def main() -> None:
    doc = store.load_catalog(force=True)
    base = names.load_prefix_maker_base()
    filled = 0
    weak = 0
    for rid, reg in doc["regions"].items():
        prefs = reg.get("prefixes") or {}
        for pref, ent in list(prefs.items()):
            raw = dict(ent)
            if not raw.get("maker") and pref in base:
                raw["maker"] = base[pref]
            resolved = names.resolve_maker_names(pref, existing=raw)
            pe = store._normalize_prefix_entry(pref, {**raw, **resolved})
            # keep latest_code etc.
            for k in ("latest_code", "serial_max_hint", "notes", "sources", "verified_at", "integrity", "status"):
                if raw.get(k) is not None and k not in pe:
                    pe[k] = raw[k]
            if raw.get("latest_code"):
                pe["latest_code"] = raw["latest_code"]
            if raw.get("serial_max_hint"):
                pe["serial_max_hint"] = raw["serial_max_hint"]
            prefs[pref] = pe
            if resolved.get("maker"):
                filled += 1
            else:
                weak += 1
                print(f"NO NAME {rid}:{pref}", flush=True)
    store.save_catalog(doc)
    print(f"filled={filled} still_empty={weak}", flush=True)
    # samples
    for rid, pref in (
        ("japan_censored", "SSIS"),
        ("japan_censored", "SONE"),
        ("japan_amateur", "300MIUM"),
        ("japan_uncensored", "CARIB"),
        ("japan_uncensored", "HEYZO"),
        ("china", "MD"),
        ("western", "BRAZZERS"),
    ):
        e = (doc["regions"].get(rid) or {}).get("prefixes", {}).get(pref)
        if e:
            print(f"  {pref}: {e.get('maker')}", flush=True)


if __name__ == "__main__":
    main()
