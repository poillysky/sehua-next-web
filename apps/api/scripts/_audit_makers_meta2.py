# -*- coding: utf-8 -*-
"""Better match catalog makers → makers.json; list gaps for user."""
from __future__ import annotations
import json, re, sys, unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.core.region_meta import REGION_ORDER
from app.prefix import catalog_store as store

makers_doc = json.loads((ROOT / "apps/maps/makers/makers.json").read_text(encoding="utf-8"))
aliases = {str(k): str(v) for k, v in (makers_doc.get("aliases") or {}).items()}
makers = makers_doc.get("makers") or {}

HAN = re.compile(r"[\u4e00-\u9fff]")
SEP = re.compile(r"[\s\-_.·・/／\\]+")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").strip().casefold()
    s = SEP.sub("", s)
    return s


# build lookup: norm → maker key
lookup: dict[str, str] = {}
for k in makers:
    lookup[norm(k)] = k
for a, canon in aliases.items():
    if canon in makers:
        lookup[norm(a)] = canon
        lookup[norm(canon)] = canon
    elif canon:  # alias target may equal key
        if canon in makers:
            lookup[norm(a)] = canon
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
        # also split "A / B"
        for part in re.split(r"\s*/\s*", xs):
            if part.strip():
                lookup.setdefault(norm(part), k)


def tokens(name: str) -> list[str]:
    s = (name or "").strip()
    parts = [p.strip() for p in re.split(r"\s*/\s*", s) if p.strip()]
    out = [s] + parts
    # also drop parenthetical
    for p in list(out):
        out.append(re.sub(r"[（(].*?[）)]", "", p).strip())
    # unique preserve order
    seen = set()
    res = []
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


def has_zh(ent: dict) -> bool:
    card = str(ent.get("card") or "").strip()
    if HAN.search(card):
        return True
    for x in ent.get("i18n") or []:
        if HAN.search(str(x or "")):
            return True
    return False


def has_intro(ent: dict) -> bool:
    intro = str(ent.get("intro") or "").strip()
    return bool(intro) and "由前缀目录同步补全" not in intro


doc = store.load_catalog(force=True)
by_maker: dict[str, list[tuple[str, str]]] = defaultdict(list)
for rid in REGION_ORDER:
    for p, e in (doc["regions"][rid].get("prefixes") or {}).items():
        m = str((e or {}).get("maker") or "").strip()
        if m:
            by_maker[m].append((rid, p))

# Also extract zh already in catalog maker string
def catalog_zh(m: str) -> str:
    for t in tokens(m):
        if HAN.search(t) and not re.search(r"[\u3040-\u30ff]", t):
            return t
        # mixed like "MOODYZ / 慕迪斯"
        if HAN.search(t):
            # take han part
            return t
    return ""


matched = unmatched = 0
need_zh = []  # (catalog_maker, key, n, sample, have_catalog_zh)
need_intro = []
need_both_or_entry = []  # fully missing from makers.json
ok = 0

for m, prefs in sorted(by_maker.items(), key=lambda x: (-len(x[1]), x[0])):
    key = resolve(m)
    n = len(prefs)
    sample = ",".join(p for _, p in prefs[:3])
    czh = catalog_zh(m)
    if not key:
        unmatched += 1
        need_both_or_entry.append((m, n, sample, czh))
        continue
    matched += 1
    ent = makers[key]
    zh_ok = has_zh(ent) or bool(czh and HAN.search(czh))
    # For makers.json completeness, catalog zh doesn't count unless we write it in
    zh_in_table = has_zh(ent)
    intro_ok = has_intro(ent)
    if zh_in_table and intro_ok:
        ok += 1
        continue
    if not zh_in_table and not intro_ok:
        need_zh.append((m, key, n, sample, czh or ""))
        need_intro.append((m, key, n, sample))
    elif not zh_in_table:
        need_zh.append((m, key, n, sample, czh or ""))
    elif not intro_ok:
        need_intro.append((m, key, n, sample))

print(f"catalog unique makers: {len(by_maker)}")
print(f"matched makers.json: {matched}")
print(f"unmatched (no entry): {unmatched}")
print(f"complete in makers.json (zh+intro): {ok}")
print(f"matched but missing zh card/i18n: {len(need_zh)}")
print(f"matched but missing intro: {len(need_intro)}")

# Deduplicate by key for asking user
from collections import OrderedDict

ask_rows = OrderedDict()
# priority: unmatched first (need full), then missing zh, then missing intro
for m, n, sample, czh in need_both_or_entry:
    ask_rows[m] = {
        "status": "NEW",
        "key": "",
        "n": n,
        "sample": sample,
        "hint_zh": czh,
        "need_zh": True,
        "need_intro": True,
    }
for m, key, n, sample, czh in need_zh:
    if key in {v["key"] for v in ask_rows.values() if v["key"]}:
        # merge
        for v in ask_rows.values():
            if v["key"] == key:
                v["need_zh"] = True
                if czh and not v["hint_zh"]:
                    v["hint_zh"] = czh
                break
        continue
    ask_rows[f"zh:{key}"] = {
        "status": "NEED_ZH",
        "key": key,
        "n": n,
        "sample": sample,
        "hint_zh": czh,
        "need_zh": True,
        "need_intro": False,
        "catalog": m,
    }
for m, key, n, sample in need_intro:
    # find existing
    found = None
    for k, v in ask_rows.items():
        if v.get("key") == key:
            found = v
            break
    if found:
        found["need_intro"] = True
        continue
    ask_rows[f"intro:{key}"] = {
        "status": "NEED_INTRO",
        "key": key,
        "n": n,
        "sample": sample,
        "hint_zh": "",
        "need_zh": False,
        "need_intro": True,
        "catalog": m,
    }

items = list(ask_rows.values())
# sort by prefix count desc
items.sort(key=lambda x: -x["n"])

out = ROOT / "data/debug/makers-ask-meta.tsv"
lines = ["status\tmaker_or_key\tcatalog\tprefix_count\tsample\thint_zh\tneed_zh\tneed_intro\n"]
for it in items:
    label = it.get("key") or it.get("catalog") or ""
    if it["status"] == "NEW":
        # find catalog name from need_both
        label = next(m for m, n, s, c in need_both_or_entry if n == it["n"] and s == it["sample"])
    lines.append(
        f"{it['status']}\t{it.get('key') or label}\t{it.get('catalog') or label}\t{it['n']}\t{it['sample']}\t{it.get('hint_zh') or ''}\t{int(it['need_zh'])}\t{int(it['need_intro'])}\n"
    )
out.write_text("".join(lines), encoding="utf-8")
print(f"ask items: {len(items)} -> {out}")

print("\n=== 需你补充 · 第1组（20）格式：通俗中文名 | 一句话介绍 ===")
for i, it in enumerate(items[:20], 1):
    if it["status"] == "NEW":
        name = next(m for m, n, s, c in need_both_or_entry if n == it["n"] and s == it["sample"])
        hint = f"  hint中文={it['hint_zh']}" if it.get("hint_zh") else ""
        print(f"{i:2d}. [新建] {name}  (前缀×{it['n']}: {it['sample']}){hint}")
    elif it["need_zh"] and it["need_intro"]:
        print(f"{i:2d}. [补中文+介绍] {it['key']}  (catalog={it.get('catalog')}, ×{it['n']})")
    elif it["need_zh"]:
        hint = f"  hint={it['hint_zh']}" if it.get("hint_zh") else ""
        print(f"{i:2d}. [补中文] {it['key']}  (×{it['n']}){hint}")
    else:
        print(f"{i:2d}. [补介绍] {it['key']}  (×{it['n']})")
print(f"… 另有 {max(0, len(items)-20)} 条")
