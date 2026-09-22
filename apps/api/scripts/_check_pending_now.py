from app.core.db import connect, init_db

init_db()
with connect() as c:
    r = c.execute(
        "SELECT status, COUNT(*) AS n FROM enrich_queue_log "
        "WHERE region=%s GROUP BY status",
        ("japan_censored",),
    ).fetchall()
    print("counts", [dict(x) for x in r])
    r2 = c.execute(
        "SELECT code FROM enrich_queue_log "
        "WHERE region=%s AND status='pending' "
        "ORDER BY updated_at DESC NULLS LAST LIMIT 5",
        ("japan_censored",),
    ).fetchall()
    print("sample", [dict(x) for x in r2])
