# -*- coding: utf-8 -*-
"""Rebuild japan_censored enrich queue via scan_enrich_queue."""
from __future__ import annotations

import time

from app.scrap_library import enrich as E


def main() -> None:
    rid = "japan_censored"
    print("scan start", rid, flush=True)
    t0 = time.time()
    out = E.scan_enrich_queue(region=rid, limit=0)
    elapsed = time.time() - t0
    counts = out.get("counts") or {}
    print("scan done sec=", round(elapsed, 1), flush=True)
    print("ok=", out.get("ok"), "scanned=", out.get("scanned"), flush=True)
    print("counts=", counts, flush=True)
    print(
        "pendingTotal=",
        out.get("pendingTotal"),
        "localDone=",
        out.get("localDone"),
        "localSoft=",
        out.get("localSoft"),
        "localFail=",
        out.get("localFail"),
        flush=True,
    )
    if out.get("error"):
        print("error=", out.get("error"), flush=True)


if __name__ == "__main__":
    main()
