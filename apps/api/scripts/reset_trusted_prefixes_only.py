# -*- coding: utf-8 -*-
"""Keep only trusted prefixes; drop unverified local-db-only junk."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import prefix_catalog_store as store  # noqa: E402
from app import prefix_ranges as pr  # noqa: E402
from app.region_meta import REGION_META, REGION_ORDER, std_prefix  # noqa: E402

SEED = ROOT / "apps" / "web" / "src" / "config" / "prefix-catalog.seed.json"


def clean(p: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", std_prefix(p).replace("-", ""))


def trusted_by_region() -> dict[str, set[str]]:
    out = {rid: set() for rid in REGION_ORDER}
    # makers
    files = [
        (
            "av-makers.japan.json",
            {
                "有码": "japan_censored",
                "写真": "japan_gravure",
                "无码": "japan_uncensored",
                "素人": "japan_amateur",
                "FC2": "fc2",
            },
        ),
        ("av-makers.china.json", {"国产": "china"}),
        ("av-makers.western.json", {"欧美": "western"}),
    ]
    for name, kinds in files:
        data = json.loads(
            (ROOT / "apps/web/src/config" / name).read_text(encoding="utf-8")
        )
        for m in data:
            rid = kinds.get(m.get("kind"))
            if not rid:
                continue
            for p in m.get("prefixes") or []:
                out[rid].add(clean(p))

    # dmm ok → censored (and amateur if digit)
    verify = json.loads(
        (ROOT / "data/_debug/dmm-prefix-verify.json").read_text(encoding="utf-8")
    )
    for row in verify.get("ok_list") or []:
        p = clean(row.get("prefix") or "")
        if not p:
            continue
        kind = row.get("kind")
        if kind == "素人" or re.match(r"^\d{2,3}[A-Z]", p):
            out["japan_amateur"].add(p)
        elif kind == "写真":
            out["japan_gravure"].add(p)
        else:
            out["japan_censored"].add(p)

    # ranges: assign digit→amateur else censored (skip western/uncensored shells)
    ranges = json.loads(
        (ROOT / "apps/web/src/config/prefix-code-ranges.json").read_text(encoding="utf-8")
    )["ranges"]
    skip = {clean(x) for x in pr.SKIP_PREFIXES}
    china = pr.load_china_prefixes()
    for k in ranges:
        p = clean(k)
        if not p or p in skip:
            # still keep skip items in proper region
            if p in china or p == "JVID":
                out["china"].add(p)
            elif p in {"FC2", "FC2PPV"}:
                out["fc2"].add(p)
            elif p in {
                "CARIB",
                "CARIBPR",
                "1PON",
                "HEYZO",
                "PACO",
                "10MU",
                "H4610",
                "C0930",
                "H0930",
                "KIN8",
                "HEYDOUGA",
                "MESUBUTA",
                "TOKYOHOT",
                "GACHINCO",
            }:
                out["japan_uncensored"].add(p)
            elif p.isalpha() and len(p) >= 5:
                out["western"].add(p)
            continue
        if p in china:
            out["china"].add(p)
        elif re.match(r"^\d{2,3}[A-Z]", p):
            out["japan_amateur"].add(p)
        else:
            out["japan_censored"].add(p)

    # force shells
    out["fc2"] |= {"FC2", "FC2PPV"}
    out["japan_uncensored"] |= {
        "CARIB",
        "CARIBPR",
        "1PON",
        "HEYZO",
        "PACO",
        "10MU",
        "H4610",
        "C0930",
        "H0930",
        "KIN8",
        "NYOSHIN",
        "HEYDOUGA",
    }
    out["japan_gravure"] |= {
        "ENFD",
        "OAE",
        "REBD",
        "REBDB",
        "MBRAA",
        "MBRBA",
        "MBDD",
        "SYD",
        "GGSID",
        "BFAZ",
    }

    # keep authority-marked entries that already have maker or javbus/mgstage/dmm sources
    doc = store.load_catalog(force=True)
    for rid in REGION_ORDER:
        for k, e in (doc["regions"][rid]["prefixes"] or {}).items():
            srcs = set(e.get("sources") or [])
            notes = str(e.get("notes") or "")
            if e.get("serials"):
                out[rid].add(k)
                continue
            if e.get("maker") and "本地库确认" not in notes:
                out[rid].add(k)
                continue
            if srcs & {"dmm", "javbus", "mgstage", "carib", "madou", "heyzo", "1pondo"}:
                if "本地库确认" not in notes or e.get("maker"):
                    out[rid].add(k)
    return out


def main() -> None:
    trusted = trusted_by_region()
    doc = store.load_catalog(force=True)
    removed = 0
    kept_extra = 0

    for rid in REGION_ORDER:
        bucket = doc["regions"][rid]["prefixes"]
        allow = trusted[rid]
        for key in list(bucket.keys()):
            ent = bucket[key]
            if key in allow:
                # strip misleading local-only note if also trusted elsewhere
                continue
            # drop
            del bucket[key]
            removed += 1
        # ensure all trusted present
        for key in allow:
            if not key:
                continue
            if key in bucket:
                continue
            pad = 4 if re.match(r"^\d", key) else (0 if rid in {"fc2", "japan_uncensored", "china", "western"} else 3)
            bucket[key] = store._normalize_prefix_entry(
                key,
                {
                    "maker": "",
                    "pad": pad,
                    "format": "{prefix}-{num}" if rid != "fc2" else (
                        "FC2-PPV-{num}" if key == "FC2PPV" else "FC2-{num}"
                    ),
                    "sources": ["trusted"],
                    "serials": [],
                    "notes": "片商表/ranges/DMM/权威站",
                    "status": "active",
                    "integrity": "unknown",
                },
            )
            kept_extra += 1

    store.save_catalog(doc)

    seed = json.loads(SEED.read_text(encoding="utf-8"))
    for rid in REGION_ORDER:
        prefs = doc["regions"][rid]["prefixes"]
        out = {}
        for key, ent in sorted(prefs.items()):
            row = {
                "maker": ent.get("maker") or "",
                "pad": int(ent.get("pad") or 0),
                "format": ent.get("format") or "{prefix}-{num}",
                "sources": list(ent.get("sources") or ["site"]),
                "serials": [],
            }
            if ent.get("dmm_digit") not in (None,):
                row["dmm_digit"] = ent.get("dmm_digit")
            if ent.get("notes"):
                row["notes"] = ent["notes"]
            out[key] = row
        seed["regions"][rid] = {
            "id": rid,
            "label": REGION_META[rid]["label"],
            "prefixes": out,
        }
    SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = store.public_summary()
    print(f"removed_untrusted={removed} ensured_trusted={kept_extra}")
    for r in summary.get("regions") or []:
        print(f"{r['id']:18} prefixes={r.get('prefix_count')}")
    print("TOTAL", summary.get("prefix_total"))


if __name__ == "__main__":
    main()
