import sys, importlib
sys.path.insert(0, ".")
from app.core import maps_paths
for fn in ("prefixes_doc", "prefix_intro_map", "makers_doc", "maker_intro_map"):
    f=getattr(maps_paths,fn,None)
    if hasattr(f,"cache_clear"): f.cache_clear()
import app.prefix.maker_names as mn
importlib.reload(mn)
from app.prefix import catalog_store as store
from app.core.region_meta import REGION_ORDER, REGION_META

doc=store.load_catalog(force=True)
no_spec=[]
for rid in REGION_ORDER:
    for pref,e in sorted((doc["regions"][rid].get("prefixes") or {}).items()):
        if (mn.PREFIX_INTRO.get(pref) or "").strip():
            continue
        maker=str((e or {}).get("maker") or "")
        fb=(mn.resolve_maker_intro_for_prefix(pref) or "").strip()
        no_spec.append((pref, rid, maker, fb[:40]))
print(f"catalog 无专属介绍: {len(no_spec)}")
for i,(p,rid,m,fb) in enumerate(no_spec,1):
    print(f"{i:2d}. {p} | {m} | fb={fb or '(无)'}")
