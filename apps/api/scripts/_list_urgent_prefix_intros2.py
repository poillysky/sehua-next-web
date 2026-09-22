# -*- coding: utf-8 -*-
"""Re-list urgent prefix intros after Aurora leak fix."""
from __future__ import annotations
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"apps"/"api"))
# clear caches
from app.core import maps_paths
for fn in ("makers_doc", "maker_i18n_map", "maker_intro_map"):
    f = getattr(maps_paths, fn, None)
    if hasattr(f, "cache_clear"):
        f.cache_clear()
import importlib
import app.prefix.maker_names as mn
importlib.reload(mn)

from app.core.region_meta import REGION_ORDER, REGION_META
from app.prefix import catalog_store as store

doc = store.load_catalog(force=True)

def code_count(e):
    for k in ("code_count","codes","count"):
        v = e.get(k)
        if isinstance(v, int): return v
        if isinstance(v, list): return len(v)
    return 0

MAIN_RE = re.compile(
    r"S1|MOODY|IDEA|Madonna|PRESTIGE|SOD|WANZ|Fitch|PREMIUM|本中|Hon-Naka|FALENO|kawaii|Das|"
    r"Caribbean|HEYZO|一本道|加勒比|麻豆|星空|Tushy|Blacked|FC2|ラグジュ|ARA|SIRO|DOC|MOON|"
    r"Hunter|OPPAI|E-BODY|Attackers|Prestige|俺の素人|S-Cute|舞ワイフ|TMA|Dogma|ドグマ|"
    r"アイエナジー|宇宙|ピーターズ|おかず|スクープ|K-Tribe|K部落|MILK|Cinemagic|Hsoda",
    re.I,
)

wrong=[]; missing_specific=[]; short=[]; no_any=[]
for rid in REGION_ORDER:
    for pref,e in (doc["regions"][rid].get("prefixes") or {}).items():
        maker=str((e or {}).get("maker") or "")
        n=code_count(e or {})
        specific=(mn.PREFIX_INTRO.get(pref) or "").strip()
        intro=(mn.resolve_maker_intro_for_prefix(pref) or "").strip()
        is_main=bool(MAIN_RE.search(maker)) or bool(re.match(r"^\d{3}[A-Z]", pref)) or n>=80

        if intro and "オーロラ・プロジェクト，凌辱" in intro and "Aurora" not in maker and "オーロラ" not in maker:
            wrong.append((pref,rid,maker,intro))
        if not specific and is_main:
            missing_specific.append((n,pref,rid,maker,intro or "(无回退)"))
        if specific and len(specific)<=8 and is_main:
            short.append((pref,rid,maker,specific))
        if is_main and not specific and not intro:
            no_any.append((pref,rid,maker))

missing_specific.sort(key=lambda x:-x[0])

print(f"串台仍残留: {len(wrong)}")
for p,rid,m,i in wrong[:10]:
    print(f"  {p} {m} -> {i[:40]}")

print(f"\n=== 急需补「前缀专属介绍」({len(missing_specific)}) — 主流/高量且无专属 ===")
print("格式: 前缀 | 厂牌 | 现回退介绍（可改写成专属）\n")
for i,(n,pref,rid,maker,intro) in enumerate(missing_specific[:45],1):
    print(f"{i:2d}. {pref}")
    print(f"    厂牌: {maker}")
    print(f"    现回退: {intro[:55]}")
    print()

print(f"=== 主流专属过短 ({len(short)}) ===")
for i,(pref,rid,maker,specific) in enumerate(short[:25],1):
    print(f"{i:2d}. {pref} | 现:{specific!r} | {maker[:36]}")

print(f"\n完全无介绍的主流: {len(no_any)}")
for p,rid,m in no_any[:20]:
    print(f"  {p} | {m}")
