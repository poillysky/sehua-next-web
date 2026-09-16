#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reset scrap_library_embed to catalog skeletons, then enrich one sample."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.core.db import init_db, get_meta_pool, data_dir
from app.scrap_library import embed as embed_svc
from app.scrap_library import enrich as enrich_svc


def main() -> None:
    init_db()

    def on_progress(ev: dict) -> None:
        stage = ev.get("stage") or ""
        label = ev.get("label") or ""
        pct = ev.get("percent")
        print(f"  [{stage}] {pct}% {label}", flush=True)

    print("=== reset embed -> skeletons ===", flush=True)
    result = embed_svc.reset_embed_to_catalog_skeletons(on_progress=on_progress)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)

    facets = data_dir() / "cache" / "facets"
    if facets.is_dir():
        shutil.rmtree(facets, ignore_errors=True)
        print("cleared facets cache", facets, flush=True)

    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT item_id, code, region, rel_path, content_sha
            FROM {embed_svc.TABLE}
            WHERE region = %s AND COALESCE(code,'') <> ''
            ORDER BY code
            LIMIT 5
            """,
            ("japan_censored",),
        )
        samples = [dict(r) for r in cur.fetchall()]
    print("sample skeletons:", flush=True)
    for s in samples:
        print(" ", s.get("code"), s.get("item_id"), flush=True)

    if not samples:
        print("no sample to enrich", flush=True)
        return

    first = samples[0]
    print(f"=== enrich one: {first.get('code')} ===", flush=True)
    one = enrich_svc.enrich_one_by_item_id(
        item_id=str(first["item_id"]),
        dry_run=False,
        overwrite=True,
    )
    print(json.dumps(one, ensure_ascii=False, indent=2, default=str)[:4000], flush=True)


if __name__ == "__main__":
    main()
