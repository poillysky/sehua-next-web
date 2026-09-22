# -*- coding: utf-8 -*-
"""Apply user corrections; dump ALL remaining weak maker metas."""
from __future__ import annotations
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "apps/maps/makers/makers.json"
doc = json.loads(PATH.read_text(encoding="utf-8"))
aliases: dict = doc.setdefault("aliases", {})
makers: dict = doc.setdefault("makers", {})

# (resolve_keys, card, i18n, intro, extra_aliases)
FIXES = [
    (["ドグマ", "Dogma", "DOGMA"], "Dogma",
     ["Dogma", "ドグマ", "Dogma"],
     "2001年由监督TOHJIRO创立。主打硬核SM、拘束、深喉、变态系，风格极端、艺术感强，业界硬核标杆。",
     ["犬马"]),
    (["IDEA POCKET", "Idea Pocket"], "IP社",
     ["IP社 / Idea Pocket", "アイデアポケット", "IDEA POCKET"],
     "美少女单体路线老牌厂。以高质量颜值、剧情、FIRST IMPRESSION出道系列闻名，专属女优众多。",
     ["理念口袋", "想法口袋", "IP", "IP社"]),
    (["Center Village", "センタービレッジ"], "Center Village",
     ["Center Village", "センタービレッジ", "Center Village"],
     "熟女・人妻专业厂。以中年、熟女、近亲、人妻题材为主，作品量大。",
     ["中心村", "中心乡村"]),
    (["Glory Quest", "グローリークエスト"], "Glory Quest",
     ["Glory Quest", "グローリークエスト", "Glory Quest"],
     "硬核・拘束・凌辱・体液系厂。风格偏激烈，有铁拘束、潮吹等特色系列。",
     ["光荣任务", "光荣探索"]),
    (["ビッグモーカル", "Big Morkal"], "Big Morkal",
     ["Big Morkal", "ビッグモーカル", "Big Morkal"],
     "素人・人妻・ナンパ文档系老牌厂。以街拍、中出人妻、真实记录风格著称。",
     ["大莫卡", "大摩卡"]),
    (["いきなりエロざんまい"], "いきなりエロざんまい",
     ["いきなりエロざんまい", "いきなりエロざんまい", "Ikinari Erozanmai"],
     "素人ナンパ・ハメ撮り配信レーベル。多重新包装既有素人作品。",
     ["突然エロ盛宴"]),
    (["アクアモール/エマニエル"], "Aqua Mall / エマニエル",
     ["Aqua Mall / エマニエル", "アクアモール/エマニエル", "Aqua Mall"],
     "エマニエル集团旗下，人妻・熟女题材。",
     ["水上商场/Emaniel", "水上商场"]),
    (["カルマ", "Karma"], "Karma",
     ["Karma", "カルマ", "Karma"],
     "盗撮・偷拍・真实记录风格老牌厂。",
     ["业力"]),
    (["エロチカ", "Erotica"], "Erotica",
     ["Erotica", "エロチカ", "Erotica"],
     "老牌厂，风格多元，含剧情、凌辱、单体作品。",
     ["情色卡"]),
    (["投稿マーケット素人イッてQ"], "投稿マーケット素人イッてQ",
     ["投稿マーケット素人イッてQ", "投稿マーケット素人イッてQ", "Toukou Market"],
     "素人投稿平台系列，真实用户投稿的素人作品。「イッてQ」为双关品牌名。",
     ["投稿市场素人去Q"]),
    (["TeamSkeet", "TEAMSKEET"], "TeamSkeet",
     ["TeamSkeet", "TeamSkeet", "TeamSkeet"],
     "年轻女优、清新与硬核并存的大型厂牌。",
     ["队小子"]),
    (["Anal Vids", "ANALVIDS"], "Anal Vids",
     ["Anal Vids", "Anal Vids", "Anal Vids"],
     "专注肛交题材的系列/平台。",
     ["肛门视频"]),
    (["Hunter", "HUNTER"], "猎人",
     ["猎人 / Hunter", "ハンター", "Hunter"],
     "家庭与情境企划多，猎户题材与潜入系作品常见。",
     ["猎户"]),
    # intros only / short updates
    (["Hsoda", "HSODA"], "Hsoda",
     ["Hsoda", "エイチソーダ", "Hsoda"],
     "以NTR、特殊体质、乳首・アナル等偏门题材为主的企画厂牌。",
     []),
    (["FAIR＆WAY", "FAIR&WAY", "Fair & Way"], "Fair & Way",
     ["Fair & Way", "フェアアンドウェイ", "FAIR&WAY"],
     "以巨乳女优单体作品为主的厂牌，画质较高，常拍丰满身材。",
     []),
    (["MBM"], "MBM",
     ["MBM", "エムビーエム", "MBM"],
     "素人・人妻系小众厂牌，作品量不大。",
     []),
    (["YONAKA"], "YONAKA",
     ["YONAKA", "ヨナカ", "YONAKA"],
     "以「夜」为主题的剧情向厂牌，主打夜间背德、诱惑、人妻题材。",
     []),
    (["ケラ工房"], "ケラ工房",
     ["ケラ工房", "ケラ工房", "Kera Kobo"],
     "小众厂牌，作品较少，风格偏特殊。",
     []),
    (["ミル", "Miru"], "ミル",
     ["ミル / Miru", "ミル", "Miru"],
     "小众厂牌，作品量少。",
     ["米尔"]),
    (["Jackson", "390JAC"], "杰克逊",
     ["杰克逊", "ジャクソン", "Jackson"],
     "MGS系素人レーベル，主打ギャル到清纯多种类型的真实素人。",
     []),
    (["JapornXXX", "JAPORNXXX"], "日产无码",
     ["日产无码", "ジャポルノXXX", "JapornXXX"],
     "无码综合平台/系列，涵盖多种日本无码内容。",
     []),
    (["Amateur Kikaku"], "Amateur Kikaku",
     ["Amateur / 素人企划", "素人企画", "Amateur Kikaku"],
     "素人企画合集向系列。",
     []),
    (["BAZOOKA"], "BAZOOKA",
     ["BAZOOKA", "バズーカ", "BAZOOKA"],
     "KMP旗下企画レーベル，主打巨乳、ギャル、素人合集。",
     []),
    (["Crystal", "クリスタル映像"], "Crystal",
     ["Crystal", "クリスタル映像", "Crystal"],
     "老牌企画厂牌，作品风格多元。",
     []),
    (["JET映像", "JET"], "JET映像",
     ["JET映像", "JET映像", "JET"],
     "以NTR（被绿）题材著称的厂牌，代表系列「くやしいのでそのままAV発売」。",
     []),
]


def resolve_key(cands: list[str]) -> str | None:
    low = {k.casefold(): k for k in makers}
    for c in cands:
        if c in makers:
            return c
        if c.casefold() in low:
            return low[c.casefold()]
        t = aliases.get(c)
        if t and t in makers:
            return t
    return None


for cands, card, i18n, intro, extra in FIXES:
    key = resolve_key(cands)
    if not key:
        # create under first cand
        key = cands[0]
        print(f"CREATE {key}")
    ent = dict(makers.get(key) or {})
    ent["card"] = card
    ent["i18n"] = i18n
    ent["intro"] = intro
    makers[key] = ent
    for a in cands + extra:
        if a:
            aliases[a] = key
    # special: merge JET -> JET映像
    if key == "JET映像" and "JET" in makers and "JET" != key:
        aliases["JET"] = "JET映像"
    print(f"OK {key} | {card}")

# Fix Hunter intro - remove 猎户 wording
if "Hunter" in makers:
    makers["Hunter"]["intro"] = "家庭与情境企划多见，猎人题材与潜入系作品常见。"

PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"updated {PATH}")

# ---- dump ALL remaining weak ----
WEAK = re.compile(
    r"较少见|小众厂牌|需具体|由前缀目录同步|综合量产|综合企划|综合大厂|综合单体|待确认|不明|风格多元$|公开资料有限"
)
HAN = re.compile(r"[\u4e00-\u9fff]")

remain = []
for key, ent in sorted(makers.items()):
    if not isinstance(ent, dict):
        continue
    card = str(ent.get("card") or "").strip()
    intro = str(ent.get("intro") or "").strip()
    reasons = []
    if not intro:
        reasons.append("无介绍")
    elif WEAK.search(intro) or len(intro) < 14:
        reasons.append("介绍偏弱")
    if not card:
        reasons.append("无card")
    elif not HAN.search(card) and not any(HAN.search(str(x)) for x in (ent.get("i18n") or [])):
        # English-only is OK if intentional; only flag if intro also weak
        if "介绍偏弱" in reasons or "无介绍" in reasons:
            reasons.append("无中文名")
    if reasons:
        remain.append((key, card, intro, "·".join(reasons)))

out = ROOT / "data/debug/makers-remain-review.tsv"
lines = ["#\tkey\tcard\treason\tintro\n"]
print(f"\n=== 剩余待审全部 ({len(remain)}) ===")
for i, (k, c, intro, reason) in enumerate(remain, 1):
    print(f"{i:3d}. [{k}] card={c}  ({reason})")
    print(f"     intro: {intro or '(空)'}")
    lines.append(f"{i}\t{k}\t{c}\t{reason}\t{intro}\n")
out.write_text("".join(lines), encoding="utf-8")
print(f"\nwrote {out}")
