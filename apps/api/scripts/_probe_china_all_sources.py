# -*- coding: utf-8 -*-
"""国产区候选源矩阵：决定哪些该进 regionSources。"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from scripts._probe_amateur_all_sources import _score_detail

CODES = [
    "MD-0020",
    "MSD-005",
    "PMC-002",
    "91CM-013",
    "EMX-001",
    "GDCM-002",
    "MDX-0001",
    "DOM-001",
    "JDSY-279",
    "LLS-053",
]

SOURCES = [
    "madouqu",
    "madou",
    "xiao_huang_shu",
    "hscangku",
    "miss_av",
    "javday",
    "iqqtv",
    "freejavbt",
    "njav",
    "airav_io",
]


def main() -> int:
    from app.core.db import init_db
    from app.scrape_details import fetch_detail_for_source, registered_detail_ids
    from app.scrape import sources_settings as scrape_src
    from app.scrap_library.embed import _fetch_cover_bytes

    init_db()
    registered = set(registered_detail_ids())
    sources = [s for s in SOURCES if s in registered]
    n = len(CODES)
    print(f"codes={n} sources={sources}", flush=True)
    agg: dict[str, dict[str, Any]] = {
        sid: {
            "hit": 0,
            "miss": 0,
            "fail": 0,
            "title": 0,
            "poster": 0,
            "actors": 0,
            "studio": 0,
            "overview": 0,
            "ms_sum": 0,
            "cover_ok": 0,
            "cover_try": 0,
            "poster_hosts": defaultdict(int),
        }
        for sid in sources
    }

    for si, sid in enumerate(sources, 1):
        print(f"\n[{si}/{len(sources)}] === {sid} ===", flush=True)
        try:
            scrape_src.apply_provider_link_for_fetch(sid)
        except Exception as e:  # noqa: BLE001
            if "已禁用" in str(e):
                print("  SKIP disabled", flush=True)
                for _ in CODES:
                    agg[sid]["miss"] += 1
                continue
            print(f"  WARN {e}", flush=True)

        for code in CODES:
            t0 = time.perf_counter()
            try:
                detail = fetch_detail_for_source(sid, code)
                ms = int((time.perf_counter() - t0) * 1000)
                sc = _score_detail(detail)
                st = agg[sid]
                st["ms_sum"] += ms
                if sc["ok"]:
                    st["hit"] += 1
                else:
                    st["miss"] += 1
                if sc["title"]:
                    st["title"] += 1
                if sc["poster"]:
                    st["poster"] += 1
                    host = (urlparse(sc["posterUrl"]).hostname or "")[:40]
                    st["poster_hosts"][host] += 1
                    st["cover_try"] += 1
                    try:
                        got = _fetch_cover_bytes(sc["posterUrl"], slot_timeout=3.0)
                        if got and len(got[0]) >= 1024:
                            st["cover_ok"] += 1
                    except Exception:  # noqa: BLE001
                        pass
                if sc["actors"]:
                    st["actors"] += 1
                if sc["studio"]:
                    st["studio"] += 1
                if sc["overview"]:
                    st["overview"] += 1
                mark = "HIT" if sc["ok"] else "MISS"
                print(
                    f"  {mark:4} {code:12} {ms:5}ms  "
                    f"T={int(sc['title'])} P={int(sc['poster'])} "
                    f"A={sc['actors']} {(sc.get('titleSample') or '')[:32]}",
                    flush=True,
                )
            except Exception as e:  # noqa: BLE001
                ms = int((time.perf_counter() - t0) * 1000)
                err = str(e)[:80]
                miss_like = any(
                    x in err
                    for x in ("未找到", "搜索无结果", "番号格式", "not found", "404")
                )
                if miss_like:
                    agg[sid]["miss"] += 1
                    kind = "MISS"
                else:
                    agg[sid]["fail"] += 1
                    kind = "FAIL"
                agg[sid]["ms_sum"] += ms
                print(f"  {kind:4} {code:12} {ms:5}ms  {err}", flush=True)

    print("\n" + "=" * 96)
    print(
        f"{'source':16} {'hit':>6} {'title':>5} {'poster':>6} "
        f"{'cover':>9} {'actor':>5} {'studio':>6} {'plot':>4} {'avgMs':>6}"
    )
    ranked = []
    for sid in sources:
        st = agg[sid]
        avg = int(st["ms_sum"]) // n if n else 0
        score = (
            int(st["hit"]) * 3
            + int(st["title"]) * 2
            + int(st["cover_ok"]) * 3
            + int(st["actors"])
            + int(st["overview"])
            - int(st["fail"]) * 2
        )
        ranked.append((score, sid, st, avg))
        print(
            f"{sid:16} {st['hit']:2}/{n} {st['title']:5} {st['poster']:6} "
            f"{st['cover_ok']}/{st['cover_try']:<7} {st['actors']:5} "
            f"{st['studio']:6} {st['overview']:4} {avg:6}"
        )
    ranked.sort(key=lambda x: -x[0])
    print("\n=== 排序 ===")
    keep = []
    for score, sid, st, avg in ranked:
        hosts = ", ".join(
            f"{h}:{c}"
            for h, c in sorted(st["poster_hosts"].items(), key=lambda x: -x[1])[:2]
        )
        print(
            f"  {sid:16} score={score:.0f} hit={st['hit']}/{n} "
            f"cover={st['cover_ok']}/{st['cover_try']} avg={avg}ms  {hosts}"
        )
        if int(st["hit"]) >= 3 or int(st["cover_ok"]) >= 2:
            keep.append(sid)
    drop = [s for s in sources if s not in keep]
    print("\n建议启用:", keep)
    print("不进链:", drop)
    out = API_ROOT / "_gap_reports" / "china_all_sources.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "codes": CODES,
                "agg": {
                    k: {
                        **{kk: vv for kk, vv in v.items() if kk != "poster_hosts"},
                        "poster_hosts": dict(v["poster_hosts"]),
                    }
                    for k, v in agg.items()
                },
                "keep": keep,
                "drop": drop,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"report={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
