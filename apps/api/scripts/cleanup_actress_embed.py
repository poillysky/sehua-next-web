#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速清理向量库女优行：drop 男优/导演 + 映射中文标准名（不改 NFO、默认不重嵌）。"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))

ACTRESS_RE = re.compile(r"^(女优：)(.+)$", re.M)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reembed", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from app.core.db import init_db, get_meta_pool
    from app.scrap_library.embed import TABLE, ensure_schema
    from app.scrap_library.nfo import content_sha
    from app.scrape.metadata_optimize import (
        clear_map_cache,
        polish_actress_names,
        actor_maps_loaded,
    )
    from app.ai.config import resolve_embed_config

    init_db()
    ensure_schema()
    clear_map_cache()
    maps = actor_maps_loaded()
    print(f"map={maps}", flush=True)

    try:
        from app.scrap_library.enrich import _clean_actors
    except Exception:  # noqa: BLE001
        def _clean_actors(xs):  # type: ignore
            return [str(x).strip() for x in (xs or []) if str(x or "").strip()]

    pool = get_meta_pool()
    t0 = time.perf_counter()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT item_id, code, source_text, model, dim
            FROM {TABLE}
            WHERE source_text LIKE %s
            ORDER BY code
            """,
            ("%女优：%",),
        )
        rows = [dict(r) for r in cur.fetchall()]
    if args.limit > 0:
        rows = rows[: args.limit]
    print(f"rows={len(rows)} loaded in {time.perf_counter()-t0:.1f}s", flush=True)

    pending: list[dict] = []
    dropped_names: dict[str, int] = {}
    renamed = 0
    removed_line = 0
    unchanged = 0
    samples: list[dict] = []

    t1 = time.perf_counter()
    for i, row in enumerate(rows, 1):
        src = str(row.get("source_text") or "")
        m = ACTRESS_RE.search(src)
        if not m:
            unchanged += 1
            continue
        raw_parts = [p for p in re.split(r"[\s、,/|]+", m.group(2).strip()) if p.strip()]
        cleaned = _clean_actors(raw_parts)
        polished = polish_actress_names(cleaned, enable_mapping=True, lang="zh-CN")
        old_line = m.group(0)
        if polished:
            new_line = f"女优：{' '.join(polished[:12])}"
        else:
            new_line = ""
        if new_line == old_line:
            unchanged += 1
            continue

        # stats
        old_set = set(cleaned)
        new_set = set(polished)
        for n in old_set - new_set:
            dropped_names[n] = dropped_names.get(n, 0) + 1
        if polished and any(a != b for a, b in zip(cleaned, polished) if a in new_set):
            renamed += 1
        elif not polished:
            removed_line += 1
        else:
            # could be rename and/or drop
            if len(polished) < len(cleaned):
                pass
            if polished != cleaned:
                renamed += 1

        if new_line:
            new_src = src[: m.start()] + new_line + src[m.end() :]
        else:
            before = src[: m.start()].rstrip("\n")
            after = src[m.end() :].lstrip("\n")
            new_src = f"{before}\n{after}" if before and after else (before or after)
        new_src = re.sub(r"\n{2,}", "\n", new_src).strip()

        model = str(row.get("model") or "") or str(resolve_embed_config()["model"])
        dim = int(row.get("dim") or 0) or int(resolve_embed_config()["dim"])
        pending.append(
            {
                "item_id": row["item_id"],
                "source_text": new_src,
                "content_sha": content_sha(new_src, model=model, dim=dim),
            }
        )
        if len(samples) < 20:
            samples.append(
                {
                    "code": row.get("code"),
                    "old": m.group(2).strip()[:80],
                    "new": " ".join(polished[:8]) if polished else "(removed)",
                }
            )
        if i % 5000 == 0:
            print(f"… scanned {i}/{len(rows)} pending={len(pending)}", flush=True)

    print(
        f"scan done in {time.perf_counter()-t1:.1f}s pending={len(pending)} unchanged={unchanged}",
        flush=True,
    )

    t2 = time.perf_counter()
    if pending:
        with pool.connection() as conn, conn.cursor() as cur:
            for j in range(0, len(pending), 500):
                chunk = pending[j : j + 500]
                for p in chunk:
                    cur.execute(
                        f"""
                        UPDATE {TABLE}
                        SET source_text = %s,
                            content_sha = %s,
                            updated_at = NOW()
                        WHERE item_id = %s
                        """,
                        (p["source_text"], p["content_sha"], p["item_id"]),
                    )
                conn.commit()
                print(f"… updated {min(j+500, len(pending))}/{len(pending)}", flush=True)
    print(f"update done in {time.perf_counter()-t2:.1f}s", flush=True)

    if args.reembed and pending:
        print("reembed requested but skipped in fast path; use UI 优化女优 or sync", flush=True)

    out = {
        "map": maps,
        "rows_scanned": len(rows),
        "updated": len(pending),
        "unchanged": unchanged,
        "removed_actress_line": removed_line,
        "dropped_name_counts": dict(
            sorted(dropped_names.items(), key=lambda x: -x[1])[:40]
        ),
        "samples": samples,
    }
    report = API / "_gap_reports" / "actress_cleanup_result.json"
    report.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)
    print(f"wrote {report}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
