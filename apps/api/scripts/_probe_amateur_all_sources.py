# -*- coding: utf-8 -*-
"""素人区：全候选数据源 × 多样本番号矩阵，找最优 regionSources。

测两类：
1) 当前素人已启用源
2) 有码池/常见聚合站候选（可能 complementary）

用法：
  .venv\\Scripts\\python.exe scripts/_probe_amateur_all_sources.py
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

# 多样本：MGS 数字前缀 / SIRO / SCUTE / 盘上厂牌 / 边缘
CODES = [
    "SIRO-3365",
    "LUXU-1783",
    "GANA-2816",
    "MAAN-844",
    "ARA-465",
    "SCUTE-1324",
    "SQTE-514",
    "SAMA-236",
    "NAMH-028",
    "SUKE-050",
]

# 当前配置 + 值得一试的候选（排除无码官网/国产/欧美/FC2）
SOURCES = [
    # 当前素人链
    "mgstage",
    "javbus",
    "airav_io",
    "jav321",
    "freejavbt",
    "miss_av",
    "javday",
    # 有码池候选
    "dmm",
    "libredmm",
    "r18dev",
    "avbase",
    "iqqtv",
    # 其它聚合
    "airav",
    "njav",
    "sevenmmtv",
    "lulubar",
    "avsox",
    "javlibrary",
]


def _score_detail(d: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(d, dict):
        return {
            "ok": False,
            "title": False,
            "poster": False,
            "actors": 0,
            "studio": False,
            "overview": False,
            "tags": 0,
        }
    title = str(d.get("title") or "").strip()
    poster = str(d.get("posterUrl") or d.get("poster") or "").strip()
    actors = d.get("actors") or []
    if not isinstance(actors, list):
        actors = []
    tags = d.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    studio = str(d.get("studio") or d.get("maker") or "").strip()
    overview = str(d.get("overview") or "").strip()
    # 标题不能只是番号本身
    code_u = str(d.get("code") or "").strip().upper()
    title_body = title
    if code_u and title_body.upper().startswith(code_u):
        title_body = title_body[len(code_u) :].strip(" -_")
    title_ok = len(title_body) >= 2
    return {
        "ok": title_ok or bool(poster) or bool(actors),
        "title": title_ok,
        "poster": poster.startswith("http"),
        "posterUrl": poster[:120] if poster.startswith("http") else "",
        "actors": len([a for a in actors if str(a).strip()]),
        "studio": bool(studio),
        "overview": len(overview) >= 20,
        "tags": len([t for t in tags if str(t).strip()]),
        "titleSample": title[:50],
    }


def main() -> int:
    from app.core.db import init_db
    from app.scrape_details import fetch_detail_for_source, registered_detail_ids
    from app.scrape import sources_settings as scrape_src

    init_db()
    registered = set(registered_detail_ids())
    sources = [s for s in SOURCES if s in registered]
    missing = [s for s in SOURCES if s not in registered]
    if missing:
        print(f"skip unregistered: {missing}")

    print(f"codes={len(CODES)} sources={len(sources)}")
    print(f"sources={sources}")
    print("=" * 100)

    # sid -> aggregates
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
    matrix: list[dict[str, Any]] = []

    from app.scrap_library.embed import _fetch_cover_bytes

    for si, sid in enumerate(sources, 1):
        print(f"\n[{si}/{len(sources)}] === {sid} ===", flush=True)
        try:
            scrape_src.apply_provider_link_for_fetch(sid)
        except Exception as e:  # noqa: BLE001
            err = str(e)
            if "已禁用" in err or "disabled" in err.lower():
                print(f"  SKIP disabled: {err}", flush=True)
                for code in CODES:
                    matrix.append(
                        {
                            "source": sid,
                            "code": code,
                            "ok": False,
                            "ms": 0,
                            "error": "disabled",
                            "skipped": True,
                        }
                    )
                    agg[sid]["miss"] += 1
                continue
            print(f"  WARN apply_link: {err[:80]}", flush=True)
        for code in CODES:
            t0 = time.perf_counter()
            row: dict[str, Any] = {"source": sid, "code": code}
            try:
                detail = fetch_detail_for_source(sid, code)
                ms = int((time.perf_counter() - t0) * 1000)
                sc = _score_detail(detail)
                row.update(sc)
                row["ms"] = ms
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
                    # host
                    from urllib.parse import urlparse

                    host = (urlparse(sc["posterUrl"]).hostname or "")[:40]
                    st["poster_hosts"][host] += 1
                    # try cover once per source×code when poster present
                    st["cover_try"] += 1
                    try:
                        got = _fetch_cover_bytes(sc["posterUrl"], slot_timeout=3.0)
                        if got and len(got[0]) >= 1024:
                            st["cover_ok"] += 1
                            row["coverOk"] = True
                        else:
                            row["coverOk"] = False
                    except Exception as ce:  # noqa: BLE001
                        row["coverOk"] = False
                        row["coverErr"] = f"{type(ce).__name__}"
                if sc["actors"]:
                    st["actors"] += 1
                if sc["studio"]:
                    st["studio"] += 1
                if sc["overview"]:
                    st["overview"] += 1
                mark = "HIT" if sc["ok"] else "MISS"
                print(
                    f"  {mark:4} {code:14} {ms:5}ms  "
                    f"T={int(sc['title'])} P={int(sc['poster'])} "
                    f"A={sc['actors']} S={int(sc['studio'])} O={int(sc['overview'])}  "
                    f"{(sc.get('titleSample') or '')[:36]}",
                    flush=True,
                )
            except Exception as e:  # noqa: BLE001
                ms = int((time.perf_counter() - t0) * 1000)
                err = str(e)[:80]
                row.update({"ok": False, "ms": ms, "error": err})
                miss_like = any(
                    x in err for x in ("未找到", "搜索无结果", "番号格式", "not found", "404")
                )
                if miss_like:
                    agg[sid]["miss"] += 1
                    kind = "MISS"
                else:
                    agg[sid]["fail"] += 1
                    kind = "FAIL"
                agg[sid]["ms_sum"] += ms
                print(f"  {kind:4} {code:14} {ms:5}ms  {err}", flush=True)
            matrix.append(row)

    n = len(CODES)
    print("\n" + "=" * 100)
    print(
        f"{'source':12} {'hit':>3}/{n} {'title':>5} {'poster':>6} "
        f"{'cover':>9} {'actor':>5} {'studio':>6} {'plot':>4} {'avgMs':>6}  rank"
    )

    ranked: list[tuple[float, str, dict[str, Any]]] = []
    for sid in sources:
        st = agg[sid]
        hit = int(st["hit"])
        # 综合分：命中×3 + 标题×2 + 可下封面×3 + 女优 + 剧情 + 片商 — 失败惩罚
        cover_ok = int(st["cover_ok"])
        score = (
            hit * 3
            + int(st["title"]) * 2
            + cover_ok * 3
            + int(st["actors"])
            + int(st["overview"])
            + int(st["studio"]) * 0.5
            - int(st["fail"]) * 2
        )
        avg = int(st["ms_sum"]) // n if n else 0
        cover_s = f"{cover_ok}/{int(st['cover_try'])}"
        ranked.append((score, sid, st))
        print(
            f"{sid:12} {hit:3}/{n} {int(st['title']):5} {int(st['poster']):6} "
            f"{cover_s:>9} {int(st['actors']):5} {int(st['studio']):6} "
            f"{int(st['overview']):4} {avg:6}  {score:.1f}"
        )

    ranked.sort(key=lambda x: (-x[0], x[1]))
    print("\n=== 推荐排序（按综合分）===")
    for i, (score, sid, st) in enumerate(ranked, 1):
        hosts = ", ".join(
            f"{h}:{c}" for h, c in sorted(st["poster_hosts"].items(), key=lambda x: -x[1])[:3]
        )
        print(
            f"{i:2}. {sid:12} score={score:.1f}  "
            f"hit={st['hit']}/{n} cover={st['cover_ok']}/{st['cover_try']}  "
            f"hosts=[{hosts}]"
        )

    # 建议链：命中≥3 或 cover≥2，去掉纯 fail 黑洞
    keep = []
    for score, sid, st in ranked:
        if int(st["hit"]) >= 3 or int(st["cover_ok"]) >= 2:
            keep.append(sid)
        elif int(st["hit"]) >= 2 and int(st["fail"]) == 0:
            keep.append(sid)
    # 封面优先：能下图的排前面一点，但 mgstage 官方图优先若 hit 够
    def _order_key(sid: str) -> tuple[int, float]:
        st = agg[sid]
        # mgstage 官方优先
        official = 0 if sid == "mgstage" else 1
        score = next(s for s, i, _ in ranked if i == sid)
        return (official, -score)

    # 重新按：官方 mgstage → 高 cover → 高 hit
    suggested = sorted(keep, key=lambda sid: (
        0 if sid == "mgstage" and agg[sid]["hit"] >= 2 else 1,
        -agg[sid]["cover_ok"],
        -agg[sid]["hit"],
        -agg[sid]["title"],
    ))
    # 去弱
    suggested = [s for s in suggested if agg[s]["hit"] > 0 or agg[s]["cover_ok"] > 0]
    drop = [sid for sid in sources if sid not in suggested]

    print("\n=== 建议素人 regionSources ===")
    print(suggested)
    print("可去掉/别进默认:", drop)

    out = API_ROOT / "_gap_reports" / "amateur_all_sources_matrix.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "codes": CODES,
                "sources": sources,
                "agg": {
                    k: {
                        **{kk: vv for kk, vv in v.items() if kk != "poster_hosts"},
                        "poster_hosts": dict(v["poster_hosts"]),
                    }
                    for k, v in agg.items()
                },
                "ranked": [{"source": s, "score": sc} for sc, s, _ in ranked],
                "suggested": suggested,
                "drop": drop,
                "matrix": matrix,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nreport={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
