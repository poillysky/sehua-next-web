import sys
sys.path.insert(0, ".")
from app.core.region_meta import REGION_ORDER
from app.prefix import catalog_store as store
from app.prefix.maker_names import PREFIX_INTRO, resolve_maker_intro_for_prefix

doc = store.load_catalog(force=True)
prefs = {}
for rid in REGION_ORDER:
    prefs.update(doc["regions"][rid].get("prefixes") or {})
specific = sum(1 for p in prefs if (PREFIX_INTRO.get(p) or "").strip())
fallback = sum(
    1
    for p in prefs
    if not (PREFIX_INTRO.get(p) or "").strip() and resolve_maker_intro_for_prefix(p)
)
none = len(prefs) - specific - fallback
print(f"prefix-specific: {specific}/{len(prefs)}")
print(f"maker-fallback only: {fallback}/{len(prefs)}")
print(f"none: {none}")
MAIN = "SONE SSIS SSNI MIDA MIDV IPZZ IPX JUR JUQ ABF ABP STARS WANZ WAAA HMN HND FSDSS CAWD PRED FPRE SIRO ARA LUXU MD TUSHY".split()
print("mainstream specific?")
for p in MAIN:
    hit = (PREFIX_INTRO.get(p) or "").strip()
    fb = resolve_maker_intro_for_prefix(p) or ""
    kind = "YES" if hit else "maker-only"
    text = hit or fb
    print(f"  {p}: {kind} | {text[:48]}")
