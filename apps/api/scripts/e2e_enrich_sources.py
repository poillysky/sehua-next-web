#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刮削库详情源 E2E（对齐 MDCS e2e-sone-source / nfo-e2e-checks）。

逐个启用源：拉样例番号 → 字段「有多少验多少」→ 基础准确性。
用法:
  .venv/Scripts/python.exe scripts/e2e_enrich_sources.py
  .venv/Scripts/python.exe scripts/e2e_enrich_sources.py --id=javbus
  .venv/Scripts/python.exe scripts/e2e_enrich_sources.py --region=japan_censored --code=SONE-001
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# MDCS e2e-fixtures 对齐
E2E_FIXTURES: dict[str, dict[str, str]] = {
    "javbus": {"code": "SONE-001", "kind": "japan_censored"},
    "dmm": {"code": "SONE-001", "kind": "japan_censored"},
    "libredmm": {"code": "SONE-001", "kind": "japan_censored"},
    "airav": {"code": "SONE-001", "kind": "japan_censored"},
    "airav_io": {"code": "SONE-001", "kind": "japan_censored"},
    "javday": {"code": "SONE-001", "kind": "japan_censored"},
    "jav321": {"code": "SONE-001", "kind": "japan_censored"},
    "avbase": {"code": "SONE-001", "kind": "japan_censored"},
    "javlibrary": {"code": "SONE-001", "kind": "japan_censored"},
    "miss_av": {"code": "SONE-001", "kind": "japan_censored"},
    "njav": {"code": "SONE-001", "kind": "japan_censored"},
    "freejavbt": {"code": "SONE-001", "kind": "japan_censored"},
    "sevenmmtv": {"code": "SONE-001", "kind": "japan_censored"},
    "iqqtv": {"code": "SONE-001", "kind": "japan_censored"},
    "avsex": {"code": "SONE-001", "kind": "japan_censored"},
    "r18dev": {"code": "SONE-001", "kind": "japan_censored"},
    "avwikidb": {"code": "SONE-001", "kind": "japan_censored"},
    "lulubar": {"code": "SONE-001", "kind": "japan_censored"},
    "mgstage": {"code": "ABP-001", "kind": "japan_censored"},
    "carib": {"code": "CARIB-010117-339", "kind": "japan_uncensored"},
    "heyzo": {"code": "HEYZO-2034", "kind": "japan_uncensored"},
    "1pondo": {"code": "1PON-062014-830", "kind": "japan_uncensored"},
    "pacopacomama": {"code": "PACO-122615-557", "kind": "japan_uncensored"},
    "kin8": {"code": "KIN8-3500", "kind": "japan_uncensored"},
    "h0930": {"code": "H0930-ki260908", "kind": "japan_uncensored"},
    "h4610": {"code": "H4610-ki260908", "kind": "japan_uncensored"},
    "c0930": {"code": "C0930-hitozuma1369", "kind": "japan_uncensored"},
    "tokyohot": {"code": "TOKYOHOT-N1234", "kind": "japan_uncensored"},
    "nyoshin": {"code": "NYOSHIN-2500", "kind": "japan_uncensored"},
    "avsox": {"code": "CARIB-010117-339", "kind": "japan_uncensored"},
    "avmoo": {"code": "SONE-001", "kind": "japan_censored"},
    "fd2ppv": {"code": "FC2-PPV-3275049", "kind": "fc2"},
    "fc2": {"code": "FC2-1545500", "kind": "fc2"},
    "madou": {"code": "MDX-0001", "kind": "china"},
    "madouqu": {"code": "MDX-0006", "kind": "china"},
    "hscangku": {"code": "MDX-0006", "kind": "china"},
    "xiao_huang_shu": {"code": "MDX-0006", "kind": "china"},
    "theporndb": {"code": "PURETABOO.2026.07.14", "kind": "western"},
    "avheat": {"code": "WeLiveTogether.12.02.23", "kind": "western"},
}

_JUNK_TITLE = (
    "会员登入",
    "會員登入",
    "login",
    "just a moment",
    "attention required",
    "access denied",
    "cloudflare",
    "404",
)


def _norm_code(s: str) -> str:
    """番号归一：去非字母数字；FC2 / FC2-PPV 视为同号。"""
    t = re.sub(r"[^A-Z0-9]", "", str(s or "").upper())
    # FC2PPV123 → FC2123（样例 FC2-1545500 与源站 FC2-PPV-1545500）
    t = re.sub(r"^FC2PPV", "FC2", t)
    return t

def _has_text(v: Any) -> bool:
    return bool(str(v or "").strip())


def _collected(detail: dict[str, Any]) -> dict[str, bool]:
    """对齐 MDCS metaCollectedFields（映射到本仓库 detail 字段）。"""
    actors = [a for a in (detail.get("actors") or []) if str(a).strip()]
    tags = [t for t in (detail.get("tags") or []) if str(t).strip()]
    poster = str(detail.get("posterUrl") or detail.get("poster") or "").strip()
    studio = str(detail.get("studio") or detail.get("maker") or "").strip()
    return {
        "code": _has_text(detail.get("code") or detail.get("id")),
        "title": _has_text(detail.get("title")),
        "actors": len(actors) > 0,
        "studio": bool(studio),
        "overview": _has_text(detail.get("overview")),
        "poster": poster.startswith(("http://", "https://")),
        "year": _has_text(detail.get("year")),
        "date": _has_text(detail.get("date")),
        "tags": len(tags) > 0,
    }


def _field_checks(
    detail: dict[str, Any], *, expect_code: str
) -> list[dict[str, Any]]:
    """有多少验多少：collected=true 的字段必须合理。"""
    collected = _collected(detail)
    code = str(detail.get("code") or detail.get("id") or "").strip().upper()
    title = str(detail.get("title") or "").strip()
    title_l = title.casefold()
    actors = [str(a).strip() for a in (detail.get("actors") or []) if str(a).strip()]
    poster = str(detail.get("posterUrl") or detail.get("poster") or "").strip()
    studio = str(detail.get("studio") or detail.get("maker") or "").strip()
    overview = str(detail.get("overview") or "").strip()
    expect_n = _norm_code(expect_code)
    got_n = _norm_code(code)

    checks: list[dict[str, Any]] = []

    def add(fid: str, label: str, ok: bool, note: str = "") -> None:
        req = bool(collected.get(fid))
        checks.append(
            {
                "id": fid,
                "label": label,
                "required": req,
                "ok": ok,
                "note": note,
                "value": None,
            }
        )

    # code：有值则须与样例归一化一致（允许前导零差异时至少包含核心）
    code_ok = bool(got_n) and (got_n == expect_n or expect_n in got_n or got_n in expect_n)
    add("code", "番号", code_ok, f"got={code or '-'}")
    checks[-1]["value"] = code

    junk = any(m in title_l for m in _JUNK_TITLE)
    thin = (not title) or title.upper() == code or len(title) < 4
    title_ok = bool(title) and not junk and not thin
    add("title", "标题", title_ok, title[:60] if title else "empty")
    checks[-1]["value"] = title[:120]

    actors_ok = len(actors) > 0 and all(1 < len(a) <= 40 for a in actors)
    add("actors", "女优", actors_ok, f"n={len(actors)}")
    checks[-1]["value"] = actors[:8]

    studio_ok = bool(studio) and len(studio) <= 80 and "登入" not in studio
    add("studio", "片商", studio_ok, studio[:40] if studio else "")
    checks[-1]["value"] = studio

    overview_ok = len(overview) >= 12
    add("overview", "剧情", overview_ok, f"len={len(overview)}")
    checks[-1]["value"] = overview[:80]

    poster_ok = poster.startswith(("http://", "https://")) and "now_printing" not in poster.lower()
    add("poster", "封面", poster_ok, poster[:64] if poster else "")
    checks[-1]["value"] = poster

    year = str(detail.get("year") or "").strip()
    year_ok = bool(re.fullmatch(r"19\d{2}|20\d{2}", year or ""))
    add("year", "年份", year_ok, year)
    checks[-1]["value"] = year

    date = str(detail.get("date") or "").strip()
    date_ok = bool(re.match(r"^\d{4}-\d{2}-\d{2}", date or ""))
    add("date", "发行日", date_ok, date)
    checks[-1]["value"] = date

    tags = [str(t).strip() for t in (detail.get("tags") or []) if str(t).strip()]
    tags_ok = len(tags) > 0
    add("tags", "标签", tags_ok, f"n={len(tags)}")
    checks[-1]["value"] = tags[:10]

    # 未收集的字段不算必过失败
    for c in checks:
        if not c["required"]:
            # 仍记录 ok，但不计入 required
            pass
    return checks


def _summarize(checks: list[dict[str, Any]]) -> dict[str, Any]:
    required = [c for c in checks if c.get("required")]
    required_ok = all(c.get("ok") for c in required) if required else False
    collected_ids = [c["id"] for c in required]
    return {
        "requiredOk": required_ok,
        "collectedCount": len(required),
        "requiredPass": sum(1 for c in required if c.get("ok")),
        "collectedIds": collected_ids,
        "failIds": [c["id"] for c in required if not c.get("ok")],
    }


def run_one(
    source_id: str,
    *,
    code: str,
    include_flare: bool,
) -> dict[str, Any]:
    from app.core import outbound_http
    from app.scrape import sources_settings as scrape_src
    from app.scrape_details import fetch_detail_for_source
    from app.scrap_library.enrich import _clean_actors, _clean_tags, _detail_usable

    outbound_http.set_thread_allow_flare(include_flare)
    t0 = time.perf_counter()
    err = ""
    detail: dict[str, Any] | None = None
    try:
        applied = scrape_src.apply_provider_link_for_fetch(source_id)
        detail = fetch_detail_for_source(
            source_id,
            code,
            base_url=str(applied.get("baseUrl") or ""),
            cookie=str(applied.get("cookie") or ""),
            api_key=str(applied.get("apiKey") or ""),
        )
        if detail:
            detail = dict(detail)
            detail["actors"] = _clean_actors(detail.get("actors"))
            detail["tags"] = _clean_tags(detail.get("tags"))
        if not _detail_usable(detail, code=code):
            err = f"rejected:{(detail or {}).get('title') or 'empty'}"
            detail = None
    except Exception as e:  # noqa: BLE001
        err = str(e)[:200]
        detail = None
    ms = int(round((time.perf_counter() - t0) * 1000))

    if not detail:
        return {
            "id": source_id,
            "code": code,
            "ok": False,
            "ms": ms,
            "error": err or "no_detail",
            "collected": {},
            "checks": [],
            "summary": {
                "requiredOk": False,
                "collectedCount": 0,
                "requiredPass": 0,
                "failIds": ["fetch"],
            },
            "sample": None,
        }

    checks = _field_checks(detail, expect_code=code)
    summary = _summarize(checks)
    collected = _collected(detail)
    sample = {
        "code": detail.get("code"),
        "title": str(detail.get("title") or "")[:100],
        "studio": detail.get("studio") or detail.get("maker"),
        "actors": (detail.get("actors") or [])[:8],
        "tags": (detail.get("tags") or [])[:8],
        "year": detail.get("year"),
        "date": detail.get("date"),
        "posterUrl": str(detail.get("posterUrl") or "")[:100],
        "overviewLen": len(str(detail.get("overview") or "")),
    }
    return {
        "id": source_id,
        "code": code,
        "ok": bool(summary.get("requiredOk")),
        "ms": ms,
        "error": "",
        "collected": collected,
        "checks": checks,
        "summary": summary,
        "sample": sample,
        "access": str(detail.get("access") or ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich sources E2E (MDCS-style)")
    parser.add_argument("--id", default="", help="只测一个源 id")
    parser.add_argument("--region", default="japan_censored")
    parser.add_argument("--code", default="", help="覆盖样例番号")
    parser.add_argument(
        "--all-catalog",
        action="store_true",
        help="测目录里全部有详情实现的源（不只 enabled）",
    )
    parser.add_argument(
        "--out",
        default="",
        help="报告 JSON 路径（默认 apps/api/_gap_reports/e2e_enrich_sources.json）",
    )
    args = parser.parse_args()

    from app.core.db import init_db

    init_db()
    from app.scrap_library import enrich_strategy as strat
    from app.scrape import sources_settings as scrape_src
    from app.scrape_details import registered_detail_ids

    cfg = strat.get_strategy()
    include_flare = bool(cfg.get("includeFlare", True))

    if args.id:
        source_ids = [str(args.id).strip()]
    elif args.all_catalog:
        source_ids = sorted(registered_detail_ids())
    else:
        rows = scrape_src.enabled_enrich_sources(region=args.region)
        source_ids = []
        for r in rows:
            sid = str(r.get("id") or "").strip()
            if not sid:
                continue
            access = str(r.get("access") or "")
            if access == "proxy_flare" and not include_flare:
                continue
            source_ids.append(sid)

    out_path = Path(
        args.out
        or (ROOT / "_gap_reports" / "e2e_enrich_sources.json")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"E2E enrich sources · region={args.region} · includeFlare={include_flare} · n={len(source_ids)}",
        flush=True,
    )
    results: list[dict[str, Any]] = []
    for i, sid in enumerate(source_ids, 1):
        fix = E2E_FIXTURES.get(sid) or {"code": "SONE-001", "kind": args.region}
        code = str(args.code or fix["code"]).strip().upper()
        print(f"\n[{i}/{len(source_ids)}] {sid} · {code} …", flush=True)
        one = run_one(sid, code=code, include_flare=include_flare)
        results.append(one)
        if one.get("ok"):
            sm = one["summary"]
            sample = one.get("sample") or {}
            print(
                f"  OK  {one['ms']}ms  "
                f"fields {sm['requiredPass']}/{sm['collectedCount']}  "
                f"actors={len(sample.get('actors') or [])}  "
                f"studio={sample.get('studio') or '-'}  "
                f"title={(sample.get('title') or '')[:40]}",
                flush=True,
            )
        else:
            fails = one.get("summary", {}).get("failIds") or []
            print(
                f"  FAIL {one['ms']}ms  {one.get('error') or fails}",
                flush=True,
            )

    ok_n = sum(1 for r in results if r.get("ok"))
    report = {
        "region": args.region,
        "includeFlare": include_flare,
        "mode": cfg.get("mode"),
        "total": len(results),
        "ok": ok_n,
        "failed": len(results) - ok_n,
        "results": results,
    }
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"\nDONE · ok={ok_n}/{len(results)} · report={out_path}",
        flush=True,
    )
    # 表格摘要
    print("\n=== summary ===", flush=True)
    for r in results:
        mark = "OK " if r.get("ok") else "FAIL"
        sm = r.get("summary") or {}
        print(
            f"{mark}  {r.get('ms', 0):6d}ms  {str(r.get('id')):14s}  "
            f"{sm.get('requiredPass', 0)}/{sm.get('collectedCount', 0)}  "
            f"{r.get('error') or (',').join(sm.get('failIds') or []) or '-'}",
            flush=True,
        )
    return 0 if ok_n == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
