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
from typing import Any

from app.core.maps_paths import (
    prefix_studio_override_map,
    studio_alias_map,
    studio_card_label_map,
)
from app.prefix.maker_names import MAKER_I18N

_ANNOT_RE = re.compile(r"[（(\[<＜【].*?[）)\]>＞】]|［.*?］")
_SEP_RE = re.compile(r"[\s\-_.·・/／\\]+")

# 别名 / 常见 NFO 写法 → MAKER_I18N 主名（或下方 CARD 覆盖的稳定主名）
STUDIO_ALIASES: dict[str, str] = studio_alias_map()
# 厂牌墙：FC2 与 FC2-PPV 分开；磁盘夹名 FC2-PPV 对应 catalog 前缀 FC2PPV
for _fc2_alias in ("FC2 PPV", "FC2PPV", "FC2_PPV"):
    STUDIO_ALIASES[_fc2_alias] = "FC2-PPV"

# 货架短名：优先中文或英文品牌名（避免日文假名）
STUDIO_CARD_LABEL: dict[str, str] = studio_card_label_map()


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
PREFIX_STUDIO_MAP: dict[str, str] = prefix_studio_override_map()
PREFIX_STUDIO_MAP["FC2PPV"] = "FC2-PPV"
PREFIX_STUDIO_MAP["FC2-PPV"] = "FC2-PPV"
PREFIX_STUDIO_MAP["FC2"] = "FC2"



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
    """upper(prefix) → 厂牌主名（fallback：av-makers / PREFIX_I18N / 硬编码）。"""
    from app.prefix.maker_names import PREFIX_I18N, load_prefix_maker_base

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


def _catalog_maker_key(ent: dict[str, Any]) -> str:
    """从 catalog 前缀条目抽出可归位的厂牌主名。

    注意：不要优先盲信 maker_en。很多条目英文名（如 JET Eizou / Momotaro）
    不在 makers.json 主名表里，会导致厂牌墙简介解析为空。
    """
    candidates: list[str] = []
    for field in ("maker", "maker_zh", "maker_ja", "maker_en"):
        raw = str(ent.get(field) or "").strip()
        if not raw:
            continue
        candidates.append(raw)
        # 「A / B」两侧都试，避免只取英文左侧
        for part in re.split(r"[/／]", raw):
            p = part.strip()
            if p and p not in candidates:
                candidates.append(p)

    def _hit(c: str) -> str:
        if c in MAKER_I18N or c in STUDIO_ALIASES or c in STUDIO_CARD_LABEL:
            return STUDIO_ALIASES.get(c, c)
        ck = resolve_studio_canon_key(c)
        if not ck:
            return ""
        for mk in MAKER_I18N:
            if studio_norm_key(mk) == ck:
                return mk
        disp = resolve_studio_display(c)
        if disp:
            for mk, label in STUDIO_CARD_LABEL.items():
                if label == disp or studio_norm_key(label) == ck:
                    return mk
            for mk in MAKER_I18N:
                if preferred_studio_label(mk) == disp:
                    return mk
        return ""

    for c in candidates:
        hit = _hit(c)
        if hit:
            return hit
    # 兜底：仍无命中时退回第一条候选（保持旧行为可追踪）
    return candidates[0] if candidates else ""


# region_id → (catalog_mtime, prefix→maker_key)
_region_prefix_maps: dict[str, tuple[float | None, dict[str, str]]] = {}


def _normalize_region_id(region: str) -> str:
    from app.core.region_meta import REGION_META, REGION_ORDER, resolve_fs_region

    raw = str(region or "").strip()
    if not raw:
        return ""
    rid = resolve_fs_region(raw) or raw
    if rid in REGION_META:
        return rid
    # 中文区名 / 库内 label
    for key in REGION_ORDER:
        meta = REGION_META[key]
        if raw == key or raw == meta.get("label") or raw == meta.get("db_region"):
            return key
    return rid


def prefix_to_maker_for_region(region: str = "") -> dict[str, str]:
    """upper(prefix) → 厂牌主名。

    有 region 时：prefix_catalog 优先，未命中再 fallback 全局表。
    无 region 时：仅全局 fallback（兼容旧调用）。
    """
    import app.prefix.catalog_store as store

    rid = _normalize_region_id(region)
    fallback = _prefix_to_maker()
    if not rid:
        return dict(fallback)

    try:
        mtime = store.catalog_path().stat().st_mtime
    except OSError:
        mtime = None
    cached = _region_prefix_maps.get(rid)
    if cached and cached[0] == mtime and cached[1]:
        return cached[1]

    out = dict(fallback)
    try:
        doc = store.load_catalog()
        bucket = (doc.get("regions") or {}).get(rid, {}).get("prefixes") or {}
    except Exception:  # noqa: BLE001
        bucket = {}
    for pref, ent in bucket.items():
        p = str(pref or "").strip().upper()
        if not p or not isinstance(ent, dict):
            continue
        mk = _catalog_maker_key(ent)
        if mk:
            out[p] = STUDIO_ALIASES.get(mk, mk)

    _region_prefix_maps[rid] = (mtime, out)
    return out


def invalidate_region_prefix_maps() -> None:
    """catalog / makers 写回后可调用，丢掉 region 与别名缓存。"""
    global STUDIO_ALIASES, STUDIO_CARD_LABEL
    _region_prefix_maps.clear()
    _prefix_to_maker.cache_clear()
    _indexes.cache_clear()
    try:
        from app.core.maps_paths import (
            makers_doc,
            studio_alias_map,
            studio_card_label_map,
        )

        makers_doc.cache_clear()
        STUDIO_ALIASES = studio_alias_map()
        STUDIO_CARD_LABEL = studio_card_label_map()
        for _fc2_alias in ("FC2 PPV", "FC2PPV", "FC2_PPV"):
            STUDIO_ALIASES[_fc2_alias] = "FC2-PPV"
    except Exception:  # noqa: BLE001
        pass


def resolve_studio_for_prefix(prefix: str, region: str = "") -> str:
    """前缀 → 厂牌展示名；无法映射则空串。region 命中 catalog 分区映射。"""
    p = str(prefix or "").strip().upper()
    if not p:
        return ""
    maker = prefix_to_maker_for_region(region).get(p, "")
    if not maker:
        return ""
    return resolve_studio_display(maker) or preferred_studio_label(maker) or maker


def prefixes_for_studio_query(studio_q: str, region: str = "") -> list[str]:
    """某厂牌下的前缀列表（catalog 分区优先）。"""
    canon = resolve_studio_canon_key(studio_q)
    if not canon:
        return []
    out: list[str] = []
    for pref, maker in prefix_to_maker_for_region(region).items():
        if resolve_studio_canon_key(maker) == canon:
            out.append(pref)
    return sorted(set(out))


def all_mapped_prefixes(region: str = "") -> list[str]:
    return sorted(prefix_to_maker_for_region(region).keys())
