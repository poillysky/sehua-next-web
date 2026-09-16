#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-check E2E scrape results for one code against a golden consensus."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# SONE-001 黄金共识（javbus/dmm 正片，非 outlet）
GOLDEN: dict[str, dict[str, Any]] = {
    "SONE-001": {
        "code": "SONE-001",
        "actor": "三田真鈴",
        "studio_contains": ["エスワン", "S1", "SONE"],
        "date": "2023-12-08",
        "year": "2023",
        "title_must": ["三田真鈴"],
        "title_junk": ["アウトレット", "プレコレ", "会員", "登入", "login"],
        "poster_junk": ["now_printing", "outlet"],
    }
}


def _norm_code(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def analyze_one(source_id: str, code: str, *, include_flare: bool) -> dict[str, Any]:
    from scripts.e2e_enrich_sources import run_one

    raw = run_one(source_id, code=code, include_flare=include_flare)
    gold = GOLDEN.get(code.upper()) or {}
    sample = raw.get("sample") or {}
    issues: list[str] = []
    ok_fields: list[str] = []

    if not raw.get("ok") and not sample:
        return {
            "id": source_id,
            "code": code,
            "fetchOk": False,
            "accuracyOk": False,
            "ms": raw.get("ms"),
            "error": raw.get("error"),
            "issues": ["fetch_failed"],
            "sample": None,
            "e2e": raw,
        }

    got_code = str(sample.get("code") or "")
    if _norm_code(got_code) == _norm_code(code):
        ok_fields.append("code")
    else:
        issues.append(f"code_mismatch:{got_code}")

    actors = [str(a) for a in (sample.get("actors") or [])]
    want_actor = str(gold.get("actor") or "")
    if want_actor:
        if want_actor in actors:
            ok_fields.append("actor")
        else:
            issues.append(f"actor_mismatch:{actors}")
    elif actors:
        ok_fields.append("actor")

    studio = str(sample.get("studio") or "")
    needles = gold.get("studio_contains") or []
    if needles:
        if any(n in studio for n in needles):
            ok_fields.append("studio")
        else:
            issues.append(f"studio_mismatch:{studio}")
    elif studio:
        ok_fields.append("studio")

    date = str(sample.get("date") or "")
    want_date = str(gold.get("date") or "")
    if want_date:
        if date.startswith(want_date):
            ok_fields.append("date")
        else:
            issues.append(f"date_mismatch:got={date} want={want_date}")
    elif date:
        ok_fields.append("date")

    year = str(sample.get("year") or "")
    want_year = str(gold.get("year") or "")
    if want_year:
        if year == want_year:
            ok_fields.append("year")
        else:
            issues.append(f"year_mismatch:got={year} want={want_year}")

    title = str(sample.get("title") or "")
    for junk in gold.get("title_junk") or []:
        if junk and junk in title:
            issues.append(f"title_junk:{junk}")
    for must in gold.get("title_must") or []:
        if must and must not in title:
            issues.append(f"title_missing:{must}")
    if title and not any(i.startswith("title_") for i in issues):
        ok_fields.append("title")

    poster = str(sample.get("posterUrl") or "")
    for junk in gold.get("poster_junk") or []:
        if junk and junk.lower() in poster.lower():
            issues.append(f"poster_junk:{junk}")
    if poster.startswith("http") and not any(i.startswith("poster_") for i in issues):
        ok_fields.append("poster")

    # outlet / reprint heuristics
    if "アウトレット" in title or "プレコレ" in title:
        issues.append("likely_outlet_or_reprint")

    accuracy_ok = raw.get("ok") and not issues
    return {
        "id": source_id,
        "code": code,
        "fetchOk": bool(raw.get("ok")),
        "accuracyOk": bool(accuracy_ok),
        "ms": raw.get("ms"),
        "error": raw.get("error") or "",
        "okFields": ok_fields,
        "issues": issues,
        "sample": sample,
        "e2eSummary": raw.get("summary"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--code", default="SONE-001")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from app.core.db import init_db
    from app import scrap_enrich_strategy as strat

    init_db()
    include_flare = bool(strat.get_strategy().get("includeFlare", True))
    print(f"ANALYZE {args.id} · {args.code} …", flush=True)
    one = analyze_one(args.id, args.code.upper(), include_flare=include_flare)
    mark = "ACCURATE" if one["accuracyOk"] else ("FETCH_OK_BUT_WRONG" if one["fetchOk"] else "FAIL")
    print(f"  {mark}  {one['ms']}ms  issues={one.get('issues') or '-'}", flush=True)
    sample = one.get("sample") or {}
    if sample:
        print(
            f"  actor={sample.get('actors')}  date={sample.get('date')}  "
            f"studio={sample.get('studio')}  title={(sample.get('title') or '')[:50]}",
            flush=True,
        )
    out = Path(
        args.out
        or (ROOT / "_gap_reports" / f"e2e_analyze_{args.id}.json")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(one, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  report={out}", flush=True)
    return 0 if one["accuracyOk"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
