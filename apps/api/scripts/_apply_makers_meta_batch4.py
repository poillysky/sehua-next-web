# -*- coding: utf-8 -*-
"""Apply makers meta batch4; list ALL remaining."""
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
    ("C0930", "人妻0930", ["人妻0930", "人妻0930", "C0930"],
     "人妻素人中出系列。真实人妻、个拍风格，无码配信为主。",
     ["人妻0930", "C0930 / 人妻0930"]),
    ("H0930", "好色0930", ["好色0930", "好色0930", "H0930"],
     "与好色4610同系。素人・人妻中出真实记录，风格朴实。",
     ["好色0930", "H0930 / 好色0930"]),
    ("Heydouga", "嘿动画", ["嘿动画 / Heydouga", "Hey動画", "Heydouga"],
     "日本老牌无码配信平台。大量素人、人妻、个拍作品的集散地。",
     ["嘿动画", "Heydouga / 嘿动画", "HEYDOUGA"]),
    ("XXX-AV", "解禁AV", ["解禁AV", "XXX-AV", "XXX-AV"],
     "无码解禁系列，多为有码作品的无码版本或特殊发行。",
     ["解禁AV", "XXX-AV / 解禁AV", "XXXAV"]),
    ("Red Hot Jam", "红热果酱", ["红热果酱", "レッドホットジャム", "Red Hot Jam"],
     "无码高画质系列，风格多样，包含单体与企画。",
     ["红热果酱", "レッドホットジャム", "RHJ"]),
    ("Sperm Mania", "精液狂热", ["精液狂热", "スペルママニア", "Sperm Mania"],
     "无码精液・颜射・口内射精专业系列。",
     ["精液狂热", "スペルママニア", "SPERMMANIA"]),
    ("Nyoshin", "女体神秘", ["女体神秘", "女体のしんぴ", "Nyoshin"],
     "女体观察・自慰・特殊玩法无码系列。",
     ["女体神秘", "Nyoshin / 女体神秘", "NYOSHIN"]),
    ("Legs Japan", "Legs Japan", ["Legs Japan", "レッグスジャパン", "Legs Japan"],
     "美腿・足交专业无码系列。",
     ["レッグスジャパン", "LEGSJAPAN"]),
    ("Fellatio Japan", "Fellatio Japan", ["Fellatio Japan", "フェラチオジャパン", "Fellatio Japan"],
     "口交专业无码系列。",
     ["フェラチオジャパン", "FELLATIOJAPAN"]),
    ("JapornXXX", "日产无码", ["日产无码", "ジャポルノXXX", "JapornXXX"],
     "无码综合系列，涵盖多种题材。",
     ["日产无码", "JapornXXX / 日产无码", "JAPORNXXX"]),
    ("Ura Bukkake", "里颜射", ["里颜射 / Ura Bukkake", "ウラブッカケ", "Ura Bukkake"],
     "无码颜射・大量精液专业系列。",
     ["里颜射", "ウラブッカケ", "URABUKKAKE"]),
    ("Rose Lip Fetish", "Rose Lip Fetish", ["Rose Lip Fetish", "ローゼリップフェティシ", "Rose Lip Fetish"],
     "恋物・特殊玩法无码系列。",
     ["ROSELIPFETISH"]),
    ("Handjob Japan", "Handjob Japan", ["Handjob Japan", "ハンドジョブジャパン", "Handjob Japan"],
     "手交专业无码系列。",
     ["HANDJOBJAPAN"]),
    ("SM-Miracle", "SM奇迹", ["SM奇迹", "SM-Miracle", "SM-Miracle"],
     "素人SM・调教无码系列，真实感强。",
     ["SM奇迹", "SM-Miracle / SM奇迹", "SMMIRACLE"]),
    ("Ura Lesbian", "里女同", ["里女同", "ウラレズビアン", "Ura Lesbian"],
     "无码女同系列。",
     ["里女同", "URALESBIAN"]),
    ("Rose Lip", "Rose Lip", ["Rose Lip", "ローゼリップ", "Rose Lip"],
     "无码恋物・特殊系列。",
     ["ROSELIP"]),
    ("Shirouto TV", "素人TV", ["素人TV", "シロウトTV", "Shirouto TV"],
     "素人个拍・真实记录系列。",
     ["素人TV", "Shirouto TV / 素人TV", "SIRO"]),
    ("Nanpa Tengoku", "搭讪天国", ["搭讪天国", "ナンパ天国", "Nanpa Tengoku"],
     "街头搭讪素人系列。",
     ["搭讪天国", "Nanpa Tengoku / Nanpa天国", "300NTK"]),
    ("Jackson", "杰克逊", ["杰克逊", "ジャクソン", "Jackson"],
     "较少见的无码或特殊系列。",
     ["杰克逊", "Jackson / 杰克逊", "390JAC"]),
    ("Hamedori", "个拍", ["个拍 / ハメ撮り", "ハメ撮り", "Hamedori"],
     "泛指个人拍摄、真实素人中出风格。",
     ["ハメ撮り", "Hamedori / ハメ撮り", "328HMDN"]),
    ("261ARA", "募集酱", ["募集酱", "ARA", "261ARA"],
     "著名素人募集系列。真实素人面试、中出风格，番号ARA。",
     ["募集酱", "261ARA / 募集酱", "ARA", "ARA（募集ちゃん）"]),
    ("himemix", "姬混", ["姬混", "ひめみっくす", "himemix"],
     "素人美少女・混合题材系列。",
     ["姬混", "himemix / 姬混", "HIMEMIX"]),
    ("Siro Hame", "白ハメ", ["白ハメ", "シロハメ", "Siro Hame"],
     "素人ハメ撮り系列。",
     ["白ハメ", "Siro Hame / 白ハメ", "SIROHAME"]),
    ("r-file", "R档案", ["R档案", "アールファイル", "r-file"],
     "素人档案・真实记录系列。",
     ["R档案", "r-file / R档案", "RFILE"]),
    ("G-area", "G区", ["G区", "ジーエリア", "G-area"],
     "素人美少女・中出系列，画质较好。",
     ["G区", "G-area / G区", "GAREA"]),
    ("しろうとまんまん", "素人人まん", ["素人人まん", "しろうとまんまん", "Shirouto Manman"],
     "素人系列，风格轻松真实。",
     ["素人人まん", "345SIMM"]),
    ("ペロンゲリオン", "ペロンゲリオン", ["ペロンゲリオン", "ペロンゲリオン", "Perongelion"],
     "较少见的特殊或恶搞向系列。",
     ["594PRGO"]),
    ("MOON FORCE", "MOON FORCE", ["MOON FORCE", "ムーンフォース", "MOON FORCE"],
     "DOC旗下素人ハメ撮り系列。主打美形素人、恋爱感中出。",
     ["435MFC"]),
    ("素人ホイホイZ", "素人ホイホイZ", ["素人ホイホイZ", "素人ホイホイZ", "Shirouto Hoihoi Z"],
     "素人搭讪・中出系列（ホイホイ系列升级版）。",
     ["420HOI"]),
    ("ドキュメンTV", "文档TV", ["文档TV", "ドキュメンTV", "Document TV"],
     "文档风格素人系列，真实记录感强。",
     ["文档TV", "277DCV"]),
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

# ---- list ALL remaining ----
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
    if has_colloquial(ent) and has_intro(ent):
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
        "need_intro": not has_intro(ent),
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
for it in sorted(filtered, key=lambda x: (-x["n"], it.get("key") or it["name"])):
    k = it["key"] or it["name"]
    if k in seen:
        continue
    seen.add(k)
    uniq.append(it)

out = ROOT / "data/debug/makers-remain-all.tsv"
lines = ["#\tstatus\tname\tkey\tn\tsample\thint\tneed\n"]
print(f"\nstill need ALL: {len(uniq)}")
print("=== 剩余全部（通俗中文名 | 一句话介绍）===")
for i, it in enumerate(uniq, 1):
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
    need = "·".join(tags) or "补"
    print(f"{i:2d}. [{need}] {label}  (×{it['n']}: {it['sample']}){hint}")
    lines.append(f"{i}\t{need}\t{it['name']}\t{it.get('key') or ''}\t{it['n']}\t{it['sample']}\t{it.get('hint_zh') or ''}\t{need}\n")
out.write_text("".join(lines), encoding="utf-8")
print(f"\nwrote {out}")
