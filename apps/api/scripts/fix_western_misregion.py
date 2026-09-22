# -*- coding: utf-8 -*-
"""纠正已同步数据：把误挂到非欧美区的欧美厂牌前缀迁回 western。

用法（在 apps/api 下）:
  python scripts/fix_western_misregion.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.prefix import catalog_store as store  # noqa: E402
from app.scrap_library import embed as scrap  # noqa: E402
from app.core.db import get_meta_pool  # noqa: E402
from app.core.region_meta import REGION_ORDER  # noqa: E402
from app.search.av import WESTERN_STUDIO_PREFIXES, is_western_studio_prefix  # noqa: E402


def fix_catalog() -> dict:
    doc = store.load_catalog(force=True)
    moved: list[tuple[str, str, int]] = []
    west_bucket = doc["regions"]["western"]["prefixes"]

    for rid in REGION_ORDER:
        if rid == "western":
            continue
        prefs = doc["regions"][rid]["prefixes"]
        for key in list(prefs.keys()):
            if not is_western_studio_prefix(key):
                continue
            ent = prefs.pop(key)
            serials = list(ent.get("serials") or [])
            existing = west_bucket.get(key)
            if existing:
                merged = sorted(
                    set(str(x).upper() for x in (existing.get("serials") or []))
                    | set(str(x).upper() for x in serials)
                )
                existing["serials"] = merged
                if not existing.get("maker") and ent.get("maker"):
                    existing["maker"] = ent["maker"]
                srcs = set(existing.get("sources") or []) | set(ent.get("sources") or [])
                existing["sources"] = sorted(srcs)
            else:
                ent["pad"] = int(ent.get("pad") or 0)
                west_bucket[key] = ent
            moved.append((rid, key, len(serials)))

    if moved:
        store.save_catalog(doc)
    return {"moved": moved, "count": len(moved)}


def fix_scrap() -> dict:
    scrap.ensure_schema()
    keys = sorted({str(x).upper() for x in WESTERN_STUDIO_PREFIXES})
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT region,
                   upper(regexp_replace(prefix, '[^A-Za-z0-9]', '', 'g')) AS pref,
                   count(*)::int AS n
            FROM {scrap.TABLE}
            WHERE upper(regexp_replace(prefix, '[^A-Za-z0-9]', '', 'g')) = ANY(%s)
              AND coalesce(region, '') NOT IN ('western', '欧美无码')
            GROUP BY 1, 2
            ORDER BY 1, 2
            """,
            (keys,),
        )
        before = [dict(r) for r in cur.fetchall()]
        cur.execute(
            f"""
            UPDATE {scrap.TABLE}
            SET region = 'western'
            WHERE upper(regexp_replace(prefix, '[^A-Za-z0-9]', '', 'g')) = ANY(%s)
              AND coalesce(region, '') NOT IN ('western', '欧美无码')
            """,
            (keys,),
        )
        updated = int(cur.rowcount or 0)
        conn.commit()
    return {"mismatched_before": before, "updated_rows": updated}


def main() -> None:
    print("catalog:", fix_catalog())
    try:
        print("scrap:", fix_scrap())
    except Exception as e:
        print("scrap skip:", e)
    doc = store.load_catalog(force=True)
    pt = (doc["regions"]["western"]["prefixes"].get("PURETABOO") or {})
    print(
        "PURETABOO → western serials=",
        len(pt.get("serials") or []),
        "| still in japan_censored=",
        "PURETABOO" in (doc["regions"]["japan_censored"]["prefixes"] or {}),
    )


if __name__ == "__main__":
    main()
