# -*- coding: utf-8 -*-
"""Second pass: lengthen remaining short prefix intros (>=20 chars)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

PREFIX_INTRO: dict[str, str] = {
    "HND": "本中中出专题主力线，浓厚玩法与直球题材并重。",
    "FSET": "アキノリ经典情境企划线，日常情景与恶搞并存。",
    "HUNTC": "Hunter 较新企划线，街头猎奇与情景剧情常见。",
    "UMD": "LEO 熟女量产合集主线，长时程与合辑作品多。",
    "DVDES": "DEEP'S 较早企划线，魔镜号等街头企画出身。",
    "IESP": "アイエナジー素人与企划主线，题材杂、片量大。",
    "AUKG": "U&K 女同系专业前缀，关系戏与轻调教细腻。",
    "MUKD": "無垢清纯外表下的禁忌感主线，反差题材突出。",
    "DVMM": "DEEP'S 现行企划线，街头与情景企画为主。",
    "SORA": "山と空户外露出企划主线，野外公开场景为主。",
    "YSN": "桃太郎映像常见主线，综合企划与单体并存。",
    "KSBJ": "KSB企画熟女人妻纪实主线，地方感题材多见。",
    "VENX": "Venus 较新熟女剧情线，家庭伦理与出轨戏多。",
    "SNOS": "S1 过渡期专属线，衔接旧专属与现行番号。",
    "MUDR": "無垢漫画改编与禁忌剧情线，清纯反差向。",
    "YMDD": "桃太郎映像常见主线变体，综合企划向。",
    "NASS": "なでしこ精选与特别篇合集，人妻题材打包。",
    "HZGD": "人妻花園劇場戏剧向人妻主线，感情冲突强。",
    "AKDL": "アキノリ恶搞情景企划线，轻松搞笑向多见。",
    "MXSPS": "MAXING 精选与合集盘线，旧作打包为主。",
    "MOT": "マザー母亲角色禁忌剧情主线，熟女家庭戏。",
    "BIJN": "美人魔女美艳熟女专题主线，形象展示取向。",
    "MDVR": "Moodyz VR 企划线，沉浸式专属与企划并存。",
    "OFJE": "S1 精选集与合集盘，专属女优作品打包。",
    "MIBD": "Moodyz 旧作精选合集，经典单体回顾向。",
    "EMBZ": "EMBZ 小众独立系企划前缀，库内稳定品番。",
    "MFYD": "溜池ゴロー旁支与特别番号，人妻剧情延伸。",
    "MRSS": "ミセスの素顔纪实素人妻主线，素颜日常感强。",
    "BMW": "WANZ 综合企划与精选旁支，题材覆盖较杂。",
    "ONSD": "S1 早期精选合集，专属女优回顾打包。",
    "JUNY": "Fitch 丰满旁支线，肉感女优企划向。",
    "MIZD": "Moodyz 新作精选合集，近期单体打包。",
    "MKCK": "E-BODY 精选合集线，身材向作品打包。",
    "MUKC": "無垢较新禁忌与清纯向线，反差题材延续。",
    "MUCD": "無垢合集与精选向，清纯禁忌题材打包。",
    "RBB": "ROOKIE 精选与合集旁支，综合企划打包。",
    "SACE": "MAX-A 早期旁支与特别线，历史番号残留。",
    "HNDS": "本中系列与合集盘，中出专题作品打包。",
    "OFES": "S1 特别篇与企划合集，专属周边向。",
    "FCDSS": "FALENO 精选合集，流媒体厂作品打包。",
    "PPSD": "OPPAI 特别篇与旁支，巨乳题材延伸。",
    "DAZD": "ダスッ！精选合集，强势凌辱题材打包。",
    "HODV": "h.m.p 常见单体主线，传统女优单片向。",
    "BID": "痴女ヘブン旁支痴女线，主动进攻题材。",
    "KWBD": "kawaii* 精选合集，美少女专属作品打包。",
    "BLO": "PRESTIGE 人妻向旁支，街访/企划延伸。",
    "HNDB": "本中少量打包与精选，中出专题合辑。",
    "KRND": "本中中出题材旁支，直球玩法延续。",
    "SODS": "SOD 综合与旁支企划，制作线延伸番号。",
    "RLMP": "REAL（レアル）旁支前缀，企划向作品。",
    "HRDV": "h.m.p 历史系列旁支，老牌厂早期番号。",
    "NAD": "DOC 旗下少量前缀，素人企划延伸。",
    "SKTH": "アキノリ恶搞情景少量旁支，轻松向。",
    "FLNS": "FALENO 少量旁支，流媒体厂延伸番号。",
    "MILK": "MILK 年轻向企划主线，清新单体与主题片。",
    "PRWF": "プレミアム新线与旁支，气质单体延伸。",
}


def main() -> None:
    path = ROOT / "apps/maps/prefixes/prefixes.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    items = doc.setdefault("prefixes", {})
    n = 0
    short = []
    for pref, intro in PREFIX_INTRO.items():
        ent = items.setdefault(pref, {})
        ent["intro"] = intro
        n += 1
        if len(intro) < 16:
            short.append((pref, len(intro), intro))
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"updated={n} still_short={len(short)}")
    for p, ln, t in short:
        print(f"  SHORT {p} len={ln} {t}")


if __name__ == "__main__":
    main()
