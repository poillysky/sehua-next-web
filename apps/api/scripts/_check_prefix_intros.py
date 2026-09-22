# -*- coding: utf-8 -*-
"""Check intro coverage for mainstream prefixes."""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.core.maps_paths import prefix_intro_map, load_json_map
from app.core.region_meta import REGION_ORDER
from app.prefix import catalog_store as store
from app.prefix.maker_names import resolve_maker_intro_for_prefix, PREFIX_INTRO

# Mainstream sample: high code_count / well-known prefixes
MAIN = [
    # S1 / Moodyz / IP / Madonna / Prestige / SOD / WANZ / Fitch / etc
    "SONE","SSIS","SSNI","SNIS","SOE",
    "MIDA","MIDV","MIDE","MIAA","MIAB",
    "IPZZ","IPX","IPZ","IPVR",
    "JUR","JUQ","JUL","JUY","JUX",
    "ABF","ABP","ABS","ONEZ","CHN",
    "STARS","START","SDDE","SDNM","STAR",
    "WAAA","WANZ","WVGD",
    "FPRE","JUFE","HIKR",
    "PRED","PBD",
    "HMN","HND","HNDB",
    "SSIS","SONE",
    "CAWD","MIDV",
    "FSDSS","DASS","NACR",
    "MVSD","CJOD","RKI",
    "SSNI","OFJE",
    "FC2","HEYZO","CWPBD","1PONDO","CARIB",
    "SIRO","ARA","LUXU","GANA","MIUM",
    "MD","MDSR","XK","TUSHY","BLACKED",
]

doc = store.load_catalog(force=True)
prefs = {}
for rid in REGION_ORDER:
    prefs.update(doc["regions"][rid].get("prefixes") or {})

# also load prefixes.json intros and av-makers prefix_notes
pdoc = load_json_map("prefixes.json") or {}
p_entries = (pdoc.get("prefixes") or {}) if isinstance(pdoc, dict) else {}

av_path = ROOT / "apps/maps/makers/av-makers.japan.json"
av_notes = {}
if av_path.exists():
    for row in json.loads(av_path.read_text(encoding="utf-8")):
        for pref, note in (row.get("prefix_notes") or {}).items():
            av_notes[str(pref).upper()] = (row.get("maker"), note)

# unique MAIN
seen=set(); mains=[]
for p in MAIN:
    if p not in seen:
        seen.add(p); mains.append(p)

print(f"PREFIX_INTRO map size: {len(PREFIX_INTRO)}")
print(f"prefixes.json with intro: {sum(1 for e in p_entries.values() if isinstance(e,dict) and str(e.get('intro') or '').strip())}")
print(f"av-makers prefix_notes: {len(av_notes)}")
print()
print("=== 主流前缀介绍覆盖 ===")
has=no=0
for p in mains:
    ent = prefs.get(p) or prefs.get(p.upper())
    maker = str((ent or {}).get("maker") or "") if ent else "(不在目录)"
    intro = resolve_maker_intro_for_prefix(p) or ""
    p_intro = ""
    pe = p_entries.get(p) or p_entries.get(p.upper())
    if isinstance(pe, dict):
        p_intro = str(pe.get("intro") or "").strip()
    note = av_notes.get(p.upper(), ("",""))[1]
    src = []
    if intro: src.append("maker/prefix_intro")
    if p_intro: src.append("prefixes.json")
    if note: src.append("av-notes")
    ok = bool(intro or p_intro or note)
    if ok: has+=1
    else: no+=1
    flag = "OK" if ok else "NO"
    text = intro or p_intro or note or "-"
    print(f"[{flag}] {p:8s} maker={maker[:28]:28s} | {text[:50]}")

print(f"\n主流样本: {len(mains)} 有介绍={has} 无介绍={no}")

# catalog-wide: how many prefixes get any intro via resolve
all_prefs=sorted(prefs)
covered=0
for p in all_prefs:
    if resolve_maker_intro_for_prefix(p) or (isinstance(p_entries.get(p),dict) and p_entries[p].get("intro")) or av_notes.get(p.upper()):
        covered+=1
print(f"全目录前缀: {len(all_prefs)} 能解析到介绍(厂牌intro或前缀intro)≈ 用 resolve_maker_intro: ", end="")
c2=sum(1 for p in all_prefs if resolve_maker_intro_for_prefix(p))
print(f"{c2}/{len(all_prefs)}")
