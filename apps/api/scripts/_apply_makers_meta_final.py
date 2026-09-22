# -*- coding: utf-8 -*-
"""Apply final makers meta batch; verify zero remain."""
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
    ("IENFH（MGS素人）", "IENFH", ["IENFH / MGS素人", "IENFH", "IENFH"],
     "MGS配信的素人系列，真实素人中出、个拍风格。",
     ["IENFH", "MGS素人", "109IENFH"]),
    ("投稿マーケット素人イッてQ", "投稿市场素人去Q", ["投稿市场素人去Q", "投稿マーケット素人イッてQ", "Toukou Market"],
     "素人投稿平台系列，真实用户投稿的素人作品。",
     ["投稿市场素人去Q", "324SRTD"]),
    ("おっぱいちゃん", "胸部酱", ["胸部酱", "おっぱいちゃん", "Oppai-chan"],
     "巨乳素人专门系列，主打大胸素人。",
     ["胸部酱", "355OPCYN"]),
    ("NTR.net", "NTR.net", ["NTR.net", "NTR.net", "NTR.net"],
     "以NTR（绿帽）题材为主的素人系列。",
     ["348NTR"]),
    ("インディ", "独立", ["独立 / Indy", "インディ", "Indy"],
     "素人独立制作、真实感强的中出系列。",
     ["独立", "Indy", "534IND"]),
    ("白完素人", "白完素人", ["白完素人", "白完素人", "Shirokan Shirouto"],
     "素人完整版系列，画质与完整性较好。",
     ["494SIKA"]),
    ("E★人妻DX", "E★人妻DX", ["E★人妻DX", "E★人妻DX", "E Hitodzuma DX"],
     "人妻素人升级系列，主打真实人妻。",
     ["299EWDX"]),
    ("ときわ映像", "常盘映像", ["常盘映像", "ときわ映像", "Tokiwa Eizou"],
     "素人个拍、真实记录风格厂牌。",
     ["常盘映像", "491TKWA"]),
    ("黒船", "黑船", ["黑船", "黒船", "Kurofune"],
     "风格偏硬核或特殊题材的素人系列。",
     ["黑船", "Kurofune", "326FCT"]),
    ("E★ナンパDX", "E★搭讪DX", ["E★搭讪DX", "E★ナンパDX", "E Nanpa DX"],
     "搭讪素人升级系列，街头真实搭讪。",
     ["E★搭讪DX", "285ENDX"]),
    ("LadyHunter", "淑女猎人", ["淑女猎人", "LadyHunter", "LadyHunter"],
     "以猎取淑女、人妻为主的搭讪系列。",
     ["淑女猎人", "318LADY"]),
    ("A子さん", "A子桑", ["A子桑", "A子さん", "A-ko san"],
     "特定素人女优系列，常以A子名义出演。",
     ["A子桑", "210AKO"]),
    ("JVID", "台湾写真", ["台湾写真 / JVID", "JVID", "JVID"],
     "台湾写真与短片平台，主打高颜值女优写真与轻度情色内容。",
     ["台湾写真", "JVID / 台湾写真"]),
    ("Tushy", "塔希", ["塔希", "Tushy", "Tushy"],
     "高端肛交专业工作室，画质精致、剧情感强。",
     ["塔希", "Tushy / 塔希", "TUSHY"]),
    ("Deeper", "更深", ["更深", "Deeper", "Deeper"],
     "由Tushy团队打造，主打情色、心理与硬核结合的高端系列。",
     ["更深", "Deeper / 更深", "DEEPER"]),
    ("Blacked Raw", "黑蚀生", ["黑蚀生", "Blacked Raw", "Blacked Raw"],
     "Blacked的无套生版本，主打Interracial无套中出。",
     ["黑蚀生", "Blacked Raw / 黑蚀生", "BLACKEDRAW"]),
    ("Tushy Raw", "塔希生", ["塔希生", "Tushy Raw", "Tushy Raw"],
     "Tushy的无套生版本，专注高质量肛交无套。",
     ["塔希生", "Tushy Raw / 塔希生", "TUSHYRAW"]),
    ("RK Prime", "现实国王精选", ["现实国王精选", "RK Prime", "RK Prime"],
     "Reality Kings旗下精选系列，风格多样。",
     ["现实国王精选", "RK Prime / 现实国王精选", "RKPRIME"]),
    ("Fake Taxi", "假出租车", ["假出租车", "Fake Taxi", "Fake Taxi"],
     "经典英国系列，假出租车搭讪真实风格。",
     ["假出租车", "Fake Taxi / 假出租车", "FAKETAXI"]),
    ("Adult Time", "成人时间", ["成人时间", "Adult Time", "Adult Time"],
     "大型网络平台，旗下拥有多个精品工作室。",
     ["成人时间", "Adult Time / 成人时间", "ADULTTIME"]),
    ("Elegant Angel", "优雅天使", ["优雅天使", "Elegant Angel", "Elegant Angel"],
     "老牌美国厂牌，以高质量剧情与女优著称。",
     ["优雅天使", "Elegant Angel / 优雅天使", "ELEGANTANGEL"]),
    ("Lethal Hardcore", "致命硬核", ["致命硬核", "Lethal Hardcore", "Lethal Hardcore"],
     "硬核风格厂牌，玩法激烈。",
     ["致命硬核", "Lethal Hardcore / 致命硬核", "LETHALHARDCORE"]),
    ("Anal Vids", "肛门视频", ["肛门视频", "Anal Vids", "Anal Vids"],
     "专注肛交题材的系列/平台。",
     ["肛门视频", "Anal Vids / 肛门视频", "ANALVIDS"]),
    ("Public Agent", "公共探员", ["公共探员", "Public Agent", "Public Agent"],
     "公共场合搭讪、户外真实风格系列。",
     ["公共探员", "Public Agent / 公共探员", "PUBLICAGENT"]),
    ("Family Strokes", "家庭爱抚", ["家庭爱抚", "Family Strokes", "Family Strokes"],
     "伪家庭、禁忌题材系列。",
     ["家庭爱抚", "Family Strokes / 家庭爱抚", "FAMILYSTROKES"]),
    ("TeamSkeet", "队小子", ["队小子", "TeamSkeet", "TeamSkeet"],
     "年轻女优、清新与硬核并存的大型厂牌。",
     ["队小子", "TeamSkeet / 队小子", "TEAMSKEET"]),
    ("Bratty Sis", "顽皮姐妹", ["顽皮姐妹", "Bratty Sis", "Bratty Sis"],
     "伪兄妹、禁忌调戏风格系列。",
     ["顽皮姐妹", "Bratty Sis / 顽皮姐妹", "BRATTYSIS"]),
    ("Nubiles", "嫩模", ["嫩模", "Nubiles", "Nubiles"],
     "年轻、清新、自然风格的女优系列。",
     ["嫩模", "Nubiles / 嫩模", "NUBILES"]),
    ("SexMex", "墨西哥性", ["墨西哥性", "SexMex", "SexMex"],
     "墨西哥出品，主打拉丁女优与家庭题材。",
     ["墨西哥性", "SexMex / 墨西哥性", "SEXMEX"]),
    ("PornWorld", "色情世界", ["色情世界", "PornWorld", "PornWorld"],
     "欧洲硬核、群交、公共场合风格系列。",
     ["色情世界", "PornWorld / 色情世界", "PORNWORLD"]),
    ("MILFY", "熟女", ["熟女 / MILFY", "MILFY", "MILFY"],
     "专注MILF（熟女）题材的高端系列。",
     ["MILFY / 熟女"]),
    ("Wicked", "邪恶", ["邪恶", "Wicked", "Wicked"],
     "老牌剧情向厂牌，以故事片和女优质量著称。",
     ["邪恶", "Wicked / 邪恶", "WICKED"]),
    ("Nubile Films", "嫩模电影", ["嫩模电影", "Nubile Films", "Nubile Films"],
     "Nubiles旗下更重剧情与美感的系列。",
     ["嫩模电影", "Nubile Films / 嫩模电影", "NUBILEFILMS"]),
    ("SexArt", "性艺术", ["性艺术", "SexArt", "SexArt"],
     "艺术向、唯美情色系列。",
     ["性艺术", "SexArt / 性艺术", "SEXART"]),
    ("Watch4Beauty", "赏美", ["赏美", "Watch4Beauty", "Watch4Beauty"],
     "唯美、自然光、艺术写真与轻度情色。",
     ["赏美", "Watch4Beauty / 赏美", "WATCH4BEAUTY"]),
    ("Playboy Plus", "花花公子+", ["花花公子+", "Playboy Plus", "Playboy Plus"],
     "Playboy旗下高端写真与情色内容。",
     ["花花公子+", "Playboy Plus / 花花公子+", "PLAYBOYPLUS"]),
    ("Dorcel Club", "多塞尔俱乐部", ["多塞尔俱乐部", "Dorcel Club", "Dorcel Club"],
     "法国高端厂牌，画质与剧情均属上乘。",
     ["多塞尔俱乐部", "Dorcel Club / 多塞尔俱乐部", "DORCELCLUB"]),
    ("Digital Playground", "数字乐园", ["数字乐园", "Digital Playground", "Digital Playground"],
     "美国老牌大厂，以大制作剧情片闻名。",
     ["数字乐园", "Digital Playground / 数字乐园", "DIGITALPLAYGROUND"]),
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

# verify remain
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


def has_colloquial(ent: dict) -> bool:
    return bool(str(ent.get("card") or "").strip())


def has_intro(ent: dict) -> bool:
    intro = str(ent.get("intro") or "").strip()
    return bool(intro) and "由前缀目录同步补全" not in intro


cat = store.load_catalog(force=True)
by_maker = defaultdict(list)
for rid in REGION_ORDER:
    for p, e in (cat["regions"][rid].get("prefixes") or {}).items():
        m = str((e or {}).get("maker") or "").strip()
        if m:
            by_maker[m].append((rid, p))

remain = []
for m, prefs in sorted(by_maker.items(), key=lambda x: -len(x[1])):
    key = resolve(m)
    if not key:
        remain.append(("NO_ENTRY", m, len(prefs)))
        continue
    ent = makers[key]
    if not has_colloquial(ent) or not has_intro(ent):
        remain.append(("INCOMPLETE", key, len(prefs)))

print(f"\ncatalog unique makers: {len(by_maker)}")
print(f"makers.json entries: {len(makers)}")
print(f"remain incomplete: {len(remain)}")
for row in remain[:20]:
    print(" ", row)
