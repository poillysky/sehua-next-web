# -*- coding: utf-8 -*-
"""Thicken weak maker intros + weak/missing prefix intros."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# 厂牌介绍：与现有 ok 条目同量级（一句定位）
MAKER_INTRO: dict[str, str] = {
    "PRESTIGE": "蚊香社系大厂，专属女优与素人街访、企划片体量都很大。",
    "Venus": "熟女人妻剧情大厂，家庭伦理与出轨题材产量高。",
    "ナチュラルハイ": "极限企划老牌，痴汉・露出・公开场合玩法出名。",
    "タカラ映像": "人妻家庭剧老厂，继子・邻居等伦理戏是主轴。",
    "プレミアム": "气质单体精品线，强调完成度与专属女优质感。",
    "WANZ": "痴女与强势女性向厂牌，节奏快、玩法直球。",
    "アキノリ": "明纪系纪实/情境企划厂，恶搞与日常情景并重。",
    "ROCKET": "奇葩道具与极端企划著称，脑洞向作品多。",
    "Million": "偶像风综合厂，单体与企划、VR 线并存。",
    "MAX-A": "综合单体老厂，女优单片与系列作品并重。",
    "Planet Plus": "熟女家政妇/家庭角色企划，日常感强。",
    "REbecca": "写真级美艳单体厂，偏形象展示与高完成度单片。",
    "Amateur Kikaku": "素人企划合集向，街头与约拍风格作品多。",
    "ながえSTYLE": "背德与阴郁美学剧情厂，心理戏与和姦氛围突出。",
    "アイエナジー": "素人与量产企划厂，题材杂、片量大。",
    "痴女ヘブン": "痴女天堂，主动进攻与群戏、女优主导向明显。",
    "変態紳士倶楽部": "偷拍/偷窥风邻居人妻企划，情景代入感强。",
    "Nanpa Japan": "搭讪纪实系合集厂，街头ナンパ与约拍为主。",
    "LEO": "熟女量产系列厂，合集与长时程作品常见。",
    "S级素人": "街头高颜值素人向，约拍与素人单片为主。",
    "DAHLIA": "精品人妻戏剧厂，气质单体与完成度取向明确。",
    "U＆K": "女同与轻调教向专业厂，关系戏细腻。",
    "FAプロ": "昭和风情色剧情老厂，怀旧氛围与戏剧感强。",
    "山と空": "户外露出与极限企划，野外・公开场景为主。",
    "赤面女子": "害羞素人女子向，初体验与紧张感题材多。",
    "SCOOP": "偷拍/猎奇纪实风，窥探与现场感是卖点。",
    "LUNATICS": "暗黑幻想与禁忌题材企划，氛围偏压抑。",
    "Boin Box": "巨乳专题厂，胸围向单体与企划为主。",
    "KSB企画": "熟女与地方感题材，纪实风人妻作品多。",
    "ROYD": "弟弟向/家庭情境剧情，关系崩坏戏常见。",
    "フリーダム": "脚・颜面等恋物企划专业向。",
    "フォーカス": "特写与局部恋物、NTR 关系戏并存。",
    "宇宙企画": "偶像风经典老厂，美少女单体传统强。",
    "かぐや姫Pt": "轻度调教与角色扮演企划，题材轻快。",
    "コスモス映像": "人妻 NTR 纪实风，出轨偷情题材为主。",
    "人妻花園劇場": "戏剧向人妻厂，感情线与家庭冲突并重。",
    "TEPPAN": "铁板高强度纪实向，汗水感与体能戏突出。",
    "GIGOLO": "综合企划厂，题材覆盖广、量产向。",
    "マザー": "母亲角色与禁忌家庭剧，熟女向明确。",
    "美人魔女": "美艳熟女专题，形象与魅力展示为主。",
    "ミセスの素顔": "纪实素人妻，素颜日常感与真实感取向。",
    "Materiall": "材质感与恋物企划，服装/触感题材多见。",
    "ボニータ": "性感/拉丁风企划向，肢体表现突出。",
    "Muteki": "「无敌」跨界名人出道企划，单发冲击强。",
    "Mothers": "熟女・人妻系小众厂，母亲角色题材常见。",
    "h.m.p": "历史悠久的综合老厂，传统单体与系列并存。",
    "MILK": "年轻向企划厂，清新单体与主题片为主。",
}

# 补全缺 i18n 的厂牌
MAKER_I18N: dict[str, list[str]] = {
    "Nanpa Japan": ["Nanpa Japan / ナンパジャパン", "ナンパジャパン", "Nanpa Japan"],
    "S级素人": ["S级素人", "S級素人", "S-class Amateur"],
}

# 前缀介绍补厚（missing + weak）
PREFIX_INTRO: dict[str, str] = {
    # missing
    "KTRA": "K-Tribe 旗下番号，综合企划与单体并存。",
    "CMN": "Cinemagic 调教/拘束系专业前缀。",
    "TCD": "Trans Club 伪娘/ニューハーフ专业前缀。",
    "SMD": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "GMA": "Global Media Annex 旗下前缀，综合企划向。",
    "TG": "库内少量品番，暂归其他有码；厂牌署名待补全。",
    "YM": "库内少量品番，暂归其他有码；厂牌署名待补全。",
    "MILK": "MILK 年轻向企划主线。",
    "SAO": "库内少量品番，暂归其他有码；厂牌署名待补全。",
    # weak — high volume first
    "MEYD": "溜池ゴロー现行主力线，人妻出轨剧情为主。",
    "MXGS": "MAXING 主流综合单片线，女优单体量大。",
    "JUC": "Madonna 早期 DVD 人妻主线，经典熟女剧情。",
    "HMN": "本中较新中出主线，浓厚玩法直球。",
    "DV": "アリスJAPAN 老牌女优单片线。",
    "DASD": "ダスッ！上一代主线，强势凌辱/NTR 氛围。",
    "NACR": "Planet Plus 人妻家政妇角色企划主线。",
    "GVH": "Glory Quest 现行综合企划线，题材覆盖广。",
    "HND": "本中中出专题主力线。",
    "NHDTA": "ナチュラルハイ现行企划线，极限情景向。",
    "VRKM": "V&R PRODUCE 的 VR 主力前缀。",
    "DSVR": "SOD 系 VR 企划线（含ダスッ！VR 等）。",
    "GVG": "Glory Quest 上一代综合企划线。",
    "DVAJ": "アリスJAPAN 较新常见单片线。",
    "SW": "アキノリ「交换夫妇」等情境企划旁支。",
    "CLUB": "変態紳士倶楽部主线，偷拍风邻居人妻。",
    "WAAA": "WANZ 现行主力线，痴女/强势女性向。",
    "HUNTB": "Hunter 常见企划变体系列。",
    "MVSD": "M's Video 吞精/精液系企划主线。",
    "FSET": "アキノリ经典情境企划线。",
    "HUNTC": "Hunter 较新企划线。",
    "JUFE": "Fitch 较新肉感/丰满女优线。",
    "XRW": "REAL 现行多见企划/单体线。",
    "HBAD": "ヒビノ剧情线，人妻与凌辱题材常见。",
    "NATR": "ビッグモーカル/なでしこ 人妻剧情线。",
    "JUKD": "Madonna 最早人妻主线之一。",
    "UMD": "LEO 熟女量产合集主线。",
    "DVDES": "DEEP'S 较早企划线。",
    "MKMP": "Million 现行更常见的综合单片线。",
    "DLDSS": "DAHLIA 人妻戏剧单片主线。",
    "IESP": "アイエナジー 素人/企划主线。",
    "AUKG": "U&K 女同系专业前缀。",
    "MUKD": "無垢 清纯外表下的禁忌感主线。",
    "ARM": "アロマ企画 近景/恋物企划主线。",
    "HAVD": "ヒビノ较早剧情线，人妻与凌辱常见。",
    "DVMM": "DEEP'S 现行企划线。",
    "NITR": "クリスタル映像 旗下综合企划前缀。",
    "SORA": "山と空 户外露出企划主线。",
    "RKI": "ROOKIE 综合企划与精选线。",
    "SCPX": "SCOOP（スクープ）偷拍/猎奇纪实主线。",
    "YSN": "桃太郎映像 常见主线。",
    "LULU": "LUNATICS 暗黑幻想企划主线。",
    "MISM": "えむっ娘ラボ 调教/硬核企划线。",
    "SMA": "マルクス兄弟（SMA）综合企划线。",
    "KSBJ": "KSB企画 熟女人妻纪实主线。",
    "NGOD": "JET映像 人妻 NTR / 出轨偷情线。",
    "VENX": "Venus 较新熟女剧情线。",
    "SNOS": "S1 过渡期专属线。",
    "MUDR": "無垢 漫画改编/禁忌剧情线。",
    "URVRSP": "PRESTIGE VR 企划线。",
    "AARM": "アロマ企画 较新近景/恋物企划。",
    "MILD": "Million 早期/旁支综合线。",
    "ROYD": "ROYD 关系崩坏戏剧企划主线。",
    "NFDM": "フリーダム 脚颜面恋物企划主线。",
    "BDSR": "ビッグモーカル 综合/人妻企划前缀。",
    "NKKD": "JET映像 人妻 NTR 旁支线。",
    "FOCS": "フォーカス NTR/关系戏与特写向。",
    "IENF": "アイエナジー 较新素人/企划线。",
    "YMDD": "桃太郎映像 常见主线变体。",
    "NASS": "なでしこ 精选/特别篇合集。",
    "VRTM": "V&R PRODUCE 综合企划前缀。",
    "NHDTC": "ナチュラルハイ 较新极限企划线。",
    "JRZE": "センタービレッジ 熟女人妻系前缀。",
    "HZGD": "人妻花園劇場 戏剧向人妻主线。",
    "MIRD": "Moodyz 大型企划/多人向。",
    "PXVR": "PRESTIGE VR 旁支企划。",
    "KAVR": "kawaii* VR 专属/企划线。",
    "MIST": "Mr.Michiru 企划前缀。",
    "TPPN": "TEPPAN 高强度纪实/铁板主线。",
    "GS": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "AKDL": "アキノリ 恶搞情景企划线。",
    "MXSPS": "MAXING 精选/合集盘线。",
    "MOT": "マザー 母亲角色禁忌剧情主线。",
    "BIJN": "美人魔女 美艳熟女专题主线。",
    "MDVR": "Moodyz VR 企划线。",
    "OFJE": "S1 精选集/合集盘。",
    "MIBD": "Moodyz 旧作精选合集。",
    "APAK": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "JURA": "センタービレッジ 五十路纪录片线。",
    "NACT": "Planet Plus 人妻家政妇企划旁支。",
    "BACJ": "Bermuda（バミューダ）小众企划前缀。",
    "EMBZ": "EMBZ 小众独立系企划前缀。",
    "JKSR": "ビッグモーカル 人妻/素人企划前缀。",
    "FJIN": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "MFYD": "溜池ゴロー 旁支/特别番号。",
    "FLAV": "Digital Ark / FLAVOUR 系企划前缀。",
    "MRSS": "ミセスの素顔 纪实素人妻主线。",
    "MVG": "M's Video 关联企划前缀。",
    "BMW": "WANZ 综合企划/精选旁支。",
    "ONSD": "S1 早期精选合集。",
    "JUNY": "Fitch 丰满旁支线。",
    "MIZD": "Moodyz 新作精选合集。",
    "BBI": "痴女ヘブン 较早痴女主动进攻线。",
    "MKCK": "E-BODY 精选合集线。",
    "IDBD": "IDEA POCKET 精选合集盘。",
    "MUKC": "無垢 较新禁忌/清纯向线。",
    "HUNBL": "Hunter 蓝光/特别版一类。",
    "HTHD": "センタービレッジ 熟女纪录片旁支。",
    "NDRA": "JET映像 人妻 NTR 旁支。",
    "OVG": "Glory Quest 合集/特别篇。",
    "MUCD": "無垢 合集/精选向。",
    "MIKR": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "MDON": "Madonna 配信限定人妻线。",
    "RBB": "ROOKIE 精选/合集旁支。",
    "ATKD": "Attackers 精选打包盘。",
    "BAGR": "BALTAN（バグス）系小众企划前缀。",
    "SACE": "MAX-A 早期旁支/特别线。",
    "NUKA": "センタービレッジ 母乳/特殊题材旁支。",
    "ANB": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "HNDS": "本中 系列/合集盘。",
    "NGHJ": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "MKD": "Mothers 熟女人妻系前缀。",
    "OFES": "S1 特别篇与企划合集。",
    "FCDSS": "FALENO 精选合集。",
    "PPSD": "OPPAI 特别篇/旁支。",
    "DAVK": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "DAZD": "ダスッ！精选合集。",
    "SAL": "SHEMALE a la carte 伪娘专业前缀。",
    "HODV": "h.m.p 常见单体主线。",
    "USAG": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "BID": "痴女ヘブン 旁支痴女线。",
    "CLOT": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "HHF": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "IPSD": "IDEA POCKET 少量旁支。",
    "KWBD": "kawaii* 精选合集。",
    "BLO": "PRESTIGE 人妻向旁支。",
    "HNDB": "本中 少量打包/精选。",
    "GAJK": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "MOOC": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "KRND": "本中 中出题材旁支。",
    "GARA": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "KAPD": "kawaii* 合辑/特别番号。",
    "SODS": "SOD 综合/旁支企划。",
    "DOJN": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "DEL": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "KOJA": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "RLMP": "REAL（レアル）旁支前缀。",
    "SITW": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "UMAN": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "OERO": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "YDNS": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "HRDV": "h.m.p 历史系列旁支。",
    "NAD": "DOC 旗下少量前缀。",
    "NNOD": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "SKTH": "アキノリ 恶搞情景少量旁支。",
    "FLNS": "FALENO 少量旁支。",
    "MSQ": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "MZQ": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "PRWF": "プレミアム 新线/旁支。",
    "SPND": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
    "TEAM": "库内稳定品番，暂归其他有码；厂牌署名待补全。",
}


def main() -> None:
    makers_path = ROOT / "apps/maps/makers/makers.json"
    pref_path = ROOT / "apps/maps/prefixes/prefixes.json"
    av_path = ROOT / "apps/maps/makers/av-makers.japan.json"

    mdoc = json.loads(makers_path.read_text(encoding="utf-8"))
    makers = mdoc.setdefault("makers", {})
    m_ok = m_miss = 0
    for key, intro in MAKER_INTRO.items():
        ent = makers.get(key)
        if not isinstance(ent, dict):
            print("MISS_MAKER", key)
            m_miss += 1
            continue
        ent["intro"] = intro
        if key in MAKER_I18N:
            ent["i18n"] = MAKER_I18N[key]
        m_ok += 1
    makers_path.write_text(
        json.dumps(mdoc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    pdoc = json.loads(pref_path.read_text(encoding="utf-8"))
    items = pdoc.setdefault("prefixes", {})
    p_ok = p_new = 0
    for pref, intro in PREFIX_INTRO.items():
        ent = items.get(pref)
        if not isinstance(ent, dict):
            ent = {}
            items[pref] = ent
            p_new += 1
        ent["intro"] = intro
        # 其他有码类统一 i18n
        if intro.startswith("库内稳定品番"):
            ent["i18n"] = ["その他有码 / 其他有码", "その他有码", "Other Censored"]
        p_ok += 1
    pref_path.write_text(
        json.dumps(pdoc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    # sync av-makers descriptions for thickened makers
    av = json.loads(av_path.read_text(encoding="utf-8"))
    av_n = 0
    for row in av:
        if not isinstance(row, dict):
            continue
        mk = str(row.get("maker") or "")
        if mk in MAKER_INTRO:
            row["description"] = MAKER_INTRO[mk]
            av_n += 1
        # also match by common aliases
    # map alternate names in av-makers
    alt = {
        "PRESTIGE": ["PRESTIGE", "プレステージ"],
        "WANZ": ["WANZ", "ワンズファクトリー", "WANZ FACTORY"],
        "プレミアム": ["プレミアム", "PREMIUM"],
        "ナチュラルハイ": ["ナチュラルハイ", "Natural High"],
        "タカラ映像": ["タカラ映像", "Takara Eizou"],
        "アキノリ": ["アキノリ", "AKNR"],
        "痴女ヘブン": ["痴女ヘブン"],
        "変態紳士倶楽部": ["変態紳士倶楽部"],
        "アイエナジー": ["アイエナジー"],
        "ながえSTYLE": ["ながえSTYLE"],
        "U＆K": ["U＆K", "U&K"],
        "山と空": ["山と空"],
        "コスモス映像": ["コスモス映像"],
        "人妻花園劇場": ["人妻花園劇場"],
        "かぐや姫Pt": ["かぐや姫Pt"],
        "宇宙企画": ["宇宙企画"],
        "ミセスの素顔": ["ミセスの素顔"],
        "ボニータ": ["ボニータ"],
        "マザー": ["マザー"],
        "フリーダム": ["フリーダム"],
        "フォーカス": ["フォーカス"],
        "FAプロ": ["FAプロ"],
        "KSB企画": ["KSB企画"],
        "美人魔女": ["美人魔女"],
        "赤面女子": ["赤面女子"],
    }
    for row in av:
        if not isinstance(row, dict):
            continue
        mk = str(row.get("maker") or "")
        for canon, names in alt.items():
            if mk in names and canon in MAKER_INTRO:
                row["description"] = MAKER_INTRO[canon]
                av_n += 1
                break
    av_path.write_text(
        json.dumps(av, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    print(f"makers thickened={m_ok} missing={m_miss}")
    print(f"prefixes thickened={p_ok} newly_created={p_new}")
    print(f"av-makers descriptions touched≈{av_n}")


if __name__ == "__main__":
    main()
