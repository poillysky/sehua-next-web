# -*- coding: utf-8 -*-
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.region_meta import REGION_META, REGION_ORDER
from app.prefix import catalog_store as store

FILL = {
    "EZD": {"maker": "プレステージ", "maker_ja": "プレステージ", "maker_en": "Prestige", "notes": "早期番号 · 用户确认"},
    "FAD": {"maker": "FAプロ", "maker_ja": "FAプロ", "notes": "ヘンリー塚本系 · 用户确认"},
    "FERA": {"maker": "センタービレッジ", "maker_ja": "センタービレッジ", "notes": "楽園レーベル · 用户确认"},
    "GOJU": {"maker": "五十路ん", "maker_ja": "五十路ん", "notes": "五十路熟女 · 用户确认"},
    "HONB": {"maker": "本中", "maker_ja": "本中", "notes": "中出し系 · 用户确认"},
    "IBW": {"maker": "I.B.WORKS", "maker_ja": "I.B.WORKS", "maker_en": "I.B.WORKS", "notes": "用户确认"},
    "INSTV": {"maker": "HMN WORKS", "maker_ja": "HMN WORKS", "notes": "いんすた · 用户确认"},
    "KBKD": {"maker": "センタービレッジ", "maker_ja": "センタービレッジ", "notes": "熟女 · 用户确认"},
    "KITAIKE": {"maker": "北池袋", "maker_ja": "北池袋", "notes": "素人ハメ撮り · 用户确认"},
    "KTDS": {"maker": "ケートライブ", "maker_ja": "ケートライブ", "notes": "TMA関連 · 用户确认"},
    "LAFBD": {"maker": "LAFBD", "maker_ja": "LAFBD", "notes": "无码HD · 用户确认"},
    "LUXU": {"maker": "ラグジュTV", "maker_ja": "ラグジュTV", "notes": "MGS配信 · 用户确认"},
    "MCSR": {"maker": "ビッグモーカル", "maker_ja": "ビッグモーカル", "notes": "中出し人妻 · 用户确认"},
}
DELETE = ["FGAN", "GETCHU", "HDKA", "HMDNV", "HMGL", "HRSM", "KBI"]


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
    print("\n=== 第 3 组（请确认；不明直接说删）===")
    for i, (rid, p) in enumerate(remain[:20], 1):
        print(f"{i:2d}. [{REGION_META[rid]['label']}] {p}")
    if len(remain) > 20:
        print(f"… 另有 {len(remain) - 20} 条")


if __name__ == "__main__":
    main()
