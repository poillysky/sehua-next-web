#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Concurrent cover stress: 5 workers × known codes under batch_mode."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image

from app.core.db import get_meta_pool, init_db, media_dir
from app.scrap_library import embed as emb
from app.scrap_library import enrich as en
from app.scrap_library.cover_scrape import analyze_local_poster


def main() -> None:
    init_db()
    root = media_dir() / "scrap-library"
    pool = get_meta_pool()
    codes = [
        "ZUKO-056",
        "ZUKO-057",
        "ZUKO-058",
        "ZUKO-059",
        "ABF-050",
        "ABF-051",
        "SSIS-002",
        "SONE-002",
    ]
    picked: list[dict] = []
    with pool.connection() as conn, conn.cursor() as cur:
        for c in codes:
            cur.execute(
                f"SELECT item_id, code, region, rel_path FROM {emb.TABLE} "
                f"WHERE upper(code)=%s LIMIT 1",
                (c,),
            )
            r = cur.fetchone()
            if r:
                picked.append(dict(r))

    print("picked", [p["code"] for p in picked], flush=True)

    def run_one(d: dict) -> dict:
        row = {
            "itemId": str(d.get("item_id") or ""),
            "code": str(d.get("code") or "").upper(),
            "rel_path": str(d.get("rel_path") or "").replace("\\", "/"),
            "relPath": str(d.get("rel_path") or "").replace("\\", "/"),
            "region": str(d.get("region") or ""),
            "gaps": [],
        }
        t0 = time.perf_counter()
        one = en.enrich_one_row(
            row, dry_run=False, overwrite=True, sync_vector=False
        )
        wall = int((time.perf_counter() - t0) * 1000)
        rel = str(d.get("rel_path") or "").replace("\\", "/")
        poster = root / rel / "poster.jpg"
        w = h = 0
        if poster.is_file():
            try:
                im = Image.open(poster)
                w, h = im.size
            except Exception:
                pass
        analysis = analyze_local_poster(poster) if poster.is_file() else {"issues": ["missing"]}
        return {
            "code": d.get("code"),
            "ok": one.get("ok"),
            "error": one.get("error"),
            "wallMs": wall,
            "fetchMs": one.get("fetchMs"),
            "coverMs": one.get("coverMs"),
            "coverFail": one.get("coverFail"),
            "posterWh": [w, h],
            "portrait": bool(w and h and h >= w * 1.05),
            "issues": analysis.get("issues"),
            "attempts": (one.get("coverAttempts") or [])[:6],
        }

    with en._enrich_lock:
        en._enrich_job["running"] = True
    t0 = time.perf_counter()
    rows: list[dict] = []
    try:
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = [ex.submit(run_one, d) for d in picked]
            for fut in as_completed(futs):
                r = fut.result()
                rows.append(r)
                print(json.dumps(r, ensure_ascii=False, default=str)[:500], flush=True)
    finally:
        with en._enrich_lock:
            en._enrich_job["running"] = False

    burst = int((time.perf_counter() - t0) * 1000)
    ok = sum(1 for r in rows if r.get("ok"))
    cms = [int(r["coverMs"]) for r in rows if r.get("coverMs") is not None]
    fails = [r for r in rows if not r.get("ok") or r.get("coverFail")]
    print(
        f"\nSUMMARY n={len(rows)} ok={ok} burstMs={burst} "
        f"avgCover={int(sum(cms)/len(cms)) if cms else None} "
        f"p90Cover={sorted(cms)[int(len(cms)*0.9)] if cms else None} "
        f"ge7s={sum(1 for x in cms if x>=7000)} fails={len(fails)}",
        flush=True,
    )
    for r in fails:
        print("FAIL", r.get("code"), r.get("error"), r.get("coverFail"), r.get("coverMs"), flush=True)


if __name__ == "__main__":
    main()
