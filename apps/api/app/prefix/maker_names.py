# -*- coding: utf-8 -*-
"""前缀厂牌三语名：中文 / 日文（英文）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.db import ROOT
from app.core.maps_paths import (
    maker_i18n_map,
    maker_intro_map,
    prefix_i18n_map,
    prefix_intro_map,
)
from app.core.region_meta import std_prefix

# maker 主名（av-makers 里的 maker 字段）→ (zh, ja, en)
MAKER_I18N: dict[str, tuple[str, str, str]] = maker_i18n_map()

# 厂牌短介绍（中文）：供货架/前缀卡展示；key 与 MAKER_I18N 主名对齐
MAKER_INTRO: dict[str, str] = maker_intro_map()

# 前缀短介绍（比厂牌简介更具体；key 为大写前缀）
PREFIX_INTRO: dict[str, str] = prefix_intro_map()

# 前缀级覆盖（无码官网系 / 素人 MGStage 等）
PREFIX_I18N: dict[str, tuple[str, str, str]] = prefix_i18n_map()


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
    from app.core.maps_paths import av_makers

    out: dict[str, str] = {}
    # china/western 先填；japan 后写且不丢已有冲突键的日本值——改为 japan 最后覆盖
    for region in ("china", "western", "japan"):
        path = av_makers(region)
        if not path.exists():
            continue
        for row in json.loads(path.read_text(encoding="utf-8")):
            maker = str(row.get("maker") or "").strip()
            for p in row.get("prefixes") or []:
                key = std_prefix(p)
                if not key or not maker:
                    continue
                # japan 文件最后加载，允许覆盖同名前缀的跨区冲突
                if region == "japan" or key not in out:
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


def _prefix_notes_from_japan_json(pref: str) -> str:
    """读取 av-makers.japan.json 里该前缀的 prefix_notes。"""
    try:
        from app.core.maps_paths import av_makers

        path = av_makers("japan")
        if not path.exists():
            return ""
        for row in json.loads(path.read_text(encoding="utf-8")):
            pn_map = row.get("prefix_notes") or {}
            pn = pn_map.get(pref) or pn_map.get(pref.upper())
            if pn:
                return str(pn).strip()
    except Exception:  # noqa: BLE001
        return ""
    return ""


def prefix_line_rank(prefix: str, blurb: str = "") -> int:
    """前缀货架优先级：越小越靠前（现行主力 < 上一代 < 旁支 < VR/合集）。

    仅用 PREFIX_INTRO + prefix_notes 推断；厂牌级通用简介含「企划」会污染排序，勿单独依赖。
    """
    pref = std_prefix(prefix)
    notes = _prefix_notes_from_japan_json(pref)
    text = f"{PREFIX_INTRO.get(pref, '')} {notes}".strip() or str(blurb or "")

    if re.search(r"专属现行|现行专属|现行主力|现行主线", text):
        return 0
    # 须先于「专属上一代」：否则「非专属上一代」会被误匹配
    if re.search(r"非专属企划现行|企划现行", text):
        return 6
    if re.search(r"非专属企划上一代|非专属上一代|企划上一代", text):
        return 7
    if re.search(r"专属上一代|上一代专属|上一代主力|上一代主线", text):
        return 2
    if re.search(r"更早专属|更早主线|经典专属|经典.*线|全盛", text):
        return 4
    if re.search(r"早期专属|早期 Acid|Acid|较早|早期|草创|历史主线|旧专属", text):
        return 5
    if re.search(r"过渡", text):
        return 7
    if re.search(r"出道|新人", text):
        return 8
    if re.search(r"(?i)(?:^|[^a-z])vr(?:[^a-z]|$)", text) or notes.upper() == "VR":
        return 10
    if re.search(r"合集|精选|特别篇|祭典|旧作精选|新作精选", text):
        return 11
    if re.search(r"旁支|企划|大型企划|硬核|漫画", text):
        return 9
    if re.search(r"主力专属|主力线|主力：|主力巨乳|专属女优主力|剧情主力", text):
        return 3
    return 99


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
        from app.scrap_library.studio_display_names import (
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
