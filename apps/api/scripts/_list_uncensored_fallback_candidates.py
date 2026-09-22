# -*- coding: utf-8 -*-
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.scrape.source_catalog import SOURCE_CATALOG, SOURCE_TRUST
from app.scrap_library.enrich_strategy import (
    UNCENSORED_OFFICIAL_SOURCE_IDS,
    get_strategy,
)
from app.scrape_details import registered_detail_ids

s = get_strategy()
cur = (s.get("regionSources") or {}).get("japan_uncensored") or []
print("current japan_uncensored:", cur)
print("official:", sorted(UNCENSORED_OFFICIAL_SOURCE_IDS))

impl = {x["id"]: x for x in SOURCE_CATALOG}
reg = set(registered_detail_ids())
print("\ngroup  trust  id               detail  flags   label")
for sid, meta in sorted(impl.items(), key=lambda kv: (kv[1].get("group") or "", -SOURCE_TRUST.get(kv[0], 0), kv[0])):
    if not meta.get("implemented"):
        continue
    g = meta.get("group") or ""
    if g not in ("av", "uncensored", "general"):
        continue
    trust = SOURCE_TRUST.get(sid, 0)
    detail = "Y" if sid in reg else "N"
    flags = []
    if sid in cur:
        flags.append("CUR")
    if sid in UNCENSORED_OFFICIAL_SOURCE_IDS:
        flags.append("OFF")
    print(
        f"{g:12} {trust:3}  {sid:16} {detail}       {'+'.join(flags) or '-':8}  {meta.get('label')}"
    )
