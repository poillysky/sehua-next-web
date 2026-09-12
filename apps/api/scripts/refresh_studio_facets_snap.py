# -*- coding: utf-8 -*-
"""Refresh + verify studio facets after catalog unify."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import scrap_library_embed as scrap  # noqa: E402
from app.scrap_library.studio_display_names import resolve_studio_for_prefix  # noqa: E402


def main() -> None:
    for rid in (
        "japan_censored",
        "japan_gravure",
        "japan_uncensored",
        "japan_amateur",
        "fc2",
        "china",
        "western",
    ):
        try:
            r = scrap.refresh_facets_snapshot(region=rid, kinds=["studio"])
            print("refresh", rid, r.get("kinds"))
        except Exception as e:  # noqa: BLE001
            print("refresh", rid, "ERR", e)

    print("--- resolve checks ---")
    for rid, pref, expect in (
        ("japan_censored", "MDL", "MOODYZ"),
        ("china", "MDL", "Madou"),
        ("japan_censored", "SSIS", "S1"),
        ("japan_censored", "PRED", "Premium"),
        ("japan_censored", "ABP", "Prestige"),
        ("japan_censored", "SACE", "MAX-A"),
    ):
        got = resolve_studio_for_prefix(pref, region=rid)
        ok = expect.casefold() in got.casefold()
        print(("OK" if ok else "FAIL"), rid, pref, "->", got)

    page = scrap.list_facets(
        region="japan_censored", kind="studio", sort="count", order="desc", limit=10
    )
    print("--- live studio top ---", "total", page["total"])
    for f in page["facets"]:
        print(f"  {f['count']:5d}  {f['name']}")

    snap = (
        ROOT
        / "data"
        / "scrap_facets_snap"
        / "japan_censored"
        / "studio.json"
    )
    if snap.exists():
        d = json.loads(snap.read_text(encoding="utf-8"))
        print("snap v=", d.get("v"), "facets=", len(d.get("facets") or []))


if __name__ == "__main__":
    main()
