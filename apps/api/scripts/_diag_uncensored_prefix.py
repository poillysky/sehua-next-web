"""无码区：大前缀（1PON/C0930/H0930/H4610/KIN8/PACO/RHJ）能否被任何已接入站点命中。只读。"""
from __future__ import annotations

import io
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

import app.core.detail_path_cache as dpc  # noqa: E402
import app.core.site_mirror as sm  # noqa: E402
import app.scrape.source_catalog as cat  # noqa: E402
import app.scrape.sources_settings as ss  # noqa: E402
from app.core import db as dbmod  # noqa: E402

dpc.remember = lambda *a, **k: None  # type: ignore[assignment]
sm.remember = lambda *a, **k: None  # type: ignore[assignment]
ss._remember_live = lambda *a, **k: None  # type: ignore[assignment]

from app.scrape_details import fetch_detail_for_source  # noqa: E402

OUT = os.path.join(ROOT_DIR, "_diag_uncensored_prefix.txt")
buf = io.StringIO()


def w(*a):
    print(*a, file=buf)


# 候选池：当前无码池 + 所有「无码/综合」已实现站点（含被禁用的，强制启用测能力）
cand = ["iqqtv", "javbus", "freejavbt", "jav321", "airav_io", "miss_av",
        "carib", "10musume", "avsox", "njav", "javday", "sevenmmtv", "lulubar", "javlibrary", "avmoo"]
w("候选站点: " + ", ".join(cand))
w("")

PREFIXES = ["1PON", "C0930", "H0930", "H4610", "KIN8", "PACO", "RHJ"]
samples: dict[str, list[str]] = {}
with dbmod.connect() as conn:
    for p in PREFIXES:
        rows = conn.execute(
            "SELECT code FROM enrich_queue_log WHERE region='japan_uncensored' "
            "AND status='pending' AND code ILIKE %s ORDER BY random() LIMIT 2",
            (p + "-%",),
        ).fetchall()
        samples[p] = [str(r["code"]).upper() for r in rows]
        if not samples[p]:
            samples[p] = []


def _one(sid: str, code: str) -> dict:
    try:
        ctx = ss.resolve_fetch_context(sid)
    except Exception as e:  # noqa: BLE001
        return {"sid": sid, "ok": False, "err": str(e)[:46]}
    try:
        d = fetch_detail_for_source(
            sid, code, base_url=ctx["baseUrl"], cookie=ctx["cookie"], api_key=ctx["apiKey"]
        )
        return {"sid": sid, "ok": bool(str((d or {}).get("title") or "")),
                "title": str((d or {}).get("title") or "")[:40]}
    except Exception as e:  # noqa: BLE001
        return {"sid": sid, "ok": False, "err": str(e)[:46]}


for p, codes in samples.items():
    if not codes:
        w(f"### {p}: 无 pending 样例")
        continue
    for code in codes:
        res = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(_one, s, code) for s in cand]
            for f in as_completed(futs, timeout=240):
                res.append(f.result())
        okn = [r for r in res if r.get("ok")]
        w(f"### {code}   命中 {len(okn)}/{len(res)}")
        for r in okn:
            w(f"      ✓ {r['sid']:14s} {r['title']}")
        errs = {}
        for r in res:
            if not r.get("ok"):
                errs.setdefault(r.get("err", "(空)"), []).append(r["sid"])
        for e, sids in sorted(errs.items(), key=lambda x: -len(x[1]))[:4]:
            w(f"      ✗ {len(sids):2d} 个源: {e}")
        w("")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
