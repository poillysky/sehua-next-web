# -*- coding: utf-8 -*-
"""Apply B-group prefix intros to prefixes.json."""
from __future__ import annotations
import json, importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "apps/maps/prefixes/prefixes.json"
doc = json.loads(PATH.read_text(encoding="utf-8"))
prefs = doc.setdefault("prefixes", {})

INTROS = {
    "IPVR": "Idea Pocket 的 VR 专属系列",
    "CAWD": "かぐや姫 / kawaii* 现行主线，美少女清新系",
    "FSDSS": "FALENO 专属单体主线，高画质美女",
    "ABF": "Prestige 专属现行主线（ABS 后继）",
    "CJOD": "痴女ヘブン现行主线，痴女・逆袭系",
    "DASS": "ダスッ！现行主线，凌辱・激烈系",
    "DASD": "ダスッ！上一代主线",
    "EBWH": "イーブス / E-BODY 现行主线，美体・巨乳",
    "BBAN": "ビビアン女同主线，女同专业",
    "BLK": "kira☆kira 辣妹黑系主线，ギャル",
    "DSVR": "ダスッ！VR 系列",
    "DVDMS": "ディープス，魔镜号等街头企画主线",
    "ABS": "Prestige 更早专属线（ABP 前身相关）",
    "ABW": "Prestige 过渡专属线",
    "HUNT": "ハンター主线，企画・逆袭・场景系",
    "HUNTA": "ハンター旁支 / 关联线",
    "FNS": "デジタルスター / FALENO 数字星线",
    "DANDY": "DANDY 厂牌同名主线，街头恶作剧・熟女",
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
print(f"\nupdated={updated} created={created}")

from app.core import maps_paths
for fn in ("prefixes_doc", "prefix_intro_map"):
    f = getattr(maps_paths, fn, None)
    if hasattr(f, "cache_clear"):
        f.cache_clear()
import app.prefix.maker_names as mn
importlib.reload(mn)
for pref, intro in INTROS.items():
    hit = (mn.PREFIX_INTRO.get(pref) or "").strip()
    ok = "OK" if hit == intro else f"BAD got={hit!r}"
    print(f"  {pref}: {ok}")
