"""诊断六：真实抓取测试 —— 当前源池能否命中「磁盘上真实存在」的番号。

只读：monkeypatch 掉所有落盘写入（detail_path_cache / site_mirror / _remember_live）。
输出 _diag_fetch.txt
"""
from __future__ import annotations

import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- 先禁掉一切写入 ----
import app.core.detail_path_cache as dpc  # noqa: E402
import app.core.site_mirror as sm  # noqa: E402
import app.scrape.sources_settings as ss  # noqa: E402

dpc.remember = lambda *a, **k: None  # type: ignore[assignment]
sm.remember = lambda *a, **k: None  # type: ignore[assignment]
ss._remember_live = lambda *a, **k: None  # type: ignore[assignment]

from app.scrape_details import fetch_detail_for_source  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_diag_fetch.txt")
buf = io.StringIO()


def w(*a):
    print(*a, file=buf)


# (番号, region, 额外强制注入的源)
CASES: list[tuple[str, str, list[str]]] = [
    ("10MU-122817-01", "japan_uncensored", []),
    ("10MU-122817-01", "japan_uncensored", ["10musume", "carib", "avsox"]),
    ("HMDN-332", "japan_amateur", []),
    ("HMDN-332", "japan_amateur", ["dmm", "libredmm", "r18dev"]),
    ("MAAN-0704", "japan_amateur", []),
    ("JDSY-275", "china", []),
    ("SDAM-042", "japan_censored", []),
]


def run_one(sid: str, base: str, cookie: str, api_key: str, code: str) -> dict:
    t0 = time.perf_counter()
    try:
        d = fetch_detail_for_source(sid, code, base_url=base, cookie=cookie, api_key=api_key)
        ms = int((time.perf_counter() - t0) * 1000)
        title = str((d or {}).get("title") or "")
        actors = (d or {}).get("actors") or []
        poster = str((d or {}).get("poster") or (d or {}).get("cover_url") or "")
        return {
            "sid": sid,
            "ok": bool(title) or bool(actors) or bool(poster),
            "ms": ms,
            "title": title[:56],
            "n_actors": len(actors),
            "poster": poster[:60],
        }
    except Exception as e:  # noqa: BLE001
        return {
            "sid": sid,
            "ok": False,
            "ms": int((time.perf_counter() - t0) * 1000),
            "err": str(e)[:110],
        }


w("=" * 84)
w("真实抓取：当前分区源池 vs 强制注入源")
w("=" * 84)

for code, rid, extra in CASES:
    pool = ss.enabled_enrich_sources(region=rid)
    rows = list(pool)
    have = {r["id"] for r in rows}
    for sid in extra:
        if sid in have:
            continue
        try:
            ctx = ss.resolve_fetch_context(sid)
            row = {
                "id": sid,
                "baseUrl": ctx["baseUrl"],
                "cookie": ctx["cookie"],
                "apiKey": ctx["apiKey"],
            }
        except Exception as e:  # noqa: BLE001
            w(f"  !! 注入 {sid} 失败: {e}")
            continue
        rows.append(row)

    w("")
    w(f"### {code}   region={rid}   源池={len(pool)}  实际并发={len(rows)}")
    w("    源池: " + ", ".join(r["id"] for r in pool))
    if extra:
        w("    注入: " + ", ".join(extra))
    t0 = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {
            ex.submit(
                run_one,
                str(r["id"]),
                str(r.get("baseUrl") or ""),
                str(r.get("cookie") or ""),
                str(r.get("apiKey") or ""),
                code,
            ): r["id"]
            for r in rows
        }
        for f in as_completed(futs, timeout=120):
            results.append(f.result())
    wall = int((time.perf_counter() - t0) * 1000)
    okn = sum(1 for r in results if r.get("ok"))
    w(f"    墙钟 {wall}ms · 命中 {okn}/{len(results)}")
    for r in sorted(results, key=lambda x: (not x.get("ok"), str(x["sid"]))):
        if r.get("ok"):
            w(f"      ✓ {r['sid']:16s} {r['ms']:6d}ms  title={r['title']}  actors={r['n_actors']}  poster={'Y' if r['poster'] else 'N'}")
        else:
            w(f"      ✗ {r['sid']:16s} {r['ms']:6d}ms  {r.get('err','(空结果)')}")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
