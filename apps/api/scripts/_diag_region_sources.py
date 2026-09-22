"""诊断三：五区「站点配置」自检 —— 每区实际参与刮削的源 + 可用性。

只读，不发外网请求。输出 _diag_sources.txt
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.scrape import sources_settings as ss  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_diag_sources.txt")
buf = io.StringIO()


def w(*a):
    print(*a, file=buf)


REGIONS = ["japan_censored", "japan_uncensored", "japan_amateur", "fc2", "china", "western"]

w("=" * 78)
w("每区 enrich 源池（enabled_enrich_sources）")
w("=" * 78)
for rid in REGIONS:
    rows = ss.enabled_enrich_sources(region=rid)
    groups = ss.enrich_groups_for_region(rid)
    w(f"--- {rid}  分组={groups}  源数={len(rows)} ---")
    for r in rows:
        w(
            f"    {r['id']:16s} key={r['detailKey']:14s} grp={r['group']:10s} "
            f"access={r['access']:14s} base={r['baseUrl']}"
        )
    w("")

w("=" * 78)
w("全部源的 enabled / baseUrl 配置现状")
w("=" * 78)
cat = ss.public_catalog()
for g in cat["groups"]:
    w(f"### {g['label']} ({g['id']})")
    for s in g["sources"]:
        w(
            f"    {s['id']:16s} enabled={str(s['enabled']):5s} "
            f"display={str(s.get('displayUrl'))[:56]:56s} "
            f"probe={str((s.get('lastProbe') or {}).get('message'))[:40]}"
        )
    w("")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
