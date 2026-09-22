# -*- coding: utf-8 -*-
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.region_meta import REGION_META, REGION_ORDER
from app.prefix import catalog_store as store

FILL = {
    "SUKE": {"maker": "訳ありZ世代", "maker_ja": "訳ありZ世代", "notes": "DOC系素人 · 用户确认"},
    "T28": {"maker": "TMA", "maker_ja": "TMA", "maker_en": "TMA", "notes": "用户确认"},
    "WNZ": {"maker": "ワンズファクトリー", "maker_ja": "ワンズファクトリー", "maker_en": "WANZ", "notes": "旧番号 · 用户确认"},
    "355OPCYN": {"maker": "おっぱいちゃん", "maker_ja": "おっぱいちゃん", "notes": "MGS素人 · 用户确认"},
    "413INST": {"maker": "いんすた", "maker_ja": "いんすた", "notes": "HMN WORKS · 用户确认"},
    "413INSTC": {"maker": "いんすた", "maker_ja": "いんすた", "notes": "HMN WORKS · 用户确认"},
    "413INSTV": {"maker": "いんすた", "maker_ja": "いんすた", "notes": "HMN WORKS · 用户确认"},
    "420HOI": {"maker": "素人ホイホイZ", "maker_ja": "素人ホイホイZ", "notes": "用户确认"},
    "435MFC": {"maker": "MOON FORCE", "maker_ja": "MOON FORCE", "notes": "FANZA素人 · 用户确认"},
}
DELETE = [
    "UMSO", "XMOM", "YST", "ZMAR", "ZRO",
    "383REIW", "393OTIM", "422ION", "476MLA", "481SACZ", "483SGK",
]


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
    if remain:
        print("\n=== 第 5 组 / 最后一批（请确认；不明直接说删）===")
        for i, (rid, p) in enumerate(remain, 1):
            print(f"{i:2d}. [{REGION_META[rid]['label']}] {p}")
    else:
        print("\n全部前缀已有片商或已删除。")


if __name__ == "__main__":
    main()
