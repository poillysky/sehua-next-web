# -*- coding: utf-8 -*-
"""Inventory scrap-library prefixes that have real code folders, with intro status."""
from __future__ import annotations
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"E:\Project\sehua-next-web")
SCRAP = ROOT / "media" / "scrap-library"
MAPS = ROOT / "apps" / "maps"

makers_path = MAPS / "makers" / "makers.json"
prefixes_path = MAPS / "prefixes" / "prefixes.json"
# catalog may live under data or maps
catalog_candidates = [
    ROOT / "data" / "prefix" / "catalog" / "catalog.json",
    ROOT / "apps" / "maps" / "prefixes" / "catalog.json",
    ROOT / "apps" / "maps" / "prefixes" / "catalog.seed.json",
]
catalog_path = next((p for p in catalog_candidates if p.exists()), None)

makers = json.loads(makers_path.read_text(encoding="utf-8"))
prefixes_doc = json.loads(prefixes_path.read_text(encoding="utf-8")) if prefixes_path.exists() else {}
# prefixes.json structure: often { "items": { PREFIX: {...} } } or flat
pref_items = prefixes_doc.get("items") or prefixes_doc.get("prefixes") or prefixes_doc
if not isinstance(pref_items, dict):
    pref_items = {}

catalog = {}
if catalog_path:
    cat = json.loads(catalog_path.read_text(encoding="utf-8"))
    # find japan region
    regions = cat.get("regions") or cat
    if isinstance(regions, dict):
        for k, v in regions.items():
            if not isinstance(v, dict):
                continue
            prefs = v.get("prefixes") or {}
            if prefs and ("japan" in str(k).lower() or "有码" in str(k) or "censored" in str(k).lower()):
                catalog.update({str(p).upper(): e for p, e in prefs.items()})
        if not catalog:
            # try top-level prefixes
            for k, v in regions.items():
                if isinstance(v, dict) and "maker" in v or "makers" in str(type(v)):
                    pass
            # flatten all regions
            for k, v in regions.items():
                if isinstance(v, dict) and isinstance(v.get("prefixes"), dict):
                    for p, e in v["prefixes"].items():
                        catalog.setdefault(str(p).upper(), e)

print("catalog_path", catalog_path)
print("catalog_prefixes", len(catalog))
print("makers_keys", len(makers) if isinstance(makers, dict) else "n/a")

# makers.json may be { makers: { key: meta } }
makers_map = makers.get("makers") if isinstance(makers, dict) and "makers" in makers else makers
if not isinstance(makers_map, dict):
    makers_map = {}

CODE_RE = re.compile(r"^[A-Z0-9]+[-_]?\d+", re.I)
SKIP_DIRS = {"_actress", "_covers", "_tmp", "_cache", ".git"}

def count_codes(prefix_dir: Path) -> int:
    n = 0
    if not prefix_dir.is_dir():
        return 0
    for child in prefix_dir.iterdir():
        if not child.is_dir():
            # also count nfo/strm at prefix level?
            continue
        name = child.name
        if name.startswith("_"):
            continue
        # count any non-underscore subdir as a title folder
        n += 1
    return n

def maker_intro_ok(meta: dict) -> bool:
    if not isinstance(meta, dict):
        return False
    # check zh intro fields commonly used
    for key in ("intro", "introZh", "intro_zh", "blurb", "description"):
        v = meta.get(key)
        if isinstance(v, str) and v.strip() and "公开资料有限" not in v and len(v.strip()) >= 8:
            return True
    i18n = meta.get("i18n") or meta.get("intros") or {}
    if isinstance(i18n, dict):
        for lang in ("zh", "zh-CN", "zh_cn", "cn", "ja", "en"):
            part = i18n.get(lang)
            if isinstance(part, dict):
                for key in ("intro", "blurb", "description"):
                    v = part.get(key)
                    if isinstance(v, str) and v.strip() and "公开资料有限" not in v and len(v.strip()) >= 8:
                        return True
            elif isinstance(part, str) and part.strip() and len(part.strip()) >= 8:
                return True
    return False

def maker_colloquial_ok(meta: dict) -> bool:
    if not isinstance(meta, dict):
        return False
    for key in ("colloquial", "displayName", "display_name", "nameZh", "name_zh", "cardName", "alias"):
        v = meta.get(key)
        if isinstance(v, str) and v.strip():
            return True
        if isinstance(v, list) and any(str(x).strip() for x in v):
            return True
    i18n = meta.get("i18n") or {}
    if isinstance(i18n, dict):
        for lang in ("zh", "zh-CN", "zh_cn", "cn"):
            part = i18n.get(lang)
            if isinstance(part, dict):
                for key in ("name", "colloquial", "displayName", "shortName"):
                    v = part.get(key)
                    if isinstance(v, str) and v.strip():
                        return True
            elif isinstance(part, str) and part.strip():
                return True
    names = meta.get("names") or {}
    if isinstance(names, dict):
        for lang in ("zh", "zh-CN", "cn"):
            v = names.get(lang)
            if isinstance(v, str) and v.strip():
                return True
    return False

def prefix_intro_ok(pref: str) -> tuple[bool, str]:
    ent = pref_items.get(pref) or pref_items.get(pref.upper()) or pref_items.get(pref.lower())
    if not isinstance(ent, dict):
        return False, ""
    for key in ("intro", "introZh", "intro_zh", "blurb", "description"):
        v = ent.get(key)
        if isinstance(v, str) and v.strip() and "公开资料有限" not in v and len(v.strip()) >= 8:
            return True, v.strip()[:40]
    i18n = ent.get("i18n") or ent.get("intros") or {}
    if isinstance(i18n, dict):
        for lang in ("zh", "zh-CN", "zh_cn", "cn"):
            part = i18n.get(lang)
            if isinstance(part, dict):
                for key in ("intro", "blurb", "description"):
                    v = part.get(key)
                    if isinstance(v, str) and v.strip() and "公开资料有限" not in v and len(v.strip()) >= 8:
                        return True, v.strip()[:40]
            elif isinstance(part, str) and part.strip() and len(part.strip()) >= 8:
                return True, part.strip()[:40]
    # weak placeholder
    for key in ("intro", "introZh", "blurb"):
        v = ent.get(key)
        if isinstance(v, str) and v.strip():
            return False, v.strip()[:40]
    return False, ""

rows = []
for region_dir in sorted(SCRAP.iterdir()):
    if not region_dir.is_dir() or region_dir.name.startswith("_"):
        continue
    region = region_dir.name
    if region.upper() == "FC2":
        # FC2 is flat codes; single prefix
        n = sum(1 for c in region_dir.iterdir() if c.is_dir() and not c.name.startswith("_"))
        if n > 0:
            rows.append({"region": region, "prefix": "FC2", "count": n, "path": str(region_dir)})
        continue
    for pref_dir in sorted(region_dir.iterdir()):
        if not pref_dir.is_dir() or pref_dir.name.startswith("_"):
            continue
        pref = pref_dir.name.upper().strip()
        n = count_codes(pref_dir)
        if n <= 0:
            continue
        rows.append({"region": region, "prefix": pref, "count": n, "path": str(pref_dir)})

print("total_prefixes_with_codes", len(rows))
print("total_codes", sum(r["count"] for r in rows))

# enrich with maker + intro status
out = []
missing_prefix_intro = []
missing_maker_intro = []
missing_both = []
ok_both = []

for r in rows:
    pref = r["prefix"]
    cat_ent = catalog.get(pref) or {}
    maker = ""
    if isinstance(cat_ent, dict):
        maker = str(cat_ent.get("maker") or cat_ent.get("makerKey") or cat_ent.get("studio") or "").strip()
        if not maker:
            makers_list = cat_ent.get("makers")
            if isinstance(makers_list, list) and makers_list:
                maker = str(makers_list[0]).strip()
            elif isinstance(makers_list, str):
                maker = makers_list.strip()
    # fallback from prefixes.json
    pent = pref_items.get(pref) or pref_items.get(pref.upper()) or {}
    if not maker and isinstance(pent, dict):
        maker = str(pent.get("maker") or pent.get("makerKey") or "").strip()

    mmeta = makers_map.get(maker) or makers_map.get(maker.lower()) or makers_map.get(maker.upper()) or {}
    # try fuzzy key
    if not mmeta and maker:
        for k, v in makers_map.items():
            if str(k).lower() == maker.lower():
                mmeta = v
                break

    p_ok, p_snip = prefix_intro_ok(pref)
    m_intro = maker_intro_ok(mmeta) if maker else False
    m_col = maker_colloquial_ok(mmeta) if maker else False

    status = {
        **r,
        "maker": maker or "(无厂牌)",
        "prefix_intro": "ok" if p_ok else ("weak" if p_snip else "missing"),
        "prefix_snip": p_snip,
        "maker_intro": "ok" if m_intro else ("no_maker" if not maker else "missing"),
        "maker_colloquial": "ok" if m_col else ("no_maker" if not maker else "missing"),
        "in_catalog": pref in catalog,
    }
    out.append(status)
    need_p = status["prefix_intro"] != "ok"
    need_m = status["maker_intro"] != "ok" or status["maker_colloquial"] != "ok"
    if need_p and need_m:
        missing_both.append(status)
    elif need_p:
        missing_prefix_intro.append(status)
    elif need_m:
        missing_maker_intro.append(status)
    else:
        ok_both.append(status)

# print sample maker structure
sample_maker_keys = list(makers_map.keys())[:3]
print("sample_maker_keys", sample_maker_keys)
if sample_maker_keys:
    sm = makers_map[sample_maker_keys[0]]
    print("sample_maker_fields", list(sm.keys())[:20] if isinstance(sm, dict) else type(sm))

sample_pref = next(iter(pref_items.keys()), None)
print("sample_pref_key", sample_pref)
if sample_pref:
    print("sample_pref_fields", list(pref_items[sample_pref].keys())[:20] if isinstance(pref_items[sample_pref], dict) else type(pref_items[sample_pref]))

print("---STATS---")
print("ok_both", len(ok_both))
print("need_prefix_only", len(missing_prefix_intro))
print("need_maker_only", len(missing_maker_intro))
print("need_both", len(missing_both))
print("need_any", len(missing_prefix_intro)+len(missing_maker_intro)+len(missing_both))

# write full list
out_path = ROOT / "apps" / "api" / "scripts" / "_scrap_prefix_intro_todo.json"
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote", out_path)

# human readable list for user - ALL prefixes with codes
lines = []
lines.append(f"# 刮削库实际有番号的前缀（共 {len(out)} 个，合计 {sum(r['count'] for r in out)} 条）")
lines.append("")
lines.append("| 前缀 | 数量 | 厂牌 | 前缀介绍 | 厂牌介绍 | 俗称 | 在catalog |")
lines.append("|---|---:|---|---|---|---|---|")
for s in sorted(out, key=lambda x: (-x["count"], x["prefix"])):
    lines.append(
        f"| {s['prefix']} | {s['count']} | {s['maker']} | {s['prefix_intro']} | {s['maker_intro']} | {s['maker_colloquial']} | {'Y' if s['in_catalog'] else 'N'} |"
    )

todo = [s for s in out if s["prefix_intro"] != "ok" or s["maker_intro"] != "ok" or s["maker_colloquial"] != "ok"]
lines.append("")
lines.append(f"## 待补清单（{len(todo)} 个）— 需前缀介绍 + 厂牌介绍/俗称")
lines.append("")
for s in sorted(todo, key=lambda x: (-x["count"], x["prefix"])):
    flags = []
    if s["prefix_intro"] != "ok":
        flags.append(f"前缀介绍={s['prefix_intro']}")
    if s["maker_intro"] != "ok":
        flags.append(f"厂牌介绍={s['maker_intro']}")
    if s["maker_colloquial"] != "ok":
        flags.append(f"俗称={s['maker_colloquial']}")
    lines.append(f"- {s['prefix']} ×{s['count']} → {s['maker']}  [{', '.join(flags)}]")

md_path = ROOT / "apps" / "api" / "scripts" / "_scrap_prefix_intro_todo.md"
md_path.write_text("\n".join(lines), encoding="utf-8")
print("wrote", md_path)

# print first 80 of todo for chat
print("---TODO_HEAD---")
for s in sorted(todo, key=lambda x: (-x["count"], x["prefix"]))[:80]:
    print(f"{s['prefix']}\t{s['count']}\t{s['maker']}\tp={s['prefix_intro']}\tm={s['maker_intro']}\tc={s['maker_colloquial']}")
print("---TODO_TAIL_COUNT---", max(0, len(todo)-80))
