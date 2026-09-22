# -*- coding: utf-8 -*-
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "apps/maps/makers/makers.json"
doc = json.loads(PATH.read_text(encoding="utf-8"))
makers = doc["makers"]
aliases = doc["aliases"]
# merge stray JET into JET映像
if "JET" in makers:
    jet = makers.pop("JET")
    aliases["JET"] = "JET映像"
    print("removed stray JET, aliased -> JET映像; old intro was:", jet.get("intro"))
PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

# Priority list for user
import re
WEAK_HARD = re.compile(r"公开资料有限|简介待核实|较少见的小众|小众独立系|小众企划系|兜底分组|内容分组")
empty = []
placeholder = []
for k, e in sorted(makers.items()):
    if not isinstance(e, dict):
        continue
    intro = str(e.get("intro") or "").strip()
    card = str(e.get("card") or "").strip()
    if not intro:
        empty.append((k, card))
    elif WEAK_HARD.search(intro):
        placeholder.append((k, card, intro))

print(f"\n无介绍: {len(empty)}")
for i,(k,c) in enumerate(empty,1):
    print(f"  {i}. {k} (card={c})")
print(f"\n占位/资料不足介绍: {len(placeholder)}")
for i,(k,c,intro) in enumerate(placeholder,1):
    print(f"  {i}. {k} | {intro}")
