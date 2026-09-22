# -*- coding: utf-8 -*-
"""Apply keep/skip decisions for remaining weak makers."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "apps/maps/makers/makers.json"
doc = json.loads(PATH.read_text(encoding="utf-8"))
aliases: dict = doc.setdefault("aliases", {})
makers: dict = doc.setdefault("makers", {})

KEEP = [
    (["Air Control"], "Air Control",
     ["Air Control / 空调", "エアコンロール", "Air Control"],
     "以偶像・グラビア女优形象视频为主的厂牌，偏软情色。",
     ["空调"]),
    (["M's Video", "エムズビデオ", "MVG"], "M's Video",
     ["M's Video / エムズ", "エムズビデオ", "M's Video"],
     "以吞精・精液系著称的老牌厂牌（M's Video Group）。",
     ["エムズ", "M’s Video", "M's Video Group"]),
    (["Opera"], "Opera",
     ["Opera", "オペラ", "Opera"],
     "以伪娘・ニューハーフ、肛交为主的专业厂牌。",
     []),
    (["SHEMALE a la carte", "Shemale a la carte", "SAL"], "人妖拼盘",
     ["人妖拼盘 / SHEMALE a la carte", "シーメールアラカルト", "SHEMALE a la carte"],
     "ニューハーフ（伪娘）专业系列，作品量较多。",
     ["人妖拼盘"]),
    (["Bermuda"], "Bermuda",
     ["Bermuda / 百慕大", "バミューダ", "Bermuda"],
     "妄想族旗下，主打陵辱、紧缚、黑人、特殊调教题材。",
     ["百慕大"]),
    (["Doujin AV"], "同人AV",
     ["同人AV", "同人AV", "Doujin AV"],
     "同人风格、非主流制作的AV作品统称。",
     ["同人AV"]),
    (["EMBZ"], "EMBZ",
     ["EMBZ", "EMBZ", "EMBZ"],
     "熟女专业レーベル（エマニエル系），主打中年女性。",
     []),
    (["Mothers", "マザーズ"], "Mothers",
     ["Mothers", "マザーズ", "Mothers"],
     "熟女・人妻系厂牌。",
     []),
    (["SPICY VR"], "SPICY VR",
     ["SPICY VR", "スパイシーVR", "SPICY VR"],
     "VR专用系列。",
     []),
    (["独占素人"], "独占素人",
     ["独占素人", "独占素人", "Dokusen Shirouto"],
     "素人独占配信系列。",
     []),
]

SKIP = [
    "Art Mode", "Glanz", "Haikara", "Kantama", "Media Brand", "Nama Nama",
    "NuPenis", "Plum", "Spartan", "Spice Visual", "Star Paradise", "Sunset Color",
    "Ureman", "Usagi", "Vi", "Yari Jouzu", "Yuzu",
    "ANB", "APAKA", "BAGUS", "CLOTH", "DAVK", "DEL", "DOJN", "FLAVOUR",
    "GARA", "GOGOS", "Garage", "HHF", "KOJA", "MOOC", "MSQ", "MZQ",
    "NGHJ", "NNOD", "OERO", "SITW", "SPND", "UMAN", "USAG", "YDNS", "teamZERO",
]

# Keep fallback groups untouched
KEEP_AS_IS = {"その他有码", "其它写真", "其它国产", "其它无码", "其它欧美"}


def resolve_key(cands: list[str]) -> str | None:
    low = {k.casefold(): k for k in makers}
    for c in cands:
        if c in makers:
            return c
        if c.casefold() in low:
            return low[c.casefold()]
        t = aliases.get(c)
        if t and t in makers:
            return t
    return None


kept = []
for cands, card, i18n, intro, extra in KEEP:
    key = resolve_key(cands) or cands[0]
    # Prefer canonical names
    if cands[0] == "SHEMALE a la carte":
        # migrate Shemale card key if present
        for old in ("Shemale a la carte", "SHEMALE a la carte"):
            if old in makers and old != key:
                makers.pop(old, None)
        key = "SHEMALE a la carte"
    if cands[0] == "M's Video":
        # consolidate MVG / エムズビデオ into M's Video
        for old in ("MVG", "エムズビデオ", "M's Video"):
            if old in makers and old != "M's Video":
                # drop after merge
                pass
        key = "M's Video"
        for old in ("MVG", "エムズビデオ"):
            if old in makers and old != key:
                makers.pop(old, None)
                aliases[old] = key
    ent = dict(makers.get(key) or {})
    ent["card"] = card
    ent["i18n"] = i18n
    ent["intro"] = intro
    makers[key] = ent
    for a in cands + extra:
        if a:
            aliases[a] = key
    # SAL -> SHEMALE
    if key == "SHEMALE a la carte":
        aliases["SAL"] = key
        if "SAL" in makers:
            makers.pop("SAL", None)
    kept.append(key)
    print(f"KEEP {key} | {card}")

deleted = []
for name in SKIP:
    # find actual key
    key = name if name in makers else None
    if not key:
        low = {k.casefold(): k for k in makers}
        key = low.get(name.casefold())
    if not key:
        t = aliases.get(name)
        if t and t in makers and t not in kept and t not in KEEP_AS_IS:
            # only delete if alias target is the skip name itself-ish
            if t.casefold() == name.casefold() or t == name:
                key = t
    if key and key in makers and key not in kept and key not in KEEP_AS_IS:
        makers.pop(key, None)
        deleted.append(key)
        print(f"DEL  {key}")
    # scrub aliases pointing to deleted
for a, t in list(aliases.items()):
    if t not in makers and t not in KEEP_AS_IS:
        # if target gone, remove alias
        if t in deleted or t in SKIP:
            aliases.pop(a, None)

# also remove aliases whose key was skipped name
for name in SKIP:
    aliases.pop(name, None)

PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"\nkept={len(kept)} deleted={len(deleted)} makers_now={len(makers)}")
print(f"updated {PATH}")

# verify priority remain
import re
WEAK_HARD = re.compile(r"公开资料有限|简介待核实|较少见的小众|小众独立系|小众企划系")
empty = []
placeholder = []
for k, e in sorted(makers.items()):
    if not isinstance(e, dict):
        continue
    if k in KEEP_AS_IS:
        continue
    intro = str(e.get("intro") or "").strip()
    if not intro:
        empty.append(k)
    elif WEAK_HARD.search(intro):
        placeholder.append((k, intro))
print(f"remain empty intro (excl fallback): {len(empty)} -> {empty}")
print(f"remain placeholder: {len(placeholder)}")
for k, intro in placeholder:
    print(f"  {k}: {intro}")
