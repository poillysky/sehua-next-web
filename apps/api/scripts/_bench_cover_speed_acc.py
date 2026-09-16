#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quick bench: enrich speed + poster accuracy (batch_mode early-crop)."""
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

    codes = ["ABF-106", "ABF-001", "SSIS-001", "SONE-001", "MIDV-001"]
    picked: list[dict] = []
    with pool.connection() as conn, conn.cursor() as cur:
        for c in codes:
            cur.execute(
                f"""
                SELECT item_id, code, region, rel_path FROM {emb.TABLE}
                WHERE upper(code)=%s LIMIT 1
                """,
                (c,),
            )
            r = cur.fetchone()
            if r:
                picked.append(dict(r))
            else:
                print("MISS", c, flush=True)

    print("picked", [p["code"] for p in picked], flush=True)

    def run_one(d: dict, *, tag: str) -> dict:
        t0 = time.perf_counter()
        row = {
            "itemId": str(d.get("item_id") or ""),
            "code": str(d.get("code") or "").upper(),
            "rel_path": str(d.get("rel_path") or "").replace("\\", "/"),
            "relPath": str(d.get("rel_path") or "").replace("\\", "/"),
            "region": str(d.get("region") or ""),
            "gaps": [],
        }
        one = en.enrich_one_row(
            row, dry_run=False, overwrite=True, sync_vector=False
        )
        wall = int((time.perf_counter() - t0) * 1000)
        rel = str(d.get("rel_path") or "").replace("\\", "/")
        poster = root / rel / "poster.jpg"
        analysis = (
            analyze_local_poster(poster)
            if poster.is_file()
            else {"ok": False, "issues": ["missing"]}
        )
        w = h = 0
        if poster.is_file():
            try:
                im = Image.open(poster)
                w, h = im.size
            except Exception as e:  # noqa: BLE001
                analysis.setdefault("issues", []).append(f"open:{e}")

        meta: dict = {}
        for k in (
            "coverMs",
            "fetchMs",
            "totalMs",
            "ok",
            "error",
            "coverFail",
            "coverTried",
        ):
            if k in (one or {}):
                meta[k] = one.get(k)
        cov = one.get("cover") if isinstance(one.get("cover"), dict) else {}
        if cov:
            meta["coverOk"] = cov.get("ok")
            meta["coverFailReason"] = cov.get("failReason")
            meta["coverMode"] = cov.get("mode")
            meta["keptOld"] = cov.get("keptOld")
            meta["triedN"] = len(cov.get("tried") or [])
            oks = [a for a in (cov.get("attempts") or []) if a.get("status") == "ok"]
            meta["okAttempt"] = oks[0] if oks else None

        portrait = (h >= w * 1.05) if w and h else None
        return {
            "tag": tag,
            "code": d.get("code"),
            "wallMs": wall,
            "fetchMs": meta.get("fetchMs"),
            "coverMs": meta.get("coverMs"),
            "totalMs": meta.get("totalMs"),
            "ok": meta.get("ok", one.get("ok")),
            "error": meta.get("error") or one.get("error"),
            "coverOk": meta.get("coverOk"),
            "coverFailReason": meta.get("coverFailReason"),
            "coverMode": meta.get("coverMode"),
            "keptOld": meta.get("keptOld"),
            "triedN": meta.get("triedN"),
            "okAttempt": meta.get("okAttempt"),
            "posterWh": [w, h],
            "portrait": portrait,
            "analyze": {
                "ok": analysis.get("ok"),
                "issues": analysis.get("issues"),
                "width": analysis.get("width"),
                "height": analysis.get("height"),
                "faceOff": analysis.get("faceOff"),
                "blank": analysis.get("blank"),
            },
        }

    def summarize(rows: list[dict], label: str) -> None:
        ok = sum(1 for r in rows if r.get("ok") and not r.get("error"))
        cover_ok = sum(1 for r in rows if r.get("coverOk"))
        port = sum(1 for r in rows if r.get("portrait"))
        face_off = sum(1 for r in rows if (r.get("analyze") or {}).get("faceOff"))
        issues = []
        for r in rows:
            iss = (r.get("analyze") or {}).get("issues") or []
            if iss:
                issues.append(f"{r['code']}:{iss}")
        cms = [r["coverMs"] for r in rows if r.get("coverMs") is not None]
        fms = [r["fetchMs"] for r in rows if r.get("fetchMs") is not None]
        wms = [r["wallMs"] for r in rows if r.get("wallMs") is not None]

        def avg(xs: list[int]) -> int | None:
            return int(sum(xs) / len(xs)) if xs else None

        print(f"\n## {label}", flush=True)
        print(
            f"n={len(rows)} ok={ok} coverOk={cover_ok} portrait={port} faceOff={face_off}",
            flush=True,
        )
        print(
            f"avg wall/fetch/cover ms = {avg(wms)} / {avg(fms)} / {avg(cms)}",
            flush=True,
        )
        print(
            f"max coverMs={max(cms) if cms else None} max wall={max(wms) if wms else None}",
            flush=True,
        )
        if issues:
            print("poster issues", issues, flush=True)

    # SEQ under batch_mode (early crop)
    print("\n=== SEQ (batch_mode) ===", flush=True)
    with en._enrich_lock:
        was = bool(en._enrich_job.get("running"))
        en._enrich_job["running"] = True
    seq: list[dict] = []
    try:
        for d in picked[:5]:
            r = run_one(d, tag="seq")
            seq.append(r)
            print(json.dumps(r, ensure_ascii=False, default=str), flush=True)
    finally:
        with en._enrich_lock:
            en._enrich_job["running"] = was

    # CONCURRENT burst
    print("\n=== CONCURRENT x5 (batch_mode) ===", flush=True)
    with en._enrich_lock:
        was = bool(en._enrich_job.get("running"))
        en._enrich_job["running"] = True
    conc: list[dict] = []
    t_burst = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {ex.submit(run_one, d, tag="conc"): d for d in picked[:5]}
            for fut in as_completed(futs):
                r = fut.result()
                conc.append(r)
                print(json.dumps(r, ensure_ascii=False, default=str), flush=True)
    finally:
        with en._enrich_lock:
            en._enrich_job["running"] = was
    burst = int((time.perf_counter() - t_burst) * 1000)

    summarize(seq, "SEQ")
    summarize(conc, "CONC")
    rate = round(len(conc) / (burst / 60000.0), 1) if burst else None
    print(
        f"\nconcurrent wall clock {burst} ms for {len(conc)} items => ~{rate}/min",
        flush=True,
    )


if __name__ == "__main__":
    main()
