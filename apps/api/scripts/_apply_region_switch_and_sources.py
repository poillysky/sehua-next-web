"""配置：六区刮削开关互斥 + 无码区源池补齐（幂等，可反复跑）。

做什么：
  1) regionsEnabled → 只有 --on 指定的区为 true，其余五区一律 false（互斥）
  2) regionSources[--on] → 按 --sources 写有序源（高→低优先级）
  3) 数据源总开关 → 把 --enable-sites 里的站置为 enabled=true

默认 dry-run 只打印；加 --apply 才落库。

用法：
  .venv\\Scripts\\python.exe scripts\\_apply_region_switch_and_sources.py
  .venv\\Scripts\\python.exe scripts\\_apply_region_switch_and_sources.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

DEFAULT_ON = "japan_uncensored"

# 无码区有序源（高→低）。顺序依据：官网/专站 → 无码专站 → 通用聚合。
DEFAULT_SOURCES = [
    "10musume",
    "carib",
    "avsox",
    "miss_av",
    "njav",
    "iqqtv",
    "javbus",
    "jav321",
    "freejavbt",
    "airav_io",
]

DEFAULT_ENABLE_SITES = ["avsox", "10musume", "carib"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正落库")
    ap.add_argument("--on", default=DEFAULT_ON, help="唯一开启的分区 id")
    ap.add_argument(
        "--sources",
        default="",
        help="该区有序源，逗号分隔；留空用脚本内默认",
    )
    ap.add_argument(
        "--enable-sites",
        default="",
        help="要打开总开关的数据源 id，逗号分隔；留空用脚本内默认",
    )
    args = ap.parse_args()

    from app.scrape import source_catalog as cat
    from app.scrape import sources_settings as ss
    from app.scrap_library import enrich_strategy as strat
    from app.scrap_library.enrich import _detail_sources

    on_rid = str(args.on).strip()
    ids = strat.enrich_region_ids()
    if on_rid not in ids:
        print(f"未知分区 id: {on_rid}；可选 {ids}")
        return 1

    sources = [
        s.strip()
        for s in (args.sources.split(",") if args.sources else DEFAULT_SOURCES)
        if s.strip()
    ]
    enable_sites = [
        s.strip()
        for s in (
            args.enable_sites.split(",")
            if args.enable_sites
            else DEFAULT_ENABLE_SITES
        )
        if s.strip()
    ]

    known = cat.catalog_by_id()
    bad = [s for s in sources if cat.canonicalize_id(s) not in known]
    if bad:
        print(f"未知数据源 id: {bad}")
        return 1

    print(f"mode = {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"唯一开启分区 = {on_rid}")
    print(f"该区源序 = {json.dumps(sources, ensure_ascii=False)}")
    print(f"要打开总开关的站 = {json.dumps(enable_sites, ensure_ascii=False)}")

    before = strat.get_strategy()
    print("")
    print("--- before · regionsEnabled ---")
    print("  " + json.dumps(before.get("regionsEnabled"), ensure_ascii=False))
    print("--- before · regionSources[" + on_rid + "] ---")
    print("  " + json.dumps(strat.region_sources_for(on_rid), ensure_ascii=False))
    praw = ss.load_raw()
    print("--- before · 相关站总开关 ---")
    for sid in sorted(set(sources) | set(enable_sites)):
        cfg = ss.provider_settings(sid, praw)
        print(f"  {sid:14s} enabled={cfg.get('enabled')}")

    if not args.apply:
        print("")
        print("（dry-run，未写库；加 --apply 生效）")
        return 0

    # 1) 数据源总开关
    changed_sites: list[str] = []
    for sid in enable_sites:
        cur = ss.provider_settings(sid)
        if not cur.get("enabled", True):
            ss.save_provider(sid, {"enabled": True})
            changed_sites.append(sid)
    print("")
    print(f"已打开总开关: {changed_sites or '（无需改动）'}")

    # 2) 策略：源序 + 互斥开关
    cur_cfg = strat.get_strategy()
    rs = dict(cur_cfg.get("regionSources") or {})
    rs[on_rid] = sources
    regions_enabled = {rid: (rid == on_rid) for rid in ids}
    body = {
        **cur_cfg,
        "regionSources": rs,
        "regionsEnabled": regions_enabled,
    }
    cfg = strat.put_strategy(body)

    print("--- after · regionsEnabled ---")
    print("  " + json.dumps(cfg.get("regionsEnabled"), ensure_ascii=False))
    print("--- after · regionSources[" + on_rid + "] ---")
    print("  " + json.dumps(strat.region_sources_for(on_rid), ensure_ascii=False))
    print("--- after · regionGroups[" + on_rid + "] ---")
    print("  " + json.dumps((cfg.get("regionGroups") or {}).get(on_rid), ensure_ascii=False))

    print("")
    print("--- 各区实际生效源池（规范化后重读） ---")
    for rid in ids:
        pool = [p["id"] for p in _detail_sources(region=rid)]
        mark = "  <= 开启" if rid == on_rid else ""
        print(f"  {rid:18s} ({len(pool)}) {pool}{mark}")

    # 复核：落库值能读回
    again = strat.get_strategy()
    ok = (
        again.get("regionsEnabled") == regions_enabled
        and list(strat.region_sources_for(on_rid)) == sources
    )
    print("")
    print(f"复核读回一致 = {ok}")
    if not ok:
        print("  regionsEnabled:", json.dumps(again.get("regionsEnabled"), ensure_ascii=False))
        print("  sources:", json.dumps(strat.region_sources_for(on_rid), ensure_ascii=False))
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
