"""Pick a japan_censored sample with local NFO and enrich it."""
from pathlib import Path
import json

from app.core.db import init_db, get_meta_pool, media_dir
from app.scrap_library import embed as e
from app.scrap_library import enrich as en

init_db()
root = media_dir() / "scrap-library"
pool = get_meta_pool()

# Prefer known good prefixes
want_codes = ["SONE-001", "SSIS-001", "MIDV-001", "IPX-001", "STARS-001", "PRED-001"]
picked = None
with pool.connection() as conn, conn.cursor() as cur:
    for code in want_codes:
        cur.execute(
            f"""
            SELECT item_id, code, region, rel_path, source_text
            FROM {e.TABLE}
            WHERE upper(code) = %s
            LIMIT 1
            """,
            (code,),
        )
        row = cur.fetchone()
        if row:
            picked = dict(row)
            break

    if not picked:
        # any 日本有码 with existing nfo on disk
        cur.execute(
            f"""
            SELECT item_id, code, region, rel_path, source_text
            FROM {e.TABLE}
            WHERE region = %s AND COALESCE(code,'') <> ''
            ORDER BY code
            LIMIT 200
            """,
            ("日本有码",),
        )
        for r in cur.fetchall():
            d = dict(r)
            rel = str(d.get("rel_path") or "")
            folder = root / rel
            if any(folder.glob("*.nfo")) if folder.is_dir() else False:
                picked = d
                break
            # also try code-sorted popular letter prefixes
            if str(d.get("code") or "").upper().startswith(("SO", "SS", "MI", "IP", "ST", "AB", "CA")):
                picked = d
                break

if not picked:
    raise SystemExit("no suitable sample")

print("picked", picked["code"], picked["region"], picked["rel_path"])
print("before source_text", repr((picked.get("source_text") or "")[:80]))

one = en.enrich_one_by_item_id(
    item_id=str(picked["item_id"]), dry_run=False, overwrite=True
)
print("ok", one.get("ok"), "result keys", list((one.get("result") or one).keys()) if isinstance(one.get("result") or one, dict) else type(one))
res = one.get("result") if isinstance(one.get("result"), dict) else one
print(json.dumps({k: res.get(k) for k in ("ok", "code", "error", "gaps", "overwrite", "dryRun") if isinstance(res, dict)}, ensure_ascii=False, indent=2))

# reload row
with pool.connection() as conn, conn.cursor() as cur:
    cur.execute(
        f"SELECT code, source_text, title FROM {e.TABLE} WHERE item_id=%s",
        (picked["item_id"],),
    )
    after = dict(cur.fetchone())
print("after title", after.get("title"))
print("after source_text:\n", after.get("source_text") or "")
