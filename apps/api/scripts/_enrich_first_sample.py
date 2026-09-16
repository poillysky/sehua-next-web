from app.core.db import init_db, get_meta_pool
from app.scrap_library import embed as e
from app.scrap_library import enrich as en
import json

init_db()
pool = get_meta_pool()
with pool.connection() as conn, conn.cursor() as cur:
    cur.execute(
        f"SELECT region, count(*) AS n FROM {e.TABLE} GROUP BY region ORDER BY n DESC"
    )
    for r in cur.fetchall():
        print("region", r["region"], r["n"])
    cur.execute(
        f"""
        SELECT item_id, code, region, rel_path, content_sha, source_text
        FROM {e.TABLE}
        WHERE COALESCE(code,'') <> ''
        ORDER BY code
        LIMIT 10
        """
    )
    rows = [dict(x) for x in cur.fetchall()]

print("--- samples ---")
for r in rows:
    print(r["code"], r["region"], r["item_id"][:32], repr((r.get("source_text") or "")[:50]))

if not rows:
    raise SystemExit("no rows")

first = rows[0]
print("=== enrich", first["code"], "===")
one = en.enrich_one_by_item_id(
    item_id=str(first["item_id"]), dry_run=False, overwrite=True
)
# compact summary
keys = [
    "ok",
    "code",
    "itemId",
    "changed",
    "written",
    "reingested",
    "error",
    "gaps",
    "skipped",
]
summary = {k: one.get(k) for k in keys if k in one}
# also peek nested
for k in ("result", "detail", "merged", "nfo"):
    if k in one:
        summary[k] = str(one.get(k))[:200]
print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
if isinstance(one, dict):
    # print useful fields from enrich result
    for k, v in one.items():
        if k in summary:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            print(f"  {k}: {v}")
        elif isinstance(v, list):
            print(f"  {k}: list[{len(v)}]")
        elif isinstance(v, dict):
            print(f"  {k}: dict keys={list(v.keys())[:12]}")
