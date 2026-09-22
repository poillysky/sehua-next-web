# -*- coding: utf-8 -*-
"""List prefixes needing intros: none first, then vague/generic."""
from __future__ import annotations
import re, sys, importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core import maps_paths
for fn in ("prefixes_doc", "prefix_intro_map", "makers_doc", "maker_intro_map", "maker_i18n_map"):
    f = getattr(maps_paths, fn, None)
    if hasattr(f, "cache_clear"):
        f.cache_clear()
import app.prefix.maker_names as mn
importlib.reload(mn)

from app.core.region_meta import REGION_ORDER, REGION_META
from app.prefix import catalog_store as store

doc = store.load_catalog(force=True)

def code_count(e: dict) -> int:
    for k in ("code_count", "codes", "count"):
        v = e.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, list):
            return len(v)
    return 0

# Vague patterns
VAGUE = re.compile(
    r"^("
    r"SOD 旁支|"
    r"旁支|"
    r"现行主线。?|"
    r"上一代。?|"
    r"更早。?|"
    r"精选。?|"
    r"VR。?|"
    r"主线。?|"
    r"企划。?|"
    r".{0,6}主线。?|"
    r"华语片商。?|"
    r"日期番号。?|"
    r"Tushy。?|"
    r".*旁支$|"
    r".*旁支。$"
    r")$"
)
# also short generic
def is_vague(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if len(t) <= 10:
        return True
    if VAGUE.match(t):
        return True
    # only "XXX 旁支" style
    if re.fullmatch(r".{2,20}旁支(企画)?。?", t):
        return True
    if re.fullmatch(r"SOD 旁支.*", t):
        return True
    # maker name only + 。
    if re.fullmatch(r"[\w\u3040-\u30ff\u4e00-\u9fff\s\*☆･・\-]+。", t) and len(t) <= 16:
        return True
    return False

none = []  # no prefix-specific AND weak/no resolved
no_specific = []  # no PREFIX_INTRO but has maker fallback
vague_specific = []  # has PREFIX_INTRO but vague

for rid in REGION_ORDER:
    for pref, e in sorted((doc["regions"][rid].get("prefixes") or {}).items()):
        maker = str((e or {}).get("maker") or "").strip()
        n = code_count(e or {})
        specific = (mn.PREFIX_INTRO.get(pref) or "").strip()
        resolved = (mn.resolve_maker_intro_for_prefix(pref) or "").strip()

        row = (n, pref, rid, maker, specific, resolved)

        if not specific:
            if not resolved:
                none.append(row)
            else:
                no_specific.append(row)
        elif is_vague(specific):
            vague_specific.append(row)

none.sort(key=lambda x: -x[0])
no_specific.sort(key=lambda x: -x[0])
vague_specific.sort(key=lambda x: -x[0])

print(f"catalog prefixes: sum check")
total = sum(len(doc['regions'][r].get('prefixes') or {}) for r in REGION_ORDER)
print(f"total={total}  no_specific+no_resolve={len(none)}  no_specific_has_maker_fb={len(no_specific)}  vague_specific={len(vague_specific)}")
print(f"PREFIX_INTRO size={len(mn.PREFIX_INTRO)}")

print("\n=== 1) 无前缀专属介绍 且 无可用回退（最优先）===")
for i, (n, pref, rid, maker, sp, rs) in enumerate(none[:60], 1):
    print(f"{i:2d}. {pref}  [{REGION_META[rid]['label']}] maker={maker[:40]}  n≈{n}")
if len(none) > 60:
    print(f"… 另有 {len(none)-60} 条")

print("\n=== 2) 介绍笼统/过短（已有专属但需加长）优先 40 ===")
for i, (n, pref, rid, maker, sp, rs) in enumerate(vague_specific[:40], 1):
    print(f"{i:2d}. {pref}  | 现:{sp!r} | {maker[:36]}")
if len(vague_specific) > 40:
    print(f"… 另有 {len(vague_specific)-40} 条")

print("\n=== 3) 无专属但有厂牌回退（可稍后补专属）按量前 30 ===")
for i, (n, pref, rid, maker, sp, rs) in enumerate(no_specific[:30], 1):
    print(f"{i:2d}. {pref}  n≈{n} | fb:{rs[:40]} | {maker[:30]}")
if len(no_specific) > 30:
    print(f"… 另有 {len(no_specific)-30} 条")

# write full lists to debug
out = ROOT / "data/debug/prefix-intros-todo.tsv"
lines = ["priority\tprefix\tregion\tmaker\tn\tcurrent_intro\n"]
for row in none:
    n, pref, rid, maker, sp, rs = row
    lines.append(f"1_none\t{pref}\t{rid}\t{maker}\t{n}\t\n")
for row in vague_specific:
    n, pref, rid, maker, sp, rs = row
    lines.append(f"2_vague\t{pref}\t{rid}\t{maker}\t{n}\t{sp}\n")
for row in no_specific:
    n, pref, rid, maker, sp, rs = row
    lines.append(f"3_fallback\t{pref}\t{rid}\t{maker}\t{n}\t{rs}\n")
out.write_text("".join(lines), encoding="utf-8")
print(f"\nwrote {out}")
