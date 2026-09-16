# -*- coding: utf-8 -*-
"""确认 japan_uncensored 各前缀最新番号（MissAV + JavBus）。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import makers_settings as ms  # noqa: E402
from app import outbound_http as o  # noqa: E402
from app import prefix_catalog_store as store  # noqa: E402

OUT = ROOT / "data" / "debug" / "prefix-uncensored-latest.json"

# 前缀 → 搜索词 + 从 HTML 抽 latest 的规则
# kind: serial = PREFIX-N 取最大；date6 = MMDDYY 日期号取最新
RULES: dict[str, dict] = {
    "HEYZO": {
        "queries": ["HEYZO"],
        "kind": "serial",
        "rx": [r"(?i)(?<![A-Z0-9])HEYZO-(\d{3,5})(?![A-Z0-9])"],
        "fmt": lambda n: f"HEYZO-{n}",
    },
    "1PON": {
        "queries": ["1pondo", "pondo"],
        "kind": "date_slug",
        "rx": [
            r"(?i)(?:1pondo|pondo)[-_](\d{6})[_-](\d{2,3})",
            r"(?i)(?<![A-Z0-9])(\d{6})[_-](\d{2,3})(?![A-Z0-9])",
        ],
        "fmt": lambda a, b: f"1PONDO-{a}_{b}",
    },
    "CARIB": {
        "queries": ["caribbeancom", "caribbean"],
        "kind": "date_slug",
        "rx": [
            r"(?i)caribbeancom[-_](\d{6})[-_](\d{2,3})",
            r"(?i)(?<![A-Z0-9])(\d{6})-(\d{3})(?![A-Z0-9])",
        ],
        "fmt": lambda a, b: f"CARIB-{a}-{b}",
    },
    "CARIBPR": {
        "queries": ["caribbeancompr", "caribpr", "caribbeancom premium"],
        "kind": "date_slug",
        "rx": [
            r"(?i)caribbeancompr?[-_](\d{6})[-_](\d{2,3})",
            r"(?i)(?:caribpr|caribbeancompr)[-_](\d{6})[-_](\d{2,3})",
        ],
        "fmt": lambda a, b: f"CARIBPR-{a}-{b}",
    },
    "10MU": {
        "queries": ["10musume", "musume"],
        "kind": "date_slug",
        "rx": [
            r"(?i)(?:10musume|musume)[-_](\d{6})[_-](\d{1,3})",
        ],
        "fmt": lambda a, b: f"10MU-{a}_{b}",
    },
    "10MUSUME": {
        "queries": ["10musume"],
        "kind": "date_slug",
        "rx": [r"(?i)(?:10musume|musume)[-_](\d{6})[_-](\d{1,3})"],
        "fmt": lambda a, b: f"10MUSUME-{a}_{b}",
    },
    "PACO": {
        "queries": ["pacopacomama", "paco"],
        "kind": "date_slug",
        "rx": [r"(?i)pacopacomama[-_](\d{6})[_-](\d{2,3})"],
        "fmt": lambda a, b: f"PACO-{a}_{b}",
    },
    "PACOMA": {
        "queries": ["pacopacomama"],
        "kind": "date_slug",
        "rx": [r"(?i)pacopacomama[-_](\d{6})[_-](\d{2,3})"],
        "fmt": lambda a, b: f"PACOMA-{a}_{b}",
    },
    "H0930": {
        "queries": ["h0930", "naughty0930", "0930"],
        "kind": "date_slug",
        "rx": [
            r"(?i)(?:h0930|naughty0930|0930)[-_](\d{6})[_-]([A-Z0-9]+)",
            r"(?i)(?:h0930|naughty0930)[-_](\d{6})",
        ],
        "fmt": lambda *g: f"H0930-{'-'.join(g)}",
    },
    "H4610": {
        "queries": ["h4610", "naughty4610", "4610"],
        "kind": "date_slug",
        "rx": [
            r"(?i)(?:h4610|naughty4610|4610)[-_](\d{6})[_-]([A-Z0-9]+)",
            r"(?i)(?:h4610|naughty4610)[-_](\d{6})",
        ],
        "fmt": lambda *g: f"H4610-{'-'.join(g)}",
    },
    "C0930": {
        "queries": ["c0930"],
        "kind": "date_slug",
        "rx": [r"(?i)c0930[-_](\d{6})(?:[_-]([A-Z0-9]+))?"],
        "fmt": lambda a, b="": f"C0930-{a}" + (f"-{b}" if b else ""),
    },
    "KIN8": {
        "queries": ["kin8tengoku", "kin8"],
        "kind": "serial",
        "rx": [r"(?i)(?<![A-Z0-9])(?:KIN8|KIN8TENGOKU)[-_]?(\d{3,5})(?![A-Z0-9])"],
        "fmt": lambda n: f"KIN8-{n}",
    },
    "HEYDOUGA": {
        "queries": ["heydouga"],
        "kind": "serial",
        "rx": [r"(?i)heydouga[-_](\d+)[-_](\d+)", r"(?i)HEYDOUGA[-_](\d+)"],
        "fmt": lambda *g: "HEYDOUGA-" + "-".join(str(x) for x in g),
    },
    "HEYPPV": {
        "queries": ["heyppv", "heyzo ppv"],
        "kind": "serial",
        "rx": [r"(?i)HEYPPV[-_](\d+)", r"(?i)heyzo[-_]ppv[-_](\d+)"],
        "fmt": lambda n: f"HEYPPV-{n}",
    },
    "XXXAV": {
        "queries": ["xxx-av", "xxxav"],
        "kind": "serial",
        "rx": [r"(?i)(?:xxx-?av|XXXAV)[-_](\d+)"],
        "fmt": lambda n: f"XXXAV-{n}",
    },
    "NYOSHIN": {
        "queries": ["nyoshin", "nymphomaniac"],
        "kind": "serial",
        "rx": [r"(?i)(?:nyoshin|n[_\-]?(\d+))", r"(?i)nyoshin[-_](\d+)"],
        "fmt": lambda n: f"NYOSHIN-{n}",
    },
    "RHJ": {
        "queries": ["rhj", "redhotjam"],
        "kind": "serial",
        "rx": [r"(?i)(?<![A-Z0-9])RHJ[-_]?(\d{2,4})(?![A-Z0-9])"],
        "fmt": lambda n: f"RHJ-{n}",
    },
    "SPERMMANIA": {
        "queries": ["spermmania"],
        "kind": "serial",
        "rx": [r"(?i)spermmania[-_](\d+)"],
        "fmt": lambda n: f"SPERMMANIA-{n}",
    },
    "LEGSJAPAN": {
        "queries": ["legsjapan"],
        "kind": "serial",
        "rx": [r"(?i)legsjapan[-_](\d+)"],
        "fmt": lambda n: f"LEGSJAPAN-{n}",
    },
    "FELLATIOJAPAN": {
        "queries": ["fellatiojapan"],
        "kind": "serial",
        "rx": [r"(?i)fellatiojapan[-_](\d+)"],
        "fmt": lambda n: f"FELLATIOJAPAN-{n}",
    },
    "HANDJOBJAPAN": {
        "queries": ["handjobjapan"],
        "kind": "serial",
        "rx": [r"(?i)handjobjapan[-_](\d+)"],
        "fmt": lambda n: f"HANDJOBJAPAN-{n}",
    },
    "URALESBIAN": {
        "queries": ["uralesbian"],
        "kind": "serial",
        "rx": [r"(?i)uralesbian[-_](\d+)"],
        "fmt": lambda n: f"URALESBIAN-{n}",
    },
    "URABUKKAKE": {
        "queries": ["urabukkake"],
        "kind": "serial",
        "rx": [r"(?i)urabukkake[-_](\d+)"],
        "fmt": lambda n: f"URABUKKAKE-{n}",
    },
    "COSPURI": {
        "queries": ["cospuri"],
        "kind": "serial",
        "rx": [r"(?i)cospuri[-_](\d+)"],
        "fmt": lambda n: f"COSPURI-{n}",
    },
    "SMMIRACLE": {
        "queries": ["sm-miracle", "smmiracle"],
        "kind": "serial",
        "rx": [r"(?i)(?:sm-?miracle|smmiracle)[-_]([a-z0-9]+)"],
        "fmt": lambda n: f"SMMIRACLE-{n}",
    },
    "ROSELIP": {
        "queries": ["roselip", "roselip-fetish"],
        "kind": "serial",
        "rx": [r"(?i)roselip[-_](\d+)"],
        "fmt": lambda n: f"ROSELIP-{n}",
    },
    "ROSELIPFETISH": {
        "queries": ["roselip-fetish", "roselip"],
        "kind": "serial",
        "rx": [r"(?i)roselip[-_](\d+)"],
        "fmt": lambda n: f"ROSELIP-{n}",
    },
    "JAPORNXXX": {
        "queries": ["japornxxx"],
        "kind": "serial",
        "rx": [r"(?i)japornxxx[-_](\d+)"],
        "fmt": lambda n: f"JAPORNXXX-{n}",
    },
}

# muramura 等数字+ZM：按 MissAV 搜完整前缀取最大流水
ZM_RE = re.compile(r"^(?P<pre>\d{2,3}ZM)$", re.I)

NOISE = {"PT", "TOKYO", "GACHI", "JAPORNXXX"}


def fetch(url: str, *, cookie: str | None = None, referer: str | None = None) -> str:
    try:
        page = o.fetch_page(
            url,
            cookie=cookie,
            referer=referer,
            timeout=16.0,
            access="proxy_only",
        )
        return page.html or ""
    except Exception:
        return ""


def date6_key(mmddyy: str) -> int:
    """MMDDYY → sortable YYYYMMDD-ish int (assume 20YY)."""
    if len(mmddyy) != 6 or not mmddyy.isdigit():
        return 0
    mm, dd, yy = mmddyy[:2], mmddyy[2:4], mmddyy[4:6]
    return int(f"20{yy}{mm}{dd}")


def pick_from_html(rule: dict, html: str) -> tuple[str, int]:
    kind = rule["kind"]
    best_code = ""
    best_score = -1
    for rx in rule["rx"]:
        for m in re.finditer(rx, html or ""):
            groups = [g for g in m.groups() if g is not None]
            if not groups:
                continue
            if kind == "serial":
                # first group numeric preferred
                nums = [int(g) for g in groups if str(g).isdigit()]
                if not nums:
                    # non-numeric token (sm-miracle)
                    token = groups[0]
                    score = len(str(token))
                    code = rule["fmt"](token)
                else:
                    score = max(nums)
                    if len(nums) == 1:
                        code = rule["fmt"](nums[0])
                    else:
                        code = rule["fmt"](*nums)
            else:  # date_slug
                d = groups[0]
                score = date6_key(d) * 1000 + (int(groups[1]) if len(groups) > 1 and str(groups[1]).isdigit() else 0)
                try:
                    code = rule["fmt"](*groups)
                except TypeError:
                    code = rule["fmt"](groups[0], groups[1] if len(groups) > 1 else "")
            if score > best_score:
                best_score = score
                best_code = code
    return best_code, best_score


def search_missav(query: str) -> str:
    html = ""
    for page in (1, 2):
        url = (
            f"https://missav.ws/cn/search/{quote(query)}"
            if page == 1
            else f"https://missav.ws/cn/search/{quote(query)}?page={page}"
        )
        html += "\n" + fetch(url)
    return html


def search_javbus(query: str) -> str:
    cookie = ms.javbus_cookie() or None
    bases = list(ms.javbus_bases())[:2] or ["https://www.javbus.com"]
    html = ""
    for base in bases:
        b = base.rstrip("/")
        for path in (f"/uncensored/search/{quote(query)}", f"/search/{quote(query)}"):
            chunk = fetch(f"{b}{path}", cookie=cookie, referer=f"{b}/")
            if chunk:
                html += "\n" + chunk
                break
        if html:
            break
    return html


def harvest_one(pref: str) -> tuple[str, str]:
    """return (latest_code, via)"""
    if pref in NOISE:
        return "", "noise"

    zm = ZM_RE.match(pref)
    if zm:
        html = search_missav(pref) + "\n" + search_javbus(pref)
        rx = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(pref)}-(\d{{2,5}})(?![A-Z0-9])")
        nums = [int(m.group(1)) for m in rx.finditer(html)]
        if nums:
            n = max(nums)
            return f"{pref.upper()}-{n}", "missav/javbus"
        return "", "empty"

    rule = RULES.get(pref)
    if not rule:
        # generic PREFIX-N
        html = search_missav(pref) + "\n" + search_javbus(pref)
        rx = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(pref)}-(\d{{2,5}})(?![A-Z0-9])")
        nums = [int(m.group(1)) for m in rx.finditer(html)]
        if nums:
            return f"{pref}-{max(nums)}", "generic"
        return "", "empty"

    best_code, best_score, via = "", -1, ""
    for q in rule["queries"]:
        for name, fn in (("missav", search_missav), ("javbus", search_javbus)):
            html = fn(q)
            code, score = pick_from_html(rule, html)
            if score > best_score:
                best_code, best_score, via = code, score, f"{name}:{q}"
        if best_score > 0:
            break
    return best_code, via


def main() -> None:
    doc = store.load_catalog(force=True)
    prefs = doc["regions"]["japan_uncensored"]["prefixes"]
    keys = sorted(prefs.keys())
    report: dict = {"ok": [], "empty": [], "noise": []}
    print(f"uncensored harvest {len(keys)}", flush=True)

    for i, pref in enumerate(keys, 1):
        print(f"[{i}/{len(keys)}] {pref}", flush=True)
        code, via = harvest_one(pref)
        ent = prefs.get(pref) or {}
        if via == "noise" or pref in NOISE:
            report["noise"].append(pref)
            print("  NOISE → delete", flush=True)
            del prefs[pref]
            continue
        if not code:
            report["empty"].append(pref)
            print("  EMPTY", flush=True)
            continue
        # serial hint if trailing digits
        m = re.search(r"(\d+)(?:\D*)$", code.replace("_", "-"))
        serial = int(m.group(1)) if m else 0
        pe = store._normalize_prefix_entry(
            pref,
            {
                **ent,
                "serials": [serial] if serial and code.upper().startswith(pref.upper()) else [],
                "latest_code": code,
                "status": "active",
                "integrity": "latest_uncensored",
                "sources": sorted(set(list(ent.get("sources") or []) + [via.split(":")[0]])),
                "verified_at": store._now(),
            },
        )
        pe["latest_code"] = code
        if serial:
            pe["serial_max_hint"] = serial
        prefs[pref] = pe
        report["ok"].append({"prefix": pref, "latest": code, "via": via})
        print(f"  OK {code} via={via}", flush=True)
        if i % 5 == 0:
            store.save_catalog(doc)

    store.save_catalog(doc)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"\nok={len(report['ok'])} empty={len(report['empty'])} noise_removed={len(report['noise'])}",
        flush=True,
    )
    print("wrote", OUT, flush=True)
    s = store.public_summary(doc)
    u = next(r for r in s["regions"] if r["id"] == "japan_uncensored")
    print(f"日本无码: {u['prefix_count']} 前缀 · {u['code_count']} 番号", flush=True)


if __name__ == "__main__":
    main()
