# -*- coding: utf-8 -*-
"""Fill empty prefix makers via DMM GraphQL; report leftovers."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.prefix import catalog_store as store
from app.prefix.catalog_dmm import content_id, gql_ppv, guess_digits, resolve_digit
from app.core.region_meta import REGION_ORDER, REGION_META

OUT_TSV = ROOT / "data" / "debug" / "prefixes-no-maker-after-dmm.tsv"
OUT_FILLED = ROOT / "data" / "debug" / "prefixes-maker-filled-dmm.tsv"


def empty_items(doc: dict) -> list[tuple[str, str, dict]]:
    rows: list[tuple[str, str, dict]] = []
    for rid in REGION_ORDER:
        prefs = (doc.get("regions") or {}).get(rid, {}).get("prefixes") or {}
        for p, e in sorted(prefs.items()):
            ent = e if isinstance(e, dict) else {}
            if str(ent.get("maker") or "").strip():
                continue
            rows.append((rid, str(p), ent))
    return rows


def probe_maker(http: httpx.Client, prefix: str) -> tuple[str, str, str]:
    """Return (maker_ja, digit, cid_or_note)."""
    # Fast path: few serials × digit guesses
    for dig in guess_digits(prefix):
        for n in (1, 50, 100, 200):
            info = gql_ppv(http, content_id(prefix, n, dig), timeout=8.0)
            if info and str(info.get("maker_ja") or "").strip():
                return (
                    str(info["maker_ja"]).strip(),
                    dig,
                    str(info.get("cid") or ""),
                )
            time.sleep(0.03)
    # Slower path via resolve_digit
    hit = resolve_digit(http, prefix, sample_ns=(1, 75, 150, 300))
    if hit:
        dig, info = hit
        maker = str(info.get("maker_ja") or "").strip()
        if maker:
            return maker, dig, str(info.get("cid") or "")
    return "", "", ""


def main() -> None:
    doc = store.load_catalog(force=True)
    items = empty_items(doc)
    print(f"empty before: {len(items)}", flush=True)

    filled: list[tuple[str, str, str, str]] = []
    remain: list[tuple[str, str]] = []

    http = httpx.Client(follow_redirects=True, timeout=12.0)
    try:
        for i, (rid, pref, ent) in enumerate(items, 1):
            maker, dig, cid = probe_maker(http, pref)
            if maker:
                ent = dict(ent)
                ent["prefix"] = pref
                ent["maker"] = maker
                if not str(ent.get("maker_ja") or "").strip():
                    ent["maker_ja"] = maker
                if dig and not str(ent.get("dmm_digit") or "").strip():
                    ent["dmm_digit"] = dig
                srcs = set(ent.get("sources") or [])
                srcs.add("dmm")
                ent["sources"] = sorted(srcs)
                notes = str(ent.get("notes") or "").strip()
                tag = f"DMM回填片商:{maker}"
                if tag not in notes:
                    ent["notes"] = f"{notes} · {tag}".strip(" ·") if notes else tag
                # normalize via store helper
                pe = store._normalize_prefix_entry(pref, ent)
                doc["regions"][rid]["prefixes"][pe["prefix"]] = pe
                filled.append((rid, pref, maker, cid or dig))
                print(f"[{i}/{len(items)}] OK {rid} {pref} -> {maker}", flush=True)
            else:
                remain.append((rid, pref))
                print(f"[{i}/{len(items)}] -- {rid} {pref}", flush=True)
            time.sleep(0.15)
            # checkpoint every 40
            if i % 40 == 0:
                store.save_catalog(doc)
                print(f"  checkpoint saved ({i})", flush=True)
    finally:
        http.close()

    store.save_catalog(doc)
    # also refresh seed so maps stay aligned
    try:
        seed_path = store.SEED_PATH
        seed = store.load_seed()
        for rid in REGION_ORDER:
            if rid not in doc["regions"]:
                continue
            seed.setdefault("regions", {}).setdefault(
                rid, {"id": rid, "label": REGION_META[rid]["label"], "prefixes": {}}
            )
            for pref, ent in (doc["regions"][rid].get("prefixes") or {}).items():
                if str((ent or {}).get("maker") or "").strip():
                    # only update maker fields into seed if prefix exists or always merge filled
                    cur = (seed["regions"][rid].get("prefixes") or {}).get(pref)
                    if isinstance(cur, dict):
                        if not str(cur.get("maker") or "").strip():
                            cur["maker"] = ent.get("maker") or ""
                            if ent.get("maker_ja"):
                                cur["maker_ja"] = ent.get("maker_ja")
                            if ent.get("dmm_digit") and not cur.get("dmm_digit"):
                                cur["dmm_digit"] = ent.get("dmm_digit")
                            srcs = set(cur.get("sources") or [])
                            srcs.add("dmm")
                            cur["sources"] = sorted(srcs)
                    else:
                        seed["regions"][rid].setdefault("prefixes", {})[pref] = {
                            k: ent.get(k)
                            for k in (
                                "maker",
                                "maker_ja",
                                "pad",
                                "format",
                                "sources",
                                "serials",
                                "dmm_digit",
                                "notes",
                            )
                            if ent.get(k) not in (None, "", [])
                        }
        seed_path.write_text(
            json.dumps(seed, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"seed updated: {seed_path}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"seed update skipped: {e}", flush=True)

    OUT_TSV.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILLED.write_text(
        "region\tprefix\tmaker\tcid_or_digit\n"
        + "\n".join(f"{a}\t{b}\t{c}\t{d}" for a, b, c, d in filled)
        + ("\n" if filled else ""),
        encoding="utf-8",
    )
    OUT_TSV.write_text(
        "region\tlabel\tprefix\n"
        + "\n".join(
            f"{rid}\t{REGION_META[rid]['label']}\t{pref}" for rid, pref in remain
        )
        + ("\n" if remain else ""),
        encoding="utf-8",
    )

    print("\n=== DONE ===", flush=True)
    print(f"filled: {len(filled)}", flush=True)
    print(f"remain: {len(remain)}", flush=True)
    print(f"remain file: {OUT_TSV}", flush=True)
    by: dict[str, list[str]] = {}
    for rid, pref in remain:
        by.setdefault(rid, []).append(pref)
    for rid, prefs in by.items():
        label = REGION_META[rid]["label"]
        print(f"\n{label} ({len(prefs)}):", flush=True)
        print(", ".join(prefs), flush=True)


if __name__ == "__main__":
    main()
