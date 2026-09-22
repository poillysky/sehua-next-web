# -*- coding: utf-8 -*-
"""Apply SOD prefix intros to prefixes.json."""
from __future__ import annotations
import json, importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "apps/maps/prefixes/prefixes.json"
doc = json.loads(PATH.read_text(encoding="utf-8"))
prefs = doc.setdefault("prefixes", {})

INTROS = {
    "STARS": "SOD star 现行专属主线，一线女优单体",
    "START": "SOD star 关联/新线",
    "STAR": "SOD star 早期专属线",
    "3DSVR": "SOD VR 主线（SODVR）",
    "SDDE": "SOD 经典企画线（魔镜号、射精管理等）",
    "SDMS": "SOD 早期主线 / 女子社员相关",
    "SDMT": "SOD 女子社员系列（中期）",
    "SDMU": "SOD 女子社员系列（后期）",
    "SDMUA": "SOD 女子社员系列变体",
    "SDNM": "SOD 人妻 / 熟女线",
    "SDJS": "SOD 女子社员现行相关",
    "SDMM": "SOD 魔镜号等街头企画",
    "SDAB": "SOD 青春 / 美少女线",
    "SDAM": "SOD ドキュメント・素人线",
    "SDDM": "SOD 最早期主线",
    "MOGI": "SOD 萌え / 新人相关",
    "SDHS": "SOD 旁支企画",
    "SDTH": "SOD 旁支",
    "SDCA": "SOD 旁支 / 早期",
    "SDEN": "SOD 旁支",
    "SDNT": "SOD 旁支",
    "SACE": "SOD 早期旁支",
    "SHYN": "SOD 旁支",
    "KIRE": "SOD 綺麗系相关",
    "KMHR": "SOD 旁支",
    "KMHRS": "SOD 旁支",
    "EMOI": "SOD 情感 / 青春线",
    "HYPN": "SOD 催眠相关",
    "SDMF": "SOD 旁支",
    "MSFH": "SOD 旁支",
    "SENN": "SOD 旁支",
    "SDSI": "SOD 旁支",
    "NTTR": "SOD 旁支",
    "SETM": "SOD 旁支",
    "KUSE": "SOD 旁支",
    "SODS": "SOD 综合 / 旁支",
    "PRDB": "SOD 旁支",
    "SDDL": "SOD 旁支",
    "SUWK": "SOD 旁支",
    "TENC": "SOD 旁支",
    "SPLY": "SOD 旁支",
    "KKTN": "SOD 旁支",
    "STKO": "SOD 旁支",
    "MASD": "SOD 早期旁支",
    "KSFN": "SOD 旁支",
    "HSDAM": "SOD 旁支",
    "SDFK": "SOD 旁支",
    "OKYH": "SOD 旁支",
}

updated = created = 0
for pref, intro in INTROS.items():
    ent = prefs.get(pref)
    if not isinstance(ent, dict):
        prefs[pref] = {"intro": intro}
        created += 1
        print(f"NEW {pref}")
    else:
        ent = dict(ent)
        ent["intro"] = intro
        prefs[pref] = ent
        updated += 1
        print(f"SET {pref}")

doc["prefixes"] = dict(sorted(prefs.items(), key=lambda x: x[0]))
PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"\nupdated={updated} created={created} total_with_intro="
      f"{sum(1 for e in doc['prefixes'].values() if isinstance(e, dict) and str(e.get('intro') or '').strip())}")

from app.core import maps_paths
for fn in ("prefixes_doc", "prefix_intro_map"):
    f = getattr(maps_paths, fn, None)
    if hasattr(f, "cache_clear"):
        f.cache_clear()
import app.prefix.maker_names as mn
importlib.reload(mn)
bad = [p for p, t in INTROS.items() if (mn.PREFIX_INTRO.get(p) or "").strip() != t]
print("verify bad:", bad or "none")
for p in ("STARS", "3DSVR", "SDDE", "SDMM", "SDNM"):
    print(f"  {p}: {mn.resolve_maker_intro_for_prefix(p)}")
