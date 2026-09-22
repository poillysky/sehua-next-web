# -*- coding: utf-8 -*-
"""Find prefixes urgently needing intro fixes."""
from __future__ import annotations
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.core.region_meta import REGION_ORDER, REGION_META
from app.prefix import catalog_store as store
from app.prefix.maker_names import (
    PREFIX_INTRO,
    MAKER_INTRO,
    resolve_maker_intro_for_prefix,
    resolve_maker_names,
)

doc = store.load_catalog(force=True)

# code_count helper
def code_count(e: dict) -> int:
    for k in ("code_count", "codes", "count", "n"):
        v = e.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, list):
            return len(v)
    # ranges?
    ranges = e.get("ranges") or e.get("serial_ranges")
    if isinstance(ranges, list) and ranges:
        try:
            total = 0
            for r in ranges:
                if isinstance(r, dict):
                    a, b = r.get("from") or r.get("start"), r.get("to") or r.get("end")
                    if a is not None and b is not None:
                        total += int(b) - int(a) + 1
            if total:
                return total
        except Exception:
            pass
    return 0

# Known wrong: intro mentions unrelated maker
WRONG_MARKERS = [
    ("オーロラ", ["Aurora", "APNS", "APNH"]),
    ("凌辱・剧情系企划厂", None),  # too generic aurora text
]

urgent = []  # (score, pref, rid, maker, reason, intro, specific?)

for rid in REGION_ORDER:
    for pref, e in (doc["regions"][rid].get("prefixes") or {}).items():
        maker = str((e or {}).get("maker") or "").strip()
        n = code_count(e or {})
        specific = (PREFIX_INTRO.get(pref) or "").strip()
        intro = (resolve_maker_intro_for_prefix(pref) or "").strip()

        reasons = []
        # wrong fallback: intro talks about Aurora but maker is not Aurora
        if intro and "オーロラ" in intro:
            if "Aurora" not in maker and "オーロラ" not in maker:
                reasons.append("介绍错成Aurora文案")
        if intro and "凌辱・剧情系企划厂" in intro:
            if "Aurora" not in maker and "オーロラ" not in maker:
                reasons.append("介绍疑似串台")

        # mainstream-ish: no specific intro + high visibility makers
        MAINSTREAM_MAKER = re.compile(
            r"S1|MOODY|IDEA|Madonna|PRESTIGE|SOD|WANZ|Fitch|PREMIUM|本中|Hon-Naka|FALENO|kawaii|Das|Attackers|"
            r"Caribbean|HEYZO|一本道|加勒比|麻豆|星空|Tushy|Blacked|FC2|素人|ラグジュ|ARA|SIRO|DOC|MOON|"
            r"Hunter|OPPAI|E-BODY|Moodyz|Madonna|Prestige",
            re.I,
        )
        is_main_maker = bool(MAINSTREAM_MAKER.search(maker))
        # digit MGS style also mainstream amateur
        is_mgs = bool(re.match(r"^\d{3}[A-Z]", pref))

        if not specific:
            if is_main_maker or is_mgs or n >= 50:
                reasons.append("主流/高量但无前缀专属介绍")
            elif not intro:
                reasons.append("无任何介绍")

        # very short specific
        if specific and len(specific) <= 6:
            reasons.append("专属介绍过短")

        if not reasons:
            continue

        # score: wrong > no intro mainstream > short
        score = 0
        if any("错" in r or "串台" in r for r in reasons):
            score += 1000
        if "主流" in "".join(reasons):
            score += 100
        if is_mgs:
            score += 20
        score += min(n, 200)
        if "过短" in "".join(reasons):
            score += 30
        urgent.append((score, pref, rid, maker, ";".join(reasons), specific or intro or "(空)", bool(specific), n))

urgent.sort(key=lambda x: -x[0])

# Dedupe by pref (keep highest)
seen = set()
uniq = []
for row in urgent:
    if row[1] in seen:
        continue
    seen.add(row[1])
    uniq.append(row)

# Split: MUST (wrong) vs NEED (mainstream no specific)
must = [r for r in uniq if "错" in r[4] or "串台" in r[4]]
need = [r for r in uniq if r not in must and "主流" in r[4]]
short = [r for r in uniq if "过短" in r[4] and r not in must]

print(f"=== 急需（介绍串台/错误）{len(must)} ===")
for i, (score, pref, rid, maker, reason, intro, spec, n) in enumerate(must[:40], 1):
    print(f"{i:2d}. {pref}  [{REGION_META[rid]['label']}] maker={maker}")
    print(f"    原因: {reason}")
    print(f"    当前: {intro[:60]}")

print(f"\n=== 主流缺专属介绍（优先补）{len(need)} ===")
for i, (score, pref, rid, maker, reason, intro, spec, n) in enumerate(need[:50], 1):
    print(f"{i:2d}. {pref}  [{REGION_META[rid]['label']}] maker={maker[:40]}  n≈{n}")
    print(f"    现回退: {(intro or '-')[:50]}")

print(f"\n=== 专属介绍过短 {len(short)}（前20）===")
for i, (score, pref, rid, maker, reason, intro, spec, n) in enumerate(short[:20], 1):
    print(f"{i:2d}. {pref} | {intro!r} | {maker[:30]}")

print(f"\nTOTAL must={len(must)} need_mainstream={len(need)} short={len(short)}")
