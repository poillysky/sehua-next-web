# -*- coding: utf-8 -*-
"""Audit code-titles region tags for catalog-ambiguous prefixes."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.prefix.catalog_store as store
from app.core.region_meta import REGION_META, REGION_ORDER

ROOT = Path(__file__).resolve().parents[3]
TITLES = ROOT / "apps" / "maps" / "scrape" / "code-titles.json"

LABEL = {
    "japan_censored": "有码",
    "japan_uncensored": "无码",
    "japan_amateur": "素人",
    "fc2": "FC2",
    "china": "国产",
    "western": "欧美",
}

# Known context overrides already applied / expected
EXPECTED_CONTEXT = {
    "ENFD": "有码",
    "MBDD": "有码",
    "MBRAA": "有码",
    "MBRBA": "有码",
    "OAE": "有码",
    "REBD": "有码",
    "REBDB": "有码",
    "MDL": "国产",
    "MKY": "国产",
}

MDS_CHINA = {
    "MDS-0014",
    "MDS-009",
    "MDS-014",
    "MDS-020",
    "MDS-038",
    "MDS-119",
}
MDM_CHINA = {"MDM-0002", "MDM-001"}
SAO_CHINA = {"SAO-001"}

CN_MARK = re.compile(
    r"(苏畅|夏晴子|艾熙|李蓉蓉|苏语棠|宋南伊|苏清歌|黎芷萱|沈娜娜|孟若羽|"
    r"徐夜夜|陈美琳|张芸熙|刘依依|苡若|梁幂|韩棠|楚梦舒|"
    r"恋爱咖啡馆|性之游戏|麻豆|精东|天美传媒|蜜桃|大像传媒|国产AV|"
    r"旗袍诱惑|飞淫之旅|绿帽子给老公|强奸暗恋|青梅竹马)"
)
JP_MARK = re.compile(r"[ぁ-んァ-ン]|宇宙企画|純真|就職活動|完全版|催眠洗脳|ALL NUDE|裸神|写真视频")
GRAVURE_MARK = re.compile(
    r"(ALL NUDE|裸神|裸天使|写真视频|写真集|接写|制服SCANDAL|女神之微笑|"
    r"幻想|Tropical|Sunshine|Lakeside|Southern Superstar)",
    re.I,
)


def extract_prefix(code: str) -> str:
    ku = str(code or "").upper().strip()
    if ku.startswith("FC2"):
        return "FC2"
    m = re.match(r"^(.+?)[-_](\d+)", ku)
    return m.group(1) if m else ku


def main() -> None:
    doc = store.load_catalog(force=True)
    pref_regions: dict[str, set[str]] = defaultdict(set)
    pref_meta: dict[str, dict[str, dict]] = defaultdict(dict)
    for rid in REGION_ORDER:
        prefs = ((doc.get("regions") or {}).get(rid) or {}).get("prefixes") or {}
        for pref, ent in prefs.items():
            p = str(pref or "").strip().upper()
            if not p:
                continue
            pref_regions[p].add(rid)
            ent = ent if isinstance(ent, dict) else {}
            pref_meta[p][rid] = {
                "maker": str(ent.get("maker") or ent.get("maker_zh") or ""),
                "notes": str(ent.get("notes") or "")[:100],
                "n": int(ent.get("code_count") or 0),
            }

    amb = {p: sorted(rs) for p, rs in pref_regions.items() if len(rs) > 1}
    print("=== catalog cross-region prefixes", len(amb), "===")
    for p, rs in sorted(amb.items()):
        print(p, [REGION_META[r]["label"] for r in rs])
        for r in rs:
            m = pref_meta[p][r]
            print(
                f"    {REGION_META[r]['label']}: {m['maker']} | {m['notes']} | n={m['n']}"
            )

    data = json.loads(TITLES.read_text(encoding="utf-8"))
    by_pref: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for k, v in data.items():
        p = extract_prefix(k)
        if p not in amb:
            continue
        lab, _, body = str(v).partition("｜")
        by_pref[p].append((k, lab, body or str(v)))

    print()
    print("=== code-titles audit ===")
    issues: list[str] = []
    for p in sorted(amb):
        rows = by_pref.get(p) or []
        expect = EXPECTED_CONTEXT.get(p, "")
        labs = Counter(r[1] for r in rows)
        print(
            f"--- {p} catalog={[REGION_META[r]['label'] for r in amb[p]]} "
            f"tags={dict(labs)} n={len(rows)} expect={expect or '-'} ---"
        )
        for k, lab, body in rows:
            flag = ""
            ku = k.upper()
            if p in {"ENFD", "MBDD", "MBRAA", "MBRBA", "OAE", "REBD", "REBDB"}:
                if lab != "有码":
                    flag = "SHOULD_有码"
                elif not GRAVURE_MARK.search(body) and not JP_MARK.search(body):
                    # still ok if short gravure-ish
                    if CN_MARK.search(body):
                        flag = "CN_MARK_UNDER_有码?"
            elif p in {"MDL", "MKY"}:
                if lab != "国产":
                    flag = "SHOULD_国产"
                elif JP_MARK.search(body) and not CN_MARK.search(body):
                    flag = "JP_MARK_UNDER_国产?"
            # MDS is NOT in amb (only japan_censored) but collision is contextual
            if flag:
                issues.append(f"{k}\t{lab}\t{flag}\t{body[:60]}")
            print(f"  {k}\t{lab}\t{body[:65]}")

    # Extra: MDS / MDM / SAO contextual collisions (same prefix string, different content)
    print()
    print("=== contextual same-prefix collisions (MDS/MDM/SAO) ===")
    for k, v in data.items():
        ku = k.upper()
        lab, _, body = str(v).partition("｜")
        body = body or str(v)
        if ku.startswith("MDS") and not ku.startswith("MDSR"):
            want = "国产" if ku in MDS_CHINA else "有码"
            ok = lab == want
            mark = "OK" if ok else "BAD"
            if not ok or ku in MDS_CHINA or "宇宙企画" in body or CN_MARK.search(body):
                print(f"  [{mark}] {k}\t{lab}\twant={want}\t{body[:60]}")
            if not ok:
                issues.append(f"{k}\t{lab}\twant={want}\t{body[:60]}")
        if ku.startswith("MDM"):
            want = "国产" if ku in MDM_CHINA else "有码"
            ok = lab == want
            mark = "OK" if ok else "BAD"
            print(f"  [{mark}] {k}\t{lab}\twant={want}\t{body[:60]}")
            if not ok:
                issues.append(f"{k}\t{lab}\twant={want}\t{body[:60]}")
        if ku.startswith("SAO"):
            want = "国产" if ku in SAO_CHINA else "有码"
            ok = lab == want
            mark = "OK" if ok else "BAD"
            print(f"  [{mark}] {k}\t{lab}\twant={want}\t{body[:60]}")
            if not ok:
                issues.append(f"{k}\t{lab}\twant={want}\t{body[:60]}")

    # Prefix-similar traps: china MD vs jp MDS/MDTM etc already different keys —
    # scan 有码 entries whose prefix is china-only but somehow tagged wrong? reverse check
    china_only = {
        p for p, rs in pref_regions.items() if rs == {"china"}
    }
    jp_only = {
        p
        for p, rs in pref_regions.items()
        if rs <= {"japan_censored", "japan_uncensored", "japan_amateur"}
        and len(rs) >= 1
        and "china" not in rs
    }

    print()
    print("=== china-only prefix tagged 有码? ===")
    n = 0
    for k, v in data.items():
        p = extract_prefix(k)
        lab, _, body = str(v).partition("｜")
        if p in china_only and lab == "有码":
            n += 1
            print(f"  {k}\t{lab}\t{body[:65]}")
            issues.append(f"{k}\t有码\tchina-prefix\t{body[:60]}")
    print("count", n)

    print()
    print("=== jp-only prefix tagged 国产? ===")
    n = 0
    for k, v in data.items():
        p = extract_prefix(k)
        lab, _, body = str(v).partition("｜")
        if p in jp_only and lab == "国产":
            # allow contextual overrides
            ku = k.upper()
            if ku in MDS_CHINA or ku in MDM_CHINA or ku in SAO_CHINA:
                continue
            if p.startswith("MDS") and ku in MDS_CHINA:
                continue
            n += 1
            print(f"  {k}\t{lab}\t{body[:65]}")
            issues.append(f"{k}\t国产\tjp-prefix\t{body[:60]}")
    print("count", n)

    print()
    print("=== ISSUES", len(issues), "===")
    for line in issues:
        print(line)


if __name__ == "__main__":
    main()
