# -*- coding: utf-8 -*-
import json, re, unicodedata
from pathlib import Path
ROOT = Path(r"E:/Project/sehua-next-web")
mdoc=json.loads((ROOT/"apps/maps/makers/makers.json").read_text(encoding="utf-8"))
makers=mdoc["makers"]; aliases=mdoc["aliases"]
SEP=re.compile(r"[\s\-_.·・/／\\]+")
def norm(s):
    s=unicodedata.normalize("NFKC",s or "").strip().casefold()
    return SEP.sub("",s)

# build lookup like audit
lookup={}
for k in makers:
    lookup[norm(k)]=k
for a,c in aliases.items():
    if c in makers:
        lookup[norm(a)]=c
        lookup[norm(c)]=c
for k,ent in makers.items():
    if not isinstance(ent,dict):
        continue
    for x in [ent.get("card")] + list(ent.get("i18n") or []):
        xs=str(x or "").strip()
        if not xs: continue
        lookup.setdefault(norm(xs),k)
        for part in re.split(r"\s*/\s*", xs):
            if part.strip():
                lookup.setdefault(norm(part),k)

print("lookup 妄想族 ->", lookup.get(norm("妄想族")))
print("lookup 犬 ->", lookup.get(norm("犬")))
print("lookup SEX Agent ->", lookup.get(norm("SEX Agent")))
print("lookup ブロッコリー ->", lookup.get(norm("ブロッコリー")))
print("lookup バミューダ ->", lookup.get(norm("バミューダ")))
print("lookup Bermuda ->", lookup.get(norm("Bermuda")))
print("lookup 姦乱者 ->", lookup.get(norm("姦乱者")))

# which i18n/card injects bare 妄想族?
for k,ent in makers.items():
    if not isinstance(ent,dict):
        continue
    for x in [ent.get("card")] + list(ent.get("i18n") or []):
        xs=str(x or "").strip()
        if not xs: continue
        for part in re.split(r"\s*/\s*", xs):
            if norm(part.strip())==norm("妄想族"):
                print(f"BARE 妄想族 from maker {k} field {xs!r}")
