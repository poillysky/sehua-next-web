# -*- coding: utf-8 -*-
"""Scrap-library prefixes with real codes + intro status via app resolvers."""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

from app.prefix.maker_names import (
    MAKER_INTRO,
    PREFIX_INTRO,
    resolve_maker_intro_for_prefix,
    resolve_maker_names,
)
from app.core.maps_paths import maker_i18n_map, studio_card_label_map
from app.prefix import catalog_store as store

ROOT = Path(r"E:\Project\sehua-next-web")
SCRAP = ROOT / "media" / "scrap-library"
MAPS = ROOT / "apps" / "maps"

makers_doc = json.loads((MAPS / "makers" / "makers.json").read_text(encoding="utf-8"))
makers_map = makers_doc.get("makers") or {}
aliases = makers_doc.get("aliases") or {}
card_map = studio_card_label_map()

pref_doc = json.loads((MAPS / "prefixes" / "prefixes.json").read_text(encoding="utf-8"))
pref_items = pref_doc.get("prefixes") or {}

# load catalog japan prefixes -> maker
cat = store.load_catalog() if hasattr(store, "load_catalog") else None
if cat is None:
    # try common API
    try:
        cat = store.get_catalog()
    except Exception:
        cat = json.loads((ROOT/"data/prefix/catalog/catalog.json").read_text(encoding="utf-8"))

catalog_maker = {}
regions = (cat.get("regions") if isinstance(cat, dict) else None) or cat
if isinstance(regions, dict):
    for rk, rv in regions.items():
        if not isinstance(rv, dict):
            continue
        prefs = rv.get("prefixes") or {}
        for p, e in prefs.items():
            if not isinstance(e, dict):
                continue
            m = str(e.get("maker") or "").strip()
            if m:
                catalog_maker[str(p).upper()] = m

def resolve_maker_key(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    if s in makers_map:
        return s
    # strip "A / B" take left then right
    parts = [x.strip() for x in s.replace("／", "/").split("/") if x.strip()]
    candidates = [s] + parts
    for c in candidates:
        if c in makers_map:
            return c
        if c in aliases:
            a = aliases[c]
            if isinstance(a, str) and a in makers_map:
                return a
        # casefold
        for k in makers_map:
            if k.casefold() == c.casefold():
                return k
    # alias values reverse: search card/i18n
    for k, meta in makers_map.items():
        card = str(meta.get("card") or "")
        if card and card in s:
            return k
        i18n = meta.get("i18n") or []
        if isinstance(i18n, list):
            for t in i18n:
                if str(t) and str(t) in s:
                    return k
                if s in str(t):
                    return k
    return ""

def prefix_intro_status(pref: str) -> tuple[str, str]:
    # PREFIX_INTRO map first, then file
    text = (PREFIX_INTRO.get(pref) or "").strip()
    if not text:
        ent = pref_items.get(pref) or {}
        if isinstance(ent, dict):
            text = str(ent.get("intro") or "").strip()
    if not text:
        return "missing", ""
    if "公开资料有限" in text or len(text) < 12:
        return "weak", text
    # very generic short
    if text.endswith("。") and len(text) < 16:
        return "weak", text
    return "ok", text

def maker_status(key: str) -> tuple[str, str, str]:
    if not key:
        return "no_maker", "", ""
    meta = makers_map.get(key) or {}
    intro = str(meta.get("intro") or "").strip()
    if not intro:
        intro = (MAKER_INTRO.get(key) or "").strip()
    card = str(meta.get("card") or card_map.get(key) or "").strip()
    if not intro:
        mi = "missing"
    elif "公开资料有限" in intro or len(intro) < 12:
        mi = "weak"
    else:
        mi = "ok"
    mc = "ok" if card else "missing"
    return mi, intro[:60], card

def count_codes(d: Path) -> int:
    return sum(1 for c in d.iterdir() if c.is_dir() and not c.name.startswith("_"))

rows = []
for region_dir in sorted(SCRAP.iterdir()):
    if not region_dir.is_dir() or region_dir.name.startswith("_"):
        continue
    region = region_dir.name
    if region.upper() == "FC2":
        n = count_codes(region_dir)
        if n:
            rows.append(("FC2", "FC2", n))
        continue
    for pref_dir in sorted(region_dir.iterdir()):
        if not pref_dir.is_dir() or pref_dir.name.startswith("_"):
            continue
        pref = pref_dir.name.upper().strip()
        n = count_codes(pref_dir)
        if n:
            rows.append((region, pref, n))

out = []
for region, pref, n in rows:
    raw_maker = catalog_maker.get(pref, "")
    mkey = resolve_maker_key(raw_maker)
    # also try resolve via prefix intro path
    if not mkey:
        # try from prefixes.json i18n first token
        ent = pref_items.get(pref) or {}
        i18n = ent.get("i18n") if isinstance(ent, dict) else None
        if isinstance(i18n, list) and i18n:
            mkey = resolve_maker_key(str(i18n[0]))
            if not raw_maker:
                raw_maker = str(i18n[0])
    ps, ptext = prefix_intro_status(pref)
    ms, mtext, card = maker_status(mkey)
    out.append({
        "region": region,
        "prefix": pref,
        "count": n,
        "maker_raw": raw_maker,
        "maker_key": mkey or "",
        "card": card,
        "prefix_intro": ps,
        "prefix_text": ptext[:80],
        "maker_intro": ms,
        "maker_text": mtext,
        "in_catalog": pref in catalog_maker,
    })

# stats
from collections import Counter
pc = Counter(x["prefix_intro"] for x in out)
mc = Counter(x["maker_intro"] for x in out)
print("prefixes", len(out), "codes", sum(x["count"] for x in out))
print("prefix_intro", dict(pc))
print("maker_intro", dict(mc))
need_p = [x for x in out if x["prefix_intro"] != "ok"]
need_m_keys = sorted({x["maker_key"] or x["maker_raw"] or "(无)" for x in out if x["maker_intro"] != "ok"})
print("need_prefix_intro", len(need_p))
print("unique_makers_need_intro", len(need_m_keys))

# unique makers across all scrap prefixes
maker_groups = defaultdict(list)
for x in out:
    mk = x["maker_key"] or x["maker_raw"] or "(无厂牌)"
    maker_groups[mk].append(x)

print("unique_makers_in_scrap", len(maker_groups))

# makers with weak/missing intro among scrap
makers_todo = []
for mk, items in sorted(maker_groups.items(), key=lambda kv: -sum(i["count"] for i in kv[1])):
    # status from first resolved
    keys = {i["maker_key"] for i in items if i["maker_key"]}
    key = next(iter(keys), "")
    ms, mtext, card = maker_status(key) if key else ("no_maker", "", "")
    if not key:
        ms = "no_maker"
    prefs = sorted(items, key=lambda i: -i["count"])
    makers_todo.append({
        "maker_key": key or mk,
        "card": card,
        "maker_intro": ms,
        "maker_text": mtext,
        "prefix_count": len(prefs),
        "code_count": sum(i["count"] for i in prefs),
        "prefixes": [(i["prefix"], i["count"], i["prefix_intro"]) for i in prefs],
    })

out_json = ROOT / "apps/api/scripts/_scrap_prefix_intro_todo.json"
out_json.write_text(json.dumps({"prefixes": out, "makers": makers_todo}, ensure_ascii=False, indent=2), encoding="utf-8")

# Markdown for user - full inventory
lines = []
lines.append(f"# 刮削库有实际番号的前缀清单")
lines.append("")
lines.append(f"- 前缀数：**{len(out)}**")
lines.append(f"- 番号文件夹合计：**{sum(x['count'] for x in out)}**")
lines.append(f"- 涉及厂牌：**{len(maker_groups)}**")
lines.append(f"- 前缀介绍需补（missing/weak）：**{len(need_p)}**")
lines.append(f"- 厂牌介绍需补：**{sum(1 for m in makers_todo if m['maker_intro']!='ok')}**")
lines.append("")
lines.append("## 按厂牌分组（方便一起补厂牌介绍 + 各前缀介绍）")
lines.append("")

for m in makers_todo:
    flag = m["maker_intro"]
    lines.append(f"### {m['maker_key']}  · card=`{m['card'] or '—'}`  · 厂牌介绍={flag}  · {m['prefix_count']}前缀 / {m['code_count']}条")
    if m["maker_text"]:
        lines.append(f"> 现有：{m['maker_text']}")
    for pref, cnt, pi in m["prefixes"]:
        mark = "" if pi == "ok" else f" ⚠{pi}"
        lines.append(f"- `{pref}` ×{cnt}{mark}")
    lines.append("")

# compact paste template for prefixes needing intro
lines.append("## 待补前缀介绍（可直接按行回填）")
lines.append("")
lines.append("格式：`前缀|介绍`")
lines.append("")
for x in sorted(need_p, key=lambda i: (-i["count"], i["prefix"])):
    lines.append(f"{x['prefix']}|")
lines.append("")
lines.append("## 待补厂牌介绍（可直接按行回填）")
lines.append("")
lines.append("格式：`厂牌Key|俗称card|介绍`")
lines.append("")
for m in makers_todo:
    if m["maker_intro"] == "ok":
        continue
    lines.append(f"{m['maker_key']}|{m['card']}|")

md = ROOT / "apps/api/scripts/_scrap_prefix_intro_todo.md"
md.write_text("\n".join(lines), encoding="utf-8")
print("wrote", md)

# print summary for chat
print("\n=== MAKERS NEED INTRO ===")
for m in makers_todo:
    if m["maker_intro"] == "ok":
        continue
    prefs = ",".join(p for p,_,_ in m["prefixes"][:12])
    more = "" if len(m["prefixes"])<=12 else f"+{len(m['prefixes'])-12}"
    print(f"{m['maker_key']}\t{m['maker_intro']}\t{m['code_count']}\t{prefs}{more}")

print("\n=== PREFIX NEED INTRO (top by count) ===")
for x in sorted(need_p, key=lambda i: (-i["count"], i["prefix"]))[:60]:
    print(f"{x['prefix']}\t{x['count']}\t{x['maker_key'] or x['maker_raw']}\t{x['prefix_intro']}\t{x['prefix_text'][:40]}")
print(f"... total need_prefix {len(need_p)}")

print("\n=== ALL PREFIX LIST (compact) ===")
print(",".join(x["prefix"] for x in sorted(out, key=lambda i: i["prefix"])))
