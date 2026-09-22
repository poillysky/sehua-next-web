# -*- coding: utf-8 -*-
"""女优别名解析（映射表 + 简繁/日汉字变体）。"""

from __future__ import annotations

import logging
import re
import unicodedata

from .bio import fold_key

log = logging.getLogger(__name__)

# 简/繁 → 日文新字体（GFriends 文件名常用：三上悠亜 ≠ 三上悠亚；吉良薫 ≠ 吉良薰）
# 查询与索引两侧都经 _jp_fold_key，避免只扩别名仍对不上。
CN_TO_JP_KANJI = str.maketrans(
    {
        # —— 女优名高频异体（简繁 ↔ 日新字）——
        "薰": "薫",
        "熏": "薫",
        "惠": "恵",
        "优": "優",
        "優": "優",
        "穗": "穂",
        "穂": "穂",
        "德": "徳",
        "徳": "徳",
        "步": "歩",
        "歩": "歩",
        "凉": "涼",
        "涼": "涼",
        "绿": "緑",
        "綠": "緑",
        "纯": "純",
        "純": "純",
        "织": "織",
        "織": "織",
        "爱": "愛",
        "愛": "愛",
        "铃": "鈴",
        "鈴": "鈴",
        "赖": "頼",
        "賴": "頼",
        "祯": "禎",
        "綾": "綾",
        "绫": "綾",
        "绣": "繍",
        "繡": "繍",
        "弥": "弥",
        "彌": "弥",
        "假": "仮",
        "気": "気",
        "气": "気",
        "氣": "気",
        "边": "辺",
        "邊": "辺",
        "変": "変",
        "变": "変",
        "變": "変",
        "恋": "恋",
        "戀": "恋",
        "体": "体",
        "體": "体",
        "两": "両",
        "兩": "両",
        "児": "児",
        "儿": "児",
        "兒": "児",
        "剣": "剣",
        "剑": "剣",
        "劍": "剣",
        "単": "単",
        "单": "単",
        "傳": "伝",
        "传": "伝",
        "価": "価",
        "价": "価",
        "價": "価",
        # —— 通用简繁 → 日新字体 ——
        "亚": "亜",
        "亞": "亜",
        "泽": "沢",
        "澤": "沢",
        "滨": "浜",
        "濱": "浜",
        "实": "実",
        "實": "実",
        "丽": "麗",
        "麗": "麗",
        "樱": "桜",
        "櫻": "桜",
        "绳": "縄",
        "繩": "縄",
        "艺": "芸",
        "藝": "芸",
        "岛": "島",
        "島": "島",
        "绪": "緒",
        "緒": "緒",
        "绘": "絵",
        "繪": "絵",
        "广": "広",
        "廣": "広",
        "关": "関",
        "關": "関",
        "经": "経",
        "經": "経",
        "转": "転",
        "轉": "転",
        "荣": "栄",
        "榮": "栄",
        "觉": "覚",
        "覺": "覚",
        "观": "観",
        "觀": "観",
        "读": "読",
        "讀": "読",
        "丝": "糸",
        "絲": "糸",
        "图": "図",
        "圖": "図",
        "脑": "脳",
        "腦": "脳",
        "药": "薬",
        "藥": "薬",
        "铁": "鉄",
        "鐵": "鉄",
        "长": "長",
        "長": "長",
        "门": "門",
        "門": "門",
        "际": "際",
        "際": "際",
        "险": "険",
        "險": "険",
        "隐": "隠",
        "隱": "隠",
        "飞": "飛",
        "飛": "飛",
        "马": "馬",
        "馬": "馬",
        "验": "験",
        "驗": "験",
        "齿": "歯",
        "齒": "歯",
        "龙": "竜",
        "龍": "竜",
        "厅": "庁",
        "廳": "庁",
        "发": "髪",
        "髮": "髪",
        "声": "声",
        "聲": "声",
        "卖": "売",
        "賣": "売",
        "圆": "円",
        "圓": "円",
        "盐": "塩",
        "鹽": "塩",
        "岁": "歳",
        "歲": "歳",
        "齐": "斉",
        "齊": "斉",
        "斋": "斎",
        "齋": "斎",
        "学": "学",
        "學": "学",
        "宝": "宝",
        "寶": "宝",
        "写": "写",
        "寫": "写",
        "处": "処",
        "處": "処",
        "泪": "涙",
        "淚": "涙",
        "浅": "浅",
        "淺": "浅",
        "满": "満",
        "滿": "満",
        "濑": "瀬",
        "瀨": "瀬",
        "桥": "橋",
        "橋": "橋",
        "产": "産",
        "產": "産",
        "电": "電",
        "電": "電",
        "画": "画",
        "畫": "画",
        "黑": "黒",
        "黒": "黒",
        "默": "黙",
        "黙": "黙",
        "颜": "顔",
        "顏": "顔",
        "饰": "飾",
        "飾": "飾",
        "馆": "館",
        "館": "館",
        "鹤": "鶴",
        "鶴": "鶴",
        "鹰": "鷹",
        "鷹": "鷹",
        "医": "医",
        "醫": "医",
        "国": "国",
        "國": "国",
        "来": "来",
        "來": "来",
        "与": "与",
        "與": "与",
        "区": "区",
        "區": "区",
        "动": "動",
        "動": "動",
        "务": "務",
        "務": "務",
        "胜": "勝",
        "勝": "勝",
        "势": "勢",
        "勢": "勢",
        "协": "協",
        "協": "協",
        "参": "参",
        "參": "参",
        "刚": "剛",
        "剛": "剛",
        "剧": "劇",
        "劇": "劇",
        "伪": "偽",
        "偽": "偽",
        "伤": "傷",
        "傷": "傷",
        "倾": "傾",
        "傾": "傾",
        "仪": "儀",
        "儀": "儀",
        "亿": "億",
        "億": "億",
        "伟": "偉",
        "偉": "偉",
        "杰": "傑",
        "傑": "傑",
        "仓": "倉",
        "倉": "倉",
        "伦": "倫",
        "倫": "倫",
        "梅": "梅",
    }
)
_ALIAS_KEY_NOISE = re.compile(
    r"SKE|NMB|AKB|HKT|乃木坂|チーム|パルプンテ|ヒュージョン|亀头|亀頭",
    re.I,
)


def jp_kanji_forms(name: str) -> list[str]:
    """生成日文汉字写法，供 GFriends / JavBus 精确匹配。"""
    s = unicodedata.normalize("NFKC", str(name or "").strip())
    if not s:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(n: str) -> None:
        t = str(n or "").strip()
        if not t or t in seen:
            return
        seen.add(t)
        out.append(t)

    add(s)
    add(s.translate(CN_TO_JP_KANJI))
    return out


def _alias_names(display: str) -> list[str]:
    """显示名 + 刮削演员映射表别名（日文键/jp 字段，供 GFriends 检索）。

    与刮削共用 apps/maps/scrape/actors.*.json：正向取 name/zh/jp，
    反向收集所有指向同一标准名的键（多为日文）。
    """
    from app.scrape.metadata_optimize import (
        _actor_maps,
        _lookup_actor_hit,
        _map_actor_entry,
        mapping_language_from_settings,
    )

    names: list[str] = []
    seen: set[str] = set()

    def add(n: str) -> None:
        s = unicodedata.normalize("NFKC", str(n or "").strip())
        if not s:
            return
        # 去掉括注：本名（别名）
        s = re.sub(r"\s*[\(（][^)）]*[\)）]\s*$", "", s).strip()
        if not s:
            return
        k = fold_key(s)
        if k in seen:
            return
        seen.add(k)
        names.append(s)

    def add_variants(n: str) -> None:
        add(n)
        s = unicodedata.normalize("NFKC", str(n or "").strip())
        if not s:
            return
        for form in jp_kanji_forms(s):
            add(form)
        # 々 ↔ 叠字（佐々波 ↔ 佐佐波）
        if "々" in s:
            chars = list(s)
            for i, c in enumerate(chars):
                if c == "々" and i > 0:
                    chars[i] = chars[i - 1]
            add("".join(chars))
            for form in jp_kanji_forms("".join(chars)):
                add(form)
        else:
            buf: list[str] = []
            i = 0
            while i < len(s):
                if (
                    i + 1 < len(s)
                    and s[i] == s[i + 1]
                    and "\u4e00" <= s[i] <= "\u9fff"
                ):
                    buf.append(s[i])
                    buf.append("々")
                    i += 2
                else:
                    buf.append(s[i])
                    i += 1
            joined = "".join(buf)
            add(joined)
            for form in jp_kanji_forms(joined):
                add(form)
        try:
            import zhconv

            for lang in ("zh-hant", "zh-cn", "zh-tw"):
                conv = zhconv.convert(s, lang)
                add(conv)
                for form in jp_kanji_forms(conv):
                    add(form)
        except Exception:  # noqa: BLE001
            pass

    add_variants(display)
    try:
        table = _actor_maps(mapping_language_from_settings())
        canon, _ = _map_actor_entry(display, table)
        add_variants(canon)
        hit = _lookup_actor_hit(display, table)
        if isinstance(hit, dict):
            add_variants(str(hit.get("name") or ""))
            add_variants(str(hit.get("zh") or ""))
            add_variants(str(hit.get("jp") or ""))
            add_variants(str(hit.get("ja") or ""))
        # 反向：所有指向同一标准名的 key（日文检索名多在键上）
        target_folds = {fold_key(x) for x in (canon, display) if x}
        if isinstance(hit, dict):
            for f in ("name", "zh"):
                v = str(hit.get(f) or "").strip()
                if v:
                    target_folds.add(fold_key(v))
        for k, v in table.items():
            if isinstance(v, dict):
                n = str(v.get("name") or v.get("zh") or "").strip()
                kn = str(k)
                # 跳过偶像团注记等脏键，避免串到无关别名
                if _ALIAS_KEY_NOISE.search(kn):
                    continue
                if fold_key(n) in target_folds or fold_key(kn) in target_folds:
                    add_variants(kn)
                    add_variants(n)
                    add_variants(str(v.get("name") or ""))
                    add_variants(str(v.get("zh") or ""))
                    add_variants(str(v.get("jp") or ""))
                    add_variants(str(v.get("ja") or ""))
            elif isinstance(v, str):
                kn = str(k)
                if _ALIAS_KEY_NOISE.search(kn):
                    continue
                if fold_key(v) in target_folds or fold_key(kn) in target_folds:
                    add_variants(kn)
                    add_variants(v)
    except Exception as e:  # noqa: BLE001
        log.debug("alias resolve failed %s: %s", display, e)
    return names


# Public API
alias_names = _alias_names

__all__ = ["alias_names", "_alias_names", "jp_kanji_forms", "CN_TO_JP_KANJI"]
