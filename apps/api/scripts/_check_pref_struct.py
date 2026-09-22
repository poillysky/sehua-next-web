import json
from pathlib import Path
ROOT = Path(r"E:\Project\sehua-next-web")
pref = json.loads((ROOT/"apps/maps/prefixes/prefixes.json").read_text(encoding="utf-8"))
print("top", list(pref.keys())[:10] if isinstance(pref,dict) else type(pref))
items = pref.get("items") or pref.get("prefixes") or pref
# sample a few known
for p in ["MEYD","JUL","APAK","JUC","VRKM","FC2","SSIS"]:
    ent = items.get(p) or items.get(p.lower())
    print(p, "=>", json.dumps(ent, ensure_ascii=False)[:200] if ent else None)

# weak intros: short or placeholder
weak=[]; miss=[]; ok=[]
for k,v in items.items():
    if not isinstance(v,dict): continue
    intro=(v.get("intro") or "").strip()
    if not intro: miss.append(k)
    elif "公开资料有限" in intro or len(intro)<12: weak.append((k,intro[:50]))
    else: ok.append(k)
print("prefix intro ok/weak/miss", len(ok), len(weak), len(miss))
print("weak samples", weak[:15])
