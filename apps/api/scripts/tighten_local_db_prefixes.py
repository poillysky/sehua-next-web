# -*- coding: utf-8 -*-
"""收紧本地库补入的前缀：两边库都出现，或命中足够次数。"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import bitmagnet_pg  # noqa: E402
from app import pg  # noqa: E402
from app import prefix_catalog_store as store  # noqa: E402
from app import prefix_ranges as pr  # noqa: E402
from app.search.av import is_western_studio_prefix  # noqa: E402
from app.core.region_meta import REGION_META, REGION_ORDER, std_prefix  # noqa: E402

SEED = ROOT / "apps" / "web" / "src" / "config" / "prefix-catalog.seed.json"
REPORT = ROOT / "data" / "_debug" / "prefix-from-local-dbs.json"

CODE_RE = re.compile(
    r"(?<![A-Z0-9])([0-9]{0,3}[A-Z]{2,12})[-_ ](\d{2,6})(?![A-Z0-9])",
    re.I,
)


def clean(p: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", std_prefix(p).replace("-", ""))


def extract(text: str, c: Counter) -> None:
    for m in CODE_RE.finditer(text or ""):
        p = clean(m.group(1))
        if not p or p in pr.NOISE or len(p) < 2 or len(p) > 12 or p.isdigit():
            continue
        c[p] += 1


def scan_sehua() -> Counter:
    c: Counter = Counter()
    rows = pg.query(
        """
        SELECT COALESCE(r.filename,'') AS filename,
               COALESCE(rs.title,'') AS title
        FROM ed2k_resources r
        LEFT JOIN LATERAL (
          SELECT title FROM resource_sources
          WHERE hash = r.hash ORDER BY created_at DESC LIMIT 1
        ) rs ON TRUE
        """
    )
    for row in rows:
        extract(f"{row.get('filename')}\n{row.get('title')}".upper(), c)
    return c


def scan_bitmagnet() -> Counter:
    c: Counter = Counter()
    for table, col, lim in (
        ("content", "title", 200000),
        ("content", "original_title", 200000),
        ("torrents", "name", 300000),
    ):
        rows = bitmagnet_pg.query(
            f'SELECT COALESCE("{col}",\'\') AS txt FROM "{table}" LIMIT {lim}'
        )
        for row in rows:
            extract(str(row.get("txt") or "").upper(), c)
    return c


def maker_set() -> set[str]:
    out: set[str] = set()
    for name in (
        "av-makers.japan.json",
        "av-makers.china.json",
        "av-makers.western.json",
    ):
        data = json.loads(
            (ROOT / "apps/web/src/config" / name).read_text(encoding="utf-8")
        )
        for m in data:
            for p in m.get("prefixes") or []:
                out.add(clean(p))
    ranges = json.loads(
        (ROOT / "apps/web/src/config/prefix-code-ranges.json").read_text(encoding="utf-8")
    )["ranges"]
    out |= {clean(k) for k in ranges}
    out |= {clean(k) for k in pr.SKIP_PREFIXES}
    return out


def guess_region(p: str, makers: dict[str, str]) -> str:
    if p in makers:
        return makers[p]
    if p in {"FC2", "FC2PPV"}:
        return "fc2"
    if p in pr.load_china_prefixes() or p.startswith(("MD", "91", "MKY", "MDSR", "MSD")):
        return "china"
    if re.match(r"^\d{2,3}[A-Z]{2,8}$", p):
        return "japan_amateur"
    if is_western_studio_prefix(p) or (
        p in pr.SKIP_PREFIXES and p.isalpha() and len(p) >= 5
    ):
        return "western"
    return "japan_censored"


def load_maker_regions() -> dict[str, str]:
    mapping: dict[str, str] = {}
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
                mapping[clean(p)] = rid
    return mapping


def main() -> None:
    print("rescan sehua…", flush=True)
    sehua = scan_sehua()
    print(f"  sehua={len(sehua)}", flush=True)
    print("rescan bitmagnet…", flush=True)
    bit = scan_bitmagnet()
    print(f"  bitmagnet={len(bit)}", flush=True)

    known = maker_set()
    regions = load_maker_regions()
    both = set(sehua) & set(bit)
    print(f"both={len(both)}", flush=True)

    # trusted new set
    trusted: set[str] = set()
    for p in known:
        trusted.add(p)
    for p in both:
        if sehua[p] + bit[p] >= 4:
            trusted.add(p)
    for p, n in sehua.items():
        if n >= 15 and p in bit and bit[p] >= 2:
            trusted.add(p)
    for p, n in bit.items():
        if n >= 20 and p in sehua and sehua[p] >= 2:
            trusted.add(p)

    # rebuild catalog prefixes for regions: keep non-local-only entries always;
    # for local-db-only entries, require trusted
    doc = store.load_catalog(force=True)
    removed = 0
    kept_local = 0
    added = 0

    # first purge weak local-only
    for rid in REGION_ORDER:
        bucket = doc["regions"][rid]["prefixes"]
        for key in list(bucket.keys()):
            ent = bucket[key]
            srcs = set(ent.get("sources") or [])
            notes = str(ent.get("notes") or "")
            local_only = (
                srcs <= {"local-db", "sehua", "bitmagnet", "authority", "site", "dmm"}
                and "本地库确认" in notes
                and not ent.get("maker")
                and not (ent.get("serials") or [])
            )
            # broader: if only local-db source and no maker/serials
            if srcs == {"local-db"} or (
                "local-db" in srcs
                and not ent.get("maker")
                and not (ent.get("serials") or [])
                and key not in known
            ):
                if key not in trusted:
                    del bucket[key]
                    removed += 1
                else:
                    kept_local += 1

    # add trusted missing
    for p in sorted(trusted):
        rid = guess_region(p, regions)
        bucket = doc["regions"][rid]["prefixes"]
        if p in bucket:
            cur = bucket[p]
            srcs = set(cur.get("sources") or [])
            srcs.add("local-db")
            cur["sources"] = sorted(srcs)
            if "本地库" not in str(cur.get("notes") or ""):
                cur["notes"] = (str(cur.get("notes") or "") + " · 本地库确认").strip(" ·")
            serials = list(cur.get("serials") or [])
            bucket[p] = store._normalize_prefix_entry(p, {**cur, "serials": serials})
            if serials:
                bucket[p]["serials"] = serials
                bucket[p] = store._normalize_prefix_entry(p, bucket[p])
            continue
        bucket[p] = store._normalize_prefix_entry(
            p,
            {
                "maker": "",
                "pad": 4 if re.match(r"^\d", p) else 3,
                "format": "{prefix}-{num}",
                "sources": ["local-db"],
                "serials": [],
                "notes": f"本地库确认 · sehua={sehua.get(p,0)} bit={bit.get(p,0)}",
                "status": "active",
                "integrity": "unknown",
            },
        )
        added += 1

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
    report = {
        "sehua": len(sehua),
        "bitmagnet": len(bit),
        "both": len(both),
        "trusted": len(trusted),
        "removed_weak": removed,
        "kept_local": kept_local,
        "added": added,
        "summary": summary,
        "new_sample": sorted(
            [
                p
                for p in trusted
                if p not in known
            ]
        )[:80],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"trusted={len(trusted)} removed_weak={removed} added={added}",
        flush=True,
    )
    for r in summary.get("regions") or []:
        print(f"{r['id']:18} prefixes={r.get('prefix_count')}", flush=True)
    print("TOTAL", summary.get("prefix_total"), flush=True)


if __name__ == "__main__":
    main()
