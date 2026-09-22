# -*- coding: utf-8 -*-
"""Self-audit: catalog prefixes ↔ makers.json consistency & suspects."""
from __future__ import annotations
import json, re, sys, unicodedata
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.core.region_meta import REGION_META, REGION_ORDER
from app.prefix import catalog_store as store

HAN = re.compile(r"[\u4e00-\u9fff]")
SEP = re.compile(r"[\s\-_.·・/／\\]+")

mdoc = json.loads((ROOT / "apps/maps/makers/makers.json").read_text(encoding="utf-8"))
makers = mdoc.get("makers") or {}
aliases = {str(k): str(v) for k, v in (mdoc.get("aliases") or {}).items()}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").strip().casefold()
    return SEP.sub("", s)


lookup: dict[str, str] = {}
for k in makers:
    lookup[norm(k)] = k
for a, canon in aliases.items():
    if canon in makers:
        lookup[norm(a)] = canon
        lookup[norm(canon)] = canon
for k, ent in makers.items():
    if not isinstance(ent, dict):
        continue
    card = str(ent.get("card") or "").strip()
    if card:
        lookup.setdefault(norm(card), k)
    for x in ent.get("i18n") or []:
        xs = str(x or "").strip()
        if not xs:
            continue
        lookup.setdefault(norm(xs), k)
        for part in re.split(r"\s*/\s*", xs):
            if part.strip():
                lookup.setdefault(norm(part), k)


def tokens(name: str) -> list[str]:
    s = (name or "").strip()
    parts = [p.strip() for p in re.split(r"\s*/\s*", s) if p.strip()]
    out = [s] + parts
    for p in list(out):
        out.append(re.sub(r"[（(].*?[）)]", "", p).strip())
    seen, res = set(), []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            res.append(x)
    return res


def resolve(name: str) -> str:
    for t in tokens(name):
        hit = lookup.get(norm(t))
        if hit:
            return hit
    return ""


doc = store.load_catalog(force=True)

# 1) prefixes missing maker
no_maker = []
# 2) maker not in makers.json
orphan = defaultdict(list)
# 3) by resolved maker -> prefixes
by_resolved: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
# 4) duplicate prefix across regions
prefix_regions: dict[str, list[str]] = defaultdict(list)
# 5) maker field variants that resolve to same key
variant_groups: dict[str, set[str]] = defaultdict(set)

total_prefs = 0
for rid in REGION_ORDER:
    for p, e in (doc["regions"][rid].get("prefixes") or {}).items():
        total_prefs += 1
        prefix_regions[p].append(rid)
        m = str((e or {}).get("maker") or "").strip()
        if not m:
            no_maker.append((rid, p))
            continue
        key = resolve(m)
        if not key:
            orphan[m].append((rid, p))
        else:
            by_resolved[key].append((rid, p, m))
            variant_groups[key].add(m)

# makers with 0 prefixes
unused_makers = sorted(k for k in makers if k not in by_resolved and k not in (
    "その他有码", "其它写真", "其它国产", "其它无码", "其它欧美", "Doujin AV"
))

# aliases pointing to missing makers
broken_alias = [(a, t) for a, t in aliases.items() if t not in makers]

# multi-region same prefix
multi_region = {p: rids for p, rids in prefix_regions.items() if len(set(rids)) > 1}

# Suspect: known confusing patterns
suspects = []

# A) "Other *" buckets with many prefs - OK but report counts
otherish = {k: v for k, v in orphan.items() if "other" in k.casefold() or "其他" in k or "其它" in k}

# B) catalog maker string looks like prefix itself only
for m, prefs in orphan.items():
    if re.fullmatch(r"[A-Z0-9\-]+", m.replace(" ", "")):
        suspects.append(("orphan_looks_like_code", m, prefs))

# C) same prefix letters as maker (weak)
# D) Digital Ark vs FLAV already fixed - check BAGR
for rid, p, m in by_resolved.get("BALTAN", []):
    if p != "BAGR" and "BALTAN" not in m.upper() and "バルタン" not in m:
        pass

# E) known wrong historical aliases in makers.json
KNOWN_SUSPECT_ALIASES = {
    "FIRST STAR": "SOD Create",  # often wrong
    "First Star": "SOD Create",
    "Plum": "SWITCH",
    "Glanz": "REbecca",
    "Radix": "S1 NO.1 STYLE",
    "邪恶帝国": "S1 NO.1 STYLE",
    "魔笛": "MOODYZ",
}
alias_suspects = []
for a, expected_wrong in KNOWN_SUSPECT_ALIASES.items():
    t = aliases.get(a)
    if t == expected_wrong:
        alias_suspects.append((a, t, "历史别名可能不准"))

# F) Center Village duplicate keys
dup_center = [k for k in makers if "center" in k.casefold() or "センター" in k or "中心" in k]

# G) JET / JET映像
jet_keys = [k for k in makers if "JET" in k.upper() or "ジェット" in k]

# H) variants too many for one maker
heavy_variants = {k: sorted(vs) for k, vs in variant_groups.items() if len(vs) >= 4}

# I) seed vs catalog maker mismatch sample
seed = store.load_seed()
mismatch = []
for rid in REGION_ORDER:
    cp = doc["regions"][rid].get("prefixes") or {}
    sp = (seed.get("regions") or {}).get(rid, {}).get("prefixes") or {}
    for p in sorted(set(cp) & set(sp)):
        cm = str((cp[p] or {}).get("maker") or "").strip()
        sm = str((sp[p] or {}).get("maker") or "").strip()
        if cm and sm and norm(cm) != norm(sm) and resolve(cm) != resolve(sm):
            mismatch.append((rid, p, cm, sm))

print("=" * 60)
print(f"catalog prefixes: {total_prefs}")
print(f"makers.json entries: {len(makers)}")
print(f"aliases: {len(aliases)}")
print(f"no_maker prefixes: {len(no_maker)}")
print(f"orphan makers (no makers.json): {len(orphan)} groups / {sum(len(v) for v in orphan.values())} prefs")
print(f"unused makers (0 prefixes): {len(unused_makers)}")
print(f"broken aliases: {len(broken_alias)}")
print(f"multi-region prefixes: {len(multi_region)}")
print(f"seed↔catalog maker mismatch: {len(mismatch)}")

print("\n=== 1) 无片商前缀 ===")
for rid, p in no_maker[:20]:
    print(f"  {REGION_META[rid]['label']} {p}")
print(f"  total {len(no_maker)}")

print("\n=== 2) catalog 厂牌不在 makers.json（按前缀数）===")
for m, prefs in sorted(orphan.items(), key=lambda x: -len(x[1]))[:35]:
    sample = ",".join(p for _, p in prefs[:4])
    print(f"  ×{len(prefs):2d}  {m}  [{sample}]")
if len(orphan) > 35:
    print(f"  ... +{len(orphan)-35} groups")

print("\n=== 3) 可疑别名 ===")
for a, t, why in alias_suspects:
    print(f"  {a!r} -> {t!r}  ({why})")

print("\n=== 4) 断别名（指向已删厂牌）===")
for a, t in broken_alias[:30]:
    print(f"  {a!r} -> {t!r}")
print(f"  total {len(broken_alias)}")

print("\n=== 5) 跨区同前缀 ===")
for p, rids in sorted(multi_region.items())[:20]:
    print(f"  {p}: {rids}")
print(f"  total {len(multi_region)}")

print("\n=== 6) seed 与 catalog 厂牌不一致（前20）===")
for rid, p, cm, sm in mismatch[:20]:
    print(f"  {rid}/{p}: catalog={cm!r} seed={sm!r}")

print("\n=== 7) 同一厂牌多种 catalog 写法（≥4）===")
for k, vs in sorted(heavy_variants.items(), key=lambda x: -len(x[1]))[:15]:
    print(f"  [{k}] {len(vs)} variants:")
    for v in vs[:8]:
        print(f"      - {v}")

print("\n=== 8) 未使用厂牌（无前缀，前30）===")
for k in unused_makers[:30]:
    card = (makers[k] or {}).get("card") if isinstance(makers[k], dict) else ""
    print(f"  {k}  card={card}")
print(f"  total {len(unused_makers)}")

# Specific known checks
print("\n=== 9) 定点抽查 ===")
checks = {
    "BAGR": "BALTAN",
    "FLAV": "Digital Ark",
    "DDT": None,  # Dogma
    "SONE": None,  # S1
    "IPZZ": None,  # IP
    "SSIS": None,
    "MIDA": None,
}
prefs_all = {}
for rid in REGION_ORDER:
    prefs_all.update(doc["regions"][rid].get("prefixes") or {})
for p, expect in checks.items():
    e = prefs_all.get(p)
    if not e:
        # search all regions properly
        found = None
        for rid in REGION_ORDER:
            if p in (doc["regions"][rid].get("prefixes") or {}):
                found = doc["regions"][rid]["prefixes"][p]
                break
        e = found
    m = str((e or {}).get("maker") or "")
    key = resolve(m)
    status = "OK" if e else "MISSING"
    if expect and key and expect.casefold() not in key.casefold() and expect.casefold() not in m.casefold():
        # soft check
        if resolve(expect) != key:
            status = f"EXPECT~{expect} got {key}"
    print(f"  {p}: maker={m!r} resolved={key!r} [{status}]")

# write report
out = ROOT / "data/debug/makers-prefix-audit.tsv"
lines = ["kind\tdetail\tn\tsample\n"]
for m, prefs in sorted(orphan.items(), key=lambda x: -len(x[1])):
    lines.append(f"orphan\t{m}\t{len(prefs)}\t{','.join(p for _,p in prefs[:5])}\n")
for a, t in broken_alias:
    lines.append(f"broken_alias\t{a}->{t}\t1\t\n")
for rid, p in no_maker:
    lines.append(f"no_maker\t{rid}/{p}\t1\t\n")
out.write_text("".join(lines), encoding="utf-8")
print(f"\nwrote {out}")
