# -*- coding: utf-8 -*-
"""Rebuild catalog.seed.json from runtime data/prefix/catalog/catalog.json.

Keeps full prefix membership + maker metadata; strips harvested serials/codes
so the seed stays git-friendly. Runtime remains the harvest store.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SEED = ROOT / "apps" / "maps" / "prefixes" / "catalog.seed.json"
RUNTIME = ROOT / "data" / "prefix" / "catalog" / "catalog.json"
EXPORT = ROOT / "apps" / "maps" / "_export"

REGION_ORDER = [
    "japan_censored",
    "japan_uncensored",
    "japan_amateur",
    "fc2",
    "china",
    "western",
]

SEED_KEYS = (
    "prefix",
    "maker",
    "maker_zh",
    "maker_ja",
    "maker_en",
    "label_ja",
    "sources",
    "pad",
    "format",
    "dmm_digit",
    "code_read",
    "status",
    "integrity",
    "notes",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def to_seed_entry(pref: str, raw: dict) -> dict:
    ent = {k: deepcopy(raw.get(k)) for k in SEED_KEYS if k in raw or k in (
        "maker", "maker_zh", "maker_ja", "maker_en", "label_ja", "sources",
        "pad", "format", "dmm_digit", "code_read", "status", "integrity", "notes",
    )}
    ent["prefix"] = str(pref).strip().upper()
    ent["maker"] = str(ent.get("maker") or "")
    ent["maker_zh"] = str(ent.get("maker_zh") or "")
    ent["maker_ja"] = str(ent.get("maker_ja") or "")
    ent["maker_en"] = str(ent.get("maker_en") or "")
    ent["label_ja"] = str(ent.get("label_ja") or "")
    srcs = ent.get("sources") or []
    if not isinstance(srcs, list):
        srcs = []
    # drop avwikidb as a discovery source tag (feature removed); keep history elsewhere
    ent["sources"] = sorted({str(s) for s in srcs if str(s) and str(s) != "avwikidb"})
    ent["pad"] = int(ent.get("pad") or 3)
    ent["format"] = str(ent.get("format") or "{prefix}-{num}")
    ent["dmm_digit"] = str(ent.get("dmm_digit") or "")
    ent["code_read"] = str(ent.get("code_read") or "std3_dmm")
    ent["serials"] = []
    ent["codes"] = []
    ent["serial_min"] = 0
    ent["serial_max"] = 0
    ent["serial_max_hint"] = 0
    ent["latest_code"] = ""
    ent["code_count"] = 0
    ent["status"] = str(ent.get("status") or "active")
    ent["integrity"] = str(ent.get("integrity") or "unknown")
    ent["verified_at"] = ""
    notes = str(ent.get("notes") or "")
    # soften expand notes
    if "avwikidb扩前缀" in notes:
        notes = notes.replace("avwikidb扩前缀", "历史扩前缀").strip(" ·；")
    ent["notes"] = notes
    return ent


def main() -> None:
    rt = json.loads(RUNTIME.read_text(encoding="utf-8"))
    # backup old seed
    if SEED.exists():
        bak = SEED.with_suffix(".json.bak-before-data-promote")
        bak.write_bytes(SEED.read_bytes())
        print("seed backup:", bak)

    regions = {}
    for rid in REGION_ORDER:
        reg = (rt.get("regions") or {}).get(rid) or {}
        prefs_in = reg.get("prefixes") or {}
        prefs_out = {}
        for pref, ent in sorted(prefs_in.items(), key=lambda x: x[0]):
            pe = to_seed_entry(pref, ent or {})
            prefs_out[pe["prefix"]] = pe
        regions[rid] = {
            "id": rid,
            "label": reg.get("label") or rid,
            "prefixes": prefs_out,
        }

    seed = {
        "version": 1,
        "updated_at": _now(),
        "principle": "network-verified prefixes/codes; not warehouse-derived",
        "promoted_from": "data/prefix/catalog/catalog.json",
        "regions": regions,
    }
    SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    counts = {rid: len(regions[rid]["prefixes"]) for rid in REGION_ORDER}
    print("new seed counts:", counts, "total", sum(counts.values()))

    # export tables
    EXPORT.mkdir(parents=True, exist_ok=True)
    rows = []
    for rid in REGION_ORDER:
        for pref, meta in regions[rid]["prefixes"].items():
            rows.append(
                {
                    "region_id": rid,
                    "region_label": regions[rid]["label"],
                    "prefix": pref,
                    "maker": meta.get("maker") or "",
                    "maker_zh": meta.get("maker_zh") or "",
                    "maker_ja": meta.get("maker_ja") or "",
                    "maker_en": meta.get("maker_en") or "",
                    "label_ja": meta.get("label_ja") or "",
                    "code_read": meta.get("code_read") or "",
                    "pad": meta.get("pad") if meta.get("pad") is not None else "",
                    "format": meta.get("format") or "",
                    "dmm_digit": meta.get("dmm_digit") or "",
                    "status": meta.get("status") or "",
                    "notes": meta.get("notes") or "",
                    "sources": "|".join(meta.get("sources") or []),
                }
            )

    with (EXPORT / "region-maker-prefix.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    with (EXPORT / "region-maker-prefix.compact.tsv").open("w", encoding="utf-8") as f:
        f.write(
            "region_id\tregion_label\tprefix\tmaker\tmaker_zh\tmaker_ja\tcode_read\tstatus\tnotes\n"
        )
        for r in rows:

            def esc(s: str) -> str:
                return (s or "").replace("\t", " ").replace("\n", " ")

            f.write(
                "\t".join(
                    esc(r[k])
                    for k in [
                        "region_id",
                        "region_label",
                        "prefix",
                        "maker",
                        "maker_zh",
                        "maker_ja",
                        "code_read",
                        "status",
                        "notes",
                    ]
                )
                + "\n"
            )

    cnt = Counter(r["region_id"] for r in rows)
    lines = [
        "# 分区 · 厂牌 · 前缀（由 data/catalog 提升为种子）",
        "",
        f"- updated_at: `{seed['updated_at']}`",
        f"- promoted_from: `data/prefix/catalog/catalog.json`",
        f"- 前缀总数: **{len(rows)}**",
        "",
        "## 分区统计",
        "",
        "| region_id | label | 前缀数 |",
        "|---|---|---:|",
    ]
    for rid in REGION_ORDER:
        lines.append(
            f"| `{rid}` | {regions[rid]['label']} | {cnt.get(rid, 0)} |"
        )
    lines += ["", "## 各分区明细", ""]
    for rid in REGION_ORDER:
        items = [x for x in rows if x["region_id"] == rid]
        lines.append(f"### {regions[rid]['label']} (`{rid}`) · {len(items)}")
        lines.append("")
        lines.append("| prefix | maker | maker_zh | maker_ja | code_read | status | notes |")
        lines.append("|---|---|---|---|---|---|---|")
        for x in items:
            notes = (x["notes"] or "").replace("|", "/")
            if len(notes) > 80:
                notes = notes[:77] + "..."
            lines.append(
                f"| `{x['prefix']}` | {x['maker'] or '-'} | {x['maker_zh'] or '-'} | "
                f"{x['maker_ja'] or '-'} | `{x['code_read'] or '-'}` | `{x['status'] or '-'}` | "
                f"{notes or '-'} |"
            )
        lines.append("")

    (EXPORT / "region-maker-prefix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (EXPORT / "region-maker-prefix.json").write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": seed["updated_at"],
                "promoted_from": "data/prefix/catalog/catalog.json",
                "count": len(rows),
                "region_counts": dict(cnt),
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("exported", EXPORT)
    # verify seed == runtime prefix sets
    mismatch = []
    for rid in REGION_ORDER:
        s = set(regions[rid]["prefixes"])
        r = set((rt.get("regions") or {}).get(rid, {}).get("prefixes") or {})
        if s != r:
            mismatch.append((rid, sorted(s - r)[:5], sorted(r - s)[:5]))
    print("prefix-set match:", "OK" if not mismatch else mismatch)


if __name__ == "__main__":
    main()
