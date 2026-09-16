"""Diagnose why enrich returns detail_not_found so fast."""
from app.core.db import init_db, get_meta_pool
from app.scrap_library import embed as e
from app.scrap_library import enrich as en
from app.scrape import sources_settings as s
from app import scrap_enrich_strategy as strat

init_db()

# enabled sources for japan
print("strategy", strat.get_strategy() if hasattr(strat, "get_strategy") else "n/a")
try:
    from app import scrap_enrich_strategy as st
    print("strategy file", st.load() if hasattr(st, "load") else dir(st)[:20])
except Exception as ex:
    print("strat err", ex)

# list detail sources for region
try:
    from app.scrap_library.enrich import _detail_sources
    srcs = _detail_sources(region="日本有码")
    print("sources", len(srcs))
    for x in srcs[:20]:
        print(" ", x.get("id"), "enabled?", x.get("enabled"), x.get("label") or x.get("name"))
except Exception as ex:
    print("detail_sources err", type(ex).__name__, ex)

pool = get_meta_pool()
with pool.connection() as conn, conn.cursor() as cur:
    cur.execute(
        f"SELECT item_id, code, region, rel_path FROM {e.TABLE} WHERE upper(code)=%s LIMIT 3",
        ("SONE-001",),
    )
    for r in cur.fetchall():
        print("row", dict(r))

# try fetch one source directly
from app.scrape_details import fetch_detail_for_source
from app import outbound_http
outbound_http.set_thread_allow_flare(True)
for sid in ["dmm", "javlibrary", "javdb", "r18dev", "avwikidb"]:
    try:
        applied = s.apply_provider_link_for_fetch(sid)
        d = fetch_detail_for_source(
            sid, "SONE-001",
            base_url=str(applied.get("baseUrl") or ""),
            cookie=str(applied.get("cookie") or ""),
        )
        print(sid, "OK" if d else "NONE", (d or {}).get("title", "")[:60] if d else "")
    except Exception as ex:
        print(sid, "ERR", type(ex).__name__, ex)
