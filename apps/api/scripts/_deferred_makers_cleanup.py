# -*- coding: utf-8 -*-
"""Deferred cleanup: merge duplicate maker keys; MDL/MKY china warn notes."""
from __future__ import annotations
import json, sys, re, unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.core.region_meta import REGION_ORDER
from app.prefix import catalog_store as store

MPATH = ROOT / "apps/maps/makers/makers.json"
mdoc = json.loads(MPATH.read_text(encoding="utf-8"))
makers: dict = mdoc.setdefault("makers", {})
aliases: dict = mdoc.setdefault("aliases", {})

SEP = re.compile(r"[\s\-_.·・/／\\]+")

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").strip().casefold()
    return SEP.sub("", s)

# Which makers are actually used by catalog?
doc = store.load_catalog(force=True)

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

lookup: dict[str, str] = {}
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

def resolve(name: str) -> str:
    for t in tokens(name):
        hit = lookup.get(norm(t))
        if hit:
            return hit
    return ""

used_keys: set[str] = set()
for rid in REGION_ORDER:
    for e in (doc["regions"][rid].get("prefixes") or {}).values():
        m = str((e or {}).get("maker") or "").strip()
        if not m:
            continue
        k = resolve(m)
        if k:
            used_keys.add(k)

# Known bilingual duplicate pairs: keep English/primary, drop JP twin if unused
# Format: (keep_key, drop_key_candidates)
MERGE_PAIRS = [
    ("Center Village", ["センタービレッジ"]),
    ("Sadistic Village", ["サディスティックヴィレッジ"]),
    ("Aurora Project", ["オーロラプロジェクト"]),
    ("Cinemagic", ["シネマジック"]),
    ("Celeb no Tomo", ["セレブの友"]),
    ("Dream Ticket", ["ドリームチケット"]),
    ("Natural High", ["ナチュラルハイ", "Nagae STYLE"]),  # careful Nagae is different!
    ("Natural High", ["ナチュラルハイ"]),
    ("Cosmos", ["コスモス映像"]),  # catalog uses Cosmos Eizou - may need alias
    ("Takara", ["タカラ映像"]),
    ("Premium", ["プレミアム"]),
    ("AVS collector's", ["AVS collector"]),
    ("NEXTGROUP", ["Next Group"]),
    ("Nadeshiko", ["なでしこ"]),
    ("Nagae STYLE", ["ながえSTYLE"]),
]

# Fix botched Natural High line - only ナチュラルハイ
MERGE_PAIRS = [p for p in MERGE_PAIRS if not (p[0] == "Natural High" and "Nagae" in str(p[1]))]
MERGE_PAIRS.append(("Natural High", ["ナチュラルハイ"]))

merged = []
for keep, drops in MERGE_PAIRS:
    # resolve keep
    keep_key = keep if keep in makers else aliases.get(keep)
    if not keep_key or keep_key not in makers:
        # try find
        keep_key = lookup.get(norm(keep))
    if not keep_key or keep_key not in makers:
        print(f"SKIP merge keep missing: {keep}")
        continue
    for drop in drops:
        drop_key = drop if drop in makers else None
        if not drop_key:
            continue
        if drop_key == keep_key:
            continue
        # Prefer dropping the unused twin; if both used, only alias don't delete
        if drop_key in used_keys and keep_key in used_keys:
            aliases[drop] = keep_key
            aliases[drop_key] = keep_key
            print(f"BOTH USED keep both, alias {drop_key} -> {keep_key}")
            continue
        if drop_key in used_keys and keep_key not in used_keys:
            # swap: keep the used one
            print(f"SWAP keep {drop_key} (used), drop {keep_key}")
            keep_key, drop_key = drop_key, keep_key
        # merge intro/i18n into keep if richer
        ke = makers[keep_key]
        de = makers.get(drop_key) or {}
        if isinstance(ke, dict) and isinstance(de, dict):
            if not str(ke.get("intro") or "").strip() and str(de.get("intro") or "").strip():
                ke["intro"] = de["intro"]
            # ensure aliases
        makers.pop(drop_key, None)
        aliases[drop] = keep_key
        aliases[drop_key] = keep_key
        # redirect aliases pointing to drop
        for a, t in list(aliases.items()):
            if t == drop_key:
                aliases[a] = keep_key
        merged.append((drop_key, keep_key))
        print(f"MERGE {drop_key} -> {keep_key}")

# Also: if Cosmos unused but Cosmos Eizou used as catalog string resolving elsewhere
# Ensure HAWA resolves: add alias Cosmos Eizou -> Cosmos if Cosmos exists
if "Cosmos" in makers:
    aliases["Cosmos Eizou"] = "Cosmos"
    aliases["コスモス映像"] = "Cosmos"
    aliases["Cosmos Eizou / コスモス映像"] = "Cosmos"

# Crystal / クリスタル映像
if "Crystal" in makers and "クリスタル映像" in makers:
    if "クリスタル映像" not in used_keys:
        makers.pop("クリスタル映像", None)
        aliases["クリスタル映像"] = "Crystal"
        aliases["Crystal Eizou"] = "Crystal"
        print("MERGE クリスタル映像 -> Crystal")
    else:
        aliases["Crystal"] = "クリスタル映像" if "クリスタル映像" in used_keys else aliases.get("Crystal", "Crystal")

MPATH.write_text(json.dumps(mdoc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"makers after merge: {len(makers)}")

# ---- MDL / MKY china warning notes ----
WARN = "【注意】与日本 MOODYZ 前缀撞车，请按 region 区分"
china = doc["regions"]["china"]["prefixes"]
for pref in ("MDL", "MKY"):
    ent = china.get(pref)
    if not isinstance(ent, dict):
        print(f"MISS china/{pref}")
        continue
    ent = dict(ent)
    notes = str(ent.get("notes") or "").strip()
    if WARN not in notes:
        ent["notes"] = f"{notes} · {WARN}".strip(" ·") if notes else WARN
    pe = store._normalize_prefix_entry(pref, ent)
    china[pe["prefix"]] = pe
    print(f"WARN china/{pref}: {pe.get('notes')}")

# also japan side brief note?
jc = doc["regions"]["japan_censored"]["prefixes"]
WARN_JP = "【注意】与国产同名号前缀撞车，请按 region 区分"
for pref in ("MDL", "MKY"):
    ent = jc.get(pref)
    if not isinstance(ent, dict):
        continue
    ent = dict(ent)
    notes = str(ent.get("notes") or "").strip()
    if "撞" not in notes:
        ent["notes"] = f"{notes} · {WARN_JP}".strip(" ·") if notes else WARN_JP
        pe = store._normalize_prefix_entry(pref, ent)
        jc[pe["prefix"]] = pe
        print(f"WARN japan_censored/{pref}")

store.save_catalog(doc)

# seed sync notes for china MDL/MKY
seed = store.load_seed()
for rid, warn in (("china", WARN), ("japan_censored", WARN_JP)):
    sp = (seed.get("regions") or {}).get(rid, {}).get("prefixes") or {}
    for pref in ("MDL", "MKY"):
        if pref not in sp:
            continue
        ent = dict(sp[pref])
        notes = str(ent.get("notes") or "").strip()
        if "撞" not in notes:
            ent["notes"] = f"{notes} · {warn}".strip(" ·") if notes else warn
            sp[pref] = store._normalize_prefix_entry(pref, ent)
            print(f"SEED WARN {rid}/{pref}")
store.SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# report remaining unused
# rebuild resolve
makers = mdoc["makers"]
aliases = mdoc["aliases"]
lookup = {}
for k in makers:
    lookup[norm(k)] = k
for a, c in aliases.items():
    if c in makers:
        lookup[norm(a)] = c
used2 = set()
for rid in REGION_ORDER:
    for e in (doc["regions"][rid].get("prefixes") or {}).values():
        m = str((e or {}).get("maker") or "").strip()
        if not m:
            continue
        for t in tokens(m):
            hit = lookup.get(norm(t))
            if hit:
                used2.add(hit)
                break
unused = sorted(k for k in makers if k not in used2)
print(f"\nunused makers remaining: {len(unused)}")
for k in unused:
    print(f"  {k}")
