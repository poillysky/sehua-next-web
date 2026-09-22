# -*- coding: utf-8 -*-
"""Apply makers meta batch2; list next 30."""
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
    ("パラダイステレビ", "天堂电视", ["天堂电视 / Paradise TV", "パラダイステレビ", "Paradise TV"],
     "スカパー成人频道出身的企画厂。主打「笑えるエロ」、素人、熟女、文档、盗撮、ナンパ等，自社节目风格鲜明。",
     ["天堂电视", "乐园电视", "Paradise TV", "083PPP"]),
    ("おかず。", "小菜", ["小菜 / おかず。", "おかず。", "Okazu"],
     "KMP旗下企画・素人・合集系厂。作品量极大，风格轻松、日常向。",
     ["小菜", "おかず", "Okazu"]),
    ("Pacopacomama", "啪啪妈妈", ["啪啪妈妈", "パコパコママ", "Pacopacomama"],
     "人妻・熟女素人中出专业系列，真实感强。",
     ["啪啪妈妈", "パコパコママ", "Pacopacomama / 啪啪妈妈", "PACOMA"]),
    ("Nanpa TV", "搭讪TV", ["搭讪TV / ナンパTV", "ナンパTV", "Nanpa TV"],
     "Prestige旗下素人搭讪系列。街头搭讪、真实记录风格，常与Premium合作。",
     ["搭讪TV", "ナンパTV", "Nanpa TV / ナンパTV", "GANA"]),
    ("Prestige Premium", "Prestige Premium", ["Prestige Premium", "プレステージプレミアム", "Prestige Premium"],
     "Prestige高端配信系列。精选高质量素人、搭讪、企画作品。",
     ["プレステージプレミアム", "Prestige Premium / プレステージプレミアム", "MIUM"]),
    ("K-Tribe", "K部落", ["K部落 / K-Tribe", "ケートライブ", "K-Tribe"],
     "以ロリ・美少女・制服系为主，风格偏清纯与禁忌。",
     ["K部落", "ケートライブ"]),
    ("Trans Club", "变性俱乐部", ["变性俱乐部 / Trans Club", "トランスクラブ", "Trans Club"],
     "ニューハーフ・男の娘专业厂。主打真实伪娘、肛交、变态玩法。",
     ["变性俱乐部", "伪娘俱乐部", "T-Club", "TRANS CLUB"]),
    ("乱丸", "乱丸", ["乱丸", "乱丸", "Ranmaru"],
     "痴女・淫乱专业厂（已停止新作）。以极度痴女、白眼高潮、潮吹乱交闻名。",
     ["Ranmaru", "TYOD"]),
    ("TMA", "TMA", ["TMA", "ティーエムエー", "TMA"],
     "コスプレ・パロディ专业厂。以ACG还原、剧情コス著名，也有女装、近亲题材。",
     ["T28"]),
    ("ラグジュTV", "奢华TV", ["奢华TV / ラグジュTV", "ラグジュTV", "Luxu TV"],
     "高端素人系列。以气质美女、OL、人妻为主，拍摄精致、氛围感强。",
     ["奢华TV", "LUXU", "Luxu TV"]),
    ("Caribbeancom Premium", "加勒比高级版", ["加勒比高级版", "カリビアンコムプレミアム", "Caribbeancom Premium"],
     "加勒比（Caribbeancom）的高画质・无码高端系列。",
     ["加勒比高级版", "カリビアンコムプレミアム", "CWPBD"]),
    ("いきなりエロざんまい", "突然エロ盛宴", ["突然エロ盛宴", "いきなりエロざんまい", "Ikinari Erozanmai"],
     "素人ナンパ・ハメ撮り配信レーベル。多重新包装既有素人作品。",
     ["突然エロ盛宴", "SGSR"]),
    ("Hsoda", "Hsoda", ["Hsoda", "エイチソーダ", "Hsoda"],
     "较少见的小众厂牌，风格偏素人或特殊题材。",
     ["HSODA"]),
    ("Hajime Kikaku", "初企画", ["初企画 / Hajime Kikaku", "はじめ企画", "Hajime Kikaku"],
     "老牌企画厂。主打剧情、凌辱、特殊玩法。",
     ["初企画", "はじめ企画"]),
    ("クロス", "クロス", ["クロス / Cross", "クロス", "Cross"],
     "硬核・凌辱・变态系厂，风格偏激烈。",
     ["Cross", "CRPD"]),
    ("h.m.p DORAMA", "h.m.p剧场版", ["h.m.p剧场版", "h.m.p DORAMA", "h.m.p DORAMA"],
     "h.m.p旗下剧情向系列。老牌厂，风格多元，含SM、剧情、单体。",
     ["h.m.p剧场版", "HOMA"]),
    ("FAIR＆WAY", "Fair & Way", ["Fair & Way", "フェアアンドウェイ", "FAIR&WAY"],
     "较少见的小众厂牌。",
     ["FAIR&WAY", "Fair & Way", "FWAY"]),
    ("ABC/妄想族", "ABC/妄想族", ["ABC/妄想族", "ABC/妄想族", "ABC"],
     "妄想族集团旗下。主打巨乳、故事性、剧情向巨乳作品。",
     ["ABC", "OKSN"]),
    ("レッド", "红", ["红 / Red", "レッド", "Red"],
     "老牌硬核・凌辱・变态系厂。",
     ["红", "Red", "REXD"]),
    ("熟女JAPAN", "熟女JAPAN", ["熟女JAPAN", "熟女JAPAN", "Jukujo Japan"],
     "熟女专业厂，主打中年、人妻、熟女题材。",
     ["JUTA"]),
    ("カルマ", "业力", ["业力 / Karma", "カルマ", "Karma"],
     "盗撮・偷拍・真实记录风格老牌厂。",
     ["业力", "Karma", "KAM"]),
    ("Fetish Box/妄想族", "Fetish Box/妄想族", ["Fetish Box/妄想族", "フェティッシュボックス/妄想族", "Fetish Box"],
     "妄想族旗下フェチ（恋物）专业レーベル。",
     ["Fetish Box", "ATFB"]),
    ("チェリーズれぼ/妄想族", "樱桃Revo/妄想族", ["樱桃Revo/妄想族", "チェリーズれぼ/妄想族", "Cherries Revo"],
     "妄想族旗下爆乳・妹系专业レーベル。以「妹の爆乳は一見にしかず」系列闻名。",
     ["樱桃Revo/妄想族", "CHRV"]),
    ("電脳ラスプーチン", "电脑拉斯普京", ["电脑拉斯普京", "電脳ラスプーチン", "Dennou Rasputin"],
     "较少见的特殊题材厂牌。",
     ["电脑拉斯普京", "DRPT"]),
    ("AVS collector's", "AVS收藏家", ["AVS收藏家", "AVS collector's", "AVS collector's"],
     "着衣フェチ、妄想、非日常情境专业厂。主打パンスト、巨乳、熟女着衣。",
     ["AVS收藏家", "AVS collector", "AVScollector", "ASW"]),
    ("FALENO TUBE", "FALENO TUBE", ["FALENO TUBE", "ファレノチューブ", "FALENO TUBE"],
     "FALENO旗下配信・YouTube风格系列。",
     ["FTHTD"]),
    ("パコパコ団とゆかいな仲間たち/妄想族", "啪啪团与快乐伙伴们/妄想族",
     ["啪啪团与快乐伙伴们/妄想族", "パコパコ団とゆかいな仲間たち/妄想族", "Pacopaco Dan"],
     "妄想族旗下轻松、搞笑、团体向レーベル。",
     ["啪啪团与快乐伙伴们/妄想族", "PKPD"]),
    ("チキチキカマー/妄想族", "奇奇奇卡玛/妄想族",
     ["奇奇奇卡玛/妄想族", "チキチキカマー/妄想族", "Chikichiki Kamaa"],
     "妄想族旗下特殊・搞笑・变态向レーベル。",
     ["奇奇奇卡玛/妄想族", "TIKB"]),
    ("NEXTGROUP", "NEXT集团", ["NEXT集团 / NEXTGROUP", "ネクストグループ", "NEXTGROUP"],
     "综合厂牌集团，旗下有多个レーベル，风格多元。",
     ["NEXT集团", "ネクスト", "NEXT", "Next Group", "SPZ"]),
    ("アンナと花子", "安娜与花子", ["安娜与花子", "アンナと花子", "Anna to Hanako"],
     "レズビアン专业レーベル（已停止新作）。主打正统女同、接吻、潮吹。",
     ["安娜与花子", "ANND"]),
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
            # also try casefold scan of makers keys
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
    # merge AVS collector -> AVS collector's if both exist
    return use


for key, card, i18n, intro, extra in BATCH:
    use = upsert(key, card, i18n, intro, extra)
    print(f"OK {key} -> {use} | {card}")

# Prefer map AVS collector to AVS collector's if both
if "AVS collector" in makers and "AVS collector's" in makers:
    # keep collector's as primary; point alias
    aliases["AVS collector"] = "AVS collector's"
    # merge intro if needed already set on collector's

PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"updated {PATH}")
try:
    maps_paths.makers_doc.cache_clear()
except Exception:
    pass

# ---- list next 30 ----
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
        items.append({"status": "NEW", "name": m, "key": "", "n": n, "sample": sample, "hint_zh": czh, "need_zh": True, "need_intro": True, "soft_zh": False})
        continue
    ent = makers[key]
    col_ok = has_colloquial(ent)
    intro_ok = has_intro(ent)
    if col_ok and intro_ok:
        # EN-only card with intro is ok
        if has_zh(ent) or LATIN.search(str(ent.get("card") or "")):
            continue
    soft = has_colloquial(ent) and not has_zh(ent)
    if soft and intro_ok:
        continue
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
print("=== 第3组（30）通俗中文名 | 一句话介绍 ===")
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
