# -*- coding: utf-8 -*-
"""前缀厂牌三语名：中文 / 日文（英文）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .db import ROOT
from .region_meta import std_prefix

# maker 主名（av-makers 里的 maker 字段）→ (zh, ja, en)
MAKER_I18N: dict[str, tuple[str, str, str]] = {
    # —— 有码大厂（人工校对 2026-09）——
    "S1 NO.1 STYLE": ("S1 / 第一风格", "エスワン ナンバーワンスタイル", "S1 NO.1 STYLE"),
    "MOODYZ": ("Moodyz / 慕迪斯", "ムーディーズ", "MOODYZ"),
    "IDEA POCKET": ("Idea Pocket", "アイデアポケット", "IDEA POCKET"),
    "Madonna": ("Madonna / 麦当娜", "マドンナ", "Madonna"),
    "Fitch": ("Fitch", "フィッチ", "Fitch"),
    "Attackers": ("Attackers / 攻击者", "アタッカーズ", "Attackers"),
    "プレミアム": ("Premium / 高级", "プレミアム", "PREMIUM"),
    "PRESTIGE": ("Prestige / 普雷斯提奇", "プレステージ", "PRESTIGE"),
    "E-BODY": ("E-BODY", "E-BODY", "E-BODY"),
    "OPPAI": ("OPPAI", "おっぱい", "OPPAI"),
    "kawaii": ("kawaii* / 卡哇伊", "kawaii*", "kawaii"),
    "本中": ("本中", "本中", "Hon-Naka"),
    "ダスッ！": ("Das!", "ダスッ！", "Das!"),
    "WANZ": ("Wanz Factory / 顽姿", "ワンズファクトリー", "WANZ FACTORY"),
    "FALENO": ("FALENO / 法雷诺", "ファレノ", "FALENO"),
    "SOD Create": ("SOD Create / SOD制作", "SODクリエイト", "SOD Create"),
    "溜池ゴロー": ("溜池五郎", "溜池ゴロー", "Tameike Goro"),
    "無垢": ("无垢", "無垢", "Muku"),
    "痴女ヘブン": ("痴女天堂", "痴女ヘブン", "Chijo Heaven"),
    "ビビアン": ("Bibian", "ビビアン", "Bibian"),
    "kira☆kira": ("Kira Kira", "キラ☆キラ", "kira☆kira"),
    "BeFree": ("BeFree", "BeFree", "BeFree"),
    "ROOKIE": ("ROOKIE", "ルーキー", "ROOKIE"),
    "ROCKET": ("Rocket", "ロケット", "ROCKET"),
    "MAXING": ("Maxing", "マキシング", "MAXING"),
    "Glory Quest": ("Glory Quest", "グローリークエスト", "Glory Quest"),
    "Hunter": ("Hunter / 猎人", "ハンター", "Hunter"),
    "DEEP'S": ("Deeps", "ディープス", "DEEP'S"),
    "DANDY": ("Dandy / 丹迪", "ダンディ", "DANDY"),
    "ナチュラルハイ": ("Natural High / 自然高", "ナチュラルハイ", "Natural High"),
    "アイエナジー": ("IEnergy", "アイエナジー", "IEnergy"),
    "アキノリ": ("AKNR / 明纪", "アキノリ", "AKNR"),
    "アリスJAPAN": ("Alice Japan / 爱丽丝日本", "アリスJAPAN", "Alice Japan"),
    "クリスタル映像": ("Crystal", "クリスタル映像", "Crystal Eizou"),
    "センタービレッジ": ("Center Village", "センタービレッジ", "Center Village"),
    "タカラ映像": ("Takara Eizou", "タカラ映像", "Takara Eizou"),
    "ヒビノ": ("Hibino", "ヒビノ", "Hibino"),
    "ドリームチケット": ("Dream Ticket", "ドリームチケット", "Dream Ticket"),
    "オーロラプロジェクト": ("Aurora Project", "オーロラプロジェクト", "Aurora Project"),
    "エムズビデオ": ("M's Video", "エムズビデオグループ", "M's Video Group"),
    "サディスティックヴィレッジ": ("Sadistic Village", "サディスティックヴィレッジ", "Sadistic Village"),
    "セレブの友": ("Celeb no Tomo", "セレブの友", "Celeb no Tomo"),
    "コスモス映像": ("Cosmos", "コスモス映像", "Cosmos Eizou"),
    "アロマ企画": ("阿洛玛企划 / 芳香企划", "アロマ企画", "Aroma Planning"),
    "KSB企画": ("KSB", "KSB企画", "KSB Kikaku"),
    "JET映像": ("JET", "JET映像", "JET Eizou"),
    "Venus": ("Venus / 维纳斯", "ヴィーナス", "Venus"),
    "MAX-A": ("Max-A", "マックスエー", "MAX-A"),
    "Million": ("Million", "ミリオン", "Million"),
    "h.m.p": ("h.m.p", "エイチエムピー", "h.m.p"),
    "Muteki": ("Muteki", "ミュートキ", "Muteki"),
    "DAHLIA": ("DAHLIA", "ダリア", "DAHLIA"),
    "BAZOOKA": ("Bazooka", "バズーカ", "BAZOOKA"),
    "SCOOP": ("SCOOP", "スクープ", "SCOOP"),
    "REAL": ("REAL", "レアル", "REAL"),
    "DOC": ("DOC", "ドック", "DOC"),
    "Mr.Michiru": ("Mr.Michiru / 美汁流", "ミスターミチル", "Mr.Michiru"),
    "ROYD": ("ROYD", "ロイド", "ROYD"),
    "Materiall": ("Materiall", "マテリアル", "Materiall"),
    "LUNATICS": ("LUNATICS", "ルナティックス", "LUNATICS"),
    "TEPPAN": ("TEPPAN", "テッパン", "TEPPAN"),
    "V＆R PRODUCE": ("V&R PRODUCE", "ブイアンドアールプロデュース", "V&R PRODUCE"),
    "U＆K": ("U&K", "ユーアンドケー", "U&K"),
    "えむっ娘ラボ": ("Muko Lab", "えむっ娘ラボ", "Emuko Labo"),
    "かぐや姫Pt": ("辉夜姬", "かぐや姫Pt", "Kaguya Hime Pt"),
    "ながえSTYLE": ("永江STYLE", "ながえSTYLE", "Nagae STYLE"),
    "なでしこ": ("Nadeshiko", "なでしこ", "Nadeshiko"),
    "ビッグモーカル": ("Big Morkal", "ビッグモーカル", "Big Morkal"),
    "フォーカス": ("Focus", "フォーカス", "Focus"),
    "フリーダム": ("Freedom", "フリーダム", "Freedom"),
    "プラネットプラス": ("Planet Plus", "プラネットプラス", "Planet Plus"),
    "ボニータ": ("Bonita", "ボニータ", "Bonita"),
    "マザー": ("Mother", "マザー", "Mother"),
    "マルクス兄弟": ("Marx Brothers", "マルクス兄弟", "Marx Brothers"),
    "ミセスの素顔": ("人妻素颜", "ミセスの素顔", "Mrs no Sugao"),
    "変態紳士倶楽部": ("变态绅士俱乐部", "変態紳士倶楽部", "Hentai Shinshi Club"),
    "宇宙企画": ("宇宙企划", "宇宙企画", "Uchu Kikaku"),
    "山と空": ("山与空", "山と空", "Yama to Sora"),
    "桃太郎": ("桃太郎映像", "桃太郎映像出版", "Momotaro"),
    "人妻花園劇場": ("人妻花园剧场", "人妻花園劇場", "Hitozuma Hanazono"),
    "美人魔女": ("美人魔女", "美人魔女", "Bijin Majo"),
    "舞ワイフ": ("舞Wife", "舞ワイフ", "Mywife"),
    "赤面女子": ("赤面女子", "赤面女子", "Sekimen Joshi"),
    "ナンパJAPAN": ("Nanpa Japan", "ナンパJAPAN", "Nanpa JAPAN"),
    "AVS collector": ("AVS", "AVScollector", "AVS collector"),
    "Boin Box": ("BoinBB", "ボインボックス", "Boin Box"),
    "GIGOLO": ("GIGOLO", "ジゴロ", "GIGOLO"),
    "LEO": ("LEO", "レオ", "LEO"),
    "MILK": ("MILK", "ミルク", "MILK"),
    "FAプロ": ("FA Pro", "FAプロ", "FA Pro"),
    "REbecca": ("REbecca", "レベッカ", "REbecca"),
    "その他有码": ("其他有码", "その他有码", "Other Censored"),
    "其它写真": ("其他写真", "その他グラビア", "Other Gravure"),
    "素人企划": ("素人企划", "素人企画", "Amateur Kikaku"),
    # —— 无码 ——
    "一本道": ("一本道", "一本道", "1pondo"),
    "加勒比": ("加勒比", "カリビアンコム", "Caribbeancom"),
    "HEYZO": ("HEYZO", "ヘイゾー", "HEYZO"),
    "金8天国": ("金8天国", "金髪天国", "Kin8tengoku"),
    "其它无码": ("其他无码", "その他無修正", "Other Uncensored"),
    "S-Cute": ("S-Cute", "エスキュート", "S-Cute"),
    "S-cute": ("S-Cute", "エスキュート", "S-Cute"),
    # —— FC2 / 欧美 / 国产 ——
    "FC2": ("FC2", "FC2", "FC2"),
    "Brazzers": ("Brazzers / 布拉泽斯", "ブラザーズ", "Brazzers"),
    "Bang Bros": ("Bang Bros / 砰兄弟", "バングブロス", "Bang Bros"),
    "Blacked / Vixen": ("Blacked / 黑蚀", "ブラックド", "Blacked / Vixen"),
    "Naughty America": ("Naughty America / 顽皮美国", "ノーティーアメリカ", "Naughty America"),
    "Reality Kings": ("Reality Kings / 现实国王", "リアリティキングス", "Reality Kings"),
    "Evil Angel": ("Evil Angel / 邪恶天使", "イービルエンジェル", "Evil Angel"),
    "Jules Jordan": ("Jules Jordan / 朱尔斯", "ジュールス・ジョーダン", "Jules Jordan"),
    "LegalPorno": ("LegalPorno / 合法色情", "リーガルポルノ", "LegalPorno"),
    "Dorcel / Private": ("Dorcel / 多塞尔", "ドーセル", "Dorcel / Private"),
    "Mofos / FakeHub": ("Mofos / 莫福斯", "モーフォス", "Mofos / FakeHub"),
    "OnlyFans / ManyVids": ("OnlyFans / 订阅粉丝", "オンリーファンズ", "OnlyFans / ManyVids"),
    "Pure Taboo": ("Pure Taboo / 纯禁忌", "ピュアタブー", "Pure Taboo"),
    "其它欧美": ("Other Western / 其他欧美", "その他西洋", "Other Western"),
    "FC2": ("FC2 / 同人平台", "FC2", "FC2"),
    "其它写真": ("Other Gravure / 其他写真", "その他グラビア", "Other Gravure"),
    "REbecca": ("REbecca / 丽贝卡", "レベッカ", "REbecca"),
    "其它国产": ("Other Chinese / 其他国产", "その他中国", "Other Chinese"),
    "E-BODY": ("E-BODY / 好身材", "E-BODY", "E-BODY"),
    "BeFree": ("BeFree / 比弗利", "ビーフリー", "BeFree"),
    "ダスッ！": ("Das! / 达斯", "ダスッ！", "Das!"),
    "IDEA POCKET": ("Idea Pocket", "アイデアポケット", "IDEA POCKET"),
    "AVS collector": ("AVS / 收藏家", "AVScollector", "AVS collector"),
    "Million": ("Million / 百万", "ミリオン", "Million"),
    "MAX-A": ("MAX-A / 麦克斯", "マックスエー", "MAX-A"),
    "ROCKET": ("ROCKET / 火箭", "ロケット", "ROCKET"),
    "kira☆kira": ("kira☆kira / 闪闪", "キラ☆キラ", "kira☆kira"),
    "ビビアン": ("Bibian / 女同", "ビビアン", "Bibian"),
    "痴女ヘブン": ("Chijo Heaven / 痴女天堂", "痴女ヘブン", "Chijo Heaven"),
    "本中": ("Hon-Naka / 本中", "本中", "Hon-Naka"),
    "アリスJAPAN": ("Alice Japan / 爱丽丝日本", "アリスJAPAN", "Alice Japan"),
    "アキノリ": ("AKNR / 明纪", "アキノリ", "AKNR"),
    "アロマ企画": ("Aroma / 阿洛玛企划", "アロマ企画", "Aroma Planning"),
    "h.m.p": ("h.m.p", "エイチエムピー", "h.m.p"),
    "HEYZO": ("HEYZO", "ヘイゾー", "HEYZO"),
    "金8天国": ("Kin8tengoku / 金8天国", "金髪天国", "Kin8tengoku"),
    "S-Cute": ("S-Cute", "エスキュート", "S-Cute"),
    "S-cute": ("S-Cute", "エスキュート", "S-Cute"),
    "Amateur Kikaku": ("Amateur / 素人企划", "素人企画", "Amateur Kikaku"),
    "素人企划": ("Amateur / 素人企划", "素人企画", "Amateur Kikaku"),
    "其它无码": ("Other Uncensored / 其他无码", "その他無修正", "Other Uncensored"),
    "その他有码": ("Other Censored / 其他有码", "その他有码", "Other Censored"),
    "其它写真": ("Other Gravure / 其他写真", "その他グラビア", "Other Gravure"),
    "其它国产": ("Other Chinese / 其他国产", "その他中国", "Other Chinese"),
    "其它欧美": ("Other Western / 其他欧美", "その他西洋", "Other Western"),
    "FC2": ("FC2 / 同人平台", "FC2", "FC2"),
    "REbecca": ("REbecca / 丽贝卡", "レベッカ", "REbecca"),
    "E-BODY": ("E-BODY / 好身材", "E-BODY", "E-BODY"),
    "BeFree": ("BeFree / 比弗利", "ビーフリー", "BeFree"),
    "ダスッ！": ("Das! / 达斯", "ダスッ！", "Das!"),
    "DANDY": ("DANDY / 丹迪", "ダンディ", "DANDY"),
    "DEEP'S": ("DEEP'S / 深斯", "ディープス", "DEEP'S"),
    "Hunter": ("Hunter / 猎人", "ハンター", "Hunter"),
    "ナチュラルハイ": ("Natural High / 自然高", "ナチュラルハイ", "Natural High"),
    "FALENO": ("FALENO / 法雷诺", "ファレノ", "FALENO"),
    "WANZ": ("WANZ FACTORY / 顽姿", "ワンズファクトリー", "WANZ FACTORY"),
    "プレミアム": ("PREMIUM / 高级", "プレミアム", "PREMIUM"),
    "SOD Create": ("SOD Create / SOD制作", "SODクリエイト", "SOD Create"),
    "PRESTIGE": ("PRESTIGE / 普雷斯提奇", "プレステージ", "PRESTIGE"),
    "kawaii": ("kawaii / 卡哇伊", "kawaii*", "kawaii"),
    "Attackers": ("Attackers / 攻击者", "アタッカーズ", "Attackers"),
    "Madonna": ("Madonna / 麦当娜", "マドンナ", "Madonna"),
    "MOODYZ": ("MOODYZ / 慕迪斯", "ムーディーズ", "MOODYZ"),
    "S1 NO.1 STYLE": ("S1 NO.1 STYLE / 第一风格", "エスワン ナンバーワンスタイル", "S1 NO.1 STYLE"),
    "Venus": ("Venus / 维纳斯", "ヴィーナス", "Venus"),
    "桃太郎": ("Momotaro / 桃太郎映像", "桃太郎映像出版", "Momotaro"),
    "一本道": ("1pondo / 一本道", "一本道", "1pondo"),
    "加勒比": ("Caribbeancom / 加勒比", "カリビアンコム", "Caribbeancom"),
    "Brazzers": ("Brazzers / 布拉泽斯", "ブラザーズ", "Brazzers"),
    "Bang Bros": ("Bang Bros / 砰兄弟", "バングブロス", "Bang Bros"),
    "Blacked / Vixen": ("Blacked / 黑蚀", "ブラックド", "Blacked / Vixen"),
    "Naughty America": ("Naughty America / 顽皮美国", "ノーティーアメリカ", "Naughty America"),
    "Reality Kings": ("Reality Kings / 现实国王", "リアリティキングス", "Reality Kings"),
    "Evil Angel": ("Evil Angel / 邪恶天使", "イービルエンジェル", "Evil Angel"),
    "Jules Jordan": ("Jules Jordan / 朱尔斯", "ジュールス・ジョーダン", "Jules Jordan"),
    "LegalPorno": ("LegalPorno / 合法色情", "リーガルポルノ", "LegalPorno"),
    "Dorcel / Private": ("Dorcel / 多塞尔", "ドーセル", "Dorcel / Private"),
    "Mofos / FakeHub": ("Mofos / 莫福斯", "モーフォス", "Mofos / FakeHub"),
    "OnlyFans / ManyVids": ("OnlyFans / 订阅粉丝", "オンリーファンズ", "OnlyFans / ManyVids"),
    "Pure Taboo": ("Pure Taboo / 纯禁忌", "ピュアタブー", "Pure Taboo"),
    "91制片厂": ("91 Produce / 91制片厂", "91制片厂", "91 Produce"),
    "麻豆传媒": ("Madou Media / 麻豆传媒", "麻豆傳媒", "Madou Media"),
    "天美传媒": ("Tianmei / 天美传媒", "天美傳媒", "Tianmei Media"),
    "果冻传媒": ("Jelly Media / 果冻传媒", "果凍傳媒", "Jelly Media"),
    "蜜桃影像": ("Mitao / 蜜桃影像", "蜜桃影像", "Mitao Media"),
    "大象传媒": ("Elephant / 大象传媒", "大象傳媒", "Elephant Media"),
    "星空无限传媒": ("Star Unlimited / 星空无限", "星空無限傳媒", "Star Unlimited"),
    "皇家华人": ("Royal Chinese / 皇家华人", "皇家華人", "Royal Chinese"),
    "精东影业": ("Jingdong / 精东影业", "精東影業", "Jingdong"),
    "起点传媒": ("Qidian / 起点传媒", "起點傳媒", "Qidian Media"),
    "扣扣传媒": ("Koukou / 扣扣传媒", "扣扣傳媒", "Koukou Media"),
    "性视界传媒": ("Sex Vision / 性视界", "性視界傳媒", "Sex Vision"),
    "爱豆传媒": ("Idol Media / 爱豆传媒", "愛豆傳媒", "Idol Media"),
    "猫爪影像": ("Catclaw / 猫爪影像", "貓爪影像", "Catclaw"),
    "杏吧传媒": ("Xingba / 杏吧传媒", "杏吧傳媒", "Xingba"),
    "色控传媒": ("Sex Control / 色控传媒", "色控傳媒", "Sex Control"),
    "萝莉社": ("Lolita Club / 萝莉社", "蘿莉社", "Lolita Club"),
    "辣椒原创": ("Lajiao / 辣椒原创", "辣椒原創", "Lajiao Original"),
    "香蕉秀": ("Banana Show / 香蕉秀", "香蕉秀", "Banana Show"),
    "兔子先生": ("Mr Rabbit / 兔子先生", "兔子先生", "Mr Rabbit"),
    "三只狼": ("Three Wolves / 三只狼", "三隻狼", "Three Wolves"),
    "人妻斩": ("Hitodzuma / 人妻斩", "人妻斬", "Hitodzuma Zan"),
    "绝对领域": ("Absolute Territory / 绝对领域", "絶対領域", "Absolute Territory"),
}

# 厂牌短介绍（中文）：供货架/前缀卡展示；key 与 MAKER_I18N 主名对齐
MAKER_INTRO: dict[str, str] = {
    "S1 NO.1 STYLE": '软片一线大厂，主打美人单体与高制作质感',
    "SOD Create": '制作主力，素人纪录片与企划题材丰富',
    "MOODYZ": '老牌综合厂，单体与企划并重，番号线庞大',
    "IDEA POCKET": '偶像风与剧情单体见长',
    "Madonna": '人妻熟女向大厂，剧情与熟女魅力并重',
    "Fitch": '巨乳肉感向，强调体型与浓密互动',
    "Attackers": '强势凌辱/NTR 剧情厂，氛围偏暗',
    "プレミアム": '气质单体与高完成度作品',
    "PRESTIGE": '素人街访与企划片量大',
    "E-BODY": '身材特化厂，巨乳纤腰等体型卖点鲜明',
    "OPPAI": '胸器专题厂，巨乳玩法与系列感强',
    "kawaii": '清纯可爱单体，偏年轻偶像风',
    "本中": '中出专题厂，浓厚玩法与企划并行',
    "ダスッ！": '硬派凌辱/激烈向，压迫感强',
    "WANZ": '痴女与强势女性向题材多',
    "FALENO": '流媒体出身新厂，画质与宣传强',
    "溜池ゴロー": '人妻出轨/禁忌关系剧情见长',
    "無垢": '清纯禁忌向，少女感与背德设定',
    "痴女ヘブン": '主动进攻与群戏多',
    "ビビアン": '女同专题厂，百合向作品集中',
    "kira☆kira": '辣妹黑辣妹向，派对与夸张风格',
    "BeFree": '都市OL/职场风单体与剧情',
    "ROOKIE": '出道与新鲜面孔向，偏发掘新人',
    "ROCKET": '奇葩企划与道具玩法出名',
    "MAXING": '综合企划厂，系列与单体并存',
    "Glory Quest": '熟女/人妻与剧情向较多',
    "Hunter": '猎户，家庭与情境企划多',
    "DEEP'S": '深度企划与街头/情境实验',
    "DANDY": '电车痴汉等情境企划经典厂',
    "ナチュラルハイ": '痴汉/露出等极限企划',
    "アイエナジー": '素人与企划片量大',
    "アキノリ": '纪实风与情境企划',
    "アリスJAPAN": '老牌厂，单体与系列传统强',
    "クリスタル映像": '综合量产与系列多',
    "センタービレッジ": '熟女中心村，五十路等熟女向',
    "タカラ映像": '人妻戏剧与家庭伦理',
    "ヒビノ": '日比野，清纯与调教向并存',
    "ドリームチケット": '企划与角色扮演',
    "オーロラプロジェクト": 'Aurora，剧情与氛围片',
    "エムズビデオ": "M's，口技与浓厚玩法专题",
    "サディスティックヴィレッジ": '虐村，极限凌辱与群体企划',
    "セレブの友": '名媛之友，熟女人妻向',
    "コスモス映像": '人妻NTR 纪实风',
    "アロマ企画": '阿洛玛，轻微恋物与近景企划',
    "KSB企画": '熟女与地方感题材',
    "JET映像": '黑人/跨文化等刺激企划',
    "Venus": '熟女人妻剧情量大',
    "MAX-A": '综合单体与系列',
    "Million": '偶像风与企划',
    "h.m.p": '老牌厂，单体传统与系列',
    "Muteki": '无敌，跨界名人出道企划',
    "DAHLIA": '精品剧情与气质单体',
    "BAZOOKA": '企划与合集向',
    "SCOOP": '偷拍/猎奇纪实风',
    "REAL": '硬派写实与强制向',
    "DOC": '素人纪实与访谈风',
    "ROYD": '弟弟向/家庭情境剧情',
    "Materiall": '材质感与恋物企划',
    "LUNATICS": '暗黑幻想向',
    "TEPPAN": '铁板系列与合集',
    "V＆R PRODUCE": 'V&R，恶搞企划与奇葩设定',
    "U＆K": '女同与轻调教向',
    "えむっ娘ラボ": 'M 女实验室，受向调教专题',
    "かぐや姫Pt": '轻度调教与角色向',
    "ながえSTYLE": '背德剧情与阴郁美学',
    "なでしこ": '专注人妻熟女，偏日常剧情与写实演技',
    "ビッグモーカル": '熟女与合集向',
    "フォーカス": '特写与局部恋物',
    "フリーダム": '脚颜面等恋物企划',
    "プラネットプラス": '熟女与家庭剧',
    "ボニータ": '拉丁风/性感向',
    "マザー": '母亲角色与禁忌剧情',
    "マルクス兄弟": '马克思兄弟，老牌综合企划',
    "ミセスの素顔": '纪实素人妻',
    "変態紳士倶楽部": '偷拍/偷窥向',
    "宇宙企画": '偶像风经典老厂',
    "山と空": '户外露出与极限企划',
    "桃太郎": '综合与特色系列',
    "人妻花園劇場": '戏剧向人妻',
    "美人魔女": '美艳熟女专题',
    "舞ワイフ": '人妻出轨纪实风',
    "赤面女子": '害羞素人女子向',
    "ナンパJAPAN": '搭讪素人纪实',
    "AVS collector": '恋物与特殊嗜好合集',
    "Boin Box": '巨乳专题',
    "GIGOLO": '综合企划',
    "LEO": '熟女与量产系列',
    "MILK": '年轻向与企划',
    "FAプロ": '昭和风情色剧情',
    "REbecca": '写真级美艳单体',
    "S级素人": '街头素人高颜值向',
    "KMP": '综合大厂与多品牌线',
    "SWITCH": '家庭错位/情境喜剧企划',
    "NON": '清淡素人与日常风',
    "Unfinished": '未完结企划风',
    "Next Group": '综合量产厂牌群',
    "Planet Plus": '熟女家庭剧',
    "Sadistic Village": '虐村，极限凌辱与群体企划',
    "JET": '黑人/跨文化刺激企划',
    "Takara": '人妻戏剧与伦理剧情',
    "Crystal": '综合量产与系列',
    "Royd": '弟弟向家庭情境剧情',
    "Nagae STYLE": '背德剧情与阴郁美学',
    "Nadeshiko": '专注人妻熟女，偏日常剧情与写实演技',
    "Premium": '气质单体与高完成度',
    "Natural High": '痴汉/露出等极限企划',
    "Prestige": '素人街访与企划量大',  # —— 无码 / 素人平台 ——
    "一本道": '无码官网，单体高清制作',
    "加勒比": '无码官网长片经典',
    "HEYZO": '无码官网，更新勤题材广',
    "金8天国": '金发天国，欧美向无码专题',
    "S-Cute": '清新短片与可爱风',
    "S-cute": '清新短片与可爱风',  # —— 国产 / 欧美摘要 ——
    "FC2": '同人平台，个人撮影与素人为主',
    "麻豆传媒": '麻豆，国产影视化剧情大厂',
    "天美传媒": '天美，国产剧情与系列制作',
    "果冻传媒": '果冻，国产都市剧情向',
    "蜜桃影像": '蜜桃，国产情色短剧风',
    "Brazzers": '欧美巨头，剧情桥段与明星卡司',
    "Naughty America": '邻居/情境系列经典',
}

# 前缀短介绍（比厂牌简介更具体；key 为大写前缀）
PREFIX_INTRO: dict[str, str] = {
    # —— S1 ——
    "SONE": "S1 现行主力专属线，新人与一线单体",
    "SSIS": "S1 上一代主力专属，美人单体高制作",
    "SSNI": "S1 经典专属线，偶像级单体全盛期",
    "SNIS": "S1 较早专属番号，单体成长期作品",
    "SOE": "S1 早期经典专属，老番号名作多",
    "ONED": "S1 草创期专属线，早期单体",
    "SNOS": "S1 过渡期专属线",
    "SIVR": "S1 的 VR 专属作品",
    "OFJE": "S1 精选集/合集盘",
    "OFES": "S1 特别篇与企划合集",
    # —— SOD Create ——
    "STARS": "SOD STAR 现行专属女优线",
    "START": "SOD STAR 系列变体番号",
    "STAR": "SOD STAR 较早专属线",
    "SAVR": "SOD 的 VR 企划与专属",
    "SDDE": "SOD 脑洞企划，情境实验味重",
    "SDMU": "SOD 魔术/街头素人企划",
    "SDMT": "SOD 剧场向企划与情境片",
    "SDNM": "SOD 人妻/素人「初次拍摄」向",
    "SDJS": "SOD 女子社员企划",
    "SDAM": "SOD 业余纪实企划",
    # —— Venus ——
    "VENU": "Venus 主力：婆媳/亲属禁忌剧情",
    "VEC": "Venus 熟女职场与人妻剧情",
    "VENX": "Venus 较新剧情线",
    "VAGU": "Venus 岳母/义母题材",
    "VEMA": "Venus 人妻出轨与家庭剧",
    # —— Attackers ——
    "SHKD": "Attackers 凌辱剧情主力线",
    "RBD": "Attackers 束缚/调教氛围剧情",
    "SAME": "Attackers 现行剧情线",
    "RBK": "Attackers 调教向关联线",
    "SSPD": "Attackers 高规格特别篇",
    "ATID": "Attackers 攻击/凌辱剧情",
    "ADN": "Attackers 不倫/禁忌情感剧",
    "AED": "Attackers 早期关联番号",
    "JBD": "Attackers 蛇缚等硬调教线",
    # —— Natural High ——
    "NHDTB": "自然高现行主力：痴汉/车内等极限企划",
    "NHDTA": "自然高现行企划线",
    "NHDTC": "自然高较新企划线",
    "NHDT": "自然高经典痴汉/露出企划",
    # —— Premium ——
    "PRED": "Premium 现行 Elegance 专属线",
    "PGD": "Premium 旧 Glamorous 专属线",
    "PFES": "Premium 特别篇/祭典企划",
    "PBD": "Premium 精选合集",
    "PJD": "Premium Jewel 线",
    "PXD": "Premium XANADU 线",
    "PRST": "Premium 关联特别番号",
    # —— OPPAI ——
    "PPPD": "OPPAI 主力巨乳专属线",
    "PPPE": "OPPAI 较新巨乳专属线",
    "PPBD": "OPPAI 巨乳精选合集",
    "PPSD": "OPPAI 特别篇",
    # —— WANZ ——
    "WANZ": "WANZ 主力：痴女与强势女向",
    "WAAA": "WANZ 较新主力线",
    # —— Nadeshiko ——
    "NASH": "なでしこ 人妻熟女主力线",
    "NATR": "なでしこ 人妻剧情线",
    "NASS": "なでしこ 精选/特别篇",
    "NADE": "なでしこ 经典人妻线",
    "NASK": "なでしこ 寝取/剪辑企划向",
    # —— ROCKET ——
    "RCT": "ROCKET 奇葩道具与脑洞企划",
    "RCTD": "ROCKET 较新奇葩企划线",
    # —— Madonna ——
    "JUL": "Madonna 主力人妻专属线",
    "JUQ": "Madonna 现行人妻专属线",
    "JUR": "Madonna 人妻剧情线",
    "JUY": "Madonna 人妻专属线",
    "JUX": "Madonna 较早人妻专属",
    "JUSD": "Madonna 人妻合集盘",
    "ROE": "Madonna 熟女/母亲向线",
    "OBA": "Madonna 叔母/年长女性向",
    "URE": "Madonna 漫画改编/熟女特别线",
    "ALDN": "Madonna 关联熟女线",
    "ACHJ": "Madonna 痴女人妻向",
    # —— REbecca ——
    "REBD": "REbecca 写真级美艳单体（BD）",
    "REBDB": "REbecca 写真单体另一编号",
    # —— S级素人 ——
    "SUPA": "S级素人 街头高颜值素人",
    "SABA": "S级素人 约拍/访谈风素人",
    # —— ながえSTYLE ——
    "NSFS": "永江 STYLE 现行背德剧情",
    "NSPS": "永江 STYLE 经典背德剧情",
    # —— タカラ映像 ——
    "SPRD": "宝映像 人妻家庭伦理剧主力",
    "MOND": "宝映像 周一剧场等人妻剧",
    # —— Moodyz 常见 ——
    "MIDE": "Moodyz 经典专属单体",
    "MIDV": "Moodyz 现行专属单体",
    "MIAA": "Moodyz 企划/痴女向",
    "MIAB": "Moodyz 较新企划线",
    "MIMK": "Moodyz 漫画改编企划",
    "MIGD": "Moodyz 解禁/浓厚向经典",
    "MIFD": "Moodyz 出道作线",
    # —— IdeaPocket ——
    "IPX": "IdeaPocket 主力专属单体",
    "IPZZ": "IdeaPocket 现行专属线",
    "IPZ": "IdeaPocket 较早专属单体",
    "IPTD": "IdeaPocket 早期专属",
    # —— Prestige 常见 ——
    "ABP": "Prestige 专属女优主力线",
    "CHN": "Prestige「到自宅」企划",
    "BGN": "Prestige 专属出道作",
    "DIC": "Prestige 职业设定企划",
    "SGA": "Prestige 轻熟女向",
    "YRZ": "Prestige OL/上班族向",
    # —— 本中 / kawaii / E-BODY 等 ——
    "HND": "本中 中出专题主力",
    "HMN": "本中 较新中出线",
    "KAWD": "kawaii* 清纯可爱专属",
    "EBOD": "E-BODY 身材特化专属",
    "EYAN": "E-BODY 人妻身材向",
    "JUFD": "Fitch 巨乳肉感主力",
    "JUFE": "Fitch 较新肉感线",
    "BF": "BeFree 都市风单体/剧情",
    "TEK": "Muteki 艺能人跨界出道",
}

# 前缀级覆盖（无码官网系 / 素人 MGStage 等）
PREFIX_I18N: dict[str, tuple[str, str, str]] = {
    # uncensored
    "HEYZO": ("HEYZO", "ヘイゾー", "HEYZO"),
    "1PON": ("一本道", "一本道", "1pondo"),
    "CARIB": ("加勒比", "カリビアンコム", "Caribbeancom"),
    "CARIBPR": ("加勒比Premium", "カリビアンコムプレミアム", "Caribbeancom Premium"),
    "10MU": ("天然少女", "天然むすめ", "10musume"),
    "10MUSUME": ("天然少女", "天然むすめ", "10musume"),
    "PACO": ("啪啪妈妈", "パコパコママ", "Pacopacomama"),
    "PACOMA": ("啪啪妈妈", "パコパコママ", "Pacopacomama"),
    "H0930": ("好色0930", "エッチな0930", "H0930"),
    "H4610": ("好色4610", "エッチな4610", "H4610"),
    "C0930": ("人妻0930", "人妻斬り/C0930", "C0930"),
    "KIN8": ("金8天国", "金髪天国", "Kin8tengoku"),
    "NYOSHIN": ("女体神秘", "女体のしんぴ", "Nyoshin"),
    "TOKYO": ("东京热", "東京熱", "Tokyo-Hot"),
    "PT": ("东京热PT", "東京熱 PT", "Tokyo-Hot PT"),
    "XXXAV": ("XXX-AV", "XXX-AV", "XXX-AV"),
    "HEYDOUGA": ("Heydouga", "ヘイ動画", "Heydouga"),
    "FELLATIOJAPAN": ("Fellatio Japan", "フェラチオジャパン", "Fellatio Japan"),
    "HANDJOBJAPAN": ("Handjob Japan", "ハンドジョブジャパン", "Handjob Japan"),
    "LEGSJAPAN": ("Legs Japan", "レッグスジャパン", "Legs Japan"),
    "SPERMMANIA": ("Sperm Mania", "スペルママニア", "Sperm Mania"),
    "URALESBIAN": ("Ura Lesbian", "ウラレズビアン", "Ura Lesbian"),
    "URABUKKAKE": ("Ura Bukkake", "ウラブッカケ", "Ura Bukkake"),
    "GACHI": ("Gachinco", "ガチん娘", "Gachinco"),
    "JAPORNXXX": ("JapornXXX", "ジャポルノ", "JapornXXX"),
    "RHJ": ("Red Hot Jam", "レッドホットジャム", "Red Hot Jam"),
    "ROSELIP": ("Rose Lip", "ローゼリップ", "Rose Lip"),
    "ROSELIPFETISH": ("Rose Lip Fetish", "ローゼリップフェティシ", "Rose Lip Fetish"),
    "SMMIRACLE": ("SM-Miracle", "SM-miracle", "SM-Miracle"),
    # amateur cores
    "SIRO": ("素人TV", "シロウトTV", "Shirouto TV"),
    "LUXU": ("Luxury TV", "ラグジュTV", "Luxu TV"),
    "259LUXU": ("Luxury TV", "ラグジュTV", "Luxu TV"),
    "MIUM": ("Prestige Premium", "プレステージプレミアム", "Prestige Premium"),
    "300MIUM": ("Prestige Premium", "プレステージプレミアム", "Prestige Premium"),
    "MAAN": ("真面目软派", "マジ軟派、初撮。", "Maji Nanpa"),
    "300MAAN": ("真面目软派", "マジ軟派、初撮。", "Maji Nanpa"),
    "GANA": ("Nanpa TV", "ナンパTV", "Nanpa TV"),
    "200GANA": ("Nanpa TV", "ナンパTV", "Nanpa TV"),
    "NTK": ("Nanpa天国", "ナンパ天国", "Nanpa Tengoku"),
    "300NTK": ("Nanpa天国", "ナンパ天国", "Nanpa Tengoku"),
    "ARA": ("募集酱", "募集ちゃん", "261ARA"),
    "ORE": ("俺的素人", "俺の素人", "Ore no Shirouto"),
    "OREX": ("俺的素人", "俺の素人", "Ore no Shirouto"),
    "230OREX": ("俺的素人", "俺の素人Z", "Ore no Shirouto"),
    "ORECO": ("俺的素人", "俺の素人", "Ore no Shirouto"),
    "ORECS": ("俺的素人", "俺の素人", "Ore no Shirouto"),
    "ORECZ": ("俺的素人", "俺の素人", "Ore no Shirouto"),
    "JAC": ("Jackson", "Jackson", "Jackson"),
    "390JAC": ("Jackson", "Jackson", "Jackson"),
    "KNB": ("恋慕", "恋慕", "Koi no Bo"),
    "336KNB": ("恋慕", "恋慕", "Koi no Bo"),
    "HMDN": ("ハメ撮り", "ハメ撮り", "Hamedori"),
    "328HMDN": ("ハメ撮り", "ハメ撮りナンパ", "Hamedori"),
    "SCUTE": ("S-Cute", "エスキュート", "S-Cute"),
    "SIROHAME": ("白ハメ", "しろハメ", "Siro Hame"),
    "HAME": ("白ハメ", "しろハメ", "Siro Hame"),
    # —— 有码前缀 ← 人工厂牌表 2026-09 ——
    **{
        p: ("Moodyz / 慕迪斯", "ムーディーズ", "MOODYZ")
        for p in (
            "MIAA", "MIAB", "MIAD", "MIAE", "MIBD", "MIDA", "MIDD", "MIDE", "MIDV",
            "MIFD", "MIGD", "MIKR", "MILD", "MIMK", "MIRD", "MISM", "MIST", "MIZD",
            "MOGI", "MVSD", "MKY",
        )
    },
    **{
        p: ("S1 / 第一风格", "エスワン ナンバーワンスタイル", "S1 NO.1 STYLE")
        for p in (
            "SSIS", "SSNI", "SONE", "SNIS", "SNOS", "SOE", "ONED", "ONSD", "OFJE",
            "OFES", "SIVR",
        )
    },
    **{
        p: ("Idea Pocket", "アイデアポケット", "IDEA POCKET")
        for p in ("IPX", "IPZ", "IPZZ", "IPTD", "IPVR", "IDBD", "IPSD", "IPBD")
    },
    **{
        p: ("Madonna / 麦当娜", "マドンナ", "Madonna")
        for p in (
            "JUL", "JUQ", "JUR", "JUY", "JUX", "JUC", "JUKD", "JUSD",
            "JURA", "JUNY", "ALDN", "OBA", "URE", "ROE", "ACHJ",
        )
    },
    **{
        p: ("Fitch", "フィッチ", "Fitch")
        for p in ("JUFD", "JUFE", "FCX", "BFIT")
    },
    **{
        p: ("Attackers / 攻击者", "アタッカーズ", "Attackers")
        for p in ("ADN", "AED", "ATID", "ATKD", "SHKD", "JBD", "RBD", "RBK", "SAME")
    },
    **{
        p: ("kawaii* / 卡哇伊", "kawaii*", "kawaii")
        for p in ("CAWD", "KWBD", "KAWD", "KAVR")
    },
    **{
        p: ("Prestige / 普雷斯提奇", "プレステージ", "PRESTIGE")
        for p in (
            "ABF", "ABP", "ABS", "ABW", "BGN", "CHN", "PPT", "ONEZ", "SGA", "TRE",
            "BLO", "DIC", "EVO", "INU", "JAN", "MAS", "ESK",
        )
    },
    **{
        p: ("SOD Create / SOD制作", "SODクリエイト", "SOD Create")
        for p in (
            "SDDE", "SDMM", "SDMU", "SDNM", "SDAB", "SDAM", "SDJS", "SDMT",
            "STAR", "STARS", "START", "DSVR", "SAVR", "SODS", "FTN", "SACE",
            "KFNE", "KDMN",
        )
    },
    **{p: ("AKNR / 明纪", "アキノリ", "AKNR") for p in ("AKNR", "AKDL", "SKTH", "FSET")},
    **{p: ("SWITCH / 开关", "スイッチ", "SWITCH") for p in ("SW",)},
    **{
        p: ("Sadistic Village / 残酷村", "サディスティックヴィレッジ", "Sadistic Village")
        for p in ("SVDVD", "SVVRT")
    },
    **{p: ("SPICY VR / 辣味VR", "スパイシーVR", "SPICY VR") for p in ("SPIVR",)},
    **{p: ("DAHLIA / 大丽花", "ダリア", "DAHLIA") for p in ("DLDSS",)},
    **{p: ("本中", "本中", "Hon-Naka") for p in ("HMN", "HND", "HNDB", "HNDS")},
    **{p: ("E-BODY", "E-BODY", "E-BODY") for p in ("EBOD", "EBWH")},
    **{
        p: ("Premium / 高级", "プレミアム", "PREMIUM")
        for p in ("PRED", "PGD", "PBD", "PRST", "PXD")
    },
    **{
        p: ("OPPAI", "おっぱい", "OPPAI")
        for p in ("PPPD", "PPBD", "PPPE", "PPSD", "PPPDV")
    },
    **{p: ("P-BOX VR", "ピーボックスVR", "P-BOX VR") for p in ("PXVR",)},
    **{p: ("Wanz Factory / 顽姿", "ワンズファクトリー", "WANZ FACTORY") for p in ("WAAA", "WANZ")},
    **{p: ("Das!", "ダスッ！", "Das!") for p in ("DASD", "DASS", "DAZD")},
    **{p: ("FALENO / 法雷诺", "ファレノ", "FALENO") for p in ("FSDSS", "FLNS", "FNS", "FCDSS", "FSVSS")},
    **{p: ("Hunter / 猎人", "ハンター", "Hunter") for p in ("HUNT", "HUNTA", "HUNTB", "HUNTC", "HUNBL")},
    **{
        p: ("Natural High / 自然高", "ナチュラルハイ", "Natural High")
        for p in ("NHDT", "NHDTB", "NHDTA", "NHDTC")
    },
    **{p: ("Deeps", "ディープス", "DEEP'S") for p in ("DVDMS", "DVDES", "DVMM")},
    **{p: ("阿洛玛企划 / 芳香企划", "アロマ企画", "Aroma Planning") for p in ("AARM", "ARM")},
    **{p: ("Alice Japan / 爱丽丝日本", "アリスJAPAN", "Alice Japan") for p in ("DVAJ",)},
    **{p: ("Dandy / 丹迪", "ダンディ", "DANDY") for p in ("DANDY",)},
    **{p: ("痴女天堂", "痴女ヘブン", "Chijo Heaven") for p in ("CJOD",)},
    **{p: ("Bibian", "ビビアン", "Bibian") for p in ("BBAN",)},
    **{p: ("Kira Kira", "キラ☆キラ", "kira☆kira") for p in ("BLK",)},
    **{p: ("BeFree", "BeFree", "BeFree") for p in ("BF",)},
    **{p: ("Venus / 维纳斯", "ヴィーナス", "Venus") for p in ("VENU", "VENX", "VEC", "VEMA", "VAGU")},
    **{p: ("Rocket", "ロケット", "ROCKET") for p in ("RCT", "RCTD")},
    **{p: ("Max-A", "マックスエー", "MAX-A") for p in ("XVSR", "SRXV")},
    **{p: ("Million", "ミリオン", "Million") for p in ("MKMP",)},
    **{p: ("h.m.p", "エイチエムピー", "h.m.p") for p in ("HODV",)},
    **{p: ("桃太郎映像", "桃太郎映像出版", "Momotaro") for p in ("YMDD",)},
    **{p: ("Nadeshiko / 抚子", "なでしこ", "Nadeshiko") for p in ("NASH", "NATR", "NASS", "NADE")},
    **{p: ("S级素人", "S級素人", "S-Class Amateur") for p in ("SABA", "SUPA")},
    **{p: ("Nanpa Japan / 搭讪日本", "ナンパJAPAN", "Nanpa Japan") for p in ("NNPJ", "NPJS", "NPJ")},
    **{p: ("NON", "ノン", "NON") for p in ("YSN", "NON")},
    **{p: ("Unfinished", "アンフィニッシュド", "Unfinished") for p in ("URVRSP",)},
    **{p: ("NEXTGROUP", "ネクストグループ", "Next Group") for p in ("VNDS",)},
    **{p: ("Air Control", "エアコントロール", "Air Control") for p in ("OAE",)},
    **{p: ("Trans Club", "トランスクラブ", "Trans Club") for p in ("TCD",)},
    **{p: ("Vi", "ヴィ", "Vi") for p in ("VICD",)},
    **{p: ("Nama Nama", "なまなま", "Nama Nama") for p in ("NAMH",)},
    **{p: ("REAL", "レアルワークス", "REAL") for p in ("XRW", "REAL", "RLMP")},
    "EKDV": ("Crystal / 水晶映像", "クリスタル映像", "Crystal Eizou"),
    "MIST": ("Mr.Michiru / 美汁流", "ミスターミチル", "Mr.Michiru"),
    "GS": ("GOGOS / 走光", "ゴーゴーズ", "GOGOS"),
    "ANB": ("Anbai / 安排", "あんばい", "ANB"),
    "DEL": ("Delicious / 美味", "デリシャス", "DEL"),
    "BF": ("BeFree / 比弗利", "ビーフリー", "BeFree"),
    **{p: ("E-BODY / 好身材", "E-BODY", "E-BODY") for p in ("EBOD", "EBWH")},
    **{p: ("Das! / 达斯", "ダスッ！", "Das!") for p in ("DASD", "DASS", "DAZD")},
    "APAK": ("APAKA / 阿帕卡", "アパカ", "APAKA"),
    "BACJ": ("Bermuda / 百慕大", "バミューダ", "Bermuda"),
    "BAGR": ("BAGUS / 巴古斯", "バグース", "BAGUS"),
    "CLOT": ("Cloth / 布料", "クロース", "CLOTH"),
    "CMN": ("Cinemagic / 电影魔术", "シネマジック", "Cinemagic"),
    "DAVK": ("Dark / 暗黑", "ダーク", "DAVK"),
    "DOJN": ("Dojin / 同人", "同人", "DOJN"),
    "EMBZ": ("EMBZ / 淫美", "エムビーズ", "EMBZ"),
    "FLAV": ("Flavor / 风味", "フレイバー", "FLAVOUR"),
    "GAJK": ("Garage / 车库", "ガレージ", "Garage"),
    "GARA": ("GARA / 加拉", "ガラ", "GARA"),
    "GMA": ("Global Media / 全球媒体", "グローバルメディアアネックス", "Global Media Annex"),
    "HHF": ("High High / 嗨嗨", "ハイハイ", "HHF"),
    "KOJA": ("Koujo / 皇女", "皇女", "KOJA"),
    "KTRA": ("K-Tribe / K部落", "ケートライブ", "K-Tribe"),
    "MKD": ("Mothers / 母亲们", "マザーズ", "Mothers"),
    "MOOC": ("Mook / 穆克", "ムーク", "MOOC"),
    "MSQ": ("Mrs Queen / 人妻女王", "ミセスクイーン", "MSQ"),
    "MVG": ("Movie Gate / 电影门", "ムービーゲート", "MVG"),
    "MZQ": ("Bishoujo / 美少女", "美少女", "MZQ"),
    "NGHJ": ("Nanpa / 搭讪", "ナンパ", "NGHJ"),
    "NNOD": ("NNOD / 诺德", "ノード", "NNOD"),
    "OERO": ("Oero / 哦エロ", "おエロ", "OERO"),
    "RLMP": ("Real / 真实", "リアル", "RLMP"),
    "SAL": ("SAL / 萨尔", "サル", "SAL"),
    "SITW": ("SITW / 西特", "シット", "SITW"),
    "SPND": ("Suspend / 悬停", "サスペンド", "SPND"),
    "UMAN": ("Umanami / 马浪", "ウマナミ", "UMAN"),
    "USAG": ("Usagi / 兔子", "うさぎ", "USAG"),
    "YDNS": ("Yadons / 亚冬", "ヤドンス", "YDNS"),
    "AVOP": ("AVS / 收藏家", "AVScollector", "AVS collector"),
    "AVSA": ("AVS / 收藏家", "AVScollector", "AVS collector"),
    "893NYN": ("Nyan / 喵", "にゃん", "NYN"),
    "908JDH": ("JDH / 素人", "ジェイディーエイチ", "JDH"),
    "GNI": ("Guni / 软萌", "ぐに", "GNI"),
    "IMJO": ("I'm Joe / 乔", "アイムジョー", "IMJO"),
    "JFM": ("JFM / 素人", "ジェイエフエム", "JFM"),
    "PASN": ("Parsley Nanpa / 香菜搭讪", "パセリナンパ", "PASN"),
    "PPX": ("PPX / 素人", "ピーピーエックス", "PPX"),
    "PRVRSS": ("Prestige VR / 普雷斯提奇VR", "プレステージVR", "PRVRSS"),
    "SHF": ("SHF / 素人", "エスエイチエフ", "SHF"),
    "336TUK": ("TUK / 凸", "トゥク", "TUK"),
    "GAREA": ("G-area / G区", "ジーエリア", "G-area"),
    "HIMEMIX": ("Hime Mix / 姬混", "ひめみっくす", "himemix"),
    "KBI": ("KANBi / 完美", "完美", "KANBi"),
    "RFILE": ("R-file / R档案", "アールファイル", "r-file"),
    "BEAF": ("Beef / 牛肉", "ビーフ", "BEAF"),
    "JAC": ("Jackson / 杰克逊", "ジャクソン", "Jackson"),
    "390JAC": ("Jackson / 杰克逊", "ジャクソン", "Jackson"),
    "230ORECO": ("Ore no Shirouto / 俺的素人", "俺の素人", "Ore no Shirouto"),
    # MGStage 素人数字头（与字母有码前缀并存，不可当别名删）
    "107SODS": ("SOD Create / SOD制作", "SODクリエイト", "SOD Create"),
    "107START": ("SOD Create / SOD制作", "SODクリエイト", "SOD Create"),
    "112SVVRT": ("Sadistic Village / 残酷村", "サディスティックヴィレッジ", "Sadistic Village"),
    "136SW": ("SWITCH / 开关", "スイッチ", "SWITCH"),
    "554SPIVR": ("SPICY VR / 辣味VR", "スパイシーVR", "SPICY VR"),
    "201KDMN": ("SOD Create / SOD制作", "SODクリエイト", "SOD Create"),
    "326KFNE": ("SOD Create / SOD制作", "SODクリエイト", "SOD Create"),
    "406FCDSS": ("FALENO / 法雷诺", "ファレノ", "FALENO"),
    "406FNS": ("FALENO / 法雷诺", "ファレノ", "FALENO"),
    "406FSDSS": ("FALENO / 法雷诺", "ファレノ", "FALENO"),
    "406FSVSS": ("FALENO / 法雷诺", "ファレノ", "FALENO"),
    "513DLDSS": ("DAHLIA / 大丽花", "ダリア", "DAHLIA"),
    "336KBL": ("Koi no Bo / 恋慕", "恋慕", "KBL"),
    "SMMIRACLE": ("SM-Miracle / SM奇迹", "SM-miracle", "SM-Miracle"),
    "XXXAV": ("XXX-AV / 解禁AV", "XXX-AV", "XXX-AV"),
    "HEYDOUGA": ("Heydouga / 嘿动画", "ヘイ動画", "Heydouga"),
    "JAPORNXXX": ("JapornXXX / 日产无码", "ジャポルノ", "JapornXXX"),
    "BFAZ": ("Fine Pictures / 精美映像", "ファインピクチャーズ", "Fine Pictures"),
    "GGSID": ("Glaze / 釉彩", "グレイズ", "Glaze"),
    "SYD": ("Spice Visual / 香料视觉", "スパイスビジュアル", "Spice Visual"),
    "REBD": ("REbecca / 丽贝卡", "レベッカ", "REbecca"),
    "REBDB": ("REbecca / 丽贝卡", "レベッカ", "REbecca"),
    "FC2": ("FC2 / 同人平台", "FC2", "FC2"),
    "FC2PPV": ("FC2PPV / 付费同人", "FC2PPV", "FC2PPV"),
    "JVID": ("JVID / 台湾写真", "ジェイヴィッド", "JVID"),
    "HKG": ("Xingkong / 星空无限", "星空無限傳媒", "Star Unlimited"),
    "BRAZZERS": ("Brazzers / 布拉泽斯", "ブラザーズ", "Brazzers"),
    "BANGBROS": ("Bang Bros / 砰兄弟", "バングブロス", "Bang Bros"),
    "BANGBUS": ("Bang Bros / 砰兄弟", "バングブロス", "Bang Bus"),
    "BLACKED": ("Blacked / 黑蚀", "ブラックド", "Blacked"),
    "BLACKEDRAW": ("Blacked Raw / 黑蚀生", "ブラックドロー", "Blacked Raw"),
    "VIXEN": ("Vixen / 狐狸精", "ヴィクセン", "Vixen"),
    "VIXENPLUS": ("Vixen Plus / 狐狸精+", "ヴィクセンプラス", "Vixen Plus"),
    "TUSHY": ("Tushy / 塔希", "タッシー", "Tushy"),
    "TUSHYRAW": ("Tushy Raw / 塔希生", "タッシーロー", "Tushy Raw"),
    "DEEPER": ("Deeper / 更深", "ディーパー", "Deeper"),
    "SLAYED": ("Slayed / 斩获", "スレイド", "Slayed"),
    "MILFY": ("MILFY / 熟女", "ミルフィー", "MILFY"),
    "NAUGHTYAMERICA": ("Naughty America / 顽皮美国", "ノーティーアメリカ", "Naughty America"),
    "REALITYKINGS": ("Reality Kings / 现实国王", "リアリティキングス", "Reality Kings"),
    "RK": ("Reality Kings / 现实国王", "リアリティキングス", "Reality Kings"),
    "RKPRIME": ("RK Prime / 现实国王精选", "RKプライム", "RK Prime"),
    "MOFOS": ("Mofos / 莫福斯", "モーフォス", "Mofos"),
    "FAKETAXI": ("Fake Taxi / 假出租车", "フェイクタクシー", "Fake Taxi"),
    "EVILANGEL": ("Evil Angel / 邪恶天使", "イービルエンジェル", "Evil Angel"),
    "JULESJORDAN": ("Jules Jordan / 朱尔斯", "ジュールス・ジョーダン", "Jules Jordan"),
    "LEGALPORNO": ("LegalPorno / 合法色情", "リーガルポルノ", "LegalPorno"),
    "PORNWORLD": ("PornWorld / 色情世界", "ポルノワールド", "PornWorld"),
    "PRIVATE": ("Private / 私人", "プライベート", "Private"),
    "DORCEL": ("Dorcel / 多塞尔", "ドーセル", "Dorcel"),
    "DORCELCLUB": ("Dorcel Club / 多塞尔俱乐部", "ドーセルクラブ", "Dorcel Club"),
    "DIGITALPLAYGROUND": ("Digital Playground / 数字乐园", "デジタルプレイグラウンド", "Digital Playground"),
    "WICKED": ("Wicked / 邪恶", "ウィキッド", "Wicked"),
    "ELEGANTANGEL": ("Elegant Angel / 优雅天使", "エレガントエンジェル", "Elegant Angel"),
    "LETHALHARDCORE": ("Lethal Hardcore / 致命硬核", "リーサルハードコア", "Lethal Hardcore"),
    "PURETABOO": ("Pure Taboo / 纯禁忌", "ピュアタブー", "Pure Taboo"),
    "ADULTTIME": ("Adult Time / 成人时间", "アダルトタイム", "Adult Time"),
    "AGIRIENE": ("Adult Time / 成人时间", "アダルトタイム", "Adult Time"),
    "TEAMSKEET": ("TeamSkeet / 队小子", "チームスキート", "TeamSkeet"),
    "NUBILES": ("Nubiles / 嫩模", "ヌーバイルズ", "Nubiles"),
    "NUBILEFILMS": ("Nubile Films / 嫩模电影", "ヌーバイルフィルムズ", "Nubile Films"),
    "BRATTYSIS": ("Bratty Sis / 顽皮姐妹", "ブラッティシス", "Bratty Sis"),
    "FAMILYSTROKES": ("Family Strokes / 家庭爱抚", "ファミリーストロークス", "Family Strokes"),
    "PUBLICAGENT": ("Public Agent / 公共探员", "パブリックエージェント", "Public Agent"),
    "SEXART": ("SexArt / 性艺术", "セックスアート", "SexArt"),
    "SEXMEX": ("SexMex / 墨西哥性", "セックスメックス", "SexMex"),
    "WATCH4BEAUTY": ("Watch4Beauty / 赏美", "ウォッチフォービューティー", "Watch4Beauty"),
    "PLAYBOYPLUS": ("Playboy Plus / 花花公子+", "プレイボーイプラス", "Playboy Plus"),
    "MANYVIDS": ("ManyVids / 多视频", "メニーvids", "ManyVids"),
    "ONLYFANS": ("OnlyFans / 订阅粉丝", "オンリーファンズ", "OnlyFans"),
    "ANALVIDS": ("Anal Vids / 肛门视频", "アナルvids", "Anal Vids"),
}


def format_maker_label(zh: str = "", ja: str = "", en: str = "") -> str:
    """最多两个名称：优先英文，其次中文，没有中文则日文。"""
    zh, ja, en = (zh or "").strip(), (ja or "").strip(), (en or "").strip()

    def _clean(s: str) -> str:
        return s.strip(" /")

    def _has_cjk(s: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff]", s or ""))

    def _first_token(s: str) -> str:
        """名称字段里若含 /，只取第一段，避免英文复合成两段后再叠中文。"""
        s = _clean(s)
        if not s:
            return ""
        return _clean(s.split("/", 1)[0])

    def _prefer_cjk_side(s: str) -> str:
        """『英文 / 中文』取中文侧；否则取第一段。"""
        s = _clean(s)
        if " / " in s:
            left, right = s.split(" / ", 1)
            if _has_cjk(right) and not _has_cjk(left):
                return _clean(right)
            if _has_cjk(left):
                return _clean(left)
        if "/" in s:
            parts = [_clean(x) for x in s.split("/") if _clean(x)]
            for part in reversed(parts):
                if _has_cjk(part):
                    return part
            return parts[0] if parts else ""
        return s

    zh, ja, en = _clean(zh), _clean(ja), _clean(en)
    zh_only = _prefer_cjk_side(zh)
    en_only = _first_token(en) if en else ""

    primary = en_only or zh_only or _first_token(ja)
    if not primary:
        return ""

    secondary = ""
    if en_only:
        if _has_cjk(zh_only) and zh_only.casefold() != primary.casefold():
            secondary = zh_only
        elif _has_cjk(ja):
            secondary = _prefer_cjk_side(ja)
    elif _has_cjk(zh_only) and _has_cjk(ja):
        j = _prefer_cjk_side(ja)
        if j and j != zh_only:
            secondary = j

    parts = [primary]
    if (
        secondary
        and secondary.casefold() != primary.casefold()
        and secondary not in primary
        and primary not in secondary
    ):
        parts.append(secondary)

    # 硬限制：最终最多两段
    return " / ".join(parts[:2])


def clamp_maker_label(label: str) -> str:
    """任意展示串裁成最多两个名称。"""
    raw = (label or "").strip()
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    if len(parts) <= 2:
        return " / ".join(parts) if len(parts) > 1 else (parts[0] if parts else "")
    return f"{parts[0]} / {parts[1]}"


def _guess_triple(raw: str) -> tuple[str, str, str]:
    s = (raw or "").strip()
    if not s:
        return "", "", ""
    if s in MAKER_I18N:
        return MAKER_I18N[s]
    # CJK-heavy → treat as ja (or zh for china)
    if re.search(r"[\u4e00-\u9fff]", s) and not re.search(r"[\u3040-\u30ff]", s):
        return s, s, ""
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", s):
        return "", s, ""
    return "", "", s


def load_prefix_maker_base() -> dict[str, str]:
    """prefix → av-makers 原始 maker 字符串。

    日本表优先：国产/欧美与有码撞前缀时（如 MDL）不覆盖日本映射。
    """
    out: dict[str, str] = {}
    cfg = ROOT / "apps" / "web" / "src" / "config"
    # china/western 先填；japan 后写且不丢已有冲突键的日本值——改为 japan 最后覆盖
    for name in ("av-makers.china.json", "av-makers.western.json", "av-makers.japan.json"):
        path = cfg / name
        if not path.exists():
            continue
        for row in json.loads(path.read_text(encoding="utf-8")):
            maker = str(row.get("maker") or "").strip()
            for p in row.get("prefixes") or []:
                key = std_prefix(p)
                if not key or not maker:
                    continue
                # japan 文件最后加载，允许覆盖同名前缀的跨区冲突
                if name.endswith("japan.json") or key not in out:
                    out[key] = maker
    return out


def resolve_maker_names(
    prefix: str,
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, str]:
    """返回 maker_zh / maker_ja / maker_en / maker（展示用合成）。"""
    ent = dict(existing or {})
    pref = std_prefix(prefix)

    zh = str(ent.get("maker_zh") or "").strip()
    ja = str(ent.get("maker_ja") or "").strip()
    en = str(ent.get("maker_en") or "").strip()
    raw = str(ent.get("maker") or "").strip()
    # 若 maker 已是合成展示串，不拿它当 lookup key
    if "（" in raw or "/" in raw:
        raw = str(ent.get("maker_en") or "").strip()

    base = load_prefix_maker_base().get(pref, "")
    lookup = base or raw

    # 精选表优先于 DMM 长名
    if pref in PREFIX_I18N:
        zh, ja, en = PREFIX_I18N[pref]
    elif lookup in MAKER_I18N:
        zh, ja, en = MAKER_I18N[lookup]
    elif base in MAKER_I18N:
        zh, ja, en = MAKER_I18N[base]
    else:
        if base:
            z, j, e = _guess_triple(base)
            zh, ja, en = zh or z, ja or j, en or e
            raw = raw or base
        elif raw:
            z, j, e = _guess_triple(raw)
            zh, ja, en = zh or z, ja or j, en or e

    if not (zh or ja or en):
        en = pref

    label = format_maker_label(zh, ja, en)
    return {
        "maker_zh": zh,
        "maker_ja": ja,
        "maker_en": en,
        "maker": clamp_maker_label(label or raw or pref),
    }


def _strip_redundant_title(text: str, *titles: str) -> str:
    """去掉简介开头重复的厂牌名（标题已展示时不必再说一遍）。"""
    t = str(text or "").strip()
    if not t:
        return ""

    def _compact(s: str) -> str:
        return re.sub(r"\s+", "", str(s or "")).casefold()

    # 长名优先，避免短名误伤
    cands = sorted(
        {str(x or "").strip() for x in titles if str(x or "").strip()},
        key=len,
        reverse=True,
    )
    compact_t = _compact(t)
    for name in cands:
        n_compact = _compact(name)
        if not n_compact:
            continue
        for sep in ("，", ",", "：", ":", " / ", "/", " "):
            # 原文字符串前缀
            needle = name + sep
            if t.startswith(needle) or t.casefold().startswith(needle.casefold()):
                rest = t[len(name) + len(sep) :].strip(" ，,：:/")
                if rest:
                    return rest
            # 忽略空白差异：如「S级素人」vs「S 级素人，…」
            sep_c = _compact(sep) if sep.strip() else ""
            prefix_c = n_compact + (sep_c if sep.strip() else "")
            if sep.strip() and compact_t.startswith(prefix_c):
                # 按原文找第一个分隔符切开
                for ch in ("，", ",", "：", ":"):
                    if ch in t:
                        left, right = t.split(ch, 1)
                        if _compact(left) == n_compact and right.strip():
                            return right.strip()
        if compact_t == n_compact:
            return ""
    return t


def _intro_for_maker_key(key: str) -> str:
    k = str(key or "").strip()
    if not k:
        return ""
    hit = MAKER_INTRO.get(k)
    if hit:
        return hit.strip()
    # CARD 短名 / 展示名反查
    for canon, text in MAKER_INTRO.items():
        if canon.casefold() == k.casefold():
            return text.strip()
    return ""


def resolve_maker_intro_for_prefix(prefix: str) -> str:
    """前缀 → 简介：优先 PREFIX_INTRO，再回退厂牌 MAKER_INTRO。"""
    pref = std_prefix(prefix)
    if not pref:
        return ""
    hit = PREFIX_INTRO.get(pref)
    if hit:
        return hit.strip()
    if pref in PREFIX_I18N:
        zh, _ja, en = PREFIX_I18N[pref]
        for key in (en, zh.split(" / ")[0].strip(), zh):
            hit = _intro_for_maker_key(key)
            if hit:
                return hit
        for canon in MAKER_I18N:
            trip = MAKER_I18N[canon]
            if pref in {canon, trip[0], trip[1], trip[2]} or en == trip[2]:
                hit = _intro_for_maker_key(canon)
                if hit:
                    return hit
    base = load_prefix_maker_base().get(pref, "")
    for key in (base, resolve_maker_names(pref).get("maker_en") or ""):
        hit = _intro_for_maker_key(str(key))
        if hit:
            return hit
    names = resolve_maker_names(pref)
    for key in (
        names.get("maker_en"),
        names.get("maker_zh"),
        names.get("maker_ja"),
        names.get("maker"),
        base,
    ):
        hit = _intro_for_maker_key(str(key or ""))
        if hit:
            return hit
        s = str(key or "").strip()
        if s in MAKER_I18N:
            hit = _intro_for_maker_key(s)
            if hit:
                return hit
        for canon, trip in MAKER_I18N.items():
            if s in trip or s == canon:
                hit = _intro_for_maker_key(canon)
                if hit:
                    return hit
    return ""


def prefix_line_rank(prefix: str, blurb: str = "") -> int:
    """前缀货架优先级：越小越靠前（现行主力 < 上一代 < 旁支 < VR/合集）。"""
    pref = std_prefix(prefix)
    notes = ""
    try:
        path = ROOT / "apps" / "web" / "src" / "config" / "av-makers.japan.json"
        if path.exists():
            for row in json.loads(path.read_text(encoding="utf-8")):
                pn_map = row.get("prefix_notes") or {}
                pn = pn_map.get(pref) or pn_map.get(pref.upper())
                if pn:
                    notes = str(pn)
                    break
    except Exception:  # noqa: BLE001
        notes = ""
    text = f"{blurb or ''} {PREFIX_INTRO.get(pref, '')} {notes}"

    if re.search(r"现行主力|现行主线|现行专属", text):
        return 0
    if re.search(r"较新主力|较新专属|较新主线", text):
        return 1
    if re.search(r"上一代主力|上一代主线", text):
        return 2
    if re.search(r"主力专属|主力线|主力：|主力巨乳|专属女优主力|剧情主力", text):
        return 3
    if re.search(r"经典专属|经典.*线|全盛", text):
        return 4
    if re.search(r"较早|早期|草创|历史主线|更早主线|旧专属", text):
        return 5
    if re.search(r"过渡", text):
        return 6
    if re.search(r"出道", text):
        return 7
    if re.search(r"旁支|企划", text) and not re.search(r"合集|精选", text):
        return 8
    if re.search(r"(?i)(?:^|[^a-z])vr(?:[^a-z]|$)", text):
        return 9
    if re.search(r"合集|精选|特别篇|祭典", text):
        return 10
    return 5


def resolve_maker_intro_for_studio(studio_name: str) -> str:
    """厂牌展示名 / 主名 → 简介（开头不重复厂牌名）。"""
    raw = str(studio_name or "").strip()
    if not raw or raw in {"未标注厂牌", "未标注", "(unknown)"}:
        return ""

    text = ""
    canon_hit = ""

    # 1) 直接命中简介表
    if _intro_for_maker_key(raw):
        text = _intro_for_maker_key(raw)

    try:
        from .studio_display_names import (
            STUDIO_CARD_LABEL,
            preferred_studio_label,
            resolve_studio_display,
            studio_norm_key,
            STUDIO_ALIASES,
        )
    except Exception:
        STUDIO_CARD_LABEL = {}
        preferred_studio_label = None  # type: ignore
        resolve_studio_display = None  # type: ignore
        studio_norm_key = None  # type: ignore
        STUDIO_ALIASES = {}

    def _set_canon(canon: str) -> None:
        nonlocal text, canon_hit
        canon_hit = canon
        if not text:
            text = _intro_for_maker_key(canon)

    # 2) MAKER_I18N / 别名 / 卡片短名 → canon
    if raw in MAKER_I18N:
        _set_canon(raw)
    else:
        for canon, trip in MAKER_I18N.items():
            zh, ja, en = trip
            if raw in {canon, zh, ja, en}:
                _set_canon(canon)
                break
            if " / " in zh and raw in {p.strip() for p in zh.split("/")}:
                _set_canon(canon)
                break

    if not canon_hit and studio_norm_key:
        nk = studio_norm_key(raw)
        for canon, label in STUDIO_CARD_LABEL.items():
            if label == raw or studio_norm_key(label) == nk or canon == raw:
                _set_canon(canon)
                break
        if not canon_hit:
            for alias, canon in STUDIO_ALIASES.items():
                if studio_norm_key(alias) == nk or studio_norm_key(canon) == nk:
                    _set_canon(canon)
                    break
        if not canon_hit and preferred_studio_label and resolve_studio_display:
            for canon in MAKER_I18N:
                label = preferred_studio_label(canon) or resolve_studio_display(canon) or ""
                if label == raw or studio_norm_key(canon) == nk:
                    _set_canon(canon)
                    break

    if not text:
        return ""

    titles: list[str] = [raw]
    if canon_hit:
        titles.append(canon_hit)
        if canon_hit in MAKER_I18N:
            zh, ja, en = MAKER_I18N[canon_hit]
            titles.extend([zh, ja, en])
            if " / " in zh:
                titles.extend(p.strip() for p in zh.split("/"))
            elif "/" in zh:
                titles.extend(p.strip() for p in zh.split("/"))
        card = STUDIO_CARD_LABEL.get(canon_hit)
        if card:
            titles.append(card)
    # 简介表里若用展示短名做 key，也并入
    for alias_key, intro in MAKER_INTRO.items():
        if intro == text:
            titles.append(alias_key)

    return _strip_redundant_title(text, *titles)
