# -*- coding: utf-8 -*-
"""Delete invalid prefixes; reassign BAGR->BALTAN, FLAV->Digital Ark."""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.core.region_meta import REGION_ORDER
from app.prefix import catalog_store as store

DELETE_PREFIXES = {
    "ANB", "APAK", "CLOT", "DAVK", "DEL", "DOJN", "GARA", "GS", "GAJK",
    "HHF", "KOJA", "MOOC", "MSQ", "MZQ", "NGHJ", "NNOD", "OERO", "SITW",
    "SPND", "UMAN", "USAG", "YDNS", "TEAM",
}
# Keep + reassign
REASSIGN = {
    "BAGR": {
        "maker": "BALTAN",
        "maker_ja": "バルタン",
        "maker_en": "BALTAN",
        "notes": "用户确认 · 改挂 BALTAN",
    },
    "FLAV": {
        "maker": "Digital Ark",
        "maker_ja": "デジタルアーク",
        "maker_en": "Digital Ark",
        "notes": "用户确认 · FLAV 属 Digital Ark",
    },
}

# Ensure BALTAN in makers.json
MPATH = ROOT / "apps/maps/makers/makers.json"
mdoc = json.loads(MPATH.read_text(encoding="utf-8"))
makers = mdoc.setdefault("makers", {})
aliases = mdoc.setdefault("aliases", {})
if "BALTAN" not in makers and "バルタン" not in makers:
    makers["BALTAN"] = {
        "card": "BALTAN",
        "i18n": ["BALTAN", "バルタン", "BALTAN"],
        "intro": "バルタン系レーベル。BAGR 等前缀归属此厂。",
    }
    aliases["BALTAN"] = "BALTAN"
    aliases["バルタン"] = "BALTAN"
    aliases["BAGUS"] = "BALTAN"
    aliases["巴古斯"] = "BALTAN"
    print("CREATE makers BALTAN")
else:
    key = "BALTAN" if "BALTAN" in makers else "バルタン"
    aliases["BALTAN"] = key
    aliases["バルタン"] = key
    aliases["BAGUS"] = key
    aliases["BAGR"] = key
    print(f"BALTAN exists as {key}")

# Digital Ark already exists
aliases["FLAV"] = aliases.get("Digital Ark") or "Digital Ark"
aliases["FLAVOUR"] = aliases.get("Digital Ark") or "Digital Ark"
MPATH.write_text(json.dumps(mdoc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def process(doc: dict, label: str) -> tuple[int, int]:
    deleted = 0
    reassigned = 0
    for rid in REGION_ORDER:
        prefs = doc["regions"][rid].get("prefixes") or {}
        for p in list(prefs.keys()):
            if p in DELETE_PREFIXES:
                del prefs[p]
                deleted += 1
                print(f"DEL  {label} {rid}/{p}")
            elif p in REASSIGN:
                info = REASSIGN[p]
                ent = dict(prefs[p])
                ent["prefix"] = p
                ent["maker"] = info["maker"]
                if info.get("maker_ja"):
                    ent["maker_ja"] = info["maker_ja"]
                if info.get("maker_en"):
                    ent["maker_en"] = info["maker_en"]
                srcs = set(ent.get("sources") or [])
                srcs.add("manual")
                ent["sources"] = sorted(srcs)
                notes = str(ent.get("notes") or "").strip()
                tag = info["notes"]
                if tag not in notes:
                    ent["notes"] = f"{notes} · {tag}".strip(" ·") if notes else tag
                pe = store._normalize_prefix_entry(p, ent)
                prefs[pe["prefix"]] = pe
                reassigned += 1
                print(f"MOVE {label} {rid}/{p} -> {info['maker']}")
    return deleted, reassigned


doc = store.load_catalog(force=True)
d1, r1 = process(doc, "catalog")
store.save_catalog(doc)

seed = store.load_seed()
d2, r2 = process(seed, "seed")
store.SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print(f"\ncatalog deleted={d1} reassigned={r1}")
print(f"seed    deleted={d2} reassigned={r2}")

# verify gone
remain = []
for rid in REGION_ORDER:
    prefs = doc["regions"][rid].get("prefixes") or {}
    for p in DELETE_PREFIXES:
        if p in prefs:
            remain.append(f"{rid}/{p}")
    for p, info in REASSIGN.items():
        ent = prefs.get(p)
        if ent:
            print(f"OK {p} maker={ent.get('maker')!r}")
        else:
            print(f"MISS {p} not in catalog after move?")
print(f"deleted still present: {remain or 'none'}")
