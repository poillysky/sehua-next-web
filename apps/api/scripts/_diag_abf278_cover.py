#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from pathlib import Path

from app.core.db import get_meta_pool, init_db, media_dir
from app.scrap_library import embed as emb
from app.scrap_library import enrich as en


def main() -> None:
    init_db()
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT item_id, code, region, rel_path, cover_url
            FROM {emb.TABLE}
            WHERE upper(code)=%s
            LIMIT 1
            """,
            ("ABF-278",),
        )
        row0 = cur.fetchone()
    if not row0:
        raise SystemExit("ABF-278 not found")
    d = dict(row0)
    print("row", {k: d.get(k) for k in ("item_id", "code", "region", "rel_path")})
    print("cover_url", (d.get("cover_url") or "")[:240])

    with en._enrich_lock:
        en._enrich_job["running"] = True
    try:
        row = {
            "itemId": str(d.get("item_id") or ""),
            "code": "ABF-278",
            "rel_path": str(d.get("rel_path") or "").replace("\\", "/"),
            "relPath": str(d.get("rel_path") or "").replace("\\", "/"),
            "region": str(d.get("region") or ""),
            "gaps": [],
        }
        t0 = time.perf_counter()
        one = en.enrich_one_row(
            row, dry_run=False, overwrite=True, sync_vector=False
        )
        print("wall", int((time.perf_counter() - t0) * 1000))
        print(
            "ok",
            one.get("ok"),
            "err",
            one.get("error"),
            "coverMs",
            one.get("coverMs"),
            "coverFail",
            one.get("coverFail"),
            "fetchMs",
            one.get("fetchMs"),
        )
        print("coverTried", one.get("coverTried"))
        print(
            "attempts",
            json.dumps(one.get("coverAttempts") or [], ensure_ascii=False, indent=2),
        )
        # also dump fieldSources poster + candidates from a fetch-only path if present
        p = (
            media_dir()
            / "scrap-library"
            / str(d.get("rel_path") or "").replace("\\", "/")
            / "poster.jpg"
        )
        print("poster", p.is_file(), p.stat().st_size if p.is_file() else 0, p)
    finally:
        with en._enrich_lock:
            en._enrich_job["running"] = False


if __name__ == "__main__":
    main()
