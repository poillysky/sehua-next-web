# -*- coding: utf-8 -*-
"""Audit makers.json coverage for catalog makers: colloquial name (card/i18n zh) + intro."""
from __future__ import annotations
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.core.region_meta import REGION_ORDER
from app.prefix import catalog_store as store

makers_doc = json.loads((ROOT / "apps/maps/makers/makers.json").read_text(encoding="utf-8"))
aliases = makers_doc.get("aliases") or {}
makers = makers_doc.get("makers") or {}

HAN = re.compile(r"[\u4e00-\u9fff]")


def resolve_key(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return ""
    if n in makers:
        return n
    # via aliases
    a = aliases.get(n) or aliases.get(n.casefold())
    if a and a in makers:
        return a
    # case-insensitive makers keys
    low = {k.casefold(): k for k in makers}
    if n.casefold() in low:
        return low[n.casefold()]
    # alias casefold map
    alow = {k.casefold(): v for k, v in aliases.items()}
    a2 = alow.get(n.casefold())
    if a2 and a2 in makers:
        return a2
    return ""


def has_colloquial(entry: dict) -> bool:
    """通俗名：card 含中文，或 i18n 任一段含中文。"""
    card = str(entry.get("card") or "").strip()
    if HAN.search(card):
        return True
    for x in entry.get("i18n") or []:
        if HAN.search(str(x or "")):
            return True
    return False


def has_intro(entry: dict) -> bool:
    intro = str(entry.get("intro") or "").strip()
    if not intro:
        return False
    # treat placeholder sync text as missing
    if "由前缀目录同步补全" in intro:
        return False
    return True


doc = store.load_catalog(force=True)
# unique makers from catalog with sample prefixes
from collections import defaultdict
by_maker: dict[str, list[tuple[str, str]]] = defaultdict(list)
for rid in REGION_ORDER:
    for p, e in (doc["regions"][rid].get("prefixes") or {}).items():
        m = str((e or {}).get("maker") or "").strip()
        if m:
            by_maker[m].append((rid, p))

missing_entry = []  # not in makers.json at all
missing_colloquial = []  # in makers but no 通俗中文名
missing_intro = []  # in makers but no intro
ok = []

for m, prefs in sorted(by_maker.items(), key=lambda x: (-len(x[1]), x[0])):
    key = resolve_key(m)
    sample = ",".join(p for _, p in prefs[:3])
    if not key:
        missing_entry.append((m, len(prefs), sample))
        continue
    ent = makers[key]
    col = has_colloquial(ent)
    intro = has_intro(ent)
    if not col and not intro:
        missing_colloquial.append((m, key, len(prefs), sample, "no_zh+no_intro"))
        missing_intro.append((m, key, len(prefs), sample))
    elif not col:
        missing_colloquial.append((m, key, len(prefs), sample, "no_zh"))
    elif not intro:
        missing_intro.append((m, key, len(prefs), sample))
    else:
        ok.append(m)

print(f"catalog unique makers: {len(by_maker)}")
print(f"ok (zh+intro): {len(ok)}")
print(f"not in makers.json: {len(missing_entry)}")
print(f"missing colloquial zh: {len(missing_colloquial)}")
print(f"missing intro: {len(missing_intro)}")

out = ROOT / "data/debug/makers-missing-meta.tsv"
lines = ["status\tmaker\tresolved_key\tprefix_count\tsample_prefixes\n"]
for m, n, sample in missing_entry:
    lines.append(f"NO_ENTRY\t{m}\t\t{n}\t{sample}\n")
for m, key, n, sample, why in missing_colloquial:
    if why.startswith("no_zh"):
        lines.append(f"NO_ZH\t{m}\t{key}\t{n}\t{sample}\n")
for m, key, n, sample in missing_intro:
    # avoid dup if already NO_ZH listed for same - still list INTRO
    lines.append(f"NO_INTRO\t{m}\t{key}\t{n}\t{sample}\n")
out.write_text("".join(lines), encoding="utf-8")
print(f"wrote {out}")

print("\n=== 第1组：完全不在 makers.json（优先问）前20 ===")
for i, (m, n, sample) in enumerate(missing_entry[:20], 1):
    print(f"{i:2d}. {m}  (前缀×{n}: {sample})")
print(f"… 共 {len(missing_entry)} 个不在表内")

print("\n=== 在表内但缺通俗中文名 前15 ===")
for i, (m, key, n, sample, why) in enumerate(missing_colloquial[:15], 1):
    print(f"{i:2d}. {m} -> {key}  ({why}, ×{n})")

print("\n=== 在表内但缺介绍 前15 ===")
# unique by key
seen = set()
shown = 0
for m, key, n, sample in missing_intro:
    if key in seen:
        continue
    seen.add(key)
    shown += 1
    if shown <= 15:
        print(f"{shown:2d}. {key}  (catalog名={m}, ×{n})")
print(f"… 缺介绍去重后约 {len(seen)} 个")
