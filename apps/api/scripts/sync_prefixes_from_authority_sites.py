# -*- coding: utf-8 -*-
"""Step1b: 各区权威站点抽前缀，合并进七区 catalog / seed。

权威映射（优先用面板已启用且测通的源）:
  japan_censored   → JavBus 有码列表（公开索引最全）
  japan_uncensored → JavBus 无码 + Caribbeancom 列表
  japan_amateur    → MGStage 检索列表
  japan_gravure    → JavBus/写真向页面 + 既有种子
  fc2              → FC2 内容站（前缀形态固定）
  china            → MissAV 国产/中文区 + Madou
  western          → MissAV 欧美区（ThePornDB 需登录，作备注）
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import outbound_http as o  # noqa: E402
from app import prefix_catalog_store as store  # noqa: E402
from app import scrape_sources_settings as sources  # noqa: E402
from app.core.region_meta import REGION_META, REGION_ORDER, std_prefix  # noqa: E402

SEED = ROOT / "apps" / "web" / "src" / "config" / "prefix-catalog.seed.json"
REPORT = ROOT / "data" / "_debug" / "prefix-authority-sync.json"

# dvd/id style: SSIS-001 / 200GANA-123 / ABP-1000
CODE_RE = re.compile(
    r"(?<![A-Z0-9])([0-9]{0,3}[A-Z]{2,12})[-_ ]?(\d{2,5})(?![A-Z0-9])",
    re.I,
)
# javbus movie href
HREF_CODE_RE = re.compile(
    r'href=["\'][^"\']*?/([0-9]{0,3}[A-Za-z]{2,12})-(\d{2,5})(?:["\'/?#]|$)',
    re.I,
)

# noise prefixes to drop
BLOCK = {
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
}


AUTHORITY: dict[str, dict[str, Any]] = {
    "japan_censored": {
        "label": "日本有码",
        "site": "javbus",
        "why": "公开有码索引最全；番号校验可再用 DMM",
        "urls": [
            "https://www.javbus.com/",
            "https://www.javbus.com/page/2",
            "https://www.javbus.com/page/3",
            "https://www.javbus.com/page/4",
            "https://www.javbus.com/page/5",
            "https://www.javbus.com/genre",
        ],
    },
    "japan_uncensored": {
        "label": "日本无码",
        "site": "javbus+carib",
        "why": "JavBus 无码区 + Caribbeancom 官方列表",
        "urls": [
            "https://www.javbus.com/uncensored",
            "https://www.javbus.com/uncensored/page/2",
            "https://www.javbus.com/uncensored/page/3",
            "https://www.caribbeancom.com/listpages/all1.htm",
            "https://www.caribbeancom.com/listpages/all2.htm",
        ],
        "force_prefixes": {
            "CARIB": {"maker": "Caribbeancom", "sources": ["carib"]},
            "CARIBPR": {"maker": "Caribbeancom Premium", "sources": ["carib"]},
            "1PON": {"maker": "1pondo", "sources": ["1pondo"]},
            "HEYZO": {"maker": "HEYZO", "sources": ["heyzo"], "pad": 4},
            "PACO": {"maker": "Pacopacomama", "sources": ["pacopacomama"]},
            "10MU": {"maker": "10musume", "sources": ["10musume"]},
            "H4610": {"maker": "H4610", "sources": ["h4610"]},
            "C0930": {"maker": "C0930", "sources": ["c0930"]},
            "KIN8": {"maker": "Kin8tengoku", "sources": ["kin8"]},
        },
    },
    "japan_amateur": {
        "label": "日本素人",
        "site": "mgstage",
        "why": "素人配信主力站（SIRO/LUXU/MAAN 等）",
        "cookie_source": "mgstage",
        "urls": [
            "https://www.mgstage.com/",
            "https://www.mgstage.com/search/cSearch.php?search_word=&type=top",
            "https://www.mgstage.com/search/cSearch.php?search_word=&type=latest",
            "https://www.mgstage.com/ppv/makers.php",
        ],
    },
    "japan_gravure": {
        "label": "日本写真",
        "site": "javbus",
        "why": "写真向公开列表较少，JavBus/种子交叉；DMM 作补充",
        "urls": [
            "https://www.javbus.com/",
            "https://www.javbus.com/page/2",
        ],
        "force_prefixes": {
            "ENFD": {"maker": "イーネット・フロンティア"},
            "OAE": {"maker": "Air control"},
            "REBD": {"maker": "REbecca"},
            "REBDB": {"maker": "REbecca"},
            "MBRAA": {"maker": "スパイスビジュアル"},
            "MBRBA": {"maker": "スパイスビジュアル"},
            "MBDD": {"maker": "メディアブランド"},
            "SYD": {"maker": "スパイスビジュアル"},
            "GGSID": {"maker": "グレイズ"},
            "BFAZ": {"maker": "ファインピクチャーズ"},
        },
    },
    "fc2": {
        "label": "FC2",
        "site": "fc2",
        "why": "FC2 以作者/PPV 号为主，前缀形态固定为 FC2 / FC2PPV",
        "urls": [
            "https://adult.contents.fc2.com/",
            "https://adult.contents.fc2.com/article_search.php?pg=1",
        ],
        "force_prefixes": {
            "FC2": {"maker": "FC2", "sources": ["fc2"], "pad": 0, "format": "FC2-{num}"},
            "FC2PPV": {
                "maker": "FC2 PPV",
                "sources": ["fc2"],
                "pad": 0,
                "format": "FC2-PPV-{num}",
            },
        },
    },
    "china": {
        "label": "国产无码",
        "site": "missav+madou",
        "why": "MissAV 中文聚合 + 麻豆站，覆盖国产片商号",
        "urls": [
            "https://missav123.com/dm22/cn",
            "https://missav123.com/dm247/cn",
            "https://madou.club/",
        ],
    },
    "western": {
        "label": "欧美无码",
        "site": "missav",
        "why": "ThePornDB 需登录；先用 MissAV 欧美区抽工作室；权威库仍属 ThePornDB",
        "urls": [
            "https://missav123.com/dm21/cn",
            "https://missav123.com/dm8/cn",
        ],
        "force_prefixes": {
            "BRAZZERS": {"maker": "Brazzers"},
            "BLACKED": {"maker": "Blacked"},
            "TUSHY": {"maker": "Tushy"},
            "VIXEN": {"maker": "Vixen"},
            "DEEPER": {"maker": "Deeper"},
            "BANGBROS": {"maker": "Bang Bros"},
            "NAUGHTYAMERICA": {"maker": "Naughty America"},
            "REALITYKINGS": {"maker": "Reality Kings"},
            "EVILANGEL": {"maker": "Evil Angel"},
            "ONLYFANS": {"maker": "OnlyFans"},
        },
    },
}


def clean_prefix(raw: str) -> str:
    p = re.sub(r"[^A-Z0-9]", "", std_prefix(raw).replace("-", ""))
    if len(p) < 2 or len(p) > 14:
        return ""
    if p in BLOCK:
        return ""
    if p.isdigit():
        return ""
    return p


def extract_prefixes(html: str) -> set[str]:
    found: set[str] = set()
    for rx in (HREF_CODE_RE, CODE_RE):
        for m in rx.finditer(html or ""):
            pref = clean_prefix(m.group(1))
            if pref:
                found.add(pref)
    return found


def source_cookie(source_id: str) -> str | None:
    try:
        cfg = sources.provider_settings(source_id)
        c = str(cfg.get("cookie") or "").strip()
        return c or None
    except Exception:
        return None


def fetch(url: str, *, cookie: str | None = None) -> str:
    page = o.fetch_page(url, cookie=cookie, timeout=28.0, fresh_probe=False)
    return page.html or ""


def harvest_region(rid: str, conf: dict[str, Any]) -> dict[str, Any]:
    cookie = None
    if conf.get("cookie_source"):
        cookie = source_cookie(str(conf["cookie_source"]))
        if conf["cookie_source"] == "mgstage" and not cookie:
            cookie = "adc=1"
        elif conf["cookie_source"] == "mgstage" and "adc=" not in cookie:
            cookie = f"{cookie}; adc=1"

    got: set[str] = set()
    pages: list[dict[str, Any]] = []
    for url in conf.get("urls") or []:
        try:
            html = fetch(url, cookie=cookie)
            prefs = extract_prefixes(html)
            # carib date pages rarely have letter prefixes — still ok
            got |= prefs
            pages.append({"url": url, "ok": True, "prefixes": len(prefs), "html": len(html)})
            print(f"  OK {rid} {url} +{len(prefs)} (html={len(html)})", flush=True)
        except Exception as e:  # noqa: BLE001
            pages.append({"url": url, "ok": False, "error": str(e)[:160]})
            print(f"  FAIL {rid} {url} {e}", flush=True)

    forced = conf.get("force_prefixes") or {}
    for k in forced:
        ck = clean_prefix(k)
        if ck:
            got.add(ck)

    return {
        "site": conf.get("site"),
        "why": conf.get("why"),
        "pages": pages,
        "prefixes": sorted(got),
        "force": list(forced.keys()),
    }


def merge_into_catalog(
    rid: str, prefixes: list[str], *, site: str, force_meta: dict[str, dict]
) -> dict[str, int]:
    doc = store.load_catalog(force=True)
    bucket = doc["regions"][rid]["prefixes"]
    added = 0
    touched = 0
    for pref in prefixes:
        key = clean_prefix(pref)
        if not key:
            continue
        meta = force_meta.get(key) or force_meta.get(pref) or {}
        srcs = list(meta.get("sources") or [site.split("+")[0], "site"])
        if key in bucket:
            cur = bucket[key]
            serials = list(cur.get("serials") or [])
            cur_sources = set(cur.get("sources") or [])
            cur_sources.update(srcs)
            cur_sources.add("authority")
            cur["sources"] = sorted(cur_sources)
            if meta.get("maker") and not cur.get("maker"):
                cur["maker"] = meta["maker"]
            notes = str(cur.get("notes") or "")
            tag = f"权威站:{site}"
            if tag not in notes:
                cur["notes"] = (notes + f" · {tag}").strip(" ·")
            bucket[key] = store._normalize_prefix_entry(key, {**cur, "serials": serials})
            if serials:
                bucket[key]["serials"] = serials
                bucket[key] = store._normalize_prefix_entry(key, bucket[key])
            touched += 1
        else:
            ent = {
                "maker": str(meta.get("maker") or ""),
                "pad": int(meta.get("pad") if meta.get("pad") is not None else (0 if rid in {"fc2", "china", "western", "japan_uncensored"} else 3)),
                "format": str(meta.get("format") or "{prefix}-{num}"),
                "sources": sorted(set(srcs + ["authority"])),
                "serials": [],
                "notes": f"权威站:{site}",
                "status": "active",
                "integrity": "unknown",
            }
            bucket[key] = store._normalize_prefix_entry(key, ent)
            added += 1
    store.save_catalog(doc)
    return {"added": added, "touched": touched, "total": len(bucket)}


def sync_seed_from_catalog() -> None:
    """把 catalog 各区前缀键回写 seed（不带 serials）。"""
    doc = store.load_catalog(force=True)
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    regions = seed.setdefault("regions", {})
    for rid in REGION_ORDER:
        meta = REGION_META[rid]
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
            if ent.get("maker_ja"):
                row["maker_ja"] = ent["maker_ja"]
            out[key] = row
        regions[rid] = {"id": rid, "label": meta["label"], "prefixes": out}
    seed["principle"] = "authority-site + curated seeds; runtime harvest fills serials"
    SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    report: dict[str, Any] = {"authority": {}, "merge": {}}
    print("=== authority prefix sync ===", flush=True)
    for rid in REGION_ORDER:
        conf = AUTHORITY[rid]
        print(f"\n[{rid}] site={conf['site']} — {conf['why']}", flush=True)
        harvested = harvest_region(rid, conf)
        report["authority"][rid] = {
            "site": harvested["site"],
            "why": harvested["why"],
            "pages": harvested["pages"],
            "prefix_count": len(harvested["prefixes"]),
            "prefixes_sample": harvested["prefixes"][:40],
        }
        force_meta = {
            clean_prefix(k): v for k, v in (conf.get("force_prefixes") or {}).items()
        }
        # for gravure: only keep force + known gravure-like, avoid polluting with SSIS etc.
        prefs = harvested["prefixes"]
        if rid == "japan_gravure":
            prefs = sorted(set(force_meta) | set(conf.get("force_prefixes") or {}))
            prefs = [clean_prefix(p) for p in prefs if clean_prefix(p)]
        if rid == "fc2":
            prefs = ["FC2", "FC2PPV"]
        if rid == "japan_uncensored":
            # keep extracted letter prefixes + forced studio shells; drop pure date noise later
            prefs = sorted(set(prefs) | set(force_meta))
        merge = merge_into_catalog(
            rid, prefs, site=str(conf["site"]), force_meta=force_meta
        )
        report["merge"][rid] = merge
        print(
            f"  -> harvested={len(harvested['prefixes'])} merge +{merge['added']} "
            f"touch={merge['touched']} total={merge['total']}",
            flush=True,
        )

    sync_seed_from_catalog()
    summary = store.public_summary()
    report["summary"] = summary
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n=== summary ===", flush=True)
    for r in summary.get("regions") or []:
        print(
            f"{r['id']:18} {r.get('label'):8} prefixes={r.get('prefix_count')}",
            flush=True,
        )
    print(f"TOTAL {summary.get('prefix_total')}  report={REPORT}", flush=True)


if __name__ == "__main__":
    main()
