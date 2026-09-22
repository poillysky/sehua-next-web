import sys, re
sys.path.insert(0, ".")
from app.core import maps_paths
for fn in ("prefixes_doc", "prefix_intro_map", "makers_doc"):
    f=getattr(maps_paths,fn,None)
    if hasattr(f,"cache_clear"): f.cache_clear()
import importlib
import app.prefix.maker_names as mn
importlib.reload(mn)
from app.prefix import catalog_store as store
from app.core.region_meta import REGION_ORDER

# stale: in PREFIX_INTRO but not in catalog
doc=store.load_catalog(force=True)
catalog_prefs=set()
for rid in REGION_ORDER:
    catalog_prefs |= set((doc["regions"][rid].get("prefixes") or {}).keys())

stale=[]
weak=[]
for pref, intro in sorted(mn.PREFIX_INTRO.items()):
    if pref not in catalog_prefs:
        stale.append((pref, intro[:50]))
    if "公开资料有限" in intro or "小众企划" in intro and "资料" in intro:
        weak.append((pref, intro[:50], pref in catalog_prefs))

print(f"PREFIX_INTRO={len(mn.PREFIX_INTRO)} catalog={len(catalog_prefs)}")
print(f"stale intros (not in catalog): {len(stale)}")
for p,i in stale[:25]:
    print(f"  {p}: {i}")
print(f"\nweak '公开资料有限' style: {len(weak)}")
for p,i,incat in weak[:20]:
    print(f"  {p} in_catalog={incat}: {i}")
