"""诊断八：当前策略的 regionsEnabled / regionSources 实况。只读。"""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.core.settings_store as settings_store  # noqa: E402
import app.scrap_library.enrich_strategy as strat  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_diag_strategy.txt")
buf = io.StringIO()


def w(*a):
    print(*a, file=buf)


for key in ("scrap.enrich.strategy", "scrap.library.embed.settings", "scrape.providers"):
    raw = settings_store.get_setting(key)
    if not isinstance(raw, dict):
        w(f"### {key} = (空/{type(raw).__name__})")
        w("")
        continue
    if key == "scrap.enrich.strategy":
        cfg = strat.normalize_strategy(raw)
        w(f"### {key}")
        w("  mode =", cfg.get("mode"), " itemWorkers =", cfg.get("itemWorkers"), " fillMode =", cfg.get("fillMode"))
        w("  regionsEnabled:")
        for rid, v in (cfg.get("regionsEnabled") or {}).items():
            w(f"      {rid:20s} {v}")
        w("  regionSources:")
        for rid, v in (cfg.get("regionSources") or {}).items():
            w(f"      {rid:20s} {v}")
        w("  regionGroups:")
        for rid, v in (cfg.get("regionGroups") or {}).items():
            w(f"      {rid:20s} {v}")
        w("  原始 regionsEnabled:", json.dumps(raw.get("regionsEnabled"), ensure_ascii=False))
        w("  原始 regionSources:", json.dumps(raw.get("regionSources"), ensure_ascii=False))
        w("  逻辑版本:", raw.get("regionSourcesLogicVersion"))
    else:
        w(f"### {key} = {json.dumps(raw, ensure_ascii=False)[:1500]}")
    w("")

w("### enabled_region_ids() =", strat.enabled_region_ids())

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
