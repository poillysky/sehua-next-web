# -*- coding: utf-8 -*-
"""审计本地扫码：准确性 / 缺失 / 未命中原因。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import bitmagnet_pg  # noqa: E402
from app import pg  # noqa: E402
from app import prefix_catalog_store as store  # noqa: E402
from app import prefix_ranges as pr  # noqa: E402
from app.core.region_meta import REGION_ORDER  # noqa: E402
from app.search.av import extract_maker_codes, resolve_maker_shape  # noqa: E402

OUT = ROOT / "data" / "debug" / "prefix-scan-audit.json"


def sehua_count(pat: str) -> int:
    rows = pg.query(
        """
        SELECT count(*)::int AS n FROM ed2k_resources r
        LEFT JOIN LATERAL (
          SELECT title FROM resource_sources
          WHERE hash = r.hash ORDER BY created_at DESC LIMIT 1
        ) rs ON TRUE
        WHERE COALESCE(r.filename,'') ILIKE %s
           OR COALESCE(rs.title,'') ILIKE %s
        """,
        [pat, pat],
    )
    return int(rows[0]["n"])


def sehua_sample(pat: str, lim: int = 6) -> list[dict]:
    return pg.query(
        """
        SELECT COALESCE(r.filename,'') AS f, COALESCE(rs.title,'') AS t
        FROM ed2k_resources r
        LEFT JOIN LATERAL (
          SELECT title FROM resource_sources
          WHERE hash = r.hash ORDER BY created_at DESC LIMIT 1
        ) rs ON TRUE
        WHERE COALESCE(r.filename,'') ILIKE %s
           OR COALESCE(rs.title,'') ILIKE %s
        LIMIT %s
        """,
        [pat, pat, lim],
    )


def bit_count(pat: str) -> int:
    try:
        rows = bitmagnet_pg.query(
            "SELECT count(*)::int AS n FROM torrents WHERE name ILIKE %s",
            [pat],
        )
        return int(rows[0]["n"])
    except Exception:
        return -1


def classify_miss(prefix: str) -> dict:
    shape = resolve_maker_shape(prefix)
    # 常见变体
    variants = [prefix]
    if prefix == "PACOMA":
        variants += ["PACO", "パコ"]
    if prefix == "SMMIRACLE":
        variants += ["SM-MIRACLE", "SMMIRACLE", "e0"]
    if prefix == "SIROHAME":
        variants += ["SIRO-HAME", "HAME"]
    if prefix == "RFILE":
        variants += ["REBD", "R-FILE"]
    if prefix == "ORECZ":
        variants += ["230ORECZ", "OREC"]
    if prefix == "FELLATIOJAPAN":
        variants += ["FellatioJapan", "FELLATIO"]
    if prefix == "ROSELIPFETISH":
        variants += ["RoseLip", "ROSELIP"]
    if prefix == "VIXENPLUS":
        variants += ["Vixen", "VIXEN.PLUS"]
    if prefix == "AGIRIENE":
        variants += ["A Girl By Night", "AGIRLS"]
    if prefix.startswith("107") or prefix.startswith("406"):
        variants += [prefix[3:], prefix.lower()]

    reasons = []
    any_rows = False
    extract_ok = []
    for v in variants:
        pat = f"%{v}%"
        sc = sehua_count(pat)
        bc = bit_count(pat)
        if sc > 0 or bc > 0:
            any_rows = True
        samples = sehua_sample(pat, 5) if sc > 0 else []
        got = []
        for r in samples:
            blob = f"{r.get('f')}\n{r.get('t')}"
            got.extend(extract_maker_codes(blob, prefix))
        if got:
            extract_ok.extend(got[:3])
        reasons.append(
            {
                "variant": v,
                "sehua": sc,
                "bitmagnet": bc,
                "extract_sample": sorted(set(got))[:5],
                "row_sample": [
                    (r.get("f") or r.get("t") or "")[:90] for r in samples[:2]
                ],
            }
        )

    if extract_ok:
        cause = "extract_miss_in_one_pass"  # 库里能抽到，全表扫漏了
    elif any_rows:
        cause = "rows_but_no_code_shape"  # 有文本但抽不出本前缀号
    else:
        cause = "absent_in_both_dbs"  # 两库基本没有

    return {
        "prefix": prefix,
        "shape": shape,
        "cause": cause,
        "probes": reasons,
    }


def main() -> None:
    doc = store.load_catalog(force=True)
    misses = []
    for rid in REGION_ORDER:
        for p, e in sorted((doc["regions"][rid].get("prefixes") or {}).items()):
            if not (e.get("codes") or e.get("serials")):
                misses.append((rid, p))

    print(f"misses={len(misses)} probing…", flush=True)
    miss_detail = []
    by_cause = {}
    for rid, p in misses:
        d = classify_miss(p)
        d["region"] = rid
        miss_detail.append(d)
        by_cause[d["cause"]] = by_cause.get(d["cause"], 0) + 1
        print(f"  {rid:16} {p:16} → {d['cause']}", flush=True)

    # accuracy samples
    bad_examples = []
    for rid in REGION_ORDER:
        for p, e in (doc["regions"][rid].get("prefixes") or {}).items():
            codes = e.get("codes") or []
            if not codes:
                continue
            shape = resolve_maker_shape(p)
            if shape == "std":
                for c in codes:
                    m = re.search(r"-(\d+)$", c)
                    if not m:
                        continue
                    n = int(m.group(1))
                    if 1990 <= n <= 2035:
                        bad_examples.append(
                            {"kind": "year_as_serial", "prefix": p, "code": c, "region": rid}
                        )
                    elif n >= 10000 and p.isalpha() and len(p) <= 5:
                        bad_examples.append(
                            {
                                "kind": "absurd_serial",
                                "prefix": p,
                                "code": c,
                                "region": rid,
                            }
                        )
            if shape in {"fc2", "fc2ppv"}:
                for c in codes:
                    m = re.search(r"(\d+)$", c)
                    if m and len(m.group(1)) >= 9:
                        bad_examples.append(
                            {
                                "kind": "fc2_id_too_long",
                                "prefix": p,
                                "code": c,
                                "region": rid,
                            }
                        )

    # dedupe kinds
    seen = set()
    bad_dedup = []
    for b in bad_examples:
        k = (b["kind"], b["prefix"], b["code"])
        if k in seen:
            continue
        seen.add(k)
        bad_dedup.append(b)
        if len(bad_dedup) >= 80:
            break

    # coverage: use robust max vs raw
    gap_notes = []
    for rid in ("japan_censored", "japan_amateur", "china"):
        for p, e in (doc["regions"][rid].get("prefixes") or {}).items():
            if resolve_maker_shape(p) != "std":
                continue
            serials = e.get("serials") or []
            if len(serials) < 30:
                continue
            raw_max = max(serials)
            rob = pr.robust_serial_max(serials)
            if raw_max > rob * 2 and raw_max - rob > 100:
                gap_notes.append(
                    {
                        "region": rid,
                        "prefix": p,
                        "count": len(serials),
                        "raw_max": raw_max,
                        "robust_max": rob,
                        "note": "raw_max 被离群高号抬高，覆盖率虚低",
                    }
                )

    report = {
        "miss_n": len(misses),
        "miss_by_cause": by_cause,
        "miss_detail": miss_detail,
        "accuracy_bad_sample": bad_dedup,
        "outlier_inflated_max": gap_notes[:40],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("by_cause", by_cause, flush=True)
    print("bad_sample", len(bad_dedup), "outlier_max", len(gap_notes), flush=True)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
