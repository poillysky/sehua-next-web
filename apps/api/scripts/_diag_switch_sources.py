"""只读探针：六区开关 / 源池 / 数据源总开关 / 当前任务状态。

不写任何配置、不写盘。输出到 _diag_switch.txt。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "_diag_switch.txt"
lines: list[str] = []


def w(*a: object) -> None:
    s = " ".join(str(x) for x in a)
    lines.append(s)
    print(s, flush=True)


def main() -> int:
    from app.core import settings_store
    from app.scrape import source_catalog as cat
    from app.scrape import sources_settings as ss
    from app.scrap_library import enrich as enrich_svc
    from app.scrap_library import enrich_strategy as strat

    w("========== 1. 当前 enrich 任务状态 ==========")
    try:
        st = enrich_svc.get_enrich_status(lite=True)
        for k in (
            "running",
            "phase",
            "halt",
            "currentRegion",
            "jobDryRun",
            "jobId",
            "mode",
            "startedAt",
        ):
            w(f"  {k} = {st.get(k)!r}")
        w(f"  regions(运行中) = {st.get('regions')!r}")
        prog = st.get("progress") or {}
        w(f"  progress = {json.dumps(prog, ensure_ascii=False)[:200]}")
        w(f"  顶层 keys = {sorted(st.keys())}")
    except Exception as e:  # noqa: BLE001
        w("  ERROR", repr(e))

    w("")
    w("========== 2. 落库的原始策略（未规范化） ==========")
    raw = settings_store.get_setting(strat.ENRICH_STRATEGY_KEY) or {}
    w(f"  key = {strat.ENRICH_STRATEGY_KEY}")
    w(f"  regionSourcesLogicVersion = {raw.get('regionSourcesLogicVersion')!r}")
    w(
        "  原始 regionsEnabled = "
        + json.dumps(raw.get("regionsEnabled"), ensure_ascii=False)
    )
    w("  原始 regionSources:")
    for rid, sites in (raw.get("regionSources") or {}).items():
        w(f"    {rid}: {json.dumps(sites, ensure_ascii=False)}")

    w("")
    w("========== 3. get_strategy() 规范化后 ==========")
    cfg = strat.get_strategy()
    w(f"  regionSourcesLogicVersion = {cfg.get('regionSourcesLogicVersion')!r}")
    w(
        "  regionsEnabled = "
        + json.dumps(cfg.get("regionsEnabled"), ensure_ascii=False)
    )
    w("  regionSources:")
    for rid, sites in (cfg.get("regionSources") or {}).items():
        w(f"    {rid}: {json.dumps(sites, ensure_ascii=False)}")
    w("  regionGroups:")
    for rid, gs in (cfg.get("regionGroups") or {}).items():
        w(f"    {rid}: {json.dumps(gs, ensure_ascii=False)}")

    w("")
    w("========== 4. 数据源总开关（enabled）+ 上次测通 ==========")
    praw = ss.load_raw()
    by = cat.catalog_by_id()
    for sid in sorted(by.keys()):
        p = ss.provider_settings(sid, praw)
        lp = p.get("lastProbe") or {}
        meta = by[sid]
        w(
            f"  {sid:16s} group={str(meta.get('group')):10s} "
            f"enabled={p.get('enabled')!s:5s} "
            f"impl={meta.get('implemented')!r:5s} "
            f"probe_ok={lp.get('ok')!r:5s} msg={str(lp.get('message'))[:60]!r}"
        )

    w("")
    w("========== 5. 各区实际生效源池 ==========")
    for rid in strat.enrich_region_ids():
        pool = ss.enabled_enrich_sources(region=rid)
        w(f"  {rid}（{len(pool)} 源）: {[p['id'] for p in pool]}")
        w(f"      regionSources 配置: {json.dumps(strat.region_sources_for(rid), ensure_ascii=False)}")

    w("")
    w("========== 6. 无码区：磁盘真实番号 ==========")
    root = Path(r"E:\Project\sehua-next-web\media\scrap-library")
    w(f"  根: {root}  exists={root.is_dir()}")
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            codes: list[str] = []
            for pref in sorted(d.iterdir()):
                if not pref.is_dir():
                    continue
                for c in sorted(pref.iterdir()):
                    if c.is_dir():
                        codes.append(f"{pref.name}/{c.name}")
            w(f"  [{d.name}] 目录数={sum(1 for _ in d.iterdir() if _.is_dir())} 番号数={len(codes)}")
            if d.name in ("日本无码", "无码", "片区"):
                for c in codes[:40]:
                    w(f"      {c}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        OUT.write_text("\n".join(lines), encoding="utf-8")
