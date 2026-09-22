import sys
sys.path.insert(0, ".")
from app.prefix import catalog_store as store
from app.core.region_meta import REGION_ORDER
doc = store.load_catalog(force=True)
for rid in REGION_ORDER:
    prefs = doc["regions"][rid].get("prefixes") or {}
    if "APAK" in prefs:
        print("FOUND APAK in", rid, prefs["APAK"])
print("APAK in catalog?", any("APAK" in (doc["regions"][r].get("prefixes") or {}) for r in REGION_ORDER))

# makers.json
import json
from pathlib import Path
m=json.loads(Path(r"E:/Project/sehua-next-web/apps/maps/makers/makers.json").read_text(encoding="utf-8"))
print("APAKA in makers", "APAKA" in m.get("makers",{}))
print("APAK alias", m.get("aliases",{}).get("APAK"), m.get("aliases",{}).get("APAKA"))
