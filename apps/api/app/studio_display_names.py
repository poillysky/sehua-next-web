# -*- coding: utf-8 -*-
"""刮削库厂牌（片商）展示名 / 别名 / 前缀映射。

有码区货架与筛选以「前缀 → 厂牌」标准表为准（覆盖库内番号前缀），
不依赖 NFO「片商：」字段（该字段经常写错发行商标注）。
展示优先中文，其次英文品牌名。
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from .prefix_maker_names import MAKER_I18N

_ANNOT_RE = re.compile(r"[（(\[<＜【].*?[）)\]>＞】]|［.*?］")
_SEP_RE = re.compile(r"[\s\-_.·・/／\\]+")

# 别名 / 常见 NFO 写法 → MAKER_I18N 主名（或下方 CARD 覆盖的稳定主名）
STUDIO_ALIASES: dict[str, str] = {
    # S1
    "S1": "S1 NO.1 STYLE",
    "S1 NO.1 STYLE": "S1 NO.1 STYLE",
    "S1 NO.1STYLE": "S1 NO.1 STYLE",
    "エスワン": "S1 NO.1 STYLE",
    "エスワン ナンバーワンスタイル": "S1 NO.1 STYLE",
    "エスワンナンバーワンスタイル": "S1 NO.1 STYLE",
    # SOD
    "SOD": "SOD Create",
    "SOD Create": "SOD Create",
    "SOD CREATE": "SOD Create",
    "SODクリエイト": "SOD Create",
    "ソフトオンデマンド": "SOD Create",
    "ソフト・オン・デマンド": "SOD Create",
    "Soft On Demand": "SOD Create",
    # Attackers
    "Attackers": "Attackers",
    "ATTACKERS": "Attackers",
    "アタッカーズ": "Attackers",
    # Venus
    "Venus": "Venus",
    "VENUS": "Venus",
    "ヴィーナス": "Venus",
    "ビナス": "Venus",
    # Premium
    "PREMIUM": "プレミアム",
    "Premium": "プレミアム",
    "プレミアム": "プレミアム",
    # Natural High
    "Natural High": "ナチュラルハイ",
    "NATURAL HIGH": "ナチュラルハイ",
    "ナチュラルハイ": "ナチュラルハイ",
    # WANZ
    "WANZ": "WANZ",
    "WANZ FACTORY": "WANZ",
    "Wanz Factory": "WANZ",
    "ワンズファクトリー": "WANZ",
    # Nagae
    "ながえSTYLE": "ながえSTYLE",
    "ながえスタイル": "ながえSTYLE",
    "Nagae STYLE": "ながえSTYLE",
    "NAGAE STYLE": "ながえSTYLE",
    # Nadeshiko
    "なでしこ": "なでしこ",
    "Nadeshiko": "なでしこ",
    "ナデシコ": "なでしこ",
    "NADESIKO": "なでしこ",
    "Nadesiko": "なでしこ",
    # Madonna
    "Madonna": "Madonna",
    "MADONNA": "Madonna",
    "マドンナ": "Madonna",
    # Moodyz
    "MOODYZ": "MOODYZ",
    "Moodyz": "MOODYZ",
    "ムーディーズ": "MOODYZ",
    # Idea Pocket
    "IDEA POCKET": "IDEA POCKET",
    "Idea Pocket": "IDEA POCKET",
    "アイデアポケット": "IDEA POCKET",
    # Prestige
    "PRESTIGE": "PRESTIGE",
    "Prestige": "PRESTIGE",
    "プレステージ": "PRESTIGE",
    # OPPAI / Fitch / E-BODY / kawaii / 本中 / Das
    "OPPAI": "OPPAI",
    "おっぱい": "OPPAI",
    "Fitch": "Fitch",
    "フィッチ": "Fitch",
    "E-BODY": "E-BODY",
    "EBODY": "E-BODY",
    "kawaii": "kawaii",
    "kawaii*": "kawaii",
    "本中": "本中",
    "ダスッ！": "ダスッ！",
    "Das!": "ダスッ！",
    "DAS!": "ダスッ！",
    # ROCKET / ROOKIE / MAXING / FALENO
    "ROCKET": "ROCKET",
    "ロケット": "ROCKET",
    "ROOKIE": "ROOKIE",
    "ルーキー": "ROOKIE",
    "MAXING": "MAXING",
    "マキシング": "MAXING",
    "FALENO": "FALENO",
    "ファレノ": "FALENO",
    # Takara / Crystal / Alice / AKNR / Hibino
    "タカラ映像": "タカラ映像",
    "Takara Eizou": "タカラ映像",
    "クリスタル映像": "クリスタル映像",
    "Crystal": "クリスタル映像",
    "アリスJAPAN": "アリスJAPAN",
    "Alice Japan": "アリスJAPAN",
    "アキノリ": "アキノリ",
    "AKNR": "アキノリ",
    "ヒビノ": "ヒビノ",
    "Hibino": "ヒビノ",
    # DANDY / DEEP'S / Hunter / IEnergy
    "DANDY": "DANDY",
    "ダンディ": "DANDY",
    "DEEP'S": "DEEP'S",
    "DEEPS": "DEEP'S",
    "ディープス": "DEEP'S",
    "Hunter": "Hunter",
    "HUNTER": "Hunter",
    "ハンター": "Hunter",
    "アイエナジー": "アイエナジー",
    "IEnergy": "アイエナジー",
    "I-ENERGY": "アイエナジー",
    # REbecca / h.m.p / Million / MAX-A
    "REbecca": "REbecca",
    "Rebecca": "REbecca",
    "REBECCA": "REbecca",
    "レベッカ": "REbecca",
    "h.m.p": "h.m.p",
    "H.M.P": "h.m.p",
    "HMP": "h.m.p",
    "Million": "Million",
    "ミリオン": "Million",
    "MAX-A": "MAX-A",
    "マックスエー": "MAX-A",
    # S级素人
    "S级素人": "S级素人",
    "S級素人": "S级素人",
    "エス級素人": "S级素人",
    # Softcore / misc JP labels often seen raw
    "溜池ゴロー": "溜池ゴロー",
    "無垢": "無垢",
    "痴女ヘブン": "痴女ヘブン",
    "ビビアン": "ビビアン",
    "kira☆kira": "kira☆kira",
    "キラ☆キラ": "kira☆kira",
    "BeFree": "BeFree",
    "ビーフリー": "BeFree",
    "Glory Quest": "Glory Quest",
    "グローリークエスト": "Glory Quest",
    "DAHLIA": "DAHLIA",
    "ダリア": "DAHLIA",
    "BAZOOKA": "BAZOOKA",
    "バズーカ": "BAZOOKA",
    "Muteki": "Muteki",
    "ミュートキ": "Muteki",
    "V＆R PRODUCE": "V＆R PRODUCE",
    "V&R PRODUCE": "V＆R PRODUCE",
    "U＆K": "U＆K",
    "U&K": "U＆K",
    # Cinemagic
    "シネマジック": "Cinemagic",
    "Cinemagic": "Cinemagic",
    "CINEMAGIC": "Cinemagic",
    "映画マジック": "Cinemagic",
    # —— 假名厂牌 → 英文/中文主名（全面整理）——
    "レアルワークス": "REAL",
    "レアル・ワークス": "REAL",
    "REAL WORKS": "REAL",
    "Real Works": "REAL",
    "ロイヤル": "Royd",
    "Royd": "Royd",
    "ROYD": "Royd",
    "ヴィ": "Vi",
    "Vi": "Vi",
    "なまなま": "Nama Nama",
    "Nama Nama": "Nama Nama",
    "グローバルメディアエンタテインメント": "Global Media",
    "グローバルメディアアネックス": "Global Media Annex",
    "Global Media": "Global Media",
    "グラッツコーポレーション": "Glanz",
    "Glanz": "Glanz",
    "ネクスト": "NEXTGROUP",
    "NEXTGROUP": "NEXTGROUP",
    "Next Group": "NEXTGROUP",
    "サイドビー": "ながえSTYLE",
    "Side-B": "ながえSTYLE",
    "Side B": "ながえSTYLE",
    "レイディックス": "Radix",
    "Radix": "Radix",
    "プラム": "Plum",
    "Plum": "Plum",
    "ケー·トライブ": "K-Tribe",
    "ケー・トライブ": "K-Tribe",
    "ケートライブ": "K-Tribe",
    "K-Tribe": "K-Tribe",
    "サンセットカラー": "Sunset Color",
    "Sunset Color": "Sunset Color",
    "ルビー": "Ruby",
    "Ruby": "Ruby",
    "アルファーインターナショナル": "Alpha International",
    "Alpha International": "Alpha International",
    "オーロラプロジェクト·アネックス": "Aurora Project Annex",
    "オーロラプロジェクト・アネックス": "Aurora Project Annex",
    "Aurora Project Annex": "Aurora Project Annex",
    "アートモード": "Art Mode",
    "Art Mode": "Art Mode",
    "オペラ": "Opera",
    "Opera": "Opera",
    "グラフィス": "Graphis",
    "Graphis": "Graphis",
    "スパイスビジュアル": "Spice Visual",
    "Spice Visual": "Spice Visual",
    "デジタルアーク": "Digital Ark",
    "Digital Ark": "Digital Ark",
    "メディアブランド": "Media Brand",
    "Media Brand": "Media Brand",
    "V&Rプランニング": "V&R Planning",
    "V＆Rプランニング": "V&R Planning",
    "V&R Planning": "V&R Planning",
    "こあらVR": "Koala VR",
    "Koala VR": "Koala VR",
    "はじめ企画": "Hajime Kikaku",
    "Hajime Kikaku": "Hajime Kikaku",
    "山と空": "山と空",
    "山と空/妄想族": "山と空",
    "うさぎ/妄想族": "Usagi",
    "Usagi": "Usagi",
    "うれまん/妄想族": "Ureman",
    "スパルタン/妄想族": "Spartan",
    "ゆず故障マシマシ/妄想族": "Yuzu",
    "ハイカラ/妄想族": "Haikara",
    "ボニータ/妄想族": "ボニータ",
    "かぐや姫Pt/妄想族": "かぐや姫Pt",
    "脱ぐのは恥だがペニス立つ/妄想族": "NuPenis",
    "脱ぐのは恥だがペニス立つ": "NuPenis",
    "ミセスの素顔/エマニエル": "ミセスの素顔",
    "熟女塾/エマニエル": "熟女塾",
    "KSB企画/エマニエル": "KSB企画",
    "同人AV倶楽部/妄想族": "Doujin AV",
    "きゃんたま清掃員": "Kantama",
    "ヤリ上手": "Yari Jouzu",
    "独占素人": "独占素人",
    "K.M.P": "KMP",
    "KMP": "KMP",
    "ケイエムプロデュース": "KMP",
    # NFO 误标：KMPVR-彩- 下全是 SOD 的 SAVR
    "KMPVR-彩-": "SOD Create",
    "KMPVR": "SOD Create",
    "KMP VR": "SOD Create",
    "KMPVR-彩": "SOD Create",
    "unfinished": "Unfinished",
    "Unfinished": "Unfinished",
    "unfinished-VR": "Unfinished",
    "unfinished VR": "Unfinished",
    "タカラ映像": "タカラ映像",
    "Takara Eizou": "タカラ映像",
    "Takara": "タカラ映像",
    "TAKARA": "タカラ映像",
    "痴女ヘブン": "痴女ヘブン",
    "痴女天堂": "痴女ヘブン",
    "Chijo Heaven": "痴女ヘブン",
    "STAR PARADISE": "Star Paradise",
    "Star Paradise": "Star Paradise",
    "Aircontrol": "Air Control",
    "Air Control": "Air Control",
    "P-BOX VR": "P-BOX VR",
    "TRANS CLUB": "Trans Club",
    "SWITCH": "SWITCH",
    "センタービレッジ": "Center Village",
    "Center Village": "Center Village",
    "ドリームチケット": "Dream Ticket",
    "Dream Ticket": "Dream Ticket",
    "オーロラプロジェクト": "Aurora Project",
    "Aurora Project": "Aurora Project",
    "エムズビデオ": "M's Video",
    "エムズビデオグループ": "M's Video",
    "M's Video": "M's Video",
    "サディスティックヴィレッジ": "Sadistic Village",
    "Sadistic Village": "Sadistic Village",
    "セレブの友": "Celeb no Tomo",
    "Celeb no Tomo": "Celeb no Tomo",
    "コスモス映像": "Cosmos",
    "Cosmos": "Cosmos",
    "アロマ企画": "アロマ企画",
    "JET映像": "JET映像",
    # NFO 误标 / 发行商标注 → 正确厂牌
    "グラッツコーポレーション": "REbecca",
    "Glanz": "REbecca",
    "レイディックス": "S1 NO.1 STYLE",
    "Radix": "S1 NO.1 STYLE",
    "First Star": "SOD Create",
    "FIRST STAR": "SOD Create",
    "プラム": "SWITCH",
    "Plum": "SWITCH",
    "NPJ": "Nanpa Japan",
    "ナンパJAPAN": "Nanpa Japan",
    "Nanpa Japan": "Nanpa Japan",
    "Nanpa JAPAN": "Nanpa Japan",
    "Star Paradise": "NEXTGROUP",
    "STAR PARADISE": "NEXTGROUP",
    "ONE MORE": "PRESTIGE",
    "One More": "PRESTIGE",
    "桃太郎映像出版": "桃太郎映像",
    "T-Club": "Trans Club",
    "TRANS CLUB": "Trans Club",
    "Aircontrol": "Air Control",
    "SHEMALE a la carte": "SHEMALE a la carte",
    "SPICY VR": "SPICY VR",
    "P-BOX VR": "P-BOX VR",
    "NON": "NON",
    "SWITCH": "SWITCH",
    "アロマ企画": "アロマ企画",
    "阿洛玛企划": "アロマ企画",
    "Aroma Planning": "アロマ企画",
    "Aroma": "アロマ企画",
    "OPPAI": "OPPAI",
}


# 货架短名：优先中文或英文品牌名（避免日文假名）
STUDIO_CARD_LABEL: dict[str, str] = {
    "S1 NO.1 STYLE": "S1",
    "SOD Create": "SOD",
    "Attackers": "Attackers",
    "Venus": "Venus",
    "プレミアム": "Premium",
    "ナチュラルハイ": "Natural High",
    "WANZ": "WANZ",
    "ながえSTYLE": "Nagae STYLE",
    "なでしこ": "Nadeshiko",
    "Madonna": "Madonna",
    "MOODYZ": "MOODYZ",
    "IDEA POCKET": "Idea Pocket",
    "PRESTIGE": "Prestige",
    "OPPAI": "OPPAI",
    "Fitch": "Fitch",
    "E-BODY": "E-BODY",
    "kawaii": "kawaii*",
    "本中": "本中",
    "ダスッ！": "Das!",
    "ROCKET": "ROCKET",
    "ROOKIE": "ROOKIE",
    "MAXING": "MAXING",
    "FALENO": "FALENO",
    "タカラ映像": "Takara",
    "クリスタル映像": "Crystal",
    "アリスJAPAN": "Alice Japan",
    "アキノリ": "AKNR",
    "ヒビノ": "Hibino",
    "DANDY": "DANDY",
    "DEEP'S": "DEEP'S",
    "Hunter": "Hunter",
    "アイエナジー": "IEnergy",
    "REbecca": "REbecca",
    "h.m.p": "h.m.p",
    "Million": "Million",
    "MAX-A": "MAX-A",
    "S级素人": "S级素人",
    "溜池ゴロー": "溜池五郎",
    "無垢": "无垢",
    "痴女ヘブン": "痴女天堂",
    "ビビアン": "Bibian",
    "kira☆kira": "kira☆kira",
    "BeFree": "BeFree",
    "Glory Quest": "Glory Quest",
    "DAHLIA": "DAHLIA",
    "BAZOOKA": "BAZOOKA",
    "Muteki": "Muteki",
    "センタービレッジ": "Center Village",
    "ドリームチケット": "Dream Ticket",
    "オーロラプロジェクト": "Aurora Project",
    "エムズビデオ": "M's Video",
    "サディスティックヴィレッジ": "Sadistic Village",
    "セレブの友": "Celeb no Tomo",
    "コスモス映像": "Cosmos",
    "アロマ企画": "阿洛玛企划",
    "KSB企画": "KSB",
    "JET映像": "JET",
    "V＆R PRODUCE": "V&R PRODUCE",
    "U＆K": "U&K",
    "えむっ娘ラボ": "Muko Lab",
    "かぐや姫Pt": "辉夜姬",
    "ビッグモーカル": "Big Morkal",
    "フォーカス": "Focus",
    "フリーダム": "Freedom",
    "プラネットプラス": "Planet Plus",
    "ボニータ": "Bonita",
    "マザー": "Mother",
    "マルクス兄弟": "Marx Brothers",
    "ミセスの素顔": "人妻素颜",
    "変態紳士倶楽部": "变态绅士俱乐部",
    "宇宙企画": "宇宙企划",
    "山と空": "山与空",
    "桃太郎": "桃太郎映像",
    "人妻花園劇場": "人妻花园剧场",
    "美人魔女": "美人魔女",
    "舞ワイフ": "舞Wife",
    "赤面女子": "赤面女子",
    "ナンパJAPAN": "Nanpa Japan",
    "AVS collector": "AVS",
    "Boin Box": "BoinBB",
    "LEO": "LEO",
    "Cinemagic": "Cinemagic",
    "シネマジック": "Cinemagic",
    "REAL": "REAL",
    "Royd": "Royd",
    "Vi": "Vi",
    "Nama Nama": "Nama Nama",
    "Global Media": "Global Media",
    "Global Media Annex": "Global Media Annex",
    "Glanz": "Glanz",
    "NEXTGROUP": "Next Group",
    "Radix": "Radix",
    "Plum": "Plum",
    "K-Tribe": "K-Tribe",
    "Sunset Color": "Sunset Color",
    "Ruby": "Ruby",
    "Alpha International": "Alpha International",
    "Aurora Project Annex": "Aurora Project Annex",
    "Art Mode": "Art Mode",
    "Opera": "Opera",
    "Graphis": "Graphis",
    "Spice Visual": "Spice Visual",
    "Digital Ark": "Digital Ark",
    "Media Brand": "Media Brand",
    "V&R Planning": "V&R Planning",
    "Koala VR": "Koala VR",
    "Hajime Kikaku": "Hajime Kikaku",
    "山と空": "山与空",
    "Usagi": "Usagi",
    "Ureman": "Ureman",
    "Spartan": "Spartan",
    "Yuzu": "Yuzu",
    "Haikara": "Haikara",
    "NuPenis": "NuPenis",
    "Doujin AV": "Doujin AV",
    "Kantama": "Kantama",
    "Yari Jouzu": "Yari Jouzu",
    "熟女塾": "熟女塾",
    "KMP": "KMP",
    "Unfinished": "Unfinished",
    "Star Paradise": "Star Paradise",
    "Air Control": "Air Control",
    "Trans Club": "Trans Club",
    "Center Village": "Center Village",
    "Dream Ticket": "Dream Ticket",
    "Aurora Project": "Aurora Project",
    "M's Video": "M's Video",
    "Sadistic Village": "Sadistic Village",
    "Celeb no Tomo": "Celeb no Tomo",
    "Cosmos": "Cosmos",
    "Nanpa Japan": "Nanpa Japan",
    "SWITCH": "SWITCH",
    "NON": "NON",
    "OPPAI": "OPPAI",
    "SPICY VR": "SPICY VR",
    "P-BOX VR": "P-BOX VR",
    "SHEMALE a la carte": "Shemale a la carte",
    "NuPenis": "NuPenis",
}


def studio_norm_key(name: str) -> str:
    """与 scrap_library_embed._studio_match_key 对齐的规范化键。"""
    s = unicodedata.normalize("NFKC", str(name or "")).strip()
    s = _ANNOT_RE.sub("", s)
    s = s.casefold()
    s = _SEP_RE.sub("", s)
    return s


def _clean_display(name: str) -> str:
    s = unicodedata.normalize("NFKC", str(name or "")).strip()
    s = _ANNOT_RE.sub("", s).strip()
    s = re.sub(r"\s+", " ", s)
    s = s.rstrip(".")
    return s or str(name or "").strip()


_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _is_ja_kana_heavy(s: str) -> bool:
    """纯日文假名（几乎无汉字/拉丁）→ 不适合做主展示。"""
    t = (s or "").strip()
    if not t or not _KANA_RE.search(t):
        return False
    if _HAN_RE.search(t) or _LATIN_RE.search(t):
        return False
    return True


def _preferred_from_triple(
    zh: str, ja: str, en: str, *, fallback: str = ""
) -> str:
    """优先中文，其次英文；尽量避开纯假名。"""
    z = str(zh or "").strip()
    e = str(en or "").strip()
    j = str(ja or "").strip()
    fb = str(fallback or "").strip()

    # 1) 中文（含汉字）
    if z and _HAN_RE.search(z):
        return z
    # 2) 英文 / 拉丁品牌
    if e and _LATIN_RE.search(e):
        return e
    # 3) zh 本身已是英文品牌（如 Nadeshiko）
    if z and _LATIN_RE.search(z) and not _is_ja_kana_heavy(z):
        return z
    # 4) fallback 非假名
    if fb and not _is_ja_kana_heavy(fb):
        return _clean_display(fb)
    # 5) 其余保底
    for cand in (z, e, fb, j):
        if cand:
            return cand if not _is_ja_kana_heavy(cand) else cand
    return _clean_display(fb or z or e or j)


def preferred_studio_label(canon_name: str) -> str:
    """厂牌货架展示：CARD 短名 > MAKER_I18N 中/英 > 清理后的原名。"""
    key = str(canon_name or "").strip()
    if not key:
        return ""
    card = STUDIO_CARD_LABEL.get(key)
    if card:
        return card
    trip = MAKER_I18N.get(key)
    if trip:
        zh, ja, en = trip
        return _preferred_from_triple(zh, ja, en, fallback=key)
    cleaned = _clean_display(key)
    if _is_ja_kana_heavy(cleaned):
        # 尝试用别名表反查不到时只能原样
        return cleaned
    return cleaned


@lru_cache(maxsize=1)
def _indexes() -> tuple[dict[str, str], dict[str, str], dict[str, frozenset[str]]]:
    """alias_norm → canon_norm；canon_norm → display；canon_norm → all alias norms。"""
    alias_to_canon: dict[str, str] = {}
    canon_display: dict[str, str] = {}
    canon_keys: dict[str, set[str]] = {}

    def register(alias: str, canon_name: str, display: str | None = None) -> None:
        ck = studio_norm_key(canon_name)
        if not ck:
            return
        ak = studio_norm_key(alias) or ck
        alias_to_canon[ak] = ck
        alias_to_canon.setdefault(ck, ck)
        canon_keys.setdefault(ck, set()).update({ak, ck})
        label = preferred_studio_label(canon_name)
        if not label or _is_ja_kana_heavy(label):
            if display and not _is_ja_kana_heavy(display):
                label = display
            elif not label:
                label = display or _clean_display(canon_name)
        # 卡片短名 / 中英名覆盖假名旧值
        prev = canon_display.get(ck)
        if not prev or (
            _is_ja_kana_heavy(prev) and label and not _is_ja_kana_heavy(label)
        ):
            canon_display[ck] = label
        elif prev and label and not _is_ja_kana_heavy(label):
            # 已有值也统一成 preferred（CARD / 中英）
            canon_display[ck] = label

    # MAKER_I18N：主名 + 三语都挂到同一 canon
    for maker_key, (zh, ja, en) in MAKER_I18N.items():
        mk = str(maker_key or "").strip()
        if not mk:
            continue
        disp = preferred_studio_label(mk)
        if not disp:
            disp = _preferred_from_triple(zh, ja, en, fallback=mk)
        register(mk, mk, disp)
        for part in (zh, ja, en):
            p = str(part or "").strip()
            if p:
                register(p, mk, disp)

    # 显式别名（覆盖 / 补全）
    for alias, canon_name in STUDIO_ALIASES.items():
        a = str(alias or "").strip()
        c = str(canon_name or "").strip()
        if not a or not c:
            continue
        disp = preferred_studio_label(c)
        register(a, c, disp)
        register(c, c, disp)

    frozen = {k: frozenset(v) for k, v in canon_keys.items()}
    return alias_to_canon, canon_display, frozen


def resolve_studio_canon_key(name: str) -> str:
    """合并用稳定键：别名收拢后的 norm key。"""
    alias_to_canon, _, _ = _indexes()
    raw = str(name or "").strip()
    base = re.sub(r"[/／]\s*(妄想族|エマニエル)\s*$", "", raw).strip() or raw
    for cand in (base, raw):
        k = studio_norm_key(cand)
        if not k:
            continue
        if k in alias_to_canon:
            return alias_to_canon[k]
    return studio_norm_key(base) or studio_norm_key(raw)


def resolve_studio_display(name: str) -> str:
    """文件夹货架 / facet 展示名。优先中文或英文，去掉 /妄想族 等后缀。"""
    raw = str(name or "").strip()
    if not raw:
        return ""
    # 发行商标注后缀：山と空/妄想族 → 山と空
    base = re.sub(r"[/／]\s*(妄想族|エマニエル)\s*$", "", raw).strip() or raw
    _, canon_display, _ = _indexes()
    for cand in (base, raw):
        ck = resolve_studio_canon_key(cand)
        if ck and ck in canon_display:
            label = canon_display[ck]
            if label and not _is_ja_kana_heavy(label):
                return label
            if label:
                return label
    cleaned = _clean_display(base)
    # 仍为假名则再试 preferred
    pref = preferred_studio_label(base) or preferred_studio_label(raw)
    if pref and not _is_ja_kana_heavy(pref):
        return pref
    if cleaned and not _is_ja_kana_heavy(cleaned):
        return cleaned
    return pref or cleaned


def studio_filter_norm_keys(name: str) -> list[str]:
    """钻取筛选：同一厂牌下所有 NFO 写法的 norm key。"""
    _, _, canon_keys = _indexes()
    ck = resolve_studio_canon_key(name)
    if not ck:
        return []
    keys = canon_keys.get(ck)
    if keys:
        return sorted(keys)
    return [ck]


# 前缀 → 厂牌主名（NFO 缺片商时按前缀归位）
# 优先于此表；其余从 PREFIX_I18N / av-makers 推导
PREFIX_STUDIO_MAP: dict[str, str] = {
    "UMD": "LEO",
    "REBD": "REbecca",
    "REBDB": "REbecca",
    "ONED": "S1 NO.1 STYLE",
    "ONSD": "S1 NO.1 STYLE",
    "SOE": "S1 NO.1 STYLE",
    "NHDT": "ナチュラルハイ",
    "NHDTB": "ナチュラルハイ",
    "NHDTA": "ナチュラルハイ",
    "NHDTC": "ナチュラルハイ",
    "NSPS": "ながえSTYLE",
    "NASS": "なでしこ",
    "NASH": "なでしこ",
    "NATR": "なでしこ",
    "NADE": "なでしこ",
    "SDDE": "SOD Create",
    "SDMT": "SOD Create",
    "STAR": "SOD Create",
    "STARS": "SOD Create",
    "SAVR": "SOD Create",
    "DSVR": "SOD Create",
    "SACE": "SOD Create",
    "KFNE": "SOD Create",
    "KDMN": "SOD Create",
    "VRKM": "KMP",
    "MKMP": "KMP",
    "RCT": "ROCKET",
    "RCTD": "ROCKET",
    "SRXV": "MAX-A",
    "XVSR": "MAX-A",
    "SHKD": "Attackers",
    "SSPD": "Attackers",
    "ATID": "Attackers",
    "ATKD": "Attackers",
    "RBD": "Attackers",
    "VRTM": "V＆R PRODUCE",
    "SABA": "S级素人",
    "SUPA": "S级素人",
    "SVDVD": "サディスティックヴィレッジ",
    "SPIVR": "SPICY VR",
    "VEC": "Venus",
    "VENU": "Venus",
    "VENX": "Venus",
    "BID": "痴女ヘブン",
    "HBAD": "ヒビノ",
    "IESP": "アイエナジー",
    "MDB": "BAZOOKA",
    "OVG": "Glory Quest",
    "PGD": "プレミアム",
    "PRED": "プレミアム",
    "PBD": "プレミアム",
    "PXD": "プレミアム",
    "PPPD": "OPPAI",
    "PPBD": "OPPAI",
    "PPPE": "OPPAI",
    "PPSD": "OPPAI",
    "PXVR": "P-BOX VR",
    "SW": "SWITCH",
    "YSN": "NON",
    "URVRSP": "Unfinished",
    "VNDS": "NEXTGROUP",
    "NNPJ": "Nanpa Japan",
    "NPJS": "Nanpa Japan",
    "NPJ": "Nanpa Japan",
    "OAE": "Air Control",
    "TCD": "Trans Club",
    "VICD": "Vi",
    "NAMH": "Nama Nama",
    "XRW": "REAL",
    "RLMP": "REAL",
    "YMDD": "桃太郎映像",
    "AARM": "アロマ企画",
    "ARM": "アロマ企画",
    "JUFD": "Fitch",
    "JUFE": "Fitch",
    "ONEZ": "PRESTIGE",
    "NGHJ": "NuPenis",
    "USAG": "Usagi",
    "UMAN": "Ureman",
    "SITW": "Spartan",
    "SAL": "SHEMALE a la carte",
    "SUPD": "IDEA POCKET",
    # 国产目录补漏
    "TMA": "天美传媒",
    "NHJ": "精东影业",
}


def _maker_key_from_triple(zh: str, ja: str, en: str) -> str:
    """把 PREFIX_I18N 三元组挂到 MAKER_I18N / 别名表主名。"""
    for cand in (en, zh, ja):
        c = str(cand or "").strip()
        if not c:
            continue
        # 已是主名
        if c in MAKER_I18N or c in STUDIO_ALIASES or c in STUDIO_CARD_LABEL:
            return STUDIO_ALIASES.get(c, c)
        # 通过 norm 反查 display 索引
        ck = resolve_studio_canon_key(c)
        if ck:
            # 找一个能 preferred 的名字
            for k in (c, en, zh):
                if k and preferred_studio_label(str(k)):
                    if str(k) in MAKER_I18N or str(k) in STUDIO_CARD_LABEL:
                        return str(k)
            return c
    return str(en or zh or ja or "").strip()


@lru_cache(maxsize=1)
def _prefix_to_maker() -> dict[str, str]:
    """upper(prefix) → 厂牌主名（用于展示/归位）。"""
    from .prefix_maker_names import PREFIX_I18N, load_prefix_maker_base

    out: dict[str, str] = {}

    for pref, maker in load_prefix_maker_base().items():
        p = str(pref or "").strip().upper()
        m = str(maker or "").strip()
        if p and m:
            out[p] = STUDIO_ALIASES.get(m, m)

    for pref, trip in PREFIX_I18N.items():
        p = str(pref or "").strip().upper()
        if not p:
            continue
        zh, ja, en = trip
        mk = _maker_key_from_triple(zh, ja, en)
        if mk:
            out[p] = STUDIO_ALIASES.get(mk, mk)

    for pref, maker in PREFIX_STUDIO_MAP.items():
        p = str(pref or "").strip().upper()
        m = str(maker or "").strip()
        if p and m:
            out[p] = STUDIO_ALIASES.get(m, m)

    return out


def resolve_studio_for_prefix(prefix: str) -> str:
    """前缀 → 厂牌展示名；无法映射则空串。"""
    p = str(prefix or "").strip().upper()
    if not p:
        return ""
    maker = _prefix_to_maker().get(p, "")
    if not maker:
        return ""
    return resolve_studio_display(maker) or preferred_studio_label(maker) or maker


def prefixes_for_studio_query(studio_q: str) -> list[str]:
    """某厂牌下应用于「缺片商」回填的前缀列表。"""
    canon = resolve_studio_canon_key(studio_q)
    if not canon:
        return []
    out: list[str] = []
    for pref, maker in _prefix_to_maker().items():
        if resolve_studio_canon_key(maker) == canon:
            out.append(pref)
    return sorted(set(out))


def all_mapped_prefixes() -> list[str]:
    return sorted(_prefix_to_maker().keys())
