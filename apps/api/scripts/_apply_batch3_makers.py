# -*- coding: utf-8 -*-
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.region_meta import REGION_META, REGION_ORDER
from app.prefix import catalog_store as store

FILL = {
    "MDTM": {"maker": "宇宙企画", "maker_ja": "宇宙企画", "notes": "用户确认"},
    "MEKO": {"maker": "熟女LABO", "maker_ja": "熟女LABO", "notes": "用户确认"},
    "MESU": {"maker": "センタービレッジ", "maker_ja": "センタービレッジ", "notes": "用户确认"},
    "MFCS": {"maker": "MOON FORCE 2nd", "maker_ja": "MOON FORCE 2nd", "notes": "FANZA素人 · 用户确认"},
    "MXBD": {"maker": "マキシング", "maker_ja": "マキシング", "maker_en": "MAXING", "notes": "BD旧番号 · 用户确认"},
    "NACX": {"maker": "プラネットプラス", "maker_ja": "プラネットプラス", "notes": "用户确认"},
    "NPS": {"maker": "ピーターズ", "maker_ja": "ピーターズ", "maker_en": "Peters", "notes": "用户确认"},
    "NWF": {"maker": "ワンズファクトリー", "maker_ja": "ワンズファクトリー", "maker_en": "WANZ", "notes": "WANZ旧番号 · 用户确认"},
    "OKAD": {"maker": "おかず。", "maker_ja": "おかず。", "notes": "KMP · 用户确认"},
    "OKAX": {"maker": "おかず。", "maker_ja": "おかず。", "notes": "KMP · 用户确认"},
    "PTS": {"maker": "ピーターズ", "maker_ja": "ピーターズ", "maker_en": "Peters", "notes": "用户确认"},
    "PYM": {"maker": "ピーターズ", "maker_ja": "ピーターズ", "notes": "极少 · 用户确认"},
    "SCOP": {"maker": "スクープ", "maker_ja": "スクープ", "maker_en": "Scoop", "notes": "用户确认"},
    "SGSR": {"maker": "いきなりエロざんまい", "maker_ja": "いきなりエロざんまい", "notes": "用户确认"},
    "SPZ": {"maker": "ネクスト", "maker_ja": "ネクスト", "maker_en": "NEXT", "notes": "用户确认"},
}
DELETE = ["MLW", "NADE", "NEO", "SHE", "STSK"]


def apply_fill(prefs: dict) -> int:
    n = 0
    for pref, info in FILL.items():
        ent = prefs.get(pref)
        if not isinstance(ent, dict):
            continue
        ent = dict(ent)
        ent["prefix"] = pref
        ent["maker"] = info["maker"]
        for k in ("maker_ja", "maker_en"):
            if info.get(k):
                ent[k] = info[k]
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


def main() -> None:
    doc = store.load_catalog(force=True)
    filled = 0
    for rid in REGION_ORDER:
        filled += apply_fill(doc["regions"][rid].get("prefixes") or {})
    gone = []
    for rid in REGION_ORDER:
        prefs = doc["regions"][rid].get("prefixes") or {}
        for pref in DELETE:
            if pref in prefs:
                del prefs[pref]
                gone.append(f"{rid}/{pref}")
                print(f"DEL  {rid} {pref}")
    store.save_catalog(doc)

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
    print(f"\ncatalog filled={filled} deleted={len(gone)}; seed filled={sf} deleted={sd}")

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
    print("\n=== 第 4 组（请确认；不明直接说删）===")
    for i, (rid, p) in enumerate(remain[:20], 1):
        print(f"{i:2d}. [{REGION_META[rid]['label']}] {p}")
    if len(remain) > 20:
        print(f"… 另有 {len(remain) - 20} 条")
    elif remain:
        print("(本组已含全部剩余)")


if __name__ == "__main__":
    main()
