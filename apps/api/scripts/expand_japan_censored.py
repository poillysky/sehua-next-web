# -*- coding: utf-8 -*-
"""Expand japan_censored prefixes from makers + DMM verify, then harvest serials."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repo root
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import prefix_catalog_dmm as dmm  # noqa: E402
from app import prefix_catalog_harvest as harvest  # noqa: E402
from app import prefix_catalog_store as store  # noqa: E402
from app.core.region_meta import std_prefix  # noqa: E402

SEED = ROOT / "apps" / "web" / "src" / "config" / "prefix-catalog.seed.json"
MAKERS = ROOT / "apps" / "web" / "src" / "config" / "av-makers.japan.json"
VERIFY = ROOT / "data" / "_debug" / "dmm-prefix-verify.json"
OUT = ROOT / "data" / "_debug" / "expand-censored.log"

# Research supplements: active / recent major series not always in local makers
EXTRA_PREFIXES: dict[str, dict] = {
    "SNOS": {"maker": "S1 NO.1 STYLE", "notes": "S1 现行主线 2025~"},
    "MIDA": {"maker": "MOODYZ", "notes": "Moodyz Diva 现行"},
    "JUR": {"maker": "Madonna", "notes": "Madonna 现行主线"},
    "FSDSS": {"maker": "FALENO", "notes": "FALENO 专属"},
    "DLDSS": {"maker": "DAHLIA", "notes": "DAHLIA"},
    "START": {"maker": "SOD Create", "notes": "SOD START"},
    "DASS": {"maker": "DAS!", "notes": "DAS! 现行"},
    "PPPE": {"maker": "OPPAI", "notes": "OPPAI 现行"},
    "HMN": {"maker": "本中", "notes": "本中现行"},
    "MVSD": {"maker": "M's Video Group", "notes": "MSVG"},
    "CJOD": {"maker": "痴女ヘブン", "notes": "痴女天堂"},
    "BLK": {"maker": "kira☆kira", "notes": "kira kira"},
    "BF": {"maker": "BeFree", "notes": "BeFree"},
    "PRED": {"maker": "PREMIUM", "notes": "PREMIUM"},
    "PRST": {"maker": "PREMIUM", "notes": "PREMIUM 专属"},
    "RKI": {"maker": "ROOKIE", "notes": "ROOKIE"},
    "NACR": {"maker": "プラネットプラス", "notes": "人妻"},
    "VEC": {"maker": "VENUS", "notes": "VENUS"},
    "VENU": {"maker": "VENUS", "notes": "VENUS"},
}


def digit_from_cid(prefix: str, cid: str) -> str | None:
    s = dmm.series_key(prefix)
    c = re.sub(r"[^a-z0-9_]", "", str(cid or "").lower())
    m = re.match(rf"^(.*?){re.escape(s)}(\d{{3,6}})$", c)
    if not m:
        return None
    return m.group(1)


def load_maker_map() -> dict[str, dict]:
    makers = json.loads(MAKERS.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for m in makers:
        if m.get("kind") != "有码":
            continue
        maker = str(m.get("maker") or "").strip()
        notes = m.get("prefix_notes") or {}
        for p in m.get("prefixes") or []:
            key = std_prefix(p)
            if not key:
                continue
            row = out.setdefault(key, {"maker": maker, "notes": ""})
            if not row.get("maker"):
                row["maker"] = maker
            note = str(notes.get(p) or notes.get(key) or "").strip()
            if note and not row.get("notes"):
                row["notes"] = note
    return out


def load_ok_digits() -> dict[str, str]:
    verify = json.loads(VERIFY.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for row in verify.get("ok_list") or []:
        if row.get("kind") and row.get("kind") != "有码":
            continue
        key = std_prefix(str(row.get("prefix") or ""))
        if not key:
            continue
        dig = digit_from_cid(key, str(row.get("cid") or ""))
        if dig is not None:
            out[key] = dig
    return out


def expand_series_digit(digits: dict[str, str]) -> int:
    """Patch SERIES_DIGIT in-memory + rewrite known map in source file lightly."""
    added = 0
    for pref, dig in digits.items():
        sk = dmm.series_key(pref)
        if sk not in dmm.SERIES_DIGIT:
            dmm.SERIES_DIGIT[sk] = dig
            added += 1
        elif dmm.SERIES_DIGIT[sk] != dig and dig != "":
            # keep existing unless empty unknown
            pass
    return added


def build_entries() -> dict[str, dict]:
    makers = load_maker_map()
    digits = load_ok_digits()
    expand_series_digit(digits)

    # seed baseline
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    seed_prefs = (seed.get("regions") or {}).get("japan_censored", {}).get("prefixes") or {}

    keys = set(makers) | set(digits) | {std_prefix(k) for k in seed_prefs} | set(
        std_prefix(k) for k in EXTRA_PREFIXES
    )
    keys = {k for k in keys if k and re.fullmatch(r"[A-Z0-9]{2,12}", k)}

    entries: dict[str, dict] = {}
    for key in sorted(keys):
        base = dict(seed_prefs.get(key) or {})
        meta = makers.get(key) or EXTRA_PREFIXES.get(key) or {}
        dig = digits.get(key)
        if dig is None:
            known = dmm.SERIES_DIGIT.get(dmm.series_key(key))
            dig = known if known is not None else ""
        ent = {
            "maker": str(base.get("maker") or meta.get("maker") or "").strip(),
            "maker_ja": str(base.get("maker_ja") or "").strip(),
            "pad": int(base.get("pad") or 3),
            "format": str(base.get("format") or "{prefix}-{num}"),
            "sources": ["dmm"],
            "dmm_digit": dig if dig is not None else str(base.get("dmm_digit") or ""),
            "serials": [],
            "status": "active",
            "integrity": "unknown",
            "notes": str(base.get("notes") or meta.get("notes") or "").strip(),
        }
        entries[key] = ent
    return entries, digits


def write_seed(entries: dict[str, dict]) -> None:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    regions = seed.setdefault("regions", {})
    jc = regions.setdefault("japan_censored", {"id": "japan_censored", "label": "日本有码"})
    # keep harvested serials out of seed (seed = curated prefixes only)
    prefs = {}
    for key, ent in entries.items():
        prefs[key] = {
            "maker": ent.get("maker") or "",
            "pad": ent.get("pad") or 3,
            "format": ent.get("format") or "{prefix}-{num}",
            "sources": ["dmm"],
            "dmm_digit": ent.get("dmm_digit") if ent.get("dmm_digit") is not None else "",
            "serials": [],
            "notes": ent.get("notes") or "",
        }
        if not prefs[key]["notes"]:
            prefs[key].pop("notes", None)
        # omit empty dmm_digit for cleaner seed? keep for SOD etc.
    jc["prefixes"] = dict(sorted(prefs.items()))
    jc["id"] = "japan_censored"
    jc["label"] = "日本有码"
    seed["principle"] = "curated network seeds; runtime harvest fills serials"
    SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_catalog(entries: dict[str, dict]) -> dict:
    doc = store.load_catalog(force=True)
    bucket = doc["regions"]["japan_censored"]["prefixes"]
    added = updated = 0
    for key, ent in entries.items():
        if key in bucket:
            cur = bucket[key]
            # fill missing meta; never wipe serials
            if not cur.get("maker") and ent.get("maker"):
                cur["maker"] = ent["maker"]
            if ent.get("dmm_digit") not in (None, "") and not cur.get("dmm_digit"):
                cur["dmm_digit"] = ent["dmm_digit"]
            if ent.get("notes") and not cur.get("notes"):
                cur["notes"] = ent["notes"]
            sources = set(cur.get("sources") or [])
            sources.add("dmm")
            cur["sources"] = sorted(sources)
            bucket[key] = store._normalize_prefix_entry(key, cur)
            if cur.get("serials"):
                bucket[key]["serials"] = list(cur["serials"])
                bucket[key] = store._normalize_prefix_entry(key, bucket[key])
            updated += 1
        else:
            bucket[key] = store._normalize_prefix_entry(key, ent)
            added += 1
    store.save_catalog(doc)
    return {"added": added, "updated": updated, "total": len(bucket)}


def patch_series_digit_file(digits: dict[str, str]) -> int:
    path = ROOT / "apps" / "api" / "app" / "prefix_catalog_dmm.py"
    text = path.read_text(encoding="utf-8")
    # find SERIES_DIGIT block end before closing }
    m = re.search(r"SERIES_DIGIT: dict\[str, str\] = \{([\s\S]*?)\n\}", text)
    if not m:
        return 0
    block = m.group(1)
    existing = set(re.findall(r'"([a-z0-9_]+)"\s*:', block))
    lines = []
    for pref, dig in sorted(digits.items()):
        sk = dmm.series_key(pref)
        if sk in existing:
            continue
        lines.append(f'    "{sk}": "{dig}",')
    if not lines:
        return 0
    insert = "\n".join(lines)
    new_block = block.rstrip() + "\n" + insert + "\n"
    text2 = text[: m.start(1)] + new_block + text[m.end(1) :]
    path.write_text(text2, encoding="utf-8")
    return len(lines)


def main() -> None:
    log_lines: list[str] = []

    def log(msg: str) -> None:
        print(msg, flush=True)
        log_lines.append(msg)

    entries, digits = build_entries()
    log(f"entries={len(entries)} digit_known={len(digits)}")
    write_seed(entries)
    log(f"seed written: {SEED}")
    n = patch_series_digit_file(digits)
    log(f"SERIES_DIGIT appended={n}")
    merge = merge_catalog(entries)
    log(f"catalog merge {merge}")

    # harvest only prefixes lacking useful serials
    doc = store.load_catalog(force=True)
    bucket = doc["regions"]["japan_censored"]["prefixes"]
    need = []
    for k, v in sorted(bucket.items()):
        serials = v.get("serials") or []
        integrity = str(v.get("integrity") or "")
        if len(serials) >= 30 and integrity in {"sampled", "dense", "quick"}:
            continue
        if v.get("status") == "miss" and integrity == "dmm_miss":
            # retry misses after digit expansion
            need.append(k)
            continue
        need.append(k)
    log(f"harvest queue={len(need)}")

    def on_progress(msg: str) -> None:
        log(msg)

    # dense/sampled fill for real code coverage; hi_cap 900 covers most active lines
    result = harvest.harvest_japan_censored(
        prefixes=need,
        hi_cap=900,
        full_scan_limit=100,
        mode="dense",
        on_progress=on_progress,
    )
    log(f"harvest done ok={result.get('ok')} miss={result.get('miss')} err={result.get('error')}")
    summary = result.get("summary") or store.public_summary()
    for reg in summary.get("regions") or []:
        if reg.get("id") == "japan_censored":
            log(
                f"japan_censored prefixes={reg.get('prefix_count')} codes={reg.get('code_count')}"
            )
    OUT.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    log(f"log -> {OUT}")


if __name__ == "__main__":
    main()
