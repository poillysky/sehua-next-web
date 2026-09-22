# -*- coding: utf-8 -*-
"""Probe uncensored codes without dedicated official scrapers."""
from __future__ import annotations

import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

PREFS = [
    "HEYDOUGA",
    "XXXAV",
    "XXX-AV",
    "LEGSJAPAN",
    "FELLATIOJAPAN",
    "HANDJOBJAPAN",
    "SPERMMANIA",
    "RHJ",
    "URALESBIAN",
    "URABUKKAKE",
    "ROSELIP",
    "SMMIRACLE",
    "JAPORNXXX",
    "CWPBD",
    "LAFBD",
]

# fallback aggregators currently used for uncensored
AGGS = ["avsox", "javbus", "airav_io", "miss_av"]


def find_samples(limit_per_pref: int = 2) -> dict[str, list[str]]:
    prefs = list(PREFS)
    rx = re.compile(
        r"\b((" + "|".join(re.escape(p) for p in prefs) + r")[-_][A-Z0-9]{2,16})\b",
        re.I,
    )
    seen: set[str] = set()
    found: list[str] = []
    paths: list[Path] = [
        API_ROOT.parent / "maps" / "scrape" / "code-titles.json",
        API_ROOT / "_gap_reports",
    ]
    for base in paths:
        files = (
            [base]
            if base.is_file()
            else list(base.rglob("*.md"))
            + list(base.rglob("*.txt"))
            + list(base.rglob("*.json"))
        )
        for f in files[:400]:
            try:
                t = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if len(t) > 6_000_000:
                continue
            for m in rx.finditer(t):
                c = m.group(1).upper().replace("_", "-")
                c = re.sub(r"^XXX-AV-", "XXXAV-", c)
                if c not in seen:
                    seen.add(c)
                    found.append(c)

    try:
        from app.core.db import get_meta_pool
        from app.scrap_library.embed import TABLE

        pool = get_meta_pool()
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT code, prefix
                FROM {TABLE}
                WHERE region = '日本无码'
                  AND (
                    prefix = ANY(%s)
                    OR code ~* '^(HEYDOUGA|XXX-?AV|LEGSJAPAN|FELLATIOJAPAN|HANDJOBJAPAN|SPERMMANIA|RHJ|URALESBIAN|URABUKKAKE|ROSELIP|SMMIRACLE|JAPORNXXX|CWPBD|LAFBD)[-_]'
                  )
                ORDER BY prefix, code
                LIMIT 200
                """,
                (prefs,),
            )
            for r in cur.fetchall() or []:
                d = dict(r)
                c = str(d.get("code") or "").strip().upper().replace("_", "-")
                c = re.sub(r"^XXX-AV-", "XXXAV-", c)
                if c and c not in seen:
                    seen.add(c)
                    found.append(c)
    except Exception as e:  # noqa: BLE001
        print("db:", e)

    g: dict[str, list[str]] = defaultdict(list)
    for c in found:
        pref = c.split("-", 1)[0]
        if pref == "XXX":
            pref = "XXXAV"
        if len(g[pref]) < limit_per_pref:
            g[pref].append(c)
    return dict(g)


def probe_one(sid: str, code: str) -> dict:
    from app.scrape_details import fetch_detail_for_source

    t0 = time.perf_counter()
    try:
        d = fetch_detail_for_source(sid, code)
        ms = int((time.perf_counter() - t0) * 1000)
        title = str(d.get("title") or "").strip()
        poster = bool(d.get("posterUrl") or d.get("poster"))
        actors = len(d.get("actors") or [])
        ok = bool(title or poster)
        return {
            "sid": sid,
            "code": code,
            "ok": ok,
            "ms": ms,
            "title": title[:40],
            "poster": poster,
            "actors": actors,
            "err": "",
        }
    except Exception as e:  # noqa: BLE001
        ms = int((time.perf_counter() - t0) * 1000)
        return {
            "sid": sid,
            "code": code,
            "ok": False,
            "ms": ms,
            "title": "",
            "poster": False,
            "actors": 0,
            "err": f"{type(e).__name__}: {e}",
        }


def main() -> int:
    samples = find_samples(2)
    print("=== samples without dedicated official ===")
    if not samples:
        print("no samples found")
        return 1
    for p, codes in sorted(samples.items()):
        print(f"  {p}: {', '.join(codes)}")

    jobs: list[tuple[str, str]] = []
    for codes in samples.values():
        for c in codes[:1]:  # 每前缀 1 条，控制墙钟
            for sid in AGGS:
                jobs.append((sid, c))

    print(f"\n=== probe aggregators ({len(jobs)} fetches) ===")
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(probe_one, sid, code) for sid, code in jobs]
        for fut in as_completed(futs):
            results.append(fut.result())

    by_code: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_code[r["code"]].append(r)

    print("-" * 88)
    need_official: list[str] = []
    ok_agg: list[str] = []
    for code in sorted(by_code):
        rows = by_code[code]
        hits = [r for r in rows if r["ok"]]
        hit_ids = [r["sid"] for r in hits]
        best = hits[0] if hits else None
        if best:
            ok_agg.append(code)
            print(
                f"OK   {code:22} via={','.join(hit_ids)}  "
                f"title={best['title']!r} poster={best['poster']}"
            )
        else:
            need_official.append(code)
            errs = "; ".join(f"{r['sid']}:{r['err'][:40]}" for r in rows[:2])
            print(f"MISS {code:22}  {errs}")
    print("-" * 88)
    print(f"aggregator OK={len(ok_agg)} MISS={len(need_official)} / {len(by_code)}")
    if need_official:
        print("weak on aggregators (consider official):", ", ".join(need_official))
    else:
        print("all probed codes hit at least one aggregator — no urgent official site")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
