# -*- coding: utf-8 -*-
"""Upsert batch-1 maker zh+intro into makers.json; print next 30."""
from __future__ import annotations
import json, re, sys, unicodedata
from collections import defaultdict, OrderedDict
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

# (canonical_key, card_zh, i18n[zh_label, ja, en], intro, extra_aliases)
BATCH = [
    (
        "ドグマ",
        "犬马",
        ["犬马 / Dogma", "ドグマ", "Dogma"],
        "2001年由监督TOHJIRO创立。主打硬核SM、拘束、深喉、变态系，风格极端、艺术感强，业界硬核标杆。",
        ["Dogma", "DOGMA", "犬马", "DDT", "DDK", "DOKS"],
    ),
    (
        "IDEA POCKET",
        "理念口袋",
        ["理念口袋 / IP", "アイデアポケット", "IDEA POCKET"],
        "美少女单体路线老牌厂。以高质量颜值、剧情、FIRST IMPRESSION出道系列闻名，专属女优众多。",
        ["理念口袋", "想法口袋", "IP", "IP社"],
    ),
    (
        "Fitch",
        "菲奇",
        ["菲奇 / Fitch", "フィッチ", "Fitch"],
        "巨乳・肉感・丰满女优专业厂。以「肉感」为核心卖点，主打大胸与丰满身材。",
        ["菲奇", "フィッチ"],
    ),
    (
        "Ore no Shirouto",
        "俺的素人",
        ["俺的素人", "俺の素人", "Ore no Shirouto"],
        "素人中出、个人拍摄风格，真实感强。",
        ["俺的素人", "俺の素人", "Ore no Shirouto / 俺的素人"],
    ),
    (
        "Center Village",
        "中心村",
        ["中心村 / Center Village", "センタービレッジ", "Center Village"],
        "熟女・人妻专业厂。以中年、熟女、近亲、人妻题材为主，作品量大。",
        ["中心村", "中心乡村", "センタービレッジ"],
    ),
    (
        "OPPAI",
        "欧派",
        ["欧派 / OPPAI", "おっぱい", "OPPAI"],
        "巨乳专业厂。专注大胸女优与巨乳题材，画质和女优质量较高。",
        ["欧派", "巨乳", "おっぱい"],
    ),
    (
        "V＆R PRODUCE",
        "V&R制作",
        ["V&R制作 / V&R", "ブイアンドアールプロデュース", "V&R PRODUCE"],
        "老牌厂牌，风格多元，含剧情、凌辱、变态系，有一定历史积淀。",
        ["V&R PRODUCE", "V&R制作", "V&R", "V＆R PRODUCE"],
    ),
    (
        "いんすた",
        "印斯塔",
        ["印斯塔 / いんすた", "いんすた", "Insta"],
        "素人个拍、中出系列（HMN WORKS旗下）。主打真实素人、社交风格拍摄。",
        ["印斯塔", "インスタ", "HMN WORKS", "INSTV"],
    ),
    (
        "ピーターズ",
        "彼得斯",
        ["彼得斯 / Peters", "ピーターズ", "Peters"],
        "素人ナンパ专业厂。以「ガチナンパ！」系列闻名，街头搭讪、按摩、レズ题材较多。",
        ["彼得斯", "Peters", "Peters MAX"],
    ),
    (
        "俺の素人-Z-",
        "俺的素人-Z-",
        ["俺的素人-Z-", "俺の素人-Z-", "Ore no Shirouto-Z-"],
        "「俺的素人」系列升级版 / SECOND IMPACT。更强调素人真实感与企画。",
        ["俺的素人-Z-", "俺の素人-Z- SECOND IMPACT", "Ore no Shirouto-Z-"],
    ),
    (
        "ビッグモーカル",
        "大莫卡",
        ["大莫卡 / Big Morkal", "ビッグモーカル", "Big Morkal"],
        "素人・人妻・ナンパ文档系老牌厂。以街拍、中出人妻、真实记录风格著称。",
        ["大莫卡", "Big Morkal", "ビッグモーカル"],
    ),
    (
        "DOC",
        "DOC",
        ["DOC", "DOC", "DOC"],
        "素人・企画・搭讪系厂。风格轻松，常有街头、家访、素人互动题材。",
        [],
    ),
    (
        "Glory Quest",
        "光荣任务",
        ["光荣任务 / Glory Quest", "グローリークエスト", "Glory Quest"],
        "硬核・拘束・凌辱・体液系厂。风格偏激烈，有铁拘束、潮吹等特色系列。",
        ["光荣任务", "光荣探索", "グローリークエスト"],
    ),
    (
        "REAL",
        "REAL",
        ["REAL / 真实", "レアル", "REAL"],
        "老牌厂牌，风格偏真实、剧情、凌辱、NTR等，作品质量稳定。",
        ["真实", "レアル", "REAL WORKS"],
    ),
    (
        "S-Cute",
        "S-Cute",
        ["S-Cute", "エスキュート", "S-Cute"],
        "清新美少女・恋爱风格厂。以可爱、温柔、恋爱感拍摄著称，画质精致。",
        ["S-cute", "エスキュート", "229SCUTE"],
    ),
    (
        "Sadistic Village",
        "施虐村",
        ["施虐村 / Sadistic Village", "サディスティックヴィレッジ", "Sadistic Village"],
        "硬核・凌辱・拘束・变态系厂。风格极端，与Dogma类似但更偏策划向。",
        ["施虐村", "虐待村", "サディスティックヴィレッジ"],
    ),
    (
        "10musume",
        "天然少女",
        ["天然少女 / 10musume", "天然むすめ", "10musume"],
        "素人美少女、清纯系个拍风格，真实感强。",
        ["天然少女", "天然むすめ", "10musume / 天然少女", "10MUSUME"],
    ),
    (
        "恋慕",
        "恋慕",
        ["恋慕", "恋の母", "Koi no Bo"],
        "偏恋爱、温柔、情感向风格。",
        ["Koi no Bo", "Koi no Bo / 恋慕", "恋の母"],
    ),
    (
        "MARRION",
        "玛丽昂",
        ["玛丽昂 / Marrion", "マリオン", "MARRION"],
        "以女优颜值与剧情为主，风格相对柔和、偏单体女优。",
        ["玛丽昂", "Marrion", "マリオン"],
    ),
    (
        "Maji Nanpa",
        "真面目软派",
        ["真面目软派", "マジ軟派", "Maji Nanpa"],
        "主打认真搭讪、真实素人ナンパ风格。",
        ["真面目软派", "Maji Nanpa / 真面目软派", "マジナンパ", "マジ軟派"],
    ),
]


def upsert(key: str, card: str, i18n: list[str], intro: str, extra_aliases: list[str]) -> str:
    # Prefer existing key if alias already points elsewhere with same meaning
    existing = None
    if key in makers:
        existing = key
    else:
        # find by alias
        for a in [key] + extra_aliases:
            t = aliases.get(a)
            if t and t in makers:
                existing = t
                break
    use = existing or key
    ent = dict(makers.get(use) or {})
    ent["card"] = card
    ent["i18n"] = i18n
    ent["intro"] = intro
    makers[use] = ent
    # aliases
    aliases[key] = use
    for a in extra_aliases:
        if a:
            aliases[a] = use
    return use


applied = []
for key, card, i18n, intro, extra in BATCH:
    use = upsert(key, card, i18n, intro, extra)
    applied.append(f"{key} -> {use} card={card}")
    print(f"OK {key} -> {use} | {card}")

PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"\nupdated {PATH}")

# clear caches if any
try:
    maps_paths.makers_doc.cache_clear()
except Exception:
    pass

# ---- re-audit next 30 ----
makers_doc = json.loads(PATH.read_text(encoding="utf-8"))
aliases = {str(k): str(v) for k, v in (makers_doc.get("aliases") or {}).items()}
makers = makers_doc.get("makers") or {}
HAN = re.compile(r"[\u4e00-\u9fff]")
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


def has_intro(ent: dict) -> bool:
    intro = str(ent.get("intro") or "").strip()
    return bool(intro) and "由前缀目录同步补全" not in intro


cat = store.load_catalog(force=True)
by_maker: dict[str, list[tuple[str, str]]] = defaultdict(list)
for rid in REGION_ORDER:
    for p, e in (cat["regions"][rid].get("prefixes") or {}).items():
        m = str((e or {}).get("maker") or "").strip()
        if m:
            by_maker[m].append((rid, p))


def catalog_zh(m: str) -> str:
    for t in tokens(m):
        if HAN.search(t):
            return t
    return ""


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
    zh_ok = has_zh(ent)
    intro_ok = has_intro(ent)
    if zh_ok and intro_ok:
        continue
    items.append({
        "status": "PATCH",
        "name": m,
        "key": key,
        "n": n,
        "sample": sample,
        "hint_zh": czh,
        "need_zh": not zh_ok,
        "need_intro": not intro_ok,
    })

# dedupe by key (or name for NEW)
seen = set()
uniq = []
for it in sorted(items, key=lambda x: -x["n"]):
    k = it["key"] or it["name"]
    if k in seen:
        continue
    seen.add(k)
    uniq.append(it)

print(f"\nstill need: {len(uniq)}")
print("=== 第2组（30）通俗中文名 | 一句话介绍 ===")
for i, it in enumerate(uniq[:30], 1):
    tag = []
    if it["status"] == "NEW":
        tag.append("新建")
    else:
        if it["need_zh"]:
            tag.append("补中文")
        if it["need_intro"]:
            tag.append("补介绍")
    hint = f"  hint={it['hint_zh']}" if it.get("hint_zh") else ""
    label = it["key"] or it["name"]
    print(f"{i:2d}. [{'·'.join(tag)}] {label}  (×{it['n']}: {it['sample']}){hint}")
print(f"… 另有 {max(0, len(uniq)-30)} 条")
