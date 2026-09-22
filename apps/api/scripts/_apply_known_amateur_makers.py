# -*- coding: utf-8 -*-
"""Apply known amateur makers; list remaining no-maker prefixes in batches of 20."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.region_meta import REGION_META, REGION_ORDER
from app.prefix import catalog_store as store

# User-provided amateur / MGS delivery makers
KNOWN: dict[str, dict[str, str]] = {
    "083PPP": {
        "maker": "パラダイステレビ",
        "maker_ja": "パラダイステレビ",
        "maker_en": "Paradise TV",
        "notes": "素人/熟女企画 · 用户确认",
    },
    "109IENFH": {
        "maker": "IENFH（MGS素人）",
        "maker_ja": "IENFH",
        "notes": "MGS素人配信 · 用户确认",
    },
    "210AKO": {
        "maker": "A子さん",
        "maker_ja": "A子さん",
        "notes": "素人ハメ撮り配信 · 用户确认",
    },
    "229SCUTE": {
        "maker": "S-Cute",
        "maker_ja": "S-CUTE",
        "maker_en": "S-Cute",
        "notes": "美少女自然体ハメ撮り · 用户确认",
    },
    "230OREC": {
        "maker": "俺の素人-Z-",
        "maker_ja": "俺の素人-Z-",
        "notes": "俺の素人系列 · 用户确认",
    },
    "230OREMO": {
        "maker": "俺の素人-Z-",
        "maker_ja": "俺の素人-Z-",
        "notes": "俺の素人系列 · 用户确认",
    },
    "230ORETD": {
        "maker": "俺の素人-Z-",
        "maker_ja": "俺の素人-Z-",
        "notes": "俺の素人系列 · 用户确认",
    },
    "261ARA": {
        "maker": "ARA（募集ちゃん）",
        "maker_ja": "ARA",
        "notes": "募集ちゃん系列 · 用户确认",
    },
    "277DCV": {
        "maker": "ドキュメンTV",
        "maker_ja": "ドキュメンTV",
        "notes": "家まで送ってイイですか？ · 用户确认",
    },
    "285ENDX": {
        "maker": "E★ナンパDX",
        "maker_ja": "E★ナンパDX",
        "notes": "素人ナンパ · 用户确认",
    },
    "292MY": {
        "maker": "舞ワイフ",
        "maker_ja": "舞ワイフ",
        "maker_en": "Mai Wife",
        "notes": "人妻素人 · 用户确认",
    },
    "299EWDX": {
        "maker": "E★人妻DX",
        "maker_ja": "E★人妻DX",
        "notes": "人妻素人 · 用户确认",
    },
    "318LADY": {
        "maker": "LadyHunter",
        "maker_ja": "LadyHunter",
        "maker_en": "LadyHunter",
        "notes": "素人ナンパ · 用户确认",
    },
    "324SRTD": {
        "maker": "投稿マーケット素人イッてQ",
        "maker_ja": "投稿マーケット素人イッてQ",
        "notes": "投稿素人 · 用户确认",
    },
    "326FCT": {
        "maker": "黒船",
        "maker_ja": "黒船",
        "maker_en": "Kurofune",
        "notes": "素人ドキュメント · 用户确认",
    },
    "345SIMM": {
        "maker": "しろうとまんまん",
        "maker_ja": "しろうとまんまん",
        "notes": "DOC相关素人 · 用户确认",
    },
    "348NTR": {
        "maker": "NTR.net",
        "maker_ja": "NTR.net",
        "maker_en": "NTR.net",
        "notes": "NTR主题素人 · 用户确认",
    },
}


def _apply_to_prefs(prefs: dict, *, overwrite: bool) -> int:
    n = 0
    for pref, info in KNOWN.items():
        ent = prefs.get(pref)
        if not isinstance(ent, dict):
            continue
        if str(ent.get("maker") or "").strip() and not overwrite:
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
        print(f"OK {pref} -> {info['maker']}")
    return n


def main() -> None:
    doc = store.load_catalog(force=True)
    applied = 0
    for rid in REGION_ORDER:
        prefs = doc["regions"][rid].get("prefixes") or {}
        # user-confirmed: overwrite empty only (don't clobber DMM if already filled)
        n = _apply_to_prefs(prefs, overwrite=False)
        if n:
            print(f"  region={rid} +{n}")
        applied += n

    store.save_catalog(doc)
    print(f"\napplied: {applied}")

    remain: list[tuple[str, str]] = []
    for rid in REGION_ORDER:
        prefs = doc["regions"][rid].get("prefixes") or {}
        for p, e in sorted(prefs.items()):
            if not str((e or {}).get("maker") or "").strip():
                remain.append((rid, p))

    out = ROOT / "data" / "debug" / "prefixes-no-maker-remain.tsv"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "region\tlabel\tprefix\n"
        + "\n".join(f"{rid}\t{REGION_META[rid]['label']}\t{p}" for rid, p in remain)
        + ("\n" if remain else ""),
        encoding="utf-8",
    )
    print(f"remain: {len(remain)} -> {out}")

    try:
        seed = store.load_seed()
        n_seed = 0
        for rid in REGION_ORDER:
            prefs = (seed.get("regions") or {}).get(rid, {}).get("prefixes") or {}
            n_seed += _apply_to_prefs(prefs, overwrite=False)
        if n_seed:
            store.SEED_PATH.write_text(
                json.dumps(seed, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"seed patched: {n_seed}")
    except Exception as e:  # noqa: BLE001
        print(f"seed skip: {e}")

    print("\n=== 仍无片商 · 第 1 组（请确认）===")
    for i, (rid, p) in enumerate(remain[:20], 1):
        print(f"{i:2d}. [{REGION_META[rid]['label']}] {p}")
    if len(remain) > 20:
        print(f"… 另有 {len(remain) - 20} 条待下一组")


if __name__ == "__main__":
    main()
