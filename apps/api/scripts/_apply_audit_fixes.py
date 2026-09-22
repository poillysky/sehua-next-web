# -*- coding: utf-8 -*-
"""Apply audit fixes: mousouzoku labels, aliases cleanup, seed sync."""
from __future__ import annotations
import json, sys, unicodedata, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.core.region_meta import REGION_ORDER
from app.prefix import catalog_store as store

MPATH = ROOT / "apps/maps/makers/makers.json"
mdoc = json.loads(MPATH.read_text(encoding="utf-8"))
makers: dict = mdoc.setdefault("makers", {})
aliases: dict = mdoc.setdefault("aliases", {})

# ---- 1) New 妄想族 sub-labels ----
NEW_MAKERS = [
    ("犬/妄想族", "犬/妄想族",
     ["犬/妄想族", "犬/妄想族", "Inu / Mousouzoku"],
     "妄想族旗下子レーベル，风格独立，不宜笼统归为「妄想族」。",
     ["犬", "DNJR"]),
    ("SEX Agent/妄想族", "SEX Agent/妄想族",
     ["SEX Agent/妄想族", "セックスエージェント/妄想族", "SEX Agent"],
     "妄想族旗下子レーベル，独立企划风格。",
     ["SEX Agent", "AGAV"]),
    ("ブロッコリー/妄想族", "ブロッコリー/妄想族",
     ["ブロッコリー/妄想族", "ブロッコリー/妄想族", "Broccoli"],
     "妄想族旗下子レーベル，独立企划风格。",
     ["ブロッコリー", "BLOR"]),
    ("姦乱者/妄想族", "姦乱者/妄想族",
     ["姦乱者/妄想族", "姦乱者/妄想族", "Kanransha"],
     "妄想族旗下子レーベル，独立企划风格。",
     ["姦乱者", "SUJI"]),
]

for key, card, i18n, intro, extra in NEW_MAKERS:
    makers[key] = {"card": card, "i18n": i18n, "intro": intro}
    aliases[key] = key
    for a in extra:
        aliases[a] = key
    print(f"NEW {key}")

# Kaguya: merge MKON into かぐや姫Pt
kaguya_key = None
for cand in ("かぐや姫Pt", "かぐや姫Pt/妄想族", "辉夜姬"):
    if cand in makers:
        kaguya_key = cand
        break
if not kaguya_key:
    # resolve via alias
    for cand in ("かぐや姫Pt", "辉夜姬", "Kaguya Hime Pt"):
        t = aliases.get(cand)
        if t and t in makers:
            kaguya_key = t
            break
if not kaguya_key:
    kaguya_key = "かぐや姫Pt"
    makers[kaguya_key] = {
        "card": "辉夜姬",
        "i18n": ["辉夜姬 / かぐや姫Pt", "かぐや姫Pt", "Kaguya Hime Pt"],
        "intro": "妄想族关联レーベル，轻度调教与角色向。",
    }
    print(f"NEW {kaguya_key}")
else:
    print(f"USE kaguya={kaguya_key}")

aliases["かぐや姫Pt"] = kaguya_key
aliases["かぐや姫Pt/妄想族"] = kaguya_key
aliases["辉夜姬"] = kaguya_key
aliases["Kaguya Hime Pt"] = kaguya_key
aliases["MKON"] = kaguya_key

# Bermuda aliases for DOA
bermuda = "Bermuda" if "Bermuda" in makers else aliases.get("Bermuda")
if bermuda and bermuda in makers:
    aliases["バミューダ"] = bermuda
    aliases["バミューダ/妄想族"] = bermuda
    aliases["DOA"] = bermuda
    print(f"Bermuda aliases -> {bermuda}")
else:
    print("WARN Bermuda missing")

# Fix lookup pollution: do NOT leave bare 「妄想族」 pointing only to ABC.
# Remove any alias that is exactly 妄想族
if aliases.get("妄想族") == "ABC/妄想族":
    aliases.pop("妄想族", None)
    print("REMOVED bare alias 妄想族 -> ABC")

# Ensure i18n for ABC doesn't get used as bare 妄想族 in our earlier audit -
# card/i18n stay as "ABC/妄想族" which is fine if resolve prefers full string first.

# ---- 3) Delete bad aliases ----
BAD_ALIASES = ["FIRST STAR", "First Star", "Radix", "邪恶帝国", "魔笛"]
for a in BAD_ALIASES:
    if a in aliases:
        aliases.pop(a)
        print(f"DEL alias {a}")
    # also case variants
for a in list(aliases.keys()):
    if a.casefold() in {x.casefold() for x in BAD_ALIASES}:
        aliases.pop(a, None)
        print(f"DEL alias {a}")

# Optional: add First Star as independent stub (no prefixes yet OK)
if "First Star" not in makers and "FIRST STAR" not in makers:
    makers["First Star"] = {
        "card": "First Star",
        "i18n": ["First Star", "ファーストスター", "First Star"],
        "intro": "独立厂牌（非 SOD Create）。别名不再并入 SOD。",
    }
    aliases["First Star"] = "First Star"
    aliases["FIRST STAR"] = "First Star"
    aliases["ファーストスター"] = "First Star"
    print("NEW First Star (independent)")

MPATH.write_text(json.dumps(mdoc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"makers.json updated, entries={len(makers)}")

# ---- catalog: DOA -> Bermuda, MKON maker unify ----
doc = store.load_catalog(force=True)

def patch_prefix(rid: str, pref: str, maker: str, maker_ja: str = "", maker_en: str = "", note: str = ""):
    prefs = doc["regions"][rid].get("prefixes") or {}
    ent = prefs.get(pref)
    if not isinstance(ent, dict):
        print(f"MISS {rid}/{pref}")
        return False
    ent = dict(ent)
    ent["prefix"] = pref
    ent["maker"] = maker
    if maker_ja:
        ent["maker_ja"] = maker_ja
    if maker_en:
        ent["maker_en"] = maker_en
    srcs = set(ent.get("sources") or [])
    srcs.add("manual")
    ent["sources"] = sorted(srcs)
    if note:
        notes = str(ent.get("notes") or "").strip()
        if note not in notes:
            ent["notes"] = f"{notes} · {note}".strip(" ·") if notes else note
    pe = store._normalize_prefix_entry(pref, ent)
    prefs[pe["prefix"]] = pe
    print(f"CAT {rid}/{pref} -> {maker}")
    return True

# find regions for DOA / MKON
for rid in REGION_ORDER:
    prefs = doc["regions"][rid].get("prefixes") or {}
    if "DOA" in prefs:
        patch_prefix(rid, "DOA", "Bermuda", "バミューダ", "Bermuda", "用户确认 · 改挂 Bermuda")
    if "MKON" in prefs:
        patch_prefix(rid, "MKON", "かぐや姫Pt/妄想族" if kaguya_key.endswith("妄想族") else "かぐや姫Pt",
                     "かぐや姫Pt", "Kaguya Hime Pt", "用户确认 · 并入かぐや姫Pt")
    # ensure DNJR/AGAV/BLOR/SUJI keep their maker strings (already correct)
    for pref, maker in (
        ("DNJR", "犬/妄想族"),
        ("AGAV", "SEX Agent/妄想族"),
        ("BLOR", "ブロッコリー/妄想族"),
        ("SUJI", "姦乱者/妄想族"),
    ):
        if pref in prefs:
            cur = str(prefs[pref].get("maker") or "")
            if cur != maker:
                patch_prefix(rid, pref, maker, note="用户确认 · 独立子レーベル")
            else:
                print(f"OK  {rid}/{pref} already {maker}")

store.save_catalog(doc)

# ---- 4) Sync seed makers from catalog ----
seed = store.load_seed()
synced = 0
mismatched_before = 0
for rid in REGION_ORDER:
    cp = doc["regions"][rid].get("prefixes") or {}
    sp = (seed.get("regions") or {}).get(rid, {}).get("prefixes") or {}
    for p, cent in cp.items():
        sent = sp.get(p)
        if not isinstance(sent, dict) or not isinstance(cent, dict):
            continue
        cm = str(cent.get("maker") or "").strip()
        sm = str(sent.get("maker") or "").strip()
        if not cm:
            continue
        if sm != cm:
            mismatched_before += 1
            sent = dict(sent)
            sent["prefix"] = p
            sent["maker"] = cm
            for k in ("maker_ja", "maker_en", "maker_zh"):
                if cent.get(k):
                    sent[k] = cent[k]
            srcs = set(sent.get("sources") or [])
            srcs.add("catalog-sync")
            sent["sources"] = sorted(srcs)
            pe = store._normalize_prefix_entry(p, sent)
            sp[pe["prefix"]] = pe
            synced += 1

# also apply DOA/MKON to seed if present
for rid in REGION_ORDER:
    sp = (seed.get("regions") or {}).get(rid, {}).get("prefixes") or {}
    if "DOA" in sp:
        e = dict(sp["DOA"])
        e["prefix"] = "DOA"
        e["maker"] = "Bermuda"
        e["maker_ja"] = "バミューダ"
        e["maker_en"] = "Bermuda"
        sp["DOA"] = store._normalize_prefix_entry("DOA", e)
        print("SEED DOA -> Bermuda")
    if "MKON" in sp:
        e = dict(sp["MKON"])
        e["prefix"] = "MKON"
        e["maker"] = "かぐや姫Pt"
        sp["MKON"] = store._normalize_prefix_entry("MKON", e)
        print("SEED MKON -> かぐや姫Pt")

store.SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"seed synced makers: {synced} (mismatched_before≈{mismatched_before})")

# verify resolve of 犬/妄想族 no longer ABC
SEP = re.compile(r"[\s\-_.·・/／\\]+")
def norm(s):
    s = unicodedata.normalize("NFKC", s or "").strip().casefold()
    return SEP.sub("", s)

lookup = {}
for k in makers:
    lookup[norm(k)] = k
for a, c in aliases.items():
    if c in makers:
        lookup[norm(a)] = c
for name in ("犬/妄想族", "SEX Agent/妄想族", "ブロッコリー/妄想族", "姦乱者/妄想族", "バミューダ/妄想族", "かぐや姫Pt/妄想族"):
    # prefer full string
    hit = lookup.get(norm(name))
    print(f"resolve {name!r} -> {hit!r}")
