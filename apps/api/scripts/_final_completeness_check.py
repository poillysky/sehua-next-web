# -*- coding: utf-8 -*-
"""Final completeness check for makers + prefixes."""
from __future__ import annotations
import json, re, sys, unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.core.region_meta import REGION_META, REGION_ORDER
from app.prefix import catalog_store as store

HAN = re.compile(r"[\u4e00-\u9fff]")
SEP = re.compile(r"[\s\-_.·・/／\\]+")
WEAK = re.compile(r"公开资料有限|简介待核实|由前缀目录同步补全")

mdoc = json.loads((ROOT / "apps/maps/makers/makers.json").read_text(encoding="utf-8"))
makers = mdoc.get("makers") or {}
aliases = {str(k): str(v) for k, v in (mdoc.get("aliases") or {}).items()}

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").strip().casefold()
    return SEP.sub("", s)

lookup = {}
for k in makers:
    lookup[norm(k)] = k
for a, c in aliases.items():
    if c in makers:
        lookup[norm(a)] = c
        lookup[norm(c)] = c
for k, ent in makers.items():
    if not isinstance(ent, dict):
        continue
    for x in [ent.get("card")] + list(ent.get("i18n") or []):
        xs = str(x or "").strip()
        if not xs:
            continue
        lookup.setdefault(norm(xs), k)
        for part in re.split(r"\s*/\s*", xs):
            if part.strip():
                lookup.setdefault(norm(part), k)

def tokens(name: str):
    s = (name or "").strip()
    parts = [s] + [p.strip() for p in re.split(r"\s*/\s*", s) if p.strip()]
    seen, res = set(), []
    for x in parts:
        if x and x not in seen:
            seen.add(x)
            res.append(x)
    return res

def resolve(name: str) -> str:
    # prefer full string first
    hit = lookup.get(norm(name))
    if hit:
        return hit
    for t in tokens(name)[1:]:
        hit = lookup.get(norm(t))
        if hit:
            return hit
    return ""

doc = store.load_catalog(force=True)
seed = store.load_seed()

no_maker = []
orphan = []
by_region = {}
total = 0
for rid in REGION_ORDER:
    prefs = doc["regions"][rid].get("prefixes") or {}
    miss = 0
    for p, e in prefs.items():
        total += 1
        m = str((e or {}).get("maker") or "").strip()
        if not m:
            no_maker.append(f"{rid}/{p}")
            miss += 1
            continue
        if not resolve(m):
            orphan.append((m, f"{rid}/{p}"))
    by_region[rid] = (len(prefs), miss)

# makers meta completeness for USED makers only
used = set()
for rid in REGION_ORDER:
    for e in (doc["regions"][rid].get("prefixes") or {}).values():
        m = str((e or {}).get("maker") or "").strip()
        k = resolve(m)
        if k:
            used.add(k)

no_intro = []
no_card = []
weak_intro = []
for k in sorted(used):
    ent = makers.get(k) or {}
    card = str(ent.get("card") or "").strip()
    intro = str(ent.get("intro") or "").strip()
    if not card:
        no_card.append(k)
    if not intro:
        no_intro.append(k)
    elif WEAK.search(intro):
        weak_intro.append(k)

# seed maker mismatch vs catalog
seed_mismatch = 0
for rid in REGION_ORDER:
    cp = doc["regions"][rid].get("prefixes") or {}
    sp = (seed.get("regions") or {}).get(rid, {}).get("prefixes") or {}
    for p in set(cp) & set(sp):
        cm = str((cp[p] or {}).get("maker") or "").strip()
        sm = str((sp[p] or {}).get("maker") or "").strip()
        if cm and sm and norm(cm) != norm(sm):
            seed_mismatch += 1

broken_alias = sum(1 for a, t in aliases.items() if t not in makers)

print("PREFIX CATALOG")
print(f"  total={total} no_maker={len(no_maker)} orphan_maker={len(orphan)}")
for rid, (n, miss) in by_region.items():
    print(f"  {REGION_META[rid]['label']}: {n} (no_maker={miss})")
print("MAKERS.JSON")
print(f"  entries={len(makers)} aliases={len(aliases)} broken_alias={broken_alias}")
print(f"  used_by_prefixes={len(used)}")
print(f"  used missing card={len(no_card)} missing intro={len(no_intro)} weak_intro={len(weak_intro)}")
if no_intro[:10]:
    print("  no_intro sample:", no_intro[:10])
if orphan[:10]:
    print("  orphan sample:", orphan[:10])
print("SEED")
print(f"  maker_mismatch_vs_catalog={seed_mismatch}")
ok = (len(no_maker) == 0 and len(orphan) == 0 and len(no_intro) == 0 and broken_alias == 0 and seed_mismatch == 0)
print("VERDICT:", "COMPLETE" if ok else "MOSTLY_COMPLETE_WITH_GAPS")
