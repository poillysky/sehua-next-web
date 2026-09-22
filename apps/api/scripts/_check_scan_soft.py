# -*- coding: utf-8 -*-
from app.core.db import connect, init_db

init_db()
rid = "japan_censored"
with connect() as c:
    rows = c.execute(
        """
        SELECT
          CASE WHEN error IS NULL OR error='' THEN 'empty_err'
               WHEN error LIKE %s THEN 'soft_err'
               ELSE 'other_err' END AS ek,
          COUNT(*) AS n
        FROM enrich_queue_log WHERE region=%s AND status='done'
        GROUP BY 1
        """,
        ("%软成功%", rid),
    ).fetchall()
    print("error kinds", [dict(r) for r in rows])
    for label, order in (("newest", "DESC"), ("oldest", "ASC")):
        sample = c.execute(
            f"""
            SELECT code, error, LEFT(COALESCE(payload_json,''), 160) AS p
            FROM enrich_queue_log
            WHERE region=%s AND status='done' AND source='scan'
            ORDER BY id {order} LIMIT 3
            """,
            (rid,),
        ).fetchall()
        print(label)
        for r in sample:
            print(dict(r))
    fail = c.execute(
        "SELECT COUNT(*) AS n FROM enrich_queue_log WHERE region=%s AND status='fail'",
        (rid,),
    ).fetchone()
    print("fail", dict(fail))
    # how many payload partialOk
    n_partial = c.execute(
        """
        SELECT COUNT(*) AS n FROM enrich_queue_log
        WHERE region=%s AND status='done'
          AND payload_json LIKE %s
        """,
        (rid, "%partialOk%: true%"),
    ).fetchone()
    print("partialOk approx", dict(n_partial))
