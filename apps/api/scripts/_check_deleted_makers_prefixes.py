# -*- coding: utf-8 -*-
"""Check if skipped/deleted makers still own prefixes in catalog."""
from __future__ import annotations
import json, sys, unicodedata, re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.core.region_meta import REGION_META, REGION_ORDER
from app.prefix import catalog_store as store

DELETED = [
    "Art Mode", "Glanz", "Haikara", "Kantama", "Media Brand", "Nama Nama",
    "NuPenis", "Plum", "Spartan", "Spice Visual", "Star Paradise", "Sunset Color",
    "Ureman", "Usagi", "Vi", "Yari Jouzu", "Yuzu",
    "ANB", "APAKA", "BAGUS", "CLOTH", "DAVK", "DEL", "DOJN", "FLAVOUR",
    "GARA", "GOGOS", "Garage", "HHF", "KOJA", "MOOC", "MSQ", "MZQ",
    "NGHJ", "NNOD", "OERO", "SITW", "SPND", "UMAN", "USAG", "YDNS", "teamZERO",
]

# also common variant spellings that might appear in catalog
EXTRA = [
    "バグス", "バミューダ", "うまなみ", "うさぎ", "マザーズ",
    "ArtMode", "STAR PARADISE", "Next Group",  # careful
]

SEP = re.compile(r"[\s\-_.·・/／\\]+")

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").strip().casefold()
    return SEP.sub("", s)

del_norms = {norm(x): x for x in DELETED}

doc = store.load_catalog(force=True)
hits: dict[str, list[tuple[str, str, str]]] = defaultdict(list)

for rid in REGION_ORDER:
    for p, e in (doc["regions"][rid].get("prefixes") or {}).items():
        m = str((e or {}).get("maker") or "").strip()
        if not m:
            continue
        # exact / token match
        tokens = [m] + [t.strip() for t in re.split(r"\s*/\s*", m) if t.strip()]
        matched = None
        for t in tokens:
            n = norm(t)
            if n in del_norms:
                matched = del_norms[n]
                break
            # also match if maker equals deleted key as whole
            if norm(m) in del_norms:
                matched = del_norms[norm(m)]
                break
        if matched:
            hits[matched].append((rid, p, m))

print(f"deleted makers with prefixes still in catalog: {len(hits)}")
total_prefs = 0
for name in sorted(hits, key=lambda x: -len(hits[x])):
    rows = hits[name]
    total_prefs += len(rows)
    print(f"\n[{name}] prefixes={len(rows)}")
    for rid, p, m in rows[:15]:
        label = REGION_META[rid]["label"]
        print(f"  - [{label}] {p}  maker={m!r}")
    if len(rows) > 15:
        print(f"  ... +{len(rows)-15}")
print(f"\nTOTAL prefixes under deleted makers: {total_prefs}")

# also: makers.json gone but catalog maker string not in deleted list?
makers_doc = json.loads((ROOT / "apps/maps/makers/makers.json").read_text(encoding="utf-8"))
makers = makers_doc.get("makers") or {}
aliases = makers_doc.get("aliases") or {}

def resolve(name: str) -> str:
    if name in makers:
        return name
    a = aliases.get(name)
    if a and a in makers:
        return a
    low = {k.casefold(): k for k in makers}
    if name.casefold() in low:
        return low[name.casefold()]
    for t in re.split(r"\s*/\s*", name):
        t = t.strip()
        if t in makers:
            return t
        if t.casefold() in low:
            return low[t.casefold()]
        a = aliases.get(t)
        if a and a in makers:
            return a
    return ""

orphan_catalog = defaultdict(list)
for rid in REGION_ORDER:
    for p, e in (doc["regions"][rid].get("prefixes") or {}).items():
        m = str((e or {}).get("maker") or "").strip()
        if not m:
            continue
        if not resolve(m):
            orphan_catalog[m].append((rid, p))

print(f"\n=== catalog makers with NO makers.json entry: {len(orphan_catalog)} ===")
for m, prefs in sorted(orphan_catalog.items(), key=lambda x: -len(x[1]))[:40]:
    sample = ",".join(p for _, p in prefs[:5])
    print(f"  {m}  (×{len(prefs)}: {sample})")
if len(orphan_catalog) > 40:
    print(f"  ... +{len(orphan_catalog)-40}")
