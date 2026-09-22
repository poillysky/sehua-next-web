# -*- coding: utf-8 -*-
"""对仍无 latest_code 的前缀，扩大站点源再搜一遍并写回 catalog。"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.makers import settings as ms  # noqa: E402
from app.core import outbound_http as o  # noqa: E402
from app.prefix import catalog_store as store  # noqa: E402
from app.core.region_meta import std_prefix  # noqa: E402
from app.scrape.source_catalog import MIRROR_SEEDS  # noqa: E402

OUT = ROOT / "data" / "debug" / "prefix-empty-expand.json"

# 额外别名（相对原 miss 复核）
ALIASES: dict[str, list[str]] = {
    "SAMA": ["SAMA", "SAMPA", "SDDE"],
    "ARA": ["ARA", "261ARA"],
    "SIROHAME": ["SIROHAME", "SIRO", "200GANA"],
    "DV": ["DV", "DVDES", "DVAJ"],
    "MDS": ["MDS", "MDYD"],
    "AKNR": ["AKNR", "FSET"],
    "MOT": ["MOT", "MOTA"],
    "SMA": ["SMA", "SMAD"],
    "SPS": ["SPS", "SPSD"],
    "XV": ["XV", "XVSR"],
    "TG": ["TG", "TGGP"],
    "AB": ["AB", "ABP", "ABW"],
    "DA": ["DA", "DAC", "DACU"],
    "RFILE": ["RFILE", "REBD"],
    "IPBD": ["IPBD", "IPX", "IPZ"],
    "HRDV": ["HRDV", "HRD"],
    "NMH": ["NMH", "NMHY"],
    "NMS": ["NMS", "NMSR"],
}


def nums_for(pref: str, html: str) -> list[int]:
    rx = re.compile(
        rf"(?<![A-Z0-9]){re.escape(pref)}[-_](\d{{2,5}})(?![A-Z0-9])",
        re.I,
    )
    return sorted({int(m.group(1)) for m in rx.finditer(html or "")})


def best_code(pref: str, html: str, aliases: list[str]) -> tuple[str, int]:
    """返回 (code_prefix, max_serial)；优先原 pref，再别名。"""
    best_p, best_n = "", 0
    for p in [pref] + [a for a in aliases if a.upper() != pref.upper()]:
        nums = nums_for(p, html)
        if nums and nums[-1] > best_n:
            best_p, best_n = std_prefix(p), nums[-1]
    return best_p, best_n


def fetch(url: str, *, cookie: str | None = None, referer: str | None = None) -> str:
    # 批量扩大查找时一律不过盾，避免 Flare 500 拖死整批
    try:
        page = o.fetch_page(
            url,
            cookie=cookie,
            referer=referer,
            timeout=14.0,
            access="proxy_only",
        )
        return page.html or ""
    except Exception:
        return ""


def search_javbus(query: str, pref: str, aliases: list[str]) -> tuple[str, int, str]:
    cookie = ms.javbus_cookie() or None
    for base in list(ms.javbus_bases())[:3]:
        for page in (1, 2):
            path = f"/search/{quote(query)}" + (f"/{page}" if page > 1 else "")
            html = fetch(f"{base}{path}", cookie=cookie, referer=f"{base}/")
            p, n = best_code(pref, html, aliases)
            if n > 0:
                return p, n, f"javbus:{query}"
    return "", 0, ""


def search_javdb(query: str, pref: str, aliases: list[str]) -> tuple[str, int, str]:
    for base in MIRROR_SEEDS.get("javdb", [])[:3]:
        html = fetch(f"{base.rstrip('/')}/search?q={quote(query)}&f=all")
        p, n = best_code(pref, html, aliases)
        if n > 0:
            return p, n, f"javdb:{query}"
    return "", 0, ""


def search_javlibrary(query: str, pref: str, aliases: list[str]) -> tuple[str, int, str]:
    for base in MIRROR_SEEDS.get("javlibrary", [])[:4]:
        html = fetch(
            f"{base.rstrip('/')}/cn/vl_searchbyid.php?keyword={quote(query)}"
        )
        p, n = best_code(pref, html, aliases)
        if n > 0:
            return p, n, f"javlibrary:{query}"
    return "", 0, ""


def search_123av(query: str, pref: str, aliases: list[str]) -> tuple[str, int, str]:
    for base in MIRROR_SEEDS.get("njav", [])[:3]:
        root = base.rstrip("/")
        html = fetch(f"{root}/search?keyword={quote(query)}")
        p, n = best_code(pref, html, aliases)
        if n > 0:
            return p, n, f"123av:{query}"
    return "", 0, ""


def search_avsox(query: str, pref: str, aliases: list[str]) -> tuple[str, int, str]:
    for base in MIRROR_SEEDS.get("avsox", [])[:2]:
        html = fetch(f"{base.rstrip('/')}/cn/search/{quote(query)}")
        p, n = best_code(pref, html, aliases)
        if n > 0:
            return p, n, f"avsox:{query}"
    return "", 0, ""


def search_missav(query: str, pref: str, aliases: list[str]) -> tuple[str, int, str]:
    seeds = MIRROR_SEEDS.get("miss_av", [])[:4]
    for base in seeds:
        root = base.rstrip("/")
        for page in (1, 2, 3):
            url = (
                f"{root}/cn/search/{quote(query)}"
                if page == 1
                else f"{root}/cn/search/{quote(query)}?page={page}"
            )
            html = fetch(url)
            p, n = best_code(pref, html, aliases)
            if n > 0:
                return p, n, f"missav:{query}"
    return "", 0, ""


def search_mgs(query: str, pref: str, aliases: list[str]) -> tuple[str, int, str]:
    html = fetch(
        f"https://www.mgstage.com/search/cSearch.php?search_word={quote(query)}",
        cookie="adc=1",
    )
    # product_detail links
    rx = re.compile(r"/product_detail/([A-Z0-9]+)-(\d+)/", re.I)
    allow = {std_prefix(x) for x in [pref] + aliases}
    best_p, best_n = "", 0
    for m in rx.finditer(html or ""):
        p = std_prefix(m.group(1))
        n = int(m.group(2))
        if p in allow and n > best_n:
            best_p, best_n = p, n
    if best_n:
        return best_p, best_n, f"mgstage:{query}"
    p, n = best_code(pref, html, aliases)
    if n:
        return p, n, f"mgstage:{query}"
    return "", 0, ""


SOURCES = [
    ("javbus", search_javbus),
    ("javdb", search_javdb),
    ("missav", search_missav),
    ("javlibrary", search_javlibrary),
    ("123av", search_123av),
    ("avsox", search_avsox),
    ("mgstage", search_mgs),
]


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
    print(f"expand {len(rows)} empties", flush=True)
    doc = store.load_catalog(force=True)
    report: dict = {"recovered": [], "empty": [], "tried": len(rows)}

    for i, (rid, pref) in enumerate(rows, 1):
        aliases = ALIASES.get(pref, [pref])
        queries = list(dict.fromkeys(aliases))
        print(f"[{i}/{len(rows)}] {rid} {pref}", flush=True)
        hit_p, hit_n, via = "", 0, ""

        for q in queries:
            for name, fn in SOURCES:
                try:
                    p, n, v = fn(q, pref, aliases)
                except Exception as e:  # noqa: BLE001
                    print(f"  {name} ERR {e}", flush=True)
                    continue
                if n > hit_n:
                    hit_p, hit_n, via = p, n, v
                    # 够用就停：同 query 下后面站点可跳；别名继续只在未命中时
                    break
            if hit_n > 0:
                break
            time.sleep(0.05)

        if hit_n > 0:
            code = f"{hit_p}-{hit_n}"
            # pad
            if hit_n < 1000:
                code = f"{hit_p}-{str(hit_n).zfill(3)}"
            ent = doc["regions"][rid]["prefixes"].get(pref) or {}
            notes = str(ent.get("notes") or "")
            if hit_p.upper() != pref.upper():
                tag = f"别名最新:{code}"
                if tag not in notes:
                    notes = (notes + " · " + tag).strip(" ·")
            pe = store._normalize_prefix_entry(
                pref,
                {
                    **ent,
                    "serials": [hit_n] if hit_p.upper() == pref.upper() else list(ent.get("serials") or []),
                    "latest_code": code,
                    "status": "active",
                    "integrity": "latest_expand",
                    "notes": notes,
                    "sources": sorted(
                        set(list(ent.get("sources") or []) + [via.split(":")[0]])
                    ),
                    "verified_at": store._now(),
                },
            )
            pe["latest_code"] = code
            pe["serial_max_hint"] = hit_n
            doc["regions"][rid]["prefixes"][pref] = pe
            report["recovered"].append(
                {"region": rid, "prefix": pref, "latest": code, "via": via}
            )
            print(f"  OK {code} via={via}", flush=True)
        else:
            report["empty"].append({"region": rid, "prefix": pref})
            print("  EMPTY", flush=True)

        if i % 5 == 0:
            store.save_catalog(doc)

    store.save_catalog(doc)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"\nrecovered={len(report['recovered'])} empty={len(report['empty'])}",
        flush=True,
    )
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
