# -*- coding: utf-8 -*-
"""Apply makers meta batch3; list next 30."""
from __future__ import annotations
import json, re, sys, unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.core.region_meta import REGION_ORDER
from app.prefix import catalog_store as store
from app.core import maps_paths

PATH = ROOT / "apps/maps/makers/makers.json"
doc = json.loads(PATH.read_text(encoding="utf-8"))
aliases: dict = doc.setdefault("aliases", {})
makers: dict = doc.setdefault("makers", {})

BATCH = [
    ("五十路ん", "五十路ん", ["五十路ん", "五十路ん", "Gojuurun"],
     "五十路（50岁以上）熟女专业レーベル。主打真实熟女、母性、羞耻与淫乱反差，作品量大。",
     ["GOJU"]),
    ("有閑ミセス/エマニエル", "有闲太太/Emaniel", ["有闲太太/Emaniel", "有閑ミセス/エマニエル", "Yukan Mrs"],
     "エマニエル集团旗下。主打优雅人妻、熟女、富裕阶层女性题材。",
     ["有闲太太/Emaniel", "SYKH"]),
    ("ミニマム", "迷你姆", ["迷你姆 / Minimum", "ミニマム", "Minimum"],
     "娇小・ロリ系专业厂。以矮小、幼齿、美少女身材为主打。",
     ["迷你姆", "Minimum", "MUM"]),
    ("あいすまん", "冰淇淋男", ["冰淇淋男 / Aisuman", "あいすまん", "Aisuman"],
     "素人・企画系厂，风格轻松、日常向。",
     ["冰淇淋男", "Aisuman", "BEAF"]),
    ("エロチカ", "情色卡", ["情色卡 / Erotica", "エロチカ", "Erotica"],
     "老牌厂，风格多元，含剧情、凌辱、单体作品。",
     ["情色卡", "Erotica", "ELO"]),
    ("teamZERO", "teamZERO", ["teamZERO", "チームゼロ", "teamZERO"],
     "较少见的小众厂牌，偏特殊或企画题材。",
     ["TEAM"]),
    ("Digital Ark", "数字方舟", ["数字方舟 / Digital Ark", "デジタルアーク", "Digital Ark"],
     "痴女・ギャル・フェチ专业厂。以黑ギャル、ハイレグ、ミニスカ、痴女系列闻名。",
     ["数字方舟", "デジタルアーク", "KCDA"]),
    ("SHIGEKI", "SHIGEKI", ["SHIGEKI / 刺激", "シゲキ", "SHIGEKI"],
     "以「イキ我慢」（忍耐高潮）为核心的企画厂。主打羞耻、忍耐、特殊挑战。",
     ["刺激", "SGKI"]),
    ("親父の個撮", "老爹的个拍", ["老爹的个拍", "親父の個撮", "Oyaji no Kosatsu"],
     "着衣フェチ专业厂。主打スクール水着、ブルマ、競泳水着完全着衣接写、ローション、ぶっかけ。",
     ["老爹的个拍", "OKB"]),
    ("中嶋興業", "中嶋兴业", ["中嶋兴业", "中嶋興業", "Nakajima Kogyo"],
     "硬核・変態・性玩系厂。主打调教、M女、极端玩法。",
     ["中嶋兴业", "NTRD"]),
    ("LAFBD", "LAFBD", ["LAFBD", "LAFBD", "LAFBD"],
     "无码高清系列（多为海外或特殊发行）。",
     []),
    ("WORLD PG", "WORLD PG", ["WORLD PG", "ワールドPG", "WORLD PG"],
     "モーションアニメ（动态漫画）系列厂。",
     ["AMCP"]),
    ("北池袋", "北池袋", ["北池袋", "北池袋", "Kitaikebukuro"],
     "素人・ハメ撮り・个人拍摄系厂。",
     ["KITAIKE"]),
    ("訳ありZ世代", "有问题的Z世代", ["有问题的Z世代", "訳ありZ世代", "Wakeari Z Sedai"],
     "素人・Z世代题材系列，主打年轻女性真实记录。",
     ["有问题的Z世代", "SUKE"]),
    ("I.B.WORKS", "I.B.WORKS", ["I.B.WORKS", "アイビーワークス", "I.B.WORKS"],
     "ロリ・美少女・制服系老牌厂。风格清纯与禁忌并存。",
     ["IBW"]),
    ("Around", "Around", ["Around", "アラウンド", "Around"],
     "人妻・熟女系厂，主打「Around 30/40」年龄层。",
     ["ARSO"]),
    ("熟女LABO", "熟女LABO", ["熟女LABO", "熟女LABO", "Jukujo LABO"],
     "熟女实验・中出・匹配应用系厂。真实感强，作品量大。",
     ["MEKO"]),
    ("熟女はつらいよ/熟女卍", "熟女好辛苦/熟女卍", ["熟女好辛苦/熟女卍", "熟女はつらいよ/熟女卍", "Jukujo wa Tsuraiyo"],
     "熟女专业レーベル。主打中年女性的真实性欲与生活感。",
     ["熟女好辛苦/熟女卍", "JYMA"]),
    ("ひよこ", "雏鸟", ["雏鸟 / Hiyoko", "ひよこ", "Hiyoko"],
     "ロリ・美少女・清纯系厂。风格偏幼齿、可爱。",
     ["雏鸟", "Hiyoko", "PIYO"]),
    ("YONAKA", "YONAKA", ["YONAKA", "ヨナカ", "YONAKA"],
     "较少见的小众厂牌。",
     ["MOON"]),
    ("エロVR", "情色VR", ["情色VR", "エロVR", "Ero VR"],
     "VR专用系列，主打沉浸式体验。",
     ["情色VR", "EROFV"]),
    ("ズッコン/バッコン", "ズッコン/バッコン", ["ズッコン/バッコン", "ズッコン/バッコン", "Zukkon Bakkon"],
     "乱交・多人运动专业厂。风格激烈、集体向。",
     ["ZUKO"]),
    ("MBM", "MBM", ["MBM", "エムビーエム", "MBM"],
     "较少见的小众厂牌。",
     []),
    ("アクアモール/エマニエル", "水上商场/Emaniel", ["水上商场/Emaniel", "アクアモール/エマニエル", "Aqua Mall"],
     "エマニエル集团旗下，人妻・熟女题材。",
     ["水上商场/Emaniel", "AQSH"]),
    ("MOON FORCE 2nd", "MOON FORCE 2nd", ["MOON FORCE 2nd", "ムーンフォースセカンド", "MOON FORCE 2nd"],
     "素人ハメ撮り・中出系列（DOC关联），主打真实素人。",
     ["MFCS"]),
    ("PoRO", "PoRO", ["PoRO", "ポロ", "PoRO"],
     "モーションアニメ（动态漫画）专业厂，风格偏剧情动画。",
     ["ACRN"]),
    ("ケラ工房", "ケラ工房", ["ケラ工房", "ケラ工房", "Kera Kobo"],
     "较少见的小众厂牌。",
     ["CLO"]),
    ("ゲインコーポレーション", "Gain Corporation", ["Gain Corporation", "ゲインコーポレーション", "Gain Corporation"],
     "老牌厂牌，风格多元。",
     ["ONSG"]),
    ("ミル", "米尔", ["米尔 / Miru", "ミル", "Miru"],
     "较少见的小众厂牌。",
     ["米尔", "Miru", "MIBB"]),
    ("H4610", "好色4610", ["好色4610", "H4610", "H4610"],
     "素人・中出・真实记录系列，风格朴实。",
     ["好色4610", "H4610 / 好色4610"]),
]


def upsert(key, card, i18n, intro, extra_aliases):
    existing = None
    if key in makers:
        existing = key
    else:
        for a in [key] + list(extra_aliases):
            t = aliases.get(a)
            if t and t in makers:
                existing = t
                break
        if not existing:
            low = {k.casefold(): k for k in makers}
            if key.casefold() in low:
                existing = low[key.casefold()]
    use = existing or key
    ent = dict(makers.get(use) or {})
    ent["card"] = card
    ent["i18n"] = i18n
    ent["intro"] = intro
    makers[use] = ent
    aliases[key] = use
    for a in extra_aliases:
        if a:
            aliases[a] = use
    return use


for row in BATCH:
    use = upsert(*row)
    print(f"OK {row[0]} -> {use} | {row[1]}")

PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"updated {PATH}")
try:
    maps_paths.makers_doc.cache_clear()
except Exception:
    pass

# ---- list next 30 (same logic as batch2) ----
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
    if has_zh(ent):
        return True
    card = str(ent.get("card") or "").strip()
    if card and LATIN.search(card):
        return True
    # kana/ja brand with intro is ok if card set
    return bool(card)


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
        items.append({"status": "NEW", "name": m, "key": "", "n": n, "sample": sample, "hint_zh": czh, "need_zh": True, "need_intro": True, "soft_zh": False})
        continue
    ent = makers[key]
    col_ok = has_colloquial(ent)
    intro_ok = has_intro(ent)
    if col_ok and intro_ok:
        continue
    soft = has_colloquial(ent) and not has_zh(ent)
    items.append({
        "status": "PATCH",
        "name": m,
        "key": key,
        "n": n,
        "sample": sample,
        "hint_zh": czh,
        "need_zh": not has_zh(ent),
        "need_intro": not intro_ok,
        "soft_zh": soft,
    })

filtered = []
for it in items:
    if it.get("soft_zh") and not it["need_intro"]:
        continue
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

print(f"\nstill need: {len(uniq)}")
print("=== 第4组（30）通俗中文名 | 一句话介绍 ===")
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
