"""只读探针：无码区候选源命中矩阵（不改任何配置）。

对「磁盘真实存在的无码番号」+「pending 里的代表前缀」，逐个候选源直连探测，
输出每个源 OK / 未收录 / 技术失败，用于决定 regionSources.japan_uncensored。

用法：
  .venv\\Scripts\\python.exe scripts\\_probe_uncensored_candidates.py
输出：
  apps/api/_probe_unc_cand.txt
"""
from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
ROOT = API_ROOT.parents[0]
sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(API_ROOT / "_gap_reports"))

OUT = API_ROOT / "_probe_unc_cand.txt"
LINES: list[str] = []
_lock = threading.Lock()


def w(*a: object) -> None:
    s = " ".join(str(x) for x in a)
    with _lock:
        LINES.append(s)
        print(s, flush=True)


# 候选源：无码相关 + 通用聚合
CANDIDATES = [
    "10musume",
    "carib",
    "avsox",
    "miss_av",
    "njav",
    "javday",
    "lulubar",
    "iqqtv",
    "javbus",
    "jav321",
    "freejavbt",
    "airav_io",
    "sevenmmtv",
    "mgstage",
]

# 磁盘上真实存在的无码番号（media/scrap-library/日本无码/10MUSUME/*）
DISK_CODES = [
    "10MU-122609-01",
    "10MU-122711-01",
    "10MU-122714-01",
    "10MU-122817-01",
    "10MU-122912-02",
    "10MU-122918-01",
    "10MU-123009-01",
]

GHOST_PREFIXES = ["CARIB", "HEYZO", "1PON", "KIN8", "PACO", "C0930", "H4610", "RHJ"]

REGION = "japan_uncensored"


def _make_row(sid: str) -> dict | None:
    from app.scrape import source_catalog as cat
    from app.scrape import sources_settings as ss
    from app.scrape.sources_settings import ENRICH_DETAIL_PROVIDERS

    sid = cat.canonicalize_id(sid)
    meta = cat.catalog_by_id().get(sid) or {}
    dk = ENRICH_DETAIL_PROVIDERS.get(sid)
    if not sid or not meta or not dk:
        return None
    cfg = ss.provider_settings(sid)
    if not cfg.get("enabled", True):
        return {
            "id": sid,
            "detailKey": dk,
            "group": str(meta.get("group") or ""),
            "label": str(meta.get("label") or sid),
            "baseUrl": "",
            "cookie": "",
            "apiKey": "",
            "access": ss.catalog_access(sid),
            "region": REGION,
            "_disabled": True,
        }
    return {
        "id": sid,
        "detailKey": dk,
        "group": str(meta.get("group") or ""),
        "label": str(meta.get("label") or sid),
        "baseUrl": ss.effective_display_url(sid, cfg=cfg),
        "cookie": str(cfg.get("cookie") or ""),
        "apiKey": str(cfg.get("apiKey") or ""),
        "access": ss.catalog_access(sid),
        "region": REGION,
    }


def _ghost_codes() -> list[str]:
    from app.core.db import get_meta_pool
    from app.scrap_library.embed import TABLE

    pool = get_meta_pool()
    out: list[str] = []
    with pool.connection() as conn, conn.cursor() as cur:
        for pref in GHOST_PREFIXES:
            cur.execute(
                f"""
                SELECT code, title, rel_path FROM {TABLE}
                WHERE region = '日本无码' AND prefix = %s
                ORDER BY random() LIMIT 2
                """,
                (pref,),
            )
            for r in cur.fetchall() or []:
                out.append(str(dict(r).get("code")))
    return out


def _db_rows(codes: list[str]) -> dict[str, dict]:
    from app.core.db import get_meta_pool
    from app.scrap_library.embed import TABLE

    pool = get_meta_pool()
    got: dict[str, dict] = {}
    with pool.connection() as conn, conn.cursor() as cur:
        for c in codes:
            cur.execute(
                f"SELECT code, prefix, rel_path, region, title, content_sha FROM {TABLE} WHERE code=%s LIMIT 1",
                (c,),
            )
            row = cur.fetchone()
            if row:
                got[c] = dict(row)
    return got


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="", help="只探这些源，逗号分隔；留空=全部候选")
    ap.add_argument("--real-only", action="store_true", help="只探磁盘真实番号")
    ap.add_argument("--ghost-only", action="store_true", help="只探幽灵前缀样本")
    args = ap.parse_args()

    from _e2e_one_code import _probe_one_source  # type: ignore

    from app.core.db import get_meta_pool
    from app.scrap_library.embed import TABLE

    wanted = [s.strip() for s in args.sources.split(",") if s.strip()]
    cands = [s for s in CANDIDATES if not wanted or s in wanted]

    w("========== 0. 磁盘真实无码番号在向量库中的行 ==========")
    db = _db_rows(DISK_CODES)
    for c in DISK_CODES:
        row = db.get(c)
        w(f"  {c:18s} inDB={bool(row)} {json.dumps(row, ensure_ascii=False) if row else ''}")

    w("")
    w("========== 1. 向量库 日本无码 前缀分布（top 25） ==========")
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT prefix, count(*) AS n FROM {TABLE}
            WHERE region='日本无码' GROUP BY prefix ORDER BY n DESC LIMIT 25
            """
        )
        for r in cur.fetchall() or []:
            d = dict(r)
            w(f"  {str(d.get('prefix')):12s} {d.get('n')}")
        cur.execute(f"SELECT count(*) AS n FROM {TABLE} WHERE region='日本无码'")
        w(f"  合计 = {dict(cur.fetchone()).get('n')}")

    w("")
    w("========== 2. 有效源池（当前配置，未改） ==========")
    from app.scrap_library.enrich import _detail_sources

    pool_ids = [str(s.get("id")) for s in _detail_sources(region=REGION)]
    w(f"  {pool_ids}")
    from app.scrap_library import enrich_strategy as strat

    w(f"  regionSources 配置: {json.dumps(strat.region_sources_for(REGION), ensure_ascii=False)}")

    rows = [_make_row(s) for s in cands]
    rows = [r for r in rows if r]
    w("")
    w("========== 3. 候选源可用性 ==========")
    for r in rows:
        w(
            f"  {r['id']:14s} group={r['group']:10s} "
            f"enabled={'NO' if r.get('_disabled') else 'yes':3s} "
            f"access={r['access']:16s} base={r['baseUrl']}"
        )

    ghost = _ghost_codes()
    w("")
    w(f"========== 4. 幽灵样本（每前缀 2 条，共 {len(ghost)}） ==========")
    w(f"  {ghost}")

    all_codes = ([] if args.ghost_only else DISK_CODES) + (
        [] if args.real_only else ghost
    )
    total_ms = 0
    # 逐番号 × 并行源
    for code in all_codes:
        w("")
        w(f"---- {code} ----")
        t0 = time.perf_counter()
        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="probe") as ex:
            futs = {
                ex.submit(_probe_one_source, r, code): r
                for r in rows
                if not r.get("_disabled")
            }
            for fut in as_completed(futs, timeout=200):
                r = futs[fut]
                try:
                    res = fut.result()
                except Exception as e:  # noqa: BLE001
                    res = {"id": r["id"], "ok": False, "error": f"{type(e).__name__}: {e}"}
                results[str(r["id"])] = res
        ms = int((time.perf_counter() - t0) * 1000)
        total_ms += ms
        for r in rows:
            sid = r["id"]
            if r.get("_disabled"):
                w(f"  [off] {sid:14s} （数据源总开关关闭，未探测）")
                continue
            res = results.get(sid) or {}
            snap = res.get("fields") or {}
            if res.get("ok"):
                mark = "OK  "
            elif res.get("expected_fail"):
                mark = "MISS"
            else:
                mark = "FAIL"
            title = str(snap.get("title") or "")[:40]
            err = str(res.get("error") or "")[:60]
            w(
                f"  [{mark}] {sid:14s} {int(res.get('ms') or 0):5d}ms "
                f"A={snap.get('actors_n', 0)} P={snap.get('overview_len', 0):4d} "
                f"S={bool(snap.get('studio'))} T={snap.get('tags_n', 0):2d} "
                f"{title or err or '-'}"
            )
    w("")
    w(f"总墙钟 {total_ms}ms / {len(all_codes)} 番号")

    # 命中汇总
    w("")
    w("========== 5. 汇总：各源命中数 ==========")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        import traceback

        traceback.print_exc()
        code = 2
    finally:
        OUT.write_text("\n".join(LINES), encoding="utf-8")
    sys.exit(code)
