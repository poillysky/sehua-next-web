# -*- coding: utf-8 -*-
"""Re-check search_miss prefixes on MissAV / MGStage / DMM; classify wrong vs empty."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import outbound_http as o  # noqa: E402
from app import prefix_catalog_dmm as dmm  # noqa: E402
from app import prefix_catalog_store as store  # noqa: E402
from app.core.region_meta import std_prefix  # noqa: E402

OUT = ROOT / "data" / "debug" / "prefix-miss-recheck.json"

# 明显不是日本有码/素人番号前缀
NOISE = {
    "JAVBUS",
    "JQUERY",
    "LAYOUT",
    "MAKER",
    "POINT",
    "SALE",
    "PURETABOO",
    "KNIGHTSVISUAL",
    "GETCHU",
    "GIGAWEB",
    "BAFFCC",
    "AFFF",
    "EDBE",
    "DENP",
    "WWSZV",
    "UFF",
    "20SEX",
    "533DB",
    "919DF",
    "93DFC",
}

# 已知别名 / 正确搜词
ALIASES: dict[str, list[str]] = {
    "STAR": ["STARS", "STAR"],
    "WANZ": ["WANZ"],
    "DANDY": ["DANDY"],
    "JUL": ["JUL"],
    "IPZ": ["IPZ"],
    "RCT": ["RCT", "RCTD"],
    "NHDT": ["NHDT", "NHDTB", "NHDTA"],
    "HUNT": ["HUNT", "HUNTA", "HUNTB"],
    "ORE": ["ORE", "230ORE", "OREX"],
    "ARA": ["ARA"],
    "SIROHAME": ["SIRO-HAME", "siro-hame", "SIROHAME"],
    "230OREX": ["230OREX", "OREX"],
    "VENU": ["VENU"],
    "RBD": ["RBD"],
    "OBA": ["OBA"],
    "ARM": ["ARM"],
    "ABS": ["ABS"],
    "AKNR": ["AKNR"],
    "BF": ["BF"],
    "DV": ["DV"],
    "MDB": ["MDB", "MDBK"],
    "MDS": ["MDS"],
    "MAS": ["MAS"],
    "SDMU": ["SDMU"],
    "SAMA": ["SAMA"],
}


def nums_for(pref: str, html: str) -> list[int]:
    rx = re.compile(
        rf"(?<![A-Z0-9]){re.escape(pref)}-(\d{{2,5}})(?![A-Z0-9])",
        re.I,
    )
    return sorted({int(m.group(1)) for m in rx.finditer(html or "")})


def missav_max(query: str, pref: str) -> int:
    url = f"https://missav.ws/cn/search/{quote(query, safe='')}"
    try:
        html = o.fetch_page(url, timeout=16.0).html or ""
    except Exception:
        return 0
    return max(nums_for(pref, html) or [0])


def mgs_max(query: str, pref: str) -> int:
    url = f"https://www.mgstage.com/search/cSearch.php?search_word={quote(query)}"
    try:
        html = o.fetch_page(url, cookie="adc=1", timeout=18.0).html or ""
    except Exception:
        return 0
    rx = re.compile(rf"/product_detail/({re.escape(pref)}-(\d+))/", re.I)
    # also allow query pref variants
    rx2 = re.compile(r"/product_detail/([A-Z0-9]+)-(\d+)/", re.I)
    best = 0
    for m in rx.finditer(html):
        best = max(best, int(m.group(2)))
    if best:
        return best
    # if searching alias, take matching codes whose letter part equals pref or alias
    for m in rx2.finditer(html):
        p = m.group(1).upper()
        if p == pref.upper() or p in {a.upper() for a in ALIASES.get(pref, [])}:
            best = max(best, int(m.group(2)))
    return best


def dmm_any(http: httpx.Client, pref: str) -> tuple[int, str]:
    resolved = dmm.resolve_digit(http, pref)
    if not resolved:
        return 0, ""
    dig, _ = resolved
    for n in (1, 50, 100, 200, 500, 800, 999):
        if dmm.probe_serial(http, pref, n, dig):
            # rough latest via sample ladder
            best = n
            for m in (n + 50, n + 100, n + 200, 999, 1200):
                if m > 3000:
                    continue
                if dmm.probe_serial(http, pref, m, dig):
                    best = m
            return best, dig
    return 0, dig


def miss_list() -> list[tuple[str, str]]:
    doc = store.load_catalog(force=True)
    out: list[tuple[str, str]] = []
    for rid in ("japan_censored", "japan_amateur"):
        for p, e in sorted((doc["regions"][rid]["prefixes"] or {}).items()):
            if e.get("latest_code") or (e.get("serials") or []):
                continue
            out.append((rid, p))
    return out


def main() -> None:
    rows = miss_list()
    print(f"recheck {len(rows)} misses", flush=True)
    proxy = o.resolve_scrape_proxy_url() or None
    kw: dict = {"trust_env": False, "follow_redirects": True, "timeout": 8.0}
    if proxy:
        kw.update(proxy=proxy, verify=False)

    report = {"recovered": [], "noise": [], "empty": [], "alias_hit": []}
    doc = store.load_catalog(force=True)

    with httpx.Client(**kw) as http:
        for i, (rid, pref) in enumerate(rows, 1):
            print(f"[{i}/{len(rows)}] {rid} {pref}", flush=True)
            if pref in NOISE:
                report["noise"].append({"region": rid, "prefix": pref, "why": "noise_token"})
                print("  NOISE", flush=True)
                continue

            queries = ALIASES.get(pref, [pref])
            hit_code = ""
            via = ""
            serial = 0

            # 1) MissAV
            for q in queries:
                mx = missav_max(q, pref if q == pref else pref)
                # if alias different, also try nums for alias
                if mx <= 0 and q != pref:
                    mx2 = missav_max(q, q)
                    if mx2 > 0:
                        serial = mx2
                        hit_code = f"{std_prefix(q)}-{mx2}"
                        via = f"missav:{q}"
                        break
                if mx > 0:
                    serial = mx
                    hit_code = store.format_code(
                        {"prefix": pref, "pad": 3, "format": "{prefix}-{num}"}, mx
                    )
                    via = "missav"
                    break
                time.sleep(0.05)

            # 2) MGStage (amateur or short fails)
            if not hit_code:
                for q in queries:
                    mx = mgs_max(q, pref)
                    if mx <= 0 and q != pref:
                        mx = mgs_max(q, q)
                        if mx > 0:
                            serial = mx
                            hit_code = f"{std_prefix(q)}-{mx}"
                            via = f"mgstage:{q}"
                            break
                    if mx > 0:
                        serial = mx
                        hit_code = store.format_code(
                            {"prefix": pref, "pad": 3, "format": "{prefix}-{num}"}, mx
                        )
                        via = "mgstage"
                        break

            # 3) DMM for censored
            if not hit_code and rid == "japan_censored":
                mx, dig = dmm_any(http, pref)
                if mx > 0:
                    serial = mx
                    hit_code = store.format_code(
                        {"prefix": pref, "pad": 3, "format": "{prefix}-{num}"}, mx
                    )
                    via = f"dmm:{dig or 'plain'}"

            if hit_code:
                kind = "alias_hit" if ":" in via and via.split(":")[-1] != "plain" and via.split(":")[-1] != pref.lower() and not via.startswith("dmm") else "recovered"
                # simplify: if via contains alias query different from pref
                if any(via.endswith(f":{q}") for q in queries if q != pref):
                    kind = "alias_hit"
                else:
                    kind = "recovered"
                report[kind].append(
                    {
                        "region": rid,
                        "prefix": pref,
                        "latest": hit_code,
                        "serial": serial,
                        "via": via,
                    }
                )
                # write back
                ent = doc["regions"][rid]["prefixes"].get(pref) or {}
                # if alias produced different prefix code (RCTD), keep note
                use_pref = pref
                use_serial = serial
                if hit_code.split("-")[0].upper() != pref.upper():
                    # store under original key but note alias code
                    ent["notes"] = (
                        str(ent.get("notes") or "") + f" · 别名最新:{hit_code}"
                    ).strip(" ·")
                    # also try parse serial from hit_code for same letter? keep serial as alias serial in notes only
                    pe = store._normalize_prefix_entry(
                        pref,
                        {
                            **ent,
                            "serials": [serial] if hit_code.upper().startswith(pref.upper() + "-") else list(ent.get("serials") or []),
                            "latest_code": hit_code,
                            "status": "active",
                            "integrity": "latest_recheck",
                            "sources": sorted(
                                set(list(ent.get("sources") or []) + [via.split(":")[0]])
                            ),
                            "verified_at": store._now(),
                        },
                    )
                else:
                    pe = store._normalize_prefix_entry(
                        pref,
                        {
                            **ent,
                            "serials": [serial],
                            "latest_code": hit_code,
                            "status": "active",
                            "integrity": "latest_recheck",
                            "sources": sorted(
                                set(list(ent.get("sources") or []) + [via.split(":")[0]])
                            ),
                            "verified_at": store._now(),
                        },
                    )
                pe["latest_code"] = hit_code
                pe["serial_max_hint"] = serial
                doc["regions"][rid]["prefixes"][pref] = pe
                print(f"  OK {hit_code} via={via}", flush=True)
            else:
                report["empty"].append({"region": rid, "prefix": pref})
                print("  EMPTY", flush=True)

            if i % 10 == 0:
                store.save_catalog(doc)

    store.save_catalog(doc)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"\nrecovered={len(report['recovered'])} alias={len(report['alias_hit'])} "
        f"noise={len(report['noise'])} empty={len(report['empty'])}",
        flush=True,
    )
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
