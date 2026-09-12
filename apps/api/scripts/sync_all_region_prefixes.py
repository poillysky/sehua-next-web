# -*- coding: utf-8 -*-
"""Step 1: sync prefix lists for all 7 regions from makers configs (+ curated extras).

Does NOT harvest serials. Preserves existing runtime serials when merging catalog.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import prefix_catalog_store as store  # noqa: E402
from app.core.region_meta import REGION_META, REGION_ORDER, std_prefix  # noqa: E402

SEED = ROOT / "apps" / "web" / "src" / "config" / "prefix-catalog.seed.json"
MAKER_FILES = [
    ROOT / "apps" / "web" / "src" / "config" / "av-makers.japan.json",
    ROOT / "apps" / "web" / "src" / "config" / "av-makers.china.json",
    ROOT / "apps" / "web" / "src" / "config" / "av-makers.western.json",
]
VERIFY = ROOT / "data" / "_debug" / "dmm-prefix-verify.json"

KIND_TO_REGION = {
    "有码": "japan_censored",
    "写真": "japan_gravure",
    "无码": "japan_uncensored",
    "素人": "japan_amateur",
    "FC2": "fc2",
    "国产": "china",
    "欧美": "western",
}

# Curated extras that makers JSON may miss (prefix-only; serials later)
EXTRA: dict[str, dict[str, dict]] = {
    "japan_censored": {
        "SNOS": {"maker": "S1 NO.1 STYLE", "notes": "S1 现行 2025~"},
        "MIDA": {"maker": "MOODYZ", "notes": "Diva 现行"},
        "JUR": {"maker": "Madonna", "notes": "Madonna 现行"},
        "FSDSS": {"maker": "FALENO"},
        "DLDSS": {"maker": "DAHLIA"},
        "START": {"maker": "SOD Create"},
        "DASS": {"maker": "DAS!"},
        "PPPE": {"maker": "OPPAI"},
        "HMN": {"maker": "本中"},
        "PRED": {"maker": "PREMIUM"},
        "CJOD": {"maker": "痴女ヘブン"},
        "BF": {"maker": "BeFree"},
        "RKI": {"maker": "ROOKIE"},
        "VENU": {"maker": "VENUS"},
        "VEC": {"maker": "VENUS"},
    },
    "japan_uncensored": {
        "HEYZO": {"maker": "HEYZO", "pad": 4, "sources": ["heyzo"]},
        "CARIB": {"maker": "Caribbeancom", "pad": 0, "sources": ["carib"], "notes": "日期番号"},
        "CARIBPR": {"maker": "Caribbeancom Premium", "pad": 0, "sources": ["carib"]},
        "1PON": {"maker": "1pondo", "pad": 0, "sources": ["1pondo"], "notes": "日期番号"},
        "PACO": {"maker": "Pacopacomama", "pad": 0, "sources": ["pacopacomama"]},
        "10MU": {"maker": "10musume", "pad": 0, "sources": ["10musume"]},
        "H4610": {"maker": "H4610", "pad": 0, "sources": ["h4610"]},
        "C0930": {"maker": "C0930", "pad": 0, "sources": ["c0930"]},
        "H0930": {"maker": "H0930", "pad": 0, "sources": ["h0930"]},
        "KIN8": {"maker": "Kin8tengoku", "pad": 4, "sources": ["kin8"]},
        "NYOSHIN": {"maker": "Nyoshin", "sources": ["nyoshin"]},
        "AVOP": {"maker": "AV OPEN", "notes": "企划号偶发无码盘"},
        "TOKYO": {"maker": "Tokyo Hot", "notes": "nXXXX"},
        "PT": {"maker": "Pacificgirls"},
        "GACHI": {"maker": "Gachinco"},
        "MESUBUTA": {"maker": "Mesubuta"},
    },
    "japan_amateur": {
        "SIRO": {"maker": "素人TOKYO / シロウトTV"},
        "LUXU": {"maker": "ラグジュTV"},
        "MAAN": {"maker": "マジ軟派、初即ハメ"},
        "MIUM": {"maker": "みうめい"},
        "ORE": {"maker": "俺の素人"},
        "GANA": {"maker": "ナンパTV"},
        "NTK": {"maker": "ネットワーク"},
        "JAC": {"maker": "Jackson"},
        "SCUTE": {"maker": "S-Cute"},
        "ARA": {"maker": "ARA"},
        "DCV": {"maker": "誰でもカット"},
        "BEAF": {"maker": "ビーフ"},
        "NAMH": {"maker": "生ハメ"},
        "EKDV": {"maker": "クリスタル映像"},
        "KBI": {"maker": "KANBi"},
    },
    "japan_gravure": {
        "ENFD": {"maker": "イーネット・フロンティア"},
        "OAE": {"maker": "Air control"},
        "REBD": {"maker": "Bamboo / REbecca"},
        "REBDB": {"maker": "Bamboo / REbecca"},
        "MBRAA": {"maker": "スパイスビジュアル"},
        "MBRBA": {"maker": "スパイスビジュアル"},
        "MBDD": {"maker": "メディアブランド"},
        "SYD": {"maker": "スパイスビジュアル"},
        "GGSID": {"maker": "グレイズ"},
        "BFAZ": {"maker": "ファインピクチャーズ"},
    },
    "fc2": {
        "FC2": {"maker": "FC2", "pad": 0, "sources": ["fc2"], "format": "FC2-{num}"},
        "FC2PPV": {"maker": "FC2 PPV", "pad": 0, "sources": ["fc2"], "format": "FC2-PPV-{num}"},
    },
    "china": {
        "MD": {"maker": "麻豆传媒"},
        "MDX": {"maker": "麻豆传媒"},
        "MDSR": {"maker": "麻豆传媒"},
        "MKY": {"maker": "麻豆传媒"},
        "MSD": {"maker": "麻豆传媒"},
        "MAD": {"maker": "麻豆传媒"},
        "91CM": {"maker": "91制片厂"},
        "JVID": {"maker": "JVID"},
        "TMW": {"maker": "天美传媒"},
        "TM": {"maker": "天美传媒"},
        "DA": {"maker": "大象传媒"},
        "HKG": {"maker": "星空无限"},
        "XKG": {"maker": "星空无限"},
        "IDG": {"maker": "爱豆传媒"},
        "RAS": {"maker": "皇家华人"},
        "PMX": {"maker": "蜜桃影像"},
        "NHJ": {"maker": "精东影业"},
        "JD": {"maker": "精东影业"},
    },
    "western": {
        "BRAZZERS": {"maker": "Brazzers"},
        "BLACKED": {"maker": "Blacked"},
        "BLACKEDRAW": {"maker": "BlackedRaw"},
        "TUSHY": {"maker": "Tushy"},
        "VIXEN": {"maker": "Vixen"},
        "DEEPER": {"maker": "Deeper"},
        "BANGBROS": {"maker": "Bang Bros"},
        "BANGBUS": {"maker": "Bang Bus"},
        "NAUGHTYAMERICA": {"maker": "Naughty America"},
        "REALITYKINGS": {"maker": "Reality Kings"},
        "MOFOS": {"maker": "Mofos"},
        "FAKETAXI": {"maker": "Fake Taxi"},
        "EVILANGEL": {"maker": "Evil Angel"},
        "LEGALPORNO": {"maker": "LegalPorno"},
        "ONLYFANS": {"maker": "OnlyFans"},
        "VIXENPLUS": {"maker": "Vixen Plus"},
        "SLAYED": {"maker": "Slayed"},
        "AGIRIENE": {"maker": "Adult Time"},
    },
}

DEFAULT_SOURCE = {
    "japan_censored": ["dmm"],
    "japan_gravure": ["dmm"],
    "japan_uncensored": ["site"],
    "japan_amateur": ["dmm"],
    "fc2": ["fc2"],
    "china": ["site"],
    "western": ["site"],
}


def _clean_prefix(raw: str) -> str:
    # catalog keys are alnum (FC2PPV / 200GANA / 91CM), no dashes
    p2 = re.sub(r"[^A-Z0-9]", "", std_prefix(raw).replace("-", ""))
    if len(p2) < 2 or len(p2) > 16:
        return ""
    return p2


def collect_from_makers() -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {rid: {} for rid in REGION_ORDER}
    for path in MAKER_FILES:
        data = json.loads(path.read_text(encoding="utf-8"))
        for m in data:
            kind = str(m.get("kind") or "").strip()
            rid = KIND_TO_REGION.get(kind)
            if not rid:
                continue
            maker = str(m.get("maker") or "").strip()
            notes_map = m.get("prefix_notes") or {}
            for raw in m.get("prefixes") or []:
                key = _clean_prefix(str(raw))
                if not key:
                    continue
                note = str(notes_map.get(raw) or notes_map.get(key) or "").strip()
                cur = out[rid].setdefault(
                    key,
                    {
                        "maker": maker,
                        "pad": 3 if rid.startswith("japan_") and rid != "japan_uncensored" else 0,
                        "format": "{prefix}-{num}",
                        "sources": list(DEFAULT_SOURCE.get(rid) or ["site"]),
                        "serials": [],
                    },
                )
                if maker and not cur.get("maker"):
                    cur["maker"] = maker
                if note and not cur.get("notes"):
                    cur["notes"] = note
    return out


def collect_from_verify(bucket: dict[str, dict[str, dict]]) -> None:
    if not VERIFY.exists():
        return
    data = json.loads(VERIFY.read_text(encoding="utf-8"))
    for row in data.get("ok_list") or []:
        kind = str(row.get("kind") or "").strip()
        rid = KIND_TO_REGION.get(kind)
        if not rid:
            continue
        key = _clean_prefix(str(row.get("prefix") or ""))
        if not key:
            continue
        cur = bucket[rid].setdefault(
            key,
            {
                "maker": str(row.get("maker") or row.get("dmm_maker") or "").strip(),
                "pad": 3,
                "format": "{prefix}-{num}",
                "sources": ["dmm"],
                "serials": [],
            },
        )
        if row.get("dmm_maker") and not cur.get("maker_ja"):
            cur["maker_ja"] = str(row.get("dmm_maker") or "")
        if "dmm" not in (cur.get("sources") or []):
            cur["sources"] = sorted(set(list(cur.get("sources") or []) + ["dmm"]))


def apply_extras(bucket: dict[str, dict[str, dict]]) -> None:
    for rid, extras in EXTRA.items():
        for key, meta in extras.items():
            k = _clean_prefix(key)
            if not k:
                continue
            cur = bucket[rid].setdefault(
                k,
                {
                    "maker": str(meta.get("maker") or ""),
                    "pad": int(meta.get("pad") if meta.get("pad") is not None else (3 if rid.startswith("japan_") and rid != "japan_uncensored" else 0)),
                    "format": str(meta.get("format") or "{prefix}-{num}"),
                    "sources": list(meta.get("sources") or DEFAULT_SOURCE.get(rid) or ["site"]),
                    "serials": [],
                },
            )
            if meta.get("maker") and not cur.get("maker"):
                cur["maker"] = meta["maker"]
            if meta.get("notes") and not cur.get("notes"):
                cur["notes"] = meta["notes"]
            if meta.get("pad") is not None:
                cur["pad"] = int(meta["pad"])
            if meta.get("format"):
                cur["format"] = str(meta["format"])
            if meta.get("sources"):
                cur["sources"] = list(meta["sources"])


def merge_existing_seed(bucket: dict[str, dict[str, dict]]) -> None:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    for rid in REGION_ORDER:
        prefs = ((seed.get("regions") or {}).get(rid) or {}).get("prefixes") or {}
        for key, ent in prefs.items():
            k = _clean_prefix(key)
            if not k:
                continue
            cur = bucket[rid].setdefault(k, {})
            # seed wins on structured fields if present
            for field in ("maker", "maker_ja", "pad", "format", "sources", "dmm_digit", "notes"):
                if ent.get(field) not in (None, "", []):
                    if field == "sources":
                        cur["sources"] = list(ent["sources"])
                    else:
                        cur[field] = ent[field]
            cur.setdefault("serials", [])
            cur.setdefault(
                "pad",
                3 if rid.startswith("japan_") and rid != "japan_uncensored" else 0,
            )
            cur.setdefault("format", "{prefix}-{num}")
            cur.setdefault("sources", list(DEFAULT_SOURCE.get(rid) or ["site"]))
            cur.setdefault("maker", "")


def write_seed(bucket: dict[str, dict[str, dict]]) -> dict[str, int]:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    seed["principle"] = "curated network seeds; runtime harvest fills serials"
    regions = seed.setdefault("regions", {})
    counts: dict[str, int] = {}
    for rid in REGION_ORDER:
        meta = REGION_META[rid]
        prefs_out = {}
        for key in sorted(bucket[rid].keys()):
            ent = bucket[rid][key]
            row = {
                "maker": str(ent.get("maker") or ""),
                "pad": int(ent.get("pad") or 0),
                "format": str(ent.get("format") or "{prefix}-{num}"),
                "sources": list(ent.get("sources") or DEFAULT_SOURCE.get(rid) or ["site"]),
                "serials": [],
            }
            if ent.get("maker_ja"):
                row["maker_ja"] = ent["maker_ja"]
            if ent.get("dmm_digit") not in (None,):
                row["dmm_digit"] = ent.get("dmm_digit")
            if ent.get("notes"):
                row["notes"] = ent["notes"]
            prefs_out[key] = row
        regions[rid] = {
            "id": rid,
            "label": meta["label"],
            "prefixes": prefs_out,
        }
        counts[rid] = len(prefs_out)
    SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return counts


def merge_catalog(bucket: dict[str, dict[str, dict]]) -> dict[str, dict[str, int]]:
    doc = store.load_catalog(force=True)
    stats: dict[str, dict[str, int]] = {}
    for rid in REGION_ORDER:
        region = doc["regions"].setdefault(
            rid,
            {"id": rid, "label": REGION_META[rid]["label"], "prefixes": {}},
        )
        region["label"] = REGION_META[rid]["label"]
        region["id"] = rid
        prefs = region.setdefault("prefixes", {})
        added = kept = 0
        for key, ent in bucket[rid].items():
            if key in prefs:
                cur = prefs[key]
                serials = list(cur.get("serials") or [])
                if not cur.get("maker") and ent.get("maker"):
                    cur["maker"] = ent["maker"]
                if ent.get("dmm_digit") not in (None, "") and not cur.get("dmm_digit"):
                    cur["dmm_digit"] = ent["dmm_digit"]
                if ent.get("notes") and not cur.get("notes"):
                    cur["notes"] = ent["notes"]
                # refresh sources union
                cur["sources"] = sorted(
                    set(list(cur.get("sources") or []) + list(ent.get("sources") or []))
                )
                prefs[key] = store._normalize_prefix_entry(key, {**cur, "serials": serials})
                if serials:
                    prefs[key]["serials"] = serials
                    prefs[key] = store._normalize_prefix_entry(key, prefs[key])
                kept += 1
            else:
                prefs[key] = store._normalize_prefix_entry(key, ent)
                added += 1
        stats[rid] = {"added": added, "kept": kept, "total": len(prefs)}
    store.save_catalog(doc)
    return stats


def main() -> None:
    bucket = collect_from_makers()
    collect_from_verify(bucket)
    apply_extras(bucket)
    merge_existing_seed(bucket)
    counts = write_seed(bucket)
    stats = merge_catalog(bucket)
    print("=== prefix sync (step1) ===")
    for rid in REGION_ORDER:
        label = REGION_META[rid]["label"]
        print(
            f"{rid:18} {label:8} seed={counts[rid]:4d}  "
            f"catalog +{stats[rid]['added']} keep={stats[rid]['kept']} total={stats[rid]['total']}"
        )
    print("TOTAL seed", sum(counts.values()))


if __name__ == "__main__":
    main()
