# -*- coding: utf-8 -*-
"""Restore Grok-suggested-delete prefixes under その他有码 (不要删除)."""
from __future__ import annotations

import json
from pathlib import Path

from app.prefix import catalog_store as store
from app.core.maps_paths import prefix_catalog_seed

ROOT = Path(__file__).resolve().parents[3]

# Grok 建议删除 + 刮削库无厂牌映射；统一挂「其他有码」，不删
PREFIXES = [
    "ANB",
    "APAK",
    "CLOT",
    "DAVK",
    "DEL",
    "DOJN",
    "GARA",
    "GS",
    "GAJK",
    "HHF",
    "KOJA",
    "MOOC",
    "MSQ",
    "MZQ",
    "NGHJ",
    "NNOD",
    "OERO",
    "SITW",
    "SPND",
    "UMAN",
    "USAG",
    "YDNS",
    "TEAM",
    # 此前当孤儿从 seed 清掉、但库里仍有片
    "SMD",
    "TG",
    "YM",
    "SAO",
]

MAKER = "Other Censored / 其他有码"
MAKER_ZH = "Other Censored / 其他有码"
MAKER_JA = "その他有码"
MAKER_EN = "Other Censored"
NOTES = "库内有片；厂牌署名不明，归入其他有码兜底（用户确认：不删）"

INTRO = "库内稳定品番，暂归其他有码；厂牌署名待补全。"
I18N = ["その他有码 / 其他有码", "その他有码", "Other Censored"]


def _entry(prefix: str) -> dict:
    return {
        "prefix": prefix,
        "maker": MAKER,
        "maker_zh": MAKER_ZH,
        "maker_ja": MAKER_JA,
        "maker_en": MAKER_EN,
        "label_ja": "",
        "sources": ["scrap-library", "maker-norm"],
        "pad": 3,
        "format": "{prefix}-{num}",
        "dmm_digit": "",
        "code_read": "std3_dmm",
        "serials": [],
        "codes": [],
        "status": "active",
        "notes": NOTES,
    }


def main() -> None:
    doc = store.load_catalog(force=True)
    prefs = doc["regions"]["japan_censored"].setdefault("prefixes", {})
    added_cat: list[str] = []
    updated_cat: list[str] = []
    for p in PREFIXES:
        if p in prefs:
            ent = prefs[p]
            ent["maker"] = MAKER
            ent["maker_zh"] = MAKER_ZH
            ent["maker_ja"] = MAKER_JA
            ent["maker_en"] = MAKER_EN
            ent["notes"] = NOTES
            updated_cat.append(p)
        else:
            prefs[p] = _entry(p)
            added_cat.append(p)
    store.save_catalog(doc)

    # seed
    seed_path = prefix_catalog_seed()
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    sprefs = seed.setdefault("regions", {}).setdefault("japan_censored", {}).setdefault(
        "prefixes", {}
    )
    added_seed: list[str] = []
    updated_seed: list[str] = []
    for p in PREFIXES:
        if p in sprefs:
            ent = sprefs[p]
            if not isinstance(ent, dict):
                ent = {"prefix": p}
                sprefs[p] = ent
            ent["prefix"] = p
            ent["maker"] = MAKER
            ent["maker_zh"] = MAKER_ZH
            ent["maker_ja"] = MAKER_JA
            ent["maker_en"] = MAKER_EN
            ent["notes"] = NOTES
            updated_seed.append(p)
        else:
            sprefs[p] = {
                "prefix": p,
                "maker": MAKER,
                "maker_zh": MAKER_ZH,
                "maker_ja": MAKER_JA,
                "maker_en": MAKER_EN,
                "notes": NOTES,
            }
            added_seed.append(p)
    seed_path.write_text(
        json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # prefixes.json
    pref_path = ROOT / "apps/maps/prefixes/prefixes.json"
    pref_doc = json.loads(pref_path.read_text(encoding="utf-8"))
    items = pref_doc.setdefault("prefixes", {})
    for p in PREFIXES:
        ent = items.get(p)
        if not isinstance(ent, dict):
            ent = {}
            items[p] = ent
        ent["i18n"] = list(I18N)
        # 保留已有非占位介绍；否则用兜底句
        old = str(ent.get("intro") or "").strip()
        if (not old) or ("公开资料有限" in old) or old.endswith("。") and len(old) < 20:
            ent["intro"] = INTRO
    pref_path.write_text(
        json.dumps(pref_doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    # av-makers.japan.json
    av_path = ROOT / "apps/maps/makers/av-makers.japan.json"
    av = json.loads(av_path.read_text(encoding="utf-8"))
    hit = None
    for row in av:
        if isinstance(row, dict) and row.get("maker") == "その他有码":
            hit = row
            break
    if hit is None:
        hit = {
            "maker": "その他有码",
            "kind": "有码",
            "description": "库内稳定品番、厂牌署名待补全。",
            "prefixes": [],
            "cover_aspect": "2/3",
            "prefix_notes": {},
        }
        av.append(hit)
    existing = list(hit.get("prefixes") or [])
    for p in PREFIXES:
        if p not in existing:
            existing.append(p)
    # keep stable order: old first then new sorted
    base = [x for x in existing if x in ("MIKR", "FJIN")]
    rest = sorted({x for x in existing if x not in base})
    hit["prefixes"] = base + rest
    av_path.write_text(
        json.dumps(av, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    # verify
    doc2 = store.load_catalog(force=True)
    prefs2 = doc2["regions"]["japan_censored"]["prefixes"]
    ok = all(
        prefs2.get(p, {}).get("maker_ja") == MAKER_JA
        or prefs2.get(p, {}).get("maker") == MAKER
        for p in PREFIXES
    )
    print("catalog added", added_cat)
    print("catalog updated", updated_cat)
    print("seed added", added_seed)
    print("seed updated", updated_seed)
    print("total targets", len(PREFIXES), "all_ok", ok)
    print("その他有码 prefixes now", hit["prefixes"])


if __name__ == "__main__":
    main()
