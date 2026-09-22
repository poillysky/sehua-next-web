# -*- coding: utf-8 -*-
"""List next 30 makers needing zh/intro (English card+intro = ok)."""
from __future__ import annotations
import json, re, sys, unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.core.region_meta import REGION_ORDER
from app.prefix import catalog_store as store

PATH = ROOT / "apps/maps/makers/makers.json"
makers_doc = json.loads(PATH.read_text(encoding="utf-8"))
aliases = {str(k): str(v) for k, v in (makers_doc.get("aliases") or {}).items()}
makers = makers_doc.get("makers") or {}
HAN = re.compile(r"[\u4e00-\u9fff]")
LATIN = re.compile(r"[A-Za-z]")
SEP = re.compile(r"[\s\-_.·・/／\\]+")


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


def has_zh(ent: dict) -> bool:
    if HAN.search(str(ent.get("card") or "")):
        return True
    for x in ent.get("i18n") or []:
        if HAN.search(str(x or "")):
            return True
    return False


def has_colloquial(ent: dict) -> bool:
    """中文通俗名，或明确英文/品牌 card（DOC、S-Cute 等）。"""
    if has_zh(ent):
        return True
    card = str(ent.get("card") or "").strip()
    return bool(card and LATIN.search(card))


def has_intro(ent: dict) -> bool:
    intro = str(ent.get("intro") or "").strip()
    return bool(intro) and "由前缀目录同步补全" not in intro


def catalog_zh(m: str) -> str:
    for t in tokens(m):
        if HAN.search(t):
            return t
    return ""


cat = store.load_catalog(force=True)
by_maker: dict[str, list[tuple[str, str]]] = defaultdict(list)
for rid in REGION_ORDER:
    for p, e in (cat["regions"][rid].get("prefixes") or {}).items():
        m = str((e or {}).get("maker") or "").strip()
        if m:
            by_maker[m].append((rid, p))

items = []
for m, prefs in by_maker.items():
    key = resolve(m)
    n = len(prefs)
    sample = ",".join(p for _, p in prefs[:3])
    czh = catalog_zh(m)
    if not key:
        items.append({"status": "NEW", "name": m, "key": "", "n": n, "sample": sample, "hint_zh": czh, "need_zh": True, "need_intro": True})
        continue
    ent = makers[key]
    col_ok = has_colloquial(ent)
    intro_ok = has_intro(ent)
    if col_ok and intro_ok:
        continue
    items.append({
        "status": "PATCH",
        "name": m,
        "key": key,
        "n": n,
        "sample": sample,
        "hint_zh": czh,
        "need_zh": not col_ok or (not has_zh(ent) and not LATIN.search(str(ent.get("card") or ""))),
        # Prefer asking for Chinese when only kana/ja card
        "need_zh": not has_zh(ent),
        "need_intro": not intro_ok,
        "soft_zh": has_colloquial(ent) and not has_zh(ent),  # has EN card, zh optional
    })

# For soft_zh (EN card + intro): skip unless missing intro
filtered = []
for it in items:
    if it["status"] == "PATCH" and it.get("soft_zh") and not it["need_intro"]:
        continue  # English brand colloquial accepted
    # if soft_zh and need intro only, keep as 补介绍
    if it.get("soft_zh") and it["need_intro"]:
        it["need_zh"] = False
    filtered.append(it)

seen = set()
uniq = []
for it in sorted(filtered, key=lambda x: -x["n"]):
    k = it["key"] or it["name"]
    if k in seen:
        continue
    seen.add(k)
    uniq.append(it)

print(f"still need: {len(uniq)}")
print("=== 第2组（30）通俗中文名 | 一句话介绍 ===")
for i, it in enumerate(uniq[:30], 1):
    tags = []
    if it["status"] == "NEW":
        tags.append("新建")
    else:
        if it["need_zh"]:
            tags.append("补中文")
        if it["need_intro"]:
            tags.append("补介绍")
    hint = f"  hint={it['hint_zh']}" if it.get("hint_zh") else ""
    label = it["key"] or it["name"]
    print(f"{i:2d}. [{'·'.join(tags) or '补'}] {label}  (×{it['n']}: {it['sample']}){hint}")
print(f"… 另有 {max(0, len(uniq)-30)} 条")
