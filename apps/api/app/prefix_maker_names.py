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
            "JUL", "JUQ", "JUR", "JUY", "JUX", "JUC", "JUFD", "JUFE", "JUKD", "JUSD",
            "JURA", "JUNY", "ALDN", "OBA", "URE", "ROE", "ACHJ",
        )
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
        for p in ("ABF", "ABP", "ABS", "ABW", "BGN", "CHN", "PPT", "ONEZ", "SGA", "TRE", "BLO", "DIC", "EVO", "INU", "JAN", "MAS", "ESK")
    },
    **{
        p: ("SOD Create / SOD制作", "SODクリエイト", "SOD Create")
        for p in (
            "SDDE", "SDMM", "SDMU", "SDNM", "SDAB", "SDAM", "SDJS", "SDMT",
            "STAR", "STARS", "START", "DSVR", "SAVR", "SODS", "FTN",
        )
    },
    **{p: ("AKNR / 明纪", "アキノリ", "AKNR") for p in ("AKNR", "AKDL", "SKTH", "FSET", "SW")},
    **{
        p: ("Sadistic Village / 残酷村", "サディスティックヴィレッジ", "Sadistic Village")
        for p in ("SVDVD", "SVVRT", "SPIVR")
    },
    **{p: ("DAHLIA / 大丽花", "ダリア", "DAHLIA") for p in ("DLDSS",)},
    **{p: ("本中", "本中", "Hon-Naka") for p in ("HMN", "HND", "HNDB", "HNDS")},
    **{p: ("E-BODY", "E-BODY", "E-BODY") for p in ("EBOD", "EBWH")},
    **{
        p: ("Premium / 高级", "プレミアム", "PREMIUM")
        for p in ("PRED", "PGD", "PBD", "PPBD", "PPPD", "PPPE", "PPSD", "PRST", "PXD", "PXVR")
    },
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
    "EKDV": ("Crystal / 水晶映像", "クリスタル映像", "Crystal Eizou"),
    "MIST": ("Mr.Michiru / 美汁流", "ミスターミチル", "Mr.Michiru"),
    "GS": ("GOGOS / 走光", "ゴーゴーズ", "GOGOS"),
    "TCD": ("Trans Club / 变性俱乐部", "トランスクラブ", "T-Club"),
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
    "136SW": ("AKNR / 明纪", "アキノリ", "AKNR"),
    "201KDMN": ("SOD Create / SOD制作", "SODクリエイト", "SOD Create"),
    "326KFNE": ("SOD Create / SOD制作", "SODクリエイト", "SOD Create"),
    "406FCDSS": ("FALENO / 法雷诺", "ファレノ", "FALENO"),
    "406FNS": ("FALENO / 法雷诺", "ファレノ", "FALENO"),
    "406FSDSS": ("FALENO / 法雷诺", "ファレノ", "FALENO"),
    "406FSVSS": ("FALENO / 法雷诺", "ファレノ", "FALENO"),
    "513DLDSS": ("DAHLIA / 大丽花", "ダリア", "DAHLIA"),
    "554SPIVR": ("Sadistic Village / 残酷村", "サディスティックヴィレッジ", "Sadistic Village"),
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
    """prefix → av-makers 原始 maker 字符串。"""
    out: dict[str, str] = {}
    cfg = ROOT / "apps" / "web" / "src" / "config"
    for name in ("av-makers.japan.json", "av-makers.china.json", "av-makers.western.json"):
        path = cfg / name
        if not path.exists():
            continue
        for row in json.loads(path.read_text(encoding="utf-8")):
            maker = str(row.get("maker") or "").strip()
            for p in row.get("prefixes") or []:
                out[std_prefix(p)] = maker
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
