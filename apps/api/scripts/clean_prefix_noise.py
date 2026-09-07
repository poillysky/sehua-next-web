# -*- coding: utf-8 -*-
"""Clean polluted prefixes from missav HTML noise; keep makers + force + sane codes."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import prefix_catalog_store as store  # noqa: E402
from app.region_meta import REGION_META, REGION_ORDER, std_prefix  # noqa: E402

SEED = ROOT / "apps" / "web" / "src" / "config" / "prefix-catalog.seed.json"

NOISE = {
    "HTTP",
    "HTTPS",
    "HTML",
    "JSON",
    "PAGE",
    "HOME",
    "NULL",
    "TRUE",
    "FALSE",
    "JPEG",
    "WEBP",
    "PNG",
    "JPG",
    "CSS",
    "WWW",
    "COM",
    "NET",
    "ORG",
    "CDN",
    "IMG",
    "PIC",
    "URL",
    "API",
    "GET",
    "POST",
    "AND",
    "THE",
    "FOR",
    "FROM",
    "WITH",
    "THIS",
    "THAT",
    "DATE",
    "TIME",
    "YEAR",
    "MONTH",
    "WEEK",
    "DAY",
    "DURATION",
    "EMERALD",
    "CLOT",
    "BASE",
    "BLUE",
    "SEARCH",
    "LOGIN",
    "SIGN",
    "USER",
    "PASS",
    "TOKEN",
    "VIDEO",
    "IMAGE",
    "TITLE",
    "CLASS",
    "STYLE",
    "SCRIPT",
    "DOCTYPE",
    "CONTENT",
    "LENGTH",
    "WIDTH",
    "HEIGHT",
    "COLOR",
    "BLACK",
    "WHITE",
    "GREEN",
    "RIGHT",
    "LEFT",
    "END",
    "NEXT",
    "PREV",
    "MORE",
    "LESS",
    "TYPE",
    "NAME",
    "TEXT",
    "DATA",
    "ITEM",
    "LIST",
    "MENU",
    "NAV",
    "MAIN",
    "FOOT",
    "HEAD",
    "BODY",
    "FORM",
    "INPUT",
    "BUTTON",
    "LINK",
    "HREF",
    "SRC",
    "ALT",
    "DIV",
    "SPAN",
    "SECTION",
    "ARTICLE",
    "HEADER",
    "FOOTER",
    "CONTAINER",
    "WRAPPER",
    "MODULE",
    "COMPONENT",
    "FUNCTION",
    "RETURN",
    "CONST",
    "VAR",
    "LET",
    "EXPORT",
    "IMPORT",
    "DEFAULT",
    "WINDOW",
    "DOCUMENT",
    "OBJECT",
    "ARRAY",
    "STRING",
    "NUMBER",
    "BOOLEAN",
    "UNDEFINED",
    "INFINITY",
    "NAN",
    "ERROR",
    "SUCCESS",
    "FAILED",
    "STATUS",
    "INDEX",
    "COUNT",
    "TOTAL",
    "SIZE",
    "LIMIT",
    "OFFSET",
    "ORDER",
    "SORT",
    "FILTER",
    "QUERY",
    "PARAM",
    "VALUE",
    "KEY",
    "UUID",
    "HASH",
    "SALT",
    "COOKIE",
    "SESSION",
    "CACHE",
    "PROXY",
    "AGENT",
    "BROWSER",
    "CHROME",
    "FIREFOX",
    "SAFARI",
    "EDGE",
    "MOBILE",
    "DESKTOP",
    "TABLET",
    "ANDROID",
    "IPHONE",
    "IPAD",
    "MACOS",
    "LINUX",
    "WINDOWS",
    "UBUNTU",
    "DEBIAN",
    "CENTOS",
    "DOCKER",
    "KUBERNETES",
    "AWS",
    "GCP",
    "AZURE",
    "CLOUD",
    "SERVER",
    "CLIENT",
    "HOST",
    "PORT",
    "PATH",
    "ROUTE",
    "ROUTER",
    "SWITCH",
    "GATEWAY",
    "DNS",
    "TCP",
    "UDP",
    "IPV",
    "SSID",
    "WIFI",
    "LAN",
    "WAN",
    "VPN",
    "SSH",
    "FTP",
    "SFTP",
    "SMTP",
    "IMAP",
    "POP",
    "HTTP2",
    "HTTP3",
    "TLS",
    "SSL",
    "CERT",
    "PEM",
    "CRT",
    "KEYFILE",
}


def clean(p: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", std_prefix(p).replace("-", ""))


def maker_prefixes(path: Path, kinds: set[str]) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for m in data:
        if m.get("kind") not in kinds:
            continue
        for p in m.get("prefixes") or []:
            c = clean(str(p))
            if c:
                out.add(c)
    return out


def is_noise(p: str) -> bool:
    if p in NOISE:
        return True
    if len(p) < 2 or len(p) > 12:
        return True
    if p.isdigit():
        return True
    # hex-ish garbage
    if re.fullmatch(r"[0-9A-F]{6,}", p) and re.search(r"\d", p) and re.search(r"[A-F]", p):
        if not re.search(r"[G-Z]", p):
            return True
    # too many digits leading weird
    if re.fullmatch(r"\d+[A-Z]{1,2}", p) and len(p) <= 4:
        return True
    return False


def china_keep(p: str, allow: set[str]) -> bool:
    if p in allow:
        return True
    if is_noise(p):
        return False
    # common cn studio shells
    if p.startswith(("MD", "91", "TM", "MK", "MS", "XK", "JD", "PM", "NH", "ID", "RAS", "TZ", "DA", "HK", "CM", "YCM")):
        return True
    if p in {"JVID", "MAD", "MSD", "FSOG", "QQOG", "XSJKY"}:
        return True
    return False


def western_keep(p: str, allow: set[str]) -> bool:
    if p in allow:
        return True
    if is_noise(p):
        return False
    # western studio names are usually longer letter-only
    if p.isalpha() and 4 <= len(p) <= 16:
        return True
    return False


def main() -> None:
    japan = ROOT / "apps/web/src/config/av-makers.japan.json"
    china_f = ROOT / "apps/web/src/config/av-makers.china.json"
    west_f = ROOT / "apps/web/src/config/av-makers.western.json"

    allow_china = maker_prefixes(china_f, {"国产"})
    allow_west = maker_prefixes(west_f, {"欧美"})
    allow_amateur = maker_prefixes(japan, {"素人"})
    allow_unc = maker_prefixes(japan, {"无码"})
    allow_grav = maker_prefixes(japan, {"写真"})

    # curated extras already in catalog notes — keep known shells
    allow_china |= {"MD", "MDX", "MDSR", "MKY", "MSD", "MAD", "91CM", "JVID", "TMW", "TM", "DA"}
    allow_west |= {
        "BRAZZERS",
        "BLACKED",
        "BLACKEDRAW",
        "TUSHY",
        "VIXEN",
        "DEEPER",
        "BANGBROS",
        "BANGBUS",
        "NAUGHTYAMERICA",
        "REALITYKINGS",
        "MOFOS",
        "FAKETAXI",
        "EVILANGEL",
        "LEGALPORNO",
        "ONLYFANS",
        "SLAYED",
        "TUSHYRAW",
        "RK",
        "RKPRIME",
    }

    doc = store.load_catalog(force=True)
    removed: dict[str, list[str]] = {}

    def purge(rid: str, keep_fn) -> None:
        bucket = doc["regions"][rid]["prefixes"]
        drop = []
        for k in list(bucket.keys()):
            if not keep_fn(k):
                drop.append(k)
                del bucket[k]
        removed[rid] = drop

    purge("china", lambda p: china_keep(p, allow_china))
    purge("western", lambda p: western_keep(p, allow_west))
    purge(
        "japan_amateur",
        lambda p: (p in allow_amateur or (not is_noise(p) and not p.isalpha() or p in allow_amateur or re.match(r"^\d{0,3}[A-Z]{2,8}$", p)))
        and not is_noise(p),
    )
    # tighten amateur: keep allow + digit-letter MGS style, drop pure English noise
    bucket = doc["regions"]["japan_amateur"]["prefixes"]
    drop = []
    for k in list(bucket.keys()):
        if is_noise(k):
            drop.append(k)
            del bucket[k]
            continue
        if k in allow_amateur:
            continue
        # MGS codes often like SIRO / 200GANA / 259LUXU
        if re.fullmatch(r"\d{0,3}[A-Z]{2,10}", k):
            continue
        # drop long English-only not in allow
        if k.isalpha() and k not in allow_amateur and len(k) >= 6:
            drop.append(k)
            del bucket[k]
    removed["japan_amateur"] = removed.get("japan_amateur", []) + drop

    purge(
        "japan_uncensored",
        lambda p: p in allow_unc
        or p
        in {
            "CARIB",
            "CARIBPR",
            "1PON",
            "HEYZO",
            "PACO",
            "10MU",
            "H4610",
            "C0930",
            "H0930",
            "KIN8",
            "NYOSHIN",
            "TOKYO",
            "GACHI",
            "MESUBUTA",
            "PT",
        }
        or (not is_noise(p) and re.fullmatch(r"[A-Z0-9]{2,12}", p) and not p.isalpha() or p in allow_unc),
    )
    # uncensored: drop pure long English except known
    bucket = doc["regions"]["japan_uncensored"]["prefixes"]
    known_u = allow_unc | {
        "CARIB",
        "CARIBPR",
        "1PON",
        "HEYZO",
        "PACO",
        "10MU",
        "H4610",
        "C0930",
        "H0930",
        "KIN8",
        "NYOSHIN",
        "TOKYO",
        "GACHI",
        "MESUBUTA",
        "PT",
        "HEYDOUGA",
        "AVOP",
    }
    drop = []
    for k in list(bucket.keys()):
        if is_noise(k) or (k.isalpha() and len(k) >= 5 and k not in known_u):
            # keep short studio codes like CARIB
            if k in known_u:
                continue
            drop.append(k)
            del bucket[k]
    removed["japan_uncensored"] = removed.get("japan_uncensored", []) + drop

    # gravure: only allow list
    purge("japan_gravure", lambda p: p in allow_grav or p in {
        "ENFD", "OAE", "REBD", "REBDB", "MBRAA", "MBRBA", "MBDD", "SYD", "GGSID", "BFAZ"
    })

    # fc2 fixed
    doc["regions"]["fc2"]["prefixes"] = {
        "FC2": store._normalize_prefix_entry(
            "FC2",
            {"maker": "FC2", "pad": 0, "format": "FC2-{num}", "sources": ["fc2", "authority"], "serials": []},
        ),
        "FC2PPV": store._normalize_prefix_entry(
            "FC2PPV",
            {
                "maker": "FC2 PPV",
                "pad": 0,
                "format": "FC2-PPV-{num}",
                "sources": ["fc2", "authority"],
                "serials": [],
            },
        ),
    }

    # censored: only remove noise words, keep the rest
    bucket = doc["regions"]["japan_censored"]["prefixes"]
    drop = []
    for k in list(bucket.keys()):
        if is_noise(k):
            drop.append(k)
            del bucket[k]
    removed["japan_censored"] = drop

    store.save_catalog(doc)

    # rewrite seed without serials
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    for rid in REGION_ORDER:
        prefs = (doc["regions"].get(rid) or {}).get("prefixes") or {}
        out = {}
        for key, ent in sorted(prefs.items()):
            row = {
                "maker": ent.get("maker") or "",
                "pad": int(ent.get("pad") or 0),
                "format": ent.get("format") or "{prefix}-{num}",
                "sources": list(ent.get("sources") or ["site"]),
                "serials": [],
            }
            if ent.get("dmm_digit") not in (None,):
                row["dmm_digit"] = ent.get("dmm_digit")
            if ent.get("notes"):
                row["notes"] = ent["notes"]
            out[key] = row
        seed["regions"][rid] = {
            "id": rid,
            "label": REGION_META[rid]["label"],
            "prefixes": out,
        }
    SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = store.public_summary()
    print("removed counts:", {k: len(v) for k, v in removed.items()})
    for r in summary.get("regions") or []:
        print(f"{r['id']:18} prefixes={r.get('prefix_count')}")
    print("TOTAL", summary.get("prefix_total"))


if __name__ == "__main__":
    main()
