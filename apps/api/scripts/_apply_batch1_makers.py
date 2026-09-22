# -*- coding: utf-8 -*-
"""Apply batch-1 makers; delete unclear prefixes; print next 20."""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.region_meta import REGION_META, REGION_ORDER
from app.prefix import catalog_store as store

FILL = {
    "ACRN": {"maker": "PoRO", "maker_ja": "PoRO", "maker_en": "PoRO", "notes": "成人动画 · 用户确认"},
    "ADZ": {"maker": "クリスタル映像", "maker_ja": "クリスタル映像", "notes": "旧番号 · 用户确认"},
    "ALD": {"maker": "桃太郎映像出版", "maker_ja": "桃太郎映像出版", "notes": "ALL IN ONE合集 · 用户确认"},
    "AMBI": {"maker": "プラネットプラス", "maker_ja": "プラネットプラス", "notes": "用户确认"},
    "AMCP": {"maker": "WORLD PG", "maker_ja": "WORLD PG", "notes": "成人动画 Motion Anime · 用户确认"},
    "ARSO": {"maker": "Around", "maker_ja": "Around", "notes": "舞ワイフ・セレブ系 · 用户确认"},
    "ASW": {"maker": "AVS collector's", "maker_ja": "AVS collector's", "notes": "着衣フェチ · 用户确认"},
    "BEAF": {"maker": "あいすまん", "maker_ja": "あいすまん", "notes": "素人個撮 · 用户确认"},
    "CWPBD": {"maker": "Caribbeancom Premium", "maker_ja": "カリビアンコムプレミアム", "maker_en": "Caribbeancom Premium", "notes": "无码BD · 用户确认"},
    "DMOW": {"maker": "ドグマ", "maker_ja": "ドグマ", "notes": "用户确认"},
    "DOKS": {"maker": "ドグマ", "maker_ja": "ドグマ", "notes": "旧番号 · 用户确认"},
    "DSE": {"maker": "ドリームチケット", "maker_ja": "ドリームチケット", "notes": "用户确认"},
    "ELO": {"maker": "エロチカ", "maker_ja": "エロチカ", "notes": "旧番号 · 用户确认"},
    "EROFV": {"maker": "エロVR", "maker_ja": "エロVR", "notes": "VR素人 · 用户确认"},
}
DELETE = ["BUR", "CHUC", "DDH", "ECB", "EUUD", "EVDV"]


def apply_fill(prefs: dict) -> int:
    n = 0
    for pref, info in FILL.items():
        ent = prefs.get(pref)
        if not isinstance(ent, dict):
            continue
        ent = dict(ent)
        ent["prefix"] = pref
        ent["maker"] = info["maker"]
        if info.get("maker_ja"):
            ent["maker_ja"] = info["maker_ja"]
        if info.get("maker_en"):
            ent["maker_en"] = info["maker_en"]
        srcs = set(ent.get("sources") or [])
        srcs.add("manual")
        ent["sources"] = sorted(srcs)
        notes = str(ent.get("notes") or "").strip()
        tag = info.get("notes") or "用户确认"
        if tag not in notes:
            ent["notes"] = f"{notes} · {tag}".strip(" ·") if notes else tag
        pe = store._normalize_prefix_entry(pref, ent)
        prefs[pe["prefix"]] = pe
        n += 1
        print(f"FILL {pref} -> {info['maker']}")
    return n


def do_delete(doc: dict) -> list[str]:
    gone = []
    for rid in REGION_ORDER:
        prefs = doc["regions"][rid].get("prefixes") or {}
        for pref in DELETE:
            if pref in prefs:
                del prefs[pref]
                gone.append(f"{rid}/{pref}")
                print(f"DEL  {rid} {pref}")
    return gone


def main() -> None:
    doc = store.load_catalog(force=True)
    filled = 0
    for rid in REGION_ORDER:
        prefs = doc["regions"][rid].get("prefixes") or {}
        filled += apply_fill(prefs)
    gone = do_delete(doc)
    store.save_catalog(doc)
    print(f"\ncatalog filled={filled} deleted={len(gone)}")

    # seed
    seed = store.load_seed()
    sf = sd = 0
    for rid in REGION_ORDER:
        prefs = (seed.get("regions") or {}).get(rid, {}).get("prefixes") or {}
        sf += apply_fill(prefs)
        for pref in DELETE:
            if pref in prefs:
                del prefs[pref]
                sd += 1
                print(f"SEED DEL {rid} {pref}")
    store.SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"seed filled={sf} deleted={sd}")

    remain = []
    for rid in REGION_ORDER:
        prefs = doc["regions"][rid].get("prefixes") or {}
        for p, e in sorted(prefs.items()):
            if not str((e or {}).get("maker") or "").strip():
                remain.append((rid, p))
    out = ROOT / "data" / "debug" / "prefixes-no-maker-remain.tsv"
    out.write_text(
        "region\tlabel\tprefix\n"
        + "\n".join(f"{rid}\t{REGION_META[rid]['label']}\t{p}" for rid, p in remain)
        + ("\n" if remain else ""),
        encoding="utf-8",
    )
    print(f"remain: {len(remain)}")
    print("\n=== 第 2 组（请确认；不明直接说删）===")
    for i, (rid, p) in enumerate(remain[:20], 1):
        print(f"{i:2d}. [{REGION_META[rid]['label']}] {p}")
    if len(remain) > 20:
        print(f"… 另有 {len(remain) - 20} 条")


if __name__ == "__main__":
    main()
