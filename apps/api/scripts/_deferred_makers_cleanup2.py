# -*- coding: utf-8 -*-
"""Finish leftover duplicate stubs after deferred cleanup."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MPATH = ROOT / "apps/maps/makers/makers.json"
mdoc = json.loads(MPATH.read_text(encoding="utf-8"))
makers = mdoc["makers"]
aliases = mdoc["aliases"]

# クリスタル映像 -> Crystal if Crystal exists
if "Crystal" in makers and "クリスタル映像" in makers:
    for a, t in list(aliases.items()):
        if t == "クリスタル映像":
            aliases[a] = "Crystal"
    aliases["クリスタル映像"] = "Crystal"
    aliases["Crystal Eizou"] = "Crystal"
    makers.pop("クリスタル映像", None)
    print("MERGE クリスタル映像 -> Crystal")

# Delete Radix stub (bad alias already removed)
if "Radix" in makers:
    makers.pop("Radix")
    aliases.pop("Radix", None)
    print("DEL Radix stub")

# Nanpa Japan / ナンパJAPAN
if "Nanpa Japan" in makers and "ナンパJAPAN" in makers:
    # keep whichever; prefer Nanpa Japan if both
    keep, drop = "Nanpa Japan", "ナンパJAPAN"
    aliases[drop] = keep
    for a, t in list(aliases.items()):
        if t == drop:
            aliases[a] = keep
    makers.pop(drop, None)
    print(f"MERGE {drop} -> {keep}")

# 桃太郎 / 桃太郎映像
if "桃太郎" in makers and "桃太郎映像" in makers:
    keep = "桃太郎映像" if "桃太郎映像" in makers else "桃太郎"
    drop = "桃太郎" if keep == "桃太郎映像" else "桃太郎映像"
    if drop in makers:
        aliases[drop] = keep
        makers.pop(drop, None)
        print(f"MERGE {drop} -> {keep}")
elif "桃太郎" in makers:
    aliases["桃太郎映像"] = "桃太郎"
    aliases["桃太郎映像出版"] = "桃太郎"

# Fallback buckets: ensure they stay (don't delete)
# Point common Other* catalog names if needed - skip

MPATH.write_text(json.dumps(mdoc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"makers now: {len(makers)}")
