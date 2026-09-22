# -*- coding: utf-8 -*-
import json, re, sys, unicodedata
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"apps"/"api"))
from app.prefix import catalog_store as store
from app.core.region_meta import REGION_ORDER

mdoc=json.loads((ROOT/"apps/maps/makers/makers.json").read_text(encoding="utf-8"))
makers=mdoc["makers"]; aliases=mdoc["aliases"]
SEP=re.compile(r"[\s\-_.·・/／\\]+")
def norm(s):
    s=unicodedata.normalize("NFKC",s or "").strip().casefold()
    return SEP.sub("",s)

# who owns 妄想族 in lookup?
print("=== aliases containing 妄想族 ===")
for a,t in sorted(aliases.items()):
    if "妄想" in a or "妄想" in t:
        print(f"  {a!r} -> {t!r}")
print("\n=== makers keys with 妄想 ===")
for k in makers:
    if "妄想" in k:
        print(" ", k, "card=", makers[k].get("card"))

# resolve simulation for 犬/妄想族
name="犬/妄想族"
parts=[name]+[p.strip() for p in name.split("/")]
print("\ntokens", parts)
for t in parts:
    # find
    for k in makers:
        if norm(t)==norm(k):
            print(f"  token {t!r} exact key {k}")
    for a,c in aliases.items():
        if norm(t)==norm(a):
            print(f"  token {t!r} alias -> {c}")

# MDL MKY cross region
doc=store.load_catalog(force=True)
for p in ("MDL","MKY"):
    print(f"\n=== {p} ===")
    for rid in REGION_ORDER:
        e=(doc["regions"][rid].get("prefixes") or {}).get(p)
        if e:
            print(f"  {rid}: maker={e.get('maker')!r} notes={(e.get('notes') or '')[:60]!r}")

# MDYD
e=doc["regions"]["japan_censored"]["prefixes"].get("MDYD")
print("\nMDYD", e.get("maker") if e else None)

# First Star check
print("\nFIRST STAR alias", aliases.get("FIRST STAR"), aliases.get("First Star"))

# unused but should map - check Cosmos
for pref in ("HAWA","NHDTB","NHDTA","TTJ"):
    for rid in REGION_ORDER:
        e=(doc["regions"][rid].get("prefixes") or {}).get(pref)
        if e:
            print(f"{pref} @{rid} maker={e.get('maker')!r}")

# list all 妄想族-related catalog makers and their prefixes
print("\n=== catalog makers with 妄想族 ===")
for rid in REGION_ORDER:
    for p,e in (doc["regions"][rid].get("prefixes") or {}).items():
        m=str(e.get("maker") or "")
        if "妄想" in m:
            print(f"  {p}: {m}")
