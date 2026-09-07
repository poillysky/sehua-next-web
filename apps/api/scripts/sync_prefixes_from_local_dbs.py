# -*- coding: utf-8 -*-
"""从两个本地资源库扫前缀：色花 resource_db + Bitmagnet，并入七区 catalog。"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import bitmagnet_pg  # noqa: E402
from app import pg  # noqa: E402
from app import prefix_catalog_store as store  # noqa: E402
from app import prefix_ranges as pr  # noqa: E402
from app.region_meta import REGION_META, REGION_ORDER, std_prefix  # noqa: E402

SEED = ROOT / "apps" / "web" / "src" / "config" / "prefix-catalog.seed.json"
REPORT = ROOT / "data" / "_debug" / "prefix-from-local-dbs.json"

CODE_RE = re.compile(
    r"(?<![A-Z0-9])([0-9]{0,3}[A-Z]{2,12})[-_ ](\d{2,6})(?![A-Z0-9])",
    re.I,
)

NOISE = set(pr.NOISE) | {
    "HTTP",
    "HTTPS",
    "HTML",
    "JSON",
    "PAGE",
    "HOME",
    "NULL",
    "TRUE",
    "FALSE",
    "DURATION",
    "SEARCH",
    "LOGIN",
    "VIDEO",
    "IMAGE",
    "TITLE",
    "CLASS",
    "STYLE",
    "SCRIPT",
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
    "SPAN",
    "SECTION",
    "ARTICLE",
    "HEADER",
    "FOOTER",
    "WINDOW",
    "DOCUMENT",
    "OBJECT",
    "ARRAY",
    "STRING",
    "NUMBER",
    "BOOLEAN",
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
    "COOKIE",
    "SESSION",
    "CACHE",
    "PROXY",
    "CHROME",
    "FIREFOX",
    "SAFARI",
    "EDGE",
    "MOBILE",
    "DESKTOP",
    "ANDROID",
    "IPHONE",
    "LINUX",
    "WINDOWS",
    "SERVER",
    "CLIENT",
    "HOST",
    "PORT",
    "PATH",
    "ROUTE",
    "X264",
    "X265",
    "HEVC",
    "AVC",
    "AAC",
    "AC3",
    "DTS",
    "REMUX",
    "WEBDL",
    "WEBRIP",
    "BLURAY",
    "HDTV",
    "SDTV",
    "COMPLETE",
    "SAMPLE",
    "TRAILER",
    "COVER",
    "POSTER",
    "SCREEN",
    "THUMB",
}


def clean(p: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", std_prefix(p).replace("-", ""))


def is_noise(p: str) -> bool:
    if not p or p in NOISE or p in pr.NOISE:
        return True
    if len(p) < 2 or len(p) > 14:
        return True
    if p.isdigit():
        return True
    if re.fullmatch(r"[0-9A-F]{8,}", p) and not re.search(r"[G-Z]", p):
        return True
    return False


def extract_from_text(text: str, counter: Counter) -> None:
    for m in CODE_RE.finditer(text or ""):
        p = clean(m.group(1))
        if is_noise(p):
            continue
        counter[p] += 1


def scan_sehua() -> Counter:
    c: Counter = Counter()
    print("scanning sehua resource_db …", flush=True)
    rows = pg.query(
        """
        SELECT COALESCE(r.filename,'') AS filename,
               COALESCE(rs.title,'') AS title
        FROM ed2k_resources r
        LEFT JOIN LATERAL (
          SELECT title FROM resource_sources
          WHERE hash = r.hash ORDER BY created_at DESC LIMIT 1
        ) rs ON TRUE
        """
    )
    print(f"  sehua rows={len(rows)}", flush=True)
    for row in rows:
        extract_from_text(f"{row.get('filename')}\n{row.get('title')}".upper(), c)
    print(f"  sehua prefixes={len(c)}", flush=True)
    return c


def scan_bitmagnet() -> Counter:
    c: Counter = Counter()
    print("scanning bitmagnet …", flush=True)
    # discover text columns
    cols = bitmagnet_pg.query(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema='public'
          AND data_type IN ('text','character varying','character')
        ORDER BY table_name, ordinal_position
        """
    )
    # prefer torrent content name tables
    interesting = []
    for row in cols:
        t = str(row["table_name"])
        col = str(row["column_name"])
        key = f"{t}.{col}".lower()
        if any(
            x in key
            for x in (
                "torrent_content.name",
                "torrent_contents.name",
                "content.title",
                "content.original_title",
                "torrents.name",
            )
        ):
            interesting.append((t, col))
        # skip torrent_files.path — tens of millions of rows, low signal
    if not interesting:
        # fallback common bitmagnet schema (avoid torrent_files)
        interesting = [
            ("content", "title"),
            ("content", "original_title"),
            ("torrents", "name"),
        ]
    print(f"  bitmagnet text targets={interesting[:12]}", flush=True)

    for table, col in interesting[:5]:
        try:
            if not re.fullmatch(r"[A-Za-z0-9_]+", table) or not re.fullmatch(
                r"[A-Za-z0-9_]+", col
            ):
                continue
            # hard cap defensive — titles/names only
            sql = f'SELECT COALESCE("{col}",\'\') AS txt FROM "{table}" LIMIT 500000'
            rows = bitmagnet_pg.query(sql)
            print(f"  {table}.{col} rows={len(rows)}", flush=True)
            for row in rows:
                extract_from_text(str(row.get("txt") or "").upper(), c)
        except Exception as e:  # noqa: BLE001
            print(f"  skip {table}.{col}: {e}", flush=True)
    print(f"  bitmagnet prefixes={len(c)}", flush=True)
    return c


def load_kind_maps() -> dict[str, str]:
    """prefix -> region from makers files."""
    mapping: dict[str, str] = {}
    files = [
        (
            ROOT / "apps/web/src/config/av-makers.japan.json",
            {
                "有码": "japan_censored",
                "写真": "japan_gravure",
                "无码": "japan_uncensored",
                "素人": "japan_amateur",
                "FC2": "fc2",
            },
        ),
        (ROOT / "apps/web/src/config/av-makers.china.json", {"国产": "china"}),
        (ROOT / "apps/web/src/config/av-makers.western.json", {"欧美": "western"}),
    ]
    for path, kinds in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for m in data:
            rid = kinds.get(m.get("kind"))
            if not rid:
                continue
            for p in m.get("prefixes") or []:
                mapping[clean(p)] = rid
    # skip lists from prefix_ranges
    for p in pr.SKIP_PREFIXES:
        c = clean(p)
        if c in {
            "FC2",
            "FC2PPV",
        }:
            mapping[c] = "fc2"
        elif c in {
            "CARIB",
            "CARIBPR",
            "1PON",
            "HEYZO",
            "TOKYOHOT",
            "H0930",
            "C0930",
            "H4610",
            "10MU",
            "PACO",
            "HEYDOUGA",
            "MESUBUTA",
            "KIN8",
            "GACHINCO",
            "XXXAV",
            "SPERMMANIA",
            "RHJ",
            "COSPURI",
        }:
            mapping.setdefault(c, "japan_uncensored")
        elif c == "JVID" or c in pr.load_china_prefixes():
            mapping.setdefault(c, "china")
        elif c.isalpha() and len(c) >= 4:
            # western shells in SKIP
            mapping.setdefault(c, "western")
    return mapping


def guess_region(pref: str, kind_map: dict[str, str]) -> str:
    if pref in kind_map:
        return kind_map[pref]
    if pref in {"FC2", "FC2PPV"}:
        return "fc2"
    if pref in pr.load_china_prefixes() or pref.startswith(("MD", "91", "MKY", "MDSR")):
        return "china"
    if re.match(r"^\d{2,3}[A-Z]{2,8}$", pref):
        return "japan_amateur"
    if pref in pr.SKIP_PREFIXES or (pref.isalpha() and len(pref) >= 6 and pref in {
        "BRAZZERS",
        "BLACKED",
        "TUSHY",
        "VIXEN",
        "DEEPER",
        "BANGBROS",
        "ONLYFANS",
        "LEGALPORNO",
        "EVILANGEL",
        "REALITYKINGS",
        "NAUGHTYAMERICA",
        "DIGITALPLAYGROUND",
    }):
        return "western"
    return "japan_censored"


def merge(prefs: dict[str, Counter], kind_map: dict[str, str]) -> dict:
    doc = store.load_catalog(force=True)
    added = defaultdict(list)
    # also add ranges-missing + digitalplayground
    ranges = json.loads(
        (ROOT / "apps/web/src/config/prefix-code-ranges.json").read_text(encoding="utf-8")
    )["ranges"]
    for k in ranges:
        prefs.setdefault("ranges", Counter())[clean(k)] += 3

    # union all sources with min hit threshold
    scores: Counter = Counter()
    for src, ctr in prefs.items():
        for p, n in ctr.items():
            if is_noise(p):
                continue
            scores[p] += n if src != "ranges" else max(n, 2)

    # keep if makers/ranges known, or seen enough in local DBs
    keep = set()
    range_keys = {clean(k) for k in ranges}
    for p, n in scores.items():
        if is_noise(p):
            continue
        if p in kind_map or p in range_keys:
            keep.add(p)
        elif n >= 5:
            keep.add(p)
        elif n >= 3 and re.match(r"^\d{0,3}[A-Z]{2,10}$", p) and 3 <= len(p) <= 12:
            keep.add(p)

    for p in sorted(keep):
        rid = guess_region(p, kind_map)
        bucket = doc["regions"][rid]["prefixes"]
        if p in bucket:
            cur = bucket[p]
            srcs = set(cur.get("sources") or [])
            srcs.update({"local-db", "sehua", "bitmagnet"})
            cur["sources"] = sorted(srcs)
            notes = str(cur.get("notes") or "")
            if "本地库" not in notes:
                cur["notes"] = (notes + " · 本地库确认").strip(" ·")
            serials = list(cur.get("serials") or [])
            bucket[p] = store._normalize_prefix_entry(p, {**cur, "serials": serials})
            if serials:
                bucket[p]["serials"] = serials
                bucket[p] = store._normalize_prefix_entry(p, bucket[p])
            continue
        ent = {
            "maker": "",
            "pad": 4 if re.match(r"^\d", p) else 3,
            "format": "{prefix}-{num}",
            "sources": ["local-db"],
            "serials": [],
            "notes": "本地库确认",
            "status": "active",
            "integrity": "unknown",
        }
        bucket[p] = store._normalize_prefix_entry(p, ent)
        added[rid].append(p)

    store.save_catalog(doc)

    # seed sync
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    for rid in REGION_ORDER:
        prefs_out = {}
        for key, ent in sorted((doc["regions"][rid]["prefixes"] or {}).items()):
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
            prefs_out[key] = row
        seed["regions"][rid] = {
            "id": rid,
            "label": REGION_META[rid]["label"],
            "prefixes": prefs_out,
        }
    SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "added": {k: v for k, v in added.items()},
        "added_counts": {k: len(v) for k, v in added.items()},
        "kept_candidates": len(keep),
        "summary": store.public_summary(),
    }


def main() -> None:
    kind_map = load_kind_maps()
    sources: dict[str, Counter] = {}
    try:
        sources["sehua"] = scan_sehua()
    except Exception as e:  # noqa: BLE001
        print(f"sehua FAIL: {e}", flush=True)
        sources["sehua"] = Counter()
    try:
        sources["bitmagnet"] = scan_bitmagnet()
    except Exception as e:  # noqa: BLE001
        print(f"bitmagnet FAIL: {e}", flush=True)
        sources["bitmagnet"] = Counter()

    # report overlap
    s, b = set(sources["sehua"]), set(sources["bitmagnet"])
    print(f"sehua={len(s)} bitmagnet={len(b)} both={len(s&b)} only_s={len(s-b)} only_b={len(b-s)}", flush=True)

    result = merge(sources, kind_map)
    report = {
        "sehua_top": sources["sehua"].most_common(30),
        "bitmagnet_top": sources["bitmagnet"].most_common(30),
        "sehua_count": len(sources["sehua"]),
        "bitmagnet_count": len(sources["bitmagnet"]),
        "added_counts": result["added_counts"],
        "added_sample": {k: v[:40] for k, v in result["added"].items()},
        "summary": result["summary"],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("added", result["added_counts"], flush=True)
    for r in result["summary"].get("regions") or []:
        print(f"{r['id']:18} prefixes={r.get('prefix_count')}", flush=True)
    print("TOTAL", result["summary"].get("prefix_total"), "report", REPORT, flush=True)


if __name__ == "__main__":
    main()
