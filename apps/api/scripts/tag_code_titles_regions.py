# -*- coding: utf-8 -*-
"""给 apps/maps/scrape/code-titles.json 每条标题加上区域代号。

规则：
1. 七区目录前缀唯一命中 → 直接标区
2. 跨区同前缀（极少）→ 按本文件段落标题上下文人工定区，禁止盲猜
3. 目录未收录 → 按番号形态兜底（日期无码 / FC2 / 其余默认有码）

标题格式：有码｜原标题
lookup_code_title 会剥掉区域前缀，避免写入 NFO。
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))

OUT = ROOT / "apps" / "maps" / "scrape" / "code-titles.json"

REGION_LABEL = {
    "japan_censored": "有码",
    "japan_uncensored": "无码",
    "japan_amateur": "素人",
    "fc2": "FC2",
    "china": "国产",
    "western": "欧美",
}
LABELS = tuple(REGION_LABEL.values())
TAG_RE = re.compile(
    r"^(?:" + "|".join(map(re.escape, LABELS)) + r")\s*[|｜·\-—]\s*"
)

# 跨区同前缀：按 code-titles 内标题上下文定区（偶像映像盘 / 国产剧情）
# 不可用脚本按前缀盲分。
AMBIGUOUS_CONTEXT: dict[str, str] = {
    # 有码∩原写真前缀 → 并入有码
    "ENFD": "japan_censored",
    "MBDD": "japan_censored",
    "MBRAA": "japan_censored",
    "MBRBA": "japan_censored",
    "OAE": "japan_censored",
    "REBD": "japan_censored",
    "REBDB": "japan_censored",
    # 国产∩有码 → 本文件 MDL 全是麻豆系中文剧情
    "MDL": "china",
    "MKY": "china",
}

# MDS：目录主线是有码「宇宙企划」；本文件少量低番号是国产麻豆误号，按番号白名单定区
MDS_CHINA_CODES = frozenset(
    {
        "MDS-0014",
        "MDS-009",
        "MDS-014",
        "MDS-020",
        "MDS-038",
        "MDS-119",
    }
)

# MDM：目录主线是有码 MOODYZ；本文件「恋爱咖啡馆」是国产麻豆撞号
# SAO-001：国产演员阵容（宋南伊/黎芷萱/艾熙）
MDM_CHINA_CODES = frozenset({"MDM-0002", "MDM-001"})
SAO_CHINA_CODES = frozenset({"SAO-001"})


def strip_region_tag(title: str) -> str:
    t = str(title or "").strip()
    return TAG_RE.sub("", t).strip() or t


def with_region_tag(region_id: str, title: str) -> str:
    label = REGION_LABEL.get(region_id, "")
    body = strip_region_tag(title)
    if not label:
        return body
    return f"{label}｜{body}"


def build_prefix_map() -> dict[str, set[str]]:
    import app.prefix.catalog_store as store
    from app.core.region_meta import REGION_ORDER

    doc = store.load_catalog(force=True)
    out: dict[str, set[str]] = {}
    for rid in REGION_ORDER:
        reg = (doc.get("regions") or {}).get(rid) or {}
        for pref in (reg.get("prefixes") or {}):
            p = str(pref or "").strip().upper()
            if p:
                out.setdefault(p, set()).add(rid)
    return out


def extract_prefix(code: str) -> str:
    ku = str(code or "").upper().strip()
    if not ku:
        return ""
    if ku.startswith("FC2"):
        return "FC2"
    m = re.match(r"^(.+?)[-_](\d+)(?:[-_].*)?$", ku)
    if m:
        return m.group(1)
    m2 = re.match(r"^([A-Z0-9]+)", ku)
    return m2.group(1) if m2 else ""


def resolve_prefix(code: str, pref_regions: dict[str, set[str]]) -> tuple[str, set[str]]:
    p = extract_prefix(code)
    if p in pref_regions:
        return p, pref_regions[p]
    # 001HMNF → HMNF
    p2 = re.sub(r"^\d+", "", p)
    if p2 and p2 in pref_regions:
        return p2, pref_regions[p2]
    return p, set()


def heuristic_region(code: str) -> str:
    """目录未收录时的形态兜底（非跨区前缀场景）。"""
    ku = str(code or "").upper().strip()
    if ku.startswith("FC2"):
        return "fc2"
    # Caribbean / 1pondo / paco 日期番号
    if re.match(r"^\d{6}[-_]\d", ku):
        return "japan_uncensored"
    if re.match(r"^(1PONDO|CARIB|HEYZO|PACO|TOKYO[-_]?HOT|KIN8|C0930|H0930|H4610)", ku):
        return "japan_uncensored"
    # 欧美厂牌常见词头（目录外遗漏）
    if re.match(
        r"^(BLACKED|BRAZZERS|VIXEN|TUSHY|EVILANGEL|NAUGHTY|REALITY|BANGBROS|ONLYFANS)",
        ku,
    ):
        return "western"
    # 国产常见
    if re.match(r"^(91|JVID|MADOL|MSD|MDX|MDHG|MDWP|TMW|DSG)", ku):
        return "china"
    return "japan_censored"


def classify(
    code: str, title: str, pref_regions: dict[str, set[str]]
) -> tuple[str, str]:
    """返回 (region_id, reason)."""
    c_u = str(code or "").strip().upper()
    # MDS 特例：同前缀两边都有，按本文件上下文白名单区分
    if c_u.startswith("MDS") and not c_u.startswith("MDSR"):
        if c_u in MDS_CHINA_CODES:
            return "china", f"context:MDS-china:{c_u}"
        # 其余走宇宙企划有码（含目录命中）
        return "japan_censored", f"context:MDS-jp:{c_u}"
    if c_u in MDM_CHINA_CODES:
        return "china", f"context:MDM-china:{c_u}"
    if c_u in SAO_CHINA_CODES:
        return "china", f"context:SAO-china:{c_u}"
    p, regions = resolve_prefix(code, pref_regions)
    if p in AMBIGUOUS_CONTEXT:
        return AMBIGUOUS_CONTEXT[p], f"context:{p}"
    if len(regions) == 1:
        return next(iter(regions)), f"catalog:{p}"
    if len(regions) > 1:
        # 未写入 AMBIGUOUS_CONTEXT 的跨区前缀：宁可标有码也不瞎猜写真/国产
        return "japan_censored", f"ambig-fallback:{p}:{sorted(regions)}"
    return heuristic_region(code), f"heuristic:{p or '?'}"


def main() -> None:
    pref_regions = build_prefix_map()
    raw = json.loads(OUT.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("code-titles.json not an object")

    out: dict[str, str] = {}
    reasons: Counter[str] = Counter()
    regions: Counter[str] = Counter()
    ambig_used: list[str] = []

    for code, title in raw.items():
        c = str(code or "").strip()
        t = str(title or "").strip()
        if not c or not t:
            continue
        rid, why = classify(c, t, pref_regions)
        if why.startswith("context:"):
            ambig_used.append(c)
        reasons[why.split(":")[0]] += 1
        regions[REGION_LABEL[rid]] += 1
        out[c] = with_region_tag(rid, t)

    # 稳定排序写出
    ordered = dict(sorted(out.items(), key=lambda kv: kv[0].upper()))
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(OUT)

    print(f"wrote {OUT} · {len(ordered):,} entries")
    print("by region:", dict(regions))
    print("by reason:", dict(reasons))
    print("context-resolved:", len(ambig_used))
    # sample
    for k in ("AARM-001", "FC2-320862", "91CM-233", "OAE-133", "MDL-001", "010109-949"):
        if k in ordered:
            sample = ordered[k][:60].encode("utf-8", "replace").decode("utf-8")
            print(" ", k, "→", sample)


if __name__ == "__main__":
    main()
