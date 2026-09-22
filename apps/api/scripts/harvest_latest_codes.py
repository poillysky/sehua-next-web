# -*- coding: utf-8 -*-
"""搜索综合站 → 排序取每个前缀最新番号。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.prefix import catalog_harvest as harvest  # noqa: E402
from app.prefix import catalog_store as store  # noqa: E402

OUT = ROOT / "data" / "debug" / "prefix-latest-codes.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--regions",
        default="japan_censored,japan_amateur",
        help="comma regions",
    )
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pages", type=int, default=2, help="MissAV search pages")
    args = ap.parse_args()

    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    report: dict = {"regions": {}}

    def prog(msg: str) -> None:
        print(msg, flush=True)

    for rid in regions:
        print(f"\n======== {rid} ========", flush=True)
        result = harvest.harvest_latest_via_search(
            rid,
            pages=args.pages,
            limit=args.limit,
            on_progress=prog,
        )
        report["regions"][rid] = {
            "ok": result["ok"],
            "miss": result["miss"],
            "error": result["error"],
            "latest_sample": dict(list((result.get("latest") or {}).items())[:40]),
            "latest_count": len(result.get("latest") or {}),
        }
        print(
            f"DONE {rid}: ok={result['ok']} miss={result['miss']} err={result['error']}",
            flush=True,
        )

    doc = store.load_catalog(force=True)
    full: dict[str, dict[str, str]] = {}
    for rid in regions:
        if rid not in doc["regions"]:
            continue
        bucket = {}
        for pref, ent in sorted((doc["regions"][rid].get("prefixes") or {}).items()):
            code = str(ent.get("latest_code") or "")
            if not code and ent.get("serials"):
                code = store.format_code(ent, int(ent["serials"][-1]))
            if code:
                bucket[pref] = code
        full[rid] = bucket
    report["latest_by_region"] = full
    report["summary"] = store.public_summary(doc)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\nwrote", OUT, flush=True)


if __name__ == "__main__":
    main()
