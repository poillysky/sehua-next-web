# -*- coding: utf-8 -*-
"""Diagnose / rebuild japan_censored pending from vector diff."""
from __future__ import annotations

import time

from app.core.db import connect, init_db
from app.scrap_library import enrich as E


def main() -> None:
    init_db()
    rid = "japan_censored"
    iids, codes = E._queue_log_classified_skip_keys(rid)
    maps = E._LocalNfoMaps()
    maps.complete_rels = set(iids)
    maps.done_n = 102135
    maps.soft_n = 6391
    maps.fail_n = 843
    print("skip", len(maps.skip_rels), "codes", len(maps.classified_codes), "codes_db", len(codes))
    vt = E._fresh_vector_library_total(rid, force=True)
    print("vt", vt)
    t0 = time.time()
    rows, n = E._replace_pending_from_vector(
        region=rid,
        local_maps=maps,
        vector_total=vt,
        clear_pending=True,
    )
    print("wrote", n, "preview", len(rows), "sec", round(time.time() - t0, 1))
    with connect() as conn:
        r = conn.execute(
            "SELECT status, COUNT(*) AS n FROM enrich_queue_log WHERE region=%s GROUP BY status",
            (rid,),
        ).fetchall()
        print("after", [dict(x) for x in r])


if __name__ == "__main__":
    main()
