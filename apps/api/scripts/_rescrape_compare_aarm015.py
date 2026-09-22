# -*- coding: utf-8 -*-
"""Rescrape AARM-015 with overwrite and compare NFO format to MDCx reference."""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from app.core.db import get_meta_pool, init_db
from app.scrap_library import enrich as enrich_svc
from app.scrap_library import embed as embed_svc

CODE = "AARM-015"
OURS = None


def main() -> int:
    global OURS
    init_db()
    settings = embed_svc.get_settings()
    lib_root = embed_svc.resolve_root(settings.get("root")).resolve()
    # region folder
    jp = None
    for p in lib_root.iterdir():
        if p.is_dir() and "有码" in p.name:
            jp = p
            break
    if jp is None:
        print("no japan region dir")
        return 2
    OURS = jp / "AARM" / CODE / f"{CODE}.nfo"
    print("ours_path", OURS)

    item_id = ""
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT item_id, code, region, rel_path FROM scrap_library_embed "
            "WHERE upper(code)=%s LIMIT 5",
            (CODE,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    print("embed_rows", rows)
    if rows:
        item_id = str(rows[0].get("item_id") or "")
    if not item_id:
        # fallback: synthesize from path like japan_censored/AARM/AARM-015
        rel = f"日本有码/AARM/{CODE}"
        item_id = f"local:{rel}"
        print("fallback item_id", item_id)

    print("enriching…", flush=True)
    try:
        data = enrich_svc.enrich_one_by_item_id(
            item_id=item_id,
            dry_run=False,
            overwrite=True,
            sync_vector=False,
        )
    except Exception as e:
        # try by scanning folder path item id formats used in project
        print("enrich_one failed:", e)
        # list possible item ids from queue log
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT item_id, code, status FROM enrich_queue_log "
                "WHERE upper(code)=%s ORDER BY id DESC LIMIT 5",
                (CODE,),
            )
            qrows = [dict(r) for r in cur.fetchall()]
        print("queue rows", qrows)
        if qrows:
            item_id = str(qrows[0].get("item_id") or "")
            print("retry with", item_id)
            data = enrich_svc.enrich_one_by_item_id(
                item_id=item_id,
                dry_run=False,
                overwrite=True,
                sync_vector=False,
            )
        else:
            raise

    print("enrich_result_keys", list(data.keys()) if isinstance(data, dict) else type(data))
    if isinstance(data, dict):
        r = data.get("result") if isinstance(data.get("result"), dict) else data
        print(
            "ok=",
            r.get("ok"),
            "nfoChanged=",
            r.get("nfoChanged"),
            "error=",
            r.get("error"),
            "source=",
            r.get("source"),
        )

    if not OURS.is_file():
        print("missing nfo after enrich")
        return 1

    raw = OURS.read_text(encoding="utf-8")
    print("=== OURS AFTER ===")
    print(raw)
    print("=== END ===")

    ref = Path(r"E:/Project/media/日本有码/AARM/AARM-015/AARM-015.nfo")
    ref_root = ET.fromstring(ref.read_text(encoding="utf-8"))
    our_root = ET.fromstring(raw)

    def tags(root: ET.Element) -> list[str]:
        return [c.tag for c in list(root)]

    def uniq(seq: list[str]) -> list[str]:
        out: list[str] = []
        for x in seq:
            if x not in out:
                out.append(x)
        return out

    ref_u = uniq(tags(ref_root))
    our_u = uniq(tags(our_root))
    print("ref_field_order", ref_u)
    print("our_field_order", our_u)
    print("order_match", ref_u == our_u)

    checks = {
        "xml_decl_space": '<?xml version="1.0" encoding="UTF-8" ?>' in raw,
        "cdata_title": bool(re.search(r"<title><!\[CDATA\[", raw)),
        "actor_type": "<type>Actor</type>" in raw,
        "has_tag": our_root.find("tag") is not None,
        "has_genre": our_root.find("genre") is not None,
        "has_sorttitle": our_root.find("sorttitle") is not None,
        "has_tagline": our_root.find("tagline") is not None,
        "has_ratings": our_root.find("ratings") is not None,
        "no_actor_all": our_root.find("actor_all") is None,
        "no_mosaic": our_root.find("mosaic") is None,
        "no_outlineshow": our_root.find("outlineshow") is None,
        "has_poster": our_root.find("poster") is not None,
        "has_num": our_root.find("num") is not None,
    }
    print("format_checks", checks)
    print("all_format_ok", all(checks.values()))
    missing = [k for k in ref_u if k not in our_u]
    extra = [k for k in our_u if k not in ref_u]
    print("missing_vs_ref", missing)
    print("extra_vs_ref", extra)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
