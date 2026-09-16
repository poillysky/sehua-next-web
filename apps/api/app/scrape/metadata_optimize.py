"""刮削后元数据优化（色花堂中文标题 / 演员·标签映射 / 简介换行）。"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.db import ROOT
from app.core.maps_paths import load_str_map

MAPPING_LANGS = frozenset({"zh-CN", "zh-TW", "ja", "en"})
_MULTI_NL_RE = re.compile(r"\n{2,}")
# 色花堂字段偶发装饰：首尾 +/-/~ / 全角～
_ACTOR_DIRTY_RE = re.compile(r"^[\+\-\~\～\s　]+|[\+\-\~\～\s　]+$")

# 繰り返し記号「々」(U+3005)：表示前一个字符重复。日文源写 `佐々波綾`，
# 中文映射表键/标准名写 `佐佐波綾` / `佐佐波绫`——不做字形归一就永远对不上，
# 表现为「overview 有中文候选但合并非中文」之类的假阴性（表内含 `々` 的键 117 个）。
# 归一为「前字重复」是确定性且无损的（々 永远只表示重复），故作为通用规则前置。
_ITER_MARK = "\u3005"


def _iter_fold(s: str) -> str:
    """`々` → 重复前一个字符：`佐々波綾` → `佐佐波綾`。"""
    s = str(s or "")
    if _ITER_MARK not in s:
        return s
    out: list[str] = []
    for ch in s:
        if ch == _ITER_MARK and out:
            out.append(out[-1])
        else:
            out.append(ch)
    return "".join(out)


# 促销 / 活动 / 临时性标签：源站常把「セール」「%オフ」当 genre，统一当噪声丢弃。
_TAG_PROMO_RE = re.compile(
    r"(セール|％オフ|%オフ|オフセール|クーポン|キャンペーン|アウトレット|バーゲン|"
    r"\bsale\b|\boff\b|セット商品|第[0-9０-９]+弾|期間限定|特別価格|奉仕価格|"
    r"ポイント還元|早割|感謝祭|感谢祭)",
    re.IGNORECASE,
)

# 年代 / 厂牌分类等元标签（如 `2010年代前半（DOD）`）：不是题材，统一丢弃。
_TAG_META_RE = re.compile(
    r"(?:19|20)\d{2}年代(?:前半|後半|中盤|初期|末期)?|"
    r"[（(](?:DOD|MGS|SOD)[）)]|"
    r"ディスク[・･]?オン[・･]?デマンド|disk\s*on\s*demand|\bDOD\b|"
    r"エマニエル|艾曼纽|妄想族|"
    r"\b4K\b|\b8K\b|ハイビジョン|高清画质|HD高画质|"
    r"\bPornstar\b|\bpornstar\b|"
    r"4小时\+|4小时以上|4時間以上|4時間以上作品|"
    # MGS/店家附赠片头：非题材
    r"MGSだけのおまけ|おまけ映像|特典映像|特典動画|ボーナス映像",
    re.IGNORECASE,
)

# 前缀恰好等于这些「有意义缩写」时不做前缀噪声处理（避免误伤题材标签）。
_TAG_PREFIX_KEEP = frozenset(
    {"SM", "VR", "OL", "POV", "JK", "AV", "NTR", "BD", "DVD", "HD", "FHD", "UHD"}
)

# 繁 / 日 → 简 常用变体对（空格分隔，每对 2 字）。仅作**映射兜底**：精确命中仍优先，
# 故不会改变既有正确结果；但能根治「繁简分裂」——映射表只写了 `義母` 时，源站的
# `义母` 也能收敛到同一标准名，不必逐字往表里补（历史反复踩此坑）。

_TAG_VARIANT_FOLD: dict[str, str] = load_str_map("tags.variant-fold.zh-CN.json")
_TAG_VARIANT_TRANS = str.maketrans(_TAG_VARIANT_FOLD) if _TAG_VARIANT_FOLD else {}


def code_prefix(code: str) -> str:
    """番号 → 前缀（`NDRA-117` → `NDRA`）。用于清理被当 genre 的系列前缀。"""
    m = re.match(r"^\s*([A-Za-z]+)", str(code or ""))
    return m.group(1).upper() if m else ""


def tag_is_noise(name: str, *, prefix: str = "") -> bool:
    """通用噪声标签：促销/活动词、番号前缀（源站常误当 genre）。

    这是「批量也不会踩」的根本防线——无需逐条往映射表里补前缀。
    """
    s = str(name or "").strip()
    if not s:
        return True
    if _TAG_PROMO_RE.search(s) or _TAG_META_RE.search(s):
        return True
    p = str(prefix or "").strip().upper()
    if p and p not in _TAG_PREFIX_KEEP:
        if re.fullmatch(
            rf"{re.escape(p)}[0-9]*(?:\s*-\s*[0-9]+)?", s, re.IGNORECASE
        ):
            return True
    return False

DEFAULT_METADATA_OPTIMIZE: dict[str, Any] = {
    "useForumZhTitle": False,
    "enableActorMapping": True,
    "enableTagMapping": True,
    "compactOutlineNewlines": True,
    "mappingLanguage": "zh-CN",
}


def _clean_actor_raw(name: str) -> str:
    s = str(name or "").strip()
    if not s:
        return ""
    # 半角片假名等：倉本ｽﾐﾚ → 倉本すみれ，便于映射命中
    s = unicodedata.normalize("NFKC", s)
    # 繰り返し記号归一：佐々波綾 → 佐佐波綾（否则永不命中只写 `佐佐…` 的表键）
    s = _iter_fold(s)
    s = _ACTOR_DIRTY_RE.sub("", s).strip()
    # 完整括号备注：愛染恭子（青山涼子）
    s = re.sub(r"\s*[\(（][^)）]*[\)）]\s*$", "", s).strip()
    # 半截开括号（JavBus span 截断）：愛染恭子（
    s = re.sub(r"\s*[\(（][^)）]*$", "", s).strip()
    s = s.rstrip("（(").strip()
    return re.sub(r"\s+", " ", s)


_CACHED_MAPPING_LANG: str | None = None
_SETTING_MAP_ENABLED: bool | None = None


def mapping_language_from_settings() -> str:
    """读 library / 旧 scrape 配置里的 mappingLanguage，失败则 zh-CN。"""
    global _CACHED_MAPPING_LANG
    if _CACHED_MAPPING_LANG is not None:
        return _CACHED_MAPPING_LANG
    try:
        import app.core.settings_store as settings_store

        raw = settings_store.get_setting(settings_store.LIBRARY_KEY) or settings_store.get_setting("scrape") or {}
        if not isinstance(raw, dict):
            lang = str(DEFAULT_METADATA_OPTIMIZE["mappingLanguage"])
        else:
            opt = normalize_metadata_optimize(
                raw.get("metadataOptimize") or raw.get("metadata_optimize")
            )
            lang = str(opt["mappingLanguage"])
    except Exception:
        lang = str(DEFAULT_METADATA_OPTIMIZE["mappingLanguage"])
    _CACHED_MAPPING_LANG = lang
    return lang


def normalize_actor_names(
    actors: list[str] | None,
    *,
    lang: str | None = None,
    enable: bool | None = None,
) -> list[str]:
    """索引/聚合后把女优名规范成映射表标准名（去重保序）。

    enable=None 时跟刮削「启用演员映射」；索引展示默认开映射。
    """
    raw_list = [str(a).strip() for a in (actors or []) if str(a or "").strip()]
    if not raw_list:
        return []

    use_map = True if enable is None else bool(enable)
    if enable is None:
        try:
            import app.core.settings_store as settings_store

            raw = settings_store.get_setting(settings_store.LIBRARY_KEY) or settings_store.get_setting("scrape") or {}
            if isinstance(raw, dict):
                opt = normalize_metadata_optimize(
                    raw.get("metadataOptimize") or raw.get("metadata_optimize")
                )
                use_map = bool(opt["enableActorMapping"])
        except Exception:
            use_map = True

    if not use_map:
        # 仍清脏装饰并去重
        out: list[str] = []
        seen: set[str] = set()
        for a in raw_list:
            name = _clean_actor_raw(a) or a
            if name in seen:
                continue
            seen.add(name)
            out.append(name)
        return out

    return polish_actress_names(
        raw_list, lang=lang or mapping_language_from_settings(), enable_mapping=True
    )


def normalize_metadata_optimize(raw: Any) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    lang = str(
        src.get("mappingLanguage")
        or src.get("mapping_language")
        or DEFAULT_METADATA_OPTIMIZE["mappingLanguage"]
    ).strip()
    if lang in {"zh", "zh_cn", "zh-cn", "cn", "hans", "简体", "简体中文"}:
        lang = "zh-CN"
    elif lang in {"zh_tw", "zh-tw", "tw", "hant", "繁体", "繁體", "繁体中文"}:
        lang = "zh-TW"
    elif lang in {"jp", "japanese", "日文", "日本語"}:
        lang = "ja"
    elif lang in {"eng", "english", "英文"}:
        lang = "en"
    if lang not in MAPPING_LANGS:
        lang = "zh-CN"

    def _b(key: str, *alts: str, default: bool = True) -> bool:
        for k in (key, *alts):
            if k in src and src[k] is not None:
                return bool(src[k])
        return default

    return {
        "useForumZhTitle": _b(
            "useForumZhTitle", "use_forum_zh_title", "useSehuatangTitle", default=True
        ),
        "enableActorMapping": _b(
            "enableActorMapping", "enable_actor_mapping", default=True
        ),
        "enableTagMapping": _b(
            "enableTagMapping", "enable_tag_mapping", default=True
        ),
        "compactOutlineNewlines": _b(
            "compactOutlineNewlines",
            "compact_outline_newlines",
            "trimOutlineNewlines",
            default=True,
        ),
        "mappingLanguage": lang,
    }


def _lang_file_stem(lang: str) -> str:
    return {
        "zh-CN": "zh-CN",
        "zh-TW": "zh-TW",
        "ja": "ja",
        "en": "en",
    }.get(lang, "zh-CN")


@lru_cache(maxsize=16)
def _load_json_map(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


# 索引缓存：`id(table)` → (table, index)。
# ⚠️ 必须把 table 自身也存进来当强引用：否则表对象一旦被 GC，
# 其 `id` 可能被**另一个表**复用，查到的就是过期索引 → 静默错误映射。
# 同时用 `hit[0] is table` 做身份校验作双保险。
_CASEFOLD_INDEX: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
# canon name forms → alias keys（避免 polish_tag 每次全表扫描）
_ACTOR_CANON_ALIASES: dict[int, tuple[dict[str, Any], dict[str, set[str]]]] = {}


_SETTING_MAP_ENABLED: bool | None = None


def clear_map_cache() -> None:
    global _SETTING_MAP_ENABLED, _CACHED_MAPPING_LANG
    _load_json_map.cache_clear()
    _CASEFOLD_INDEX.clear()
    _VARIANT_INDEX.clear()
    _ACTOR_CANON_ALIASES.clear()
    _SETTING_MAP_ENABLED = None
    _CACHED_MAPPING_LANG = None


def _actor_canon_alias_index(table: dict[str, Any]) -> dict[str, set[str]]:
    """name/zh 折叠形 → 表内键集合，供标签排除女优别名时 O(1) 扩表。"""
    tid = id(table)
    hit = _ACTOR_CANON_ALIASES.get(tid)
    if hit is not None and hit[0] is table:
        return hit[1]
    idx: dict[str, set[str]] = {}
    for k, raw in table.items():
        name = ""
        if isinstance(raw, dict):
            name = str(raw.get("name") or raw.get("zh") or "").strip()
        elif isinstance(raw, str):
            name = raw.strip()
        if not name:
            continue
        key_s = str(k)
        forms_name = _name_ban_forms(name)
        # 原写法在 `for form in ...` 循环体内反复调 `_name_ban_forms(key_s/name)`
        # 并对每个 form 重复做同一次并集 —— 结果恒等于 {key_s} ∪ forms_key ∪ forms_name。
        # 提到循环外：等价、少 O(len(forms)) 倍重复（第九轮）。
        extra = _name_ban_forms(key_s) | forms_name
        for form in forms_name:
            bucket = idx.get(form)
            if bucket is None:
                bucket = set()
                idx[form] = bucket
            bucket.add(key_s)
            bucket |= extra
    _ACTOR_CANON_ALIASES[tid] = (table, idx)
    return idx


def _actor_mapping_enabled() -> bool:
    global _SETTING_MAP_ENABLED
    if _SETTING_MAP_ENABLED is not None:
        return _SETTING_MAP_ENABLED
    use_map = True
    try:
        import app.core.settings_store as settings_store

        raw = (
            settings_store.get_setting(settings_store.LIBRARY_KEY)
            or settings_store.get_setting("scrape")
            or {}
        )
        if isinstance(raw, dict):
            opt = normalize_metadata_optimize(
                raw.get("metadataOptimize") or raw.get("metadata_optimize")
            )
            use_map = bool(opt["enableActorMapping"])
    except Exception:
        use_map = True
    _SETTING_MAP_ENABLED = use_map
    return use_map


def _actor_maps(lang: str) -> dict[str, Any]:
    stem = _lang_file_stem(lang)
    from app.core.maps_paths import scrape_maps_seed_dir

    root = scrape_maps_seed_dir()
    for name in (f"actors.{stem}.json", "actors.json"):
        m = _load_json_map(str(root / name))
        if m:
            return m
    return {}


def _tag_maps(lang: str) -> dict[str, Any]:
    stem = _lang_file_stem(lang)
    from app.core.maps_paths import scrape_maps_seed_dir

    root = scrape_maps_seed_dir()
    for name in (f"tags.{stem}.json", "tags.json"):
        m = _load_json_map(str(root / name))
        if m:
            return m
    return {}


def actor_maps_loaded(lang: str | None = None) -> dict[str, Any]:
    """供任务状态展示：映射表条目数。"""
    table = _actor_maps(lang or mapping_language_from_settings())
    return {"count": len(table), "lang": lang or mapping_language_from_settings()}


def _casefold_index(table: dict[str, Any]) -> dict[str, Any]:
    tid = id(table)
    hit = _CASEFOLD_INDEX.get(tid)
    if hit is not None and hit[0] is table:
        return hit[1]
    idx: dict[str, Any] = {}
    for k, v in table.items():
        raw = str(k).strip()
        if not raw:
            continue
        idx[raw.casefold()] = v
        folded = _kana_fold(raw)
        if folded and folded.casefold() not in idx:
            idx[folded.casefold()] = v
    _CASEFOLD_INDEX[tid] = (table, idx)
    return idx


# ⚠️ 折叠链必须记忆化：这三个函数只依赖入参 + 模块常量（`_TAG_VARIANT_TRANS`
# 在 import 时由 `load_str_map` 建好，运行期不变）→ **纯函数**，且被 `_merge_got`
# 的标签/女优路径按**每标签 × 每形态**反复调用（第九轮实测单番号
# `_kana_fold` 141458 次 / `_fold_variant` 156678 次，占 `_merge_got` CPU 的 ~2/3）。
# 缓存后同样输入只算一次，语义零变化。
@lru_cache(maxsize=16384)
def _kana_fold(s: str) -> str:
    """片假名 → 平假名，便于 倉本スミレ / 倉本すみれ 命中同一映射。"""
    out: list[str] = []
    for ch in str(s or ""):
        o = ord(ch)
        if 0x30A1 <= o <= 0x30F6:  # ァ-ヶ
            out.append(chr(o - 0x60))
        else:
            out.append(ch)
    return "".join(out)


@lru_cache(maxsize=16384)
def _fold_variant(s: str) -> str:
    """繁/日 → 简 折叠（仅用于映射兜底，解繁简分裂）。

    先做 `々` 重复记号归一（`佐々波綾` → `佐佐波綾`），再做繁简折叠
    （→ `佐佐波绫`），使表键 / 标准名 / 源站名三侧都能收敛到同一字形。
    """
    s = _iter_fold(str(s or ""))
    if not _TAG_VARIANT_TRANS:
        return s
    return s.translate(_TAG_VARIANT_TRANS)


@lru_cache(maxsize=8192)
def _name_ban_forms(name: str) -> frozenset[str]:
    """女优排除集：原串 + 繁简折叠 + 片假名折叠，避免标签侧折叠后漏删。

    案例 MOT-276：源标签「眞実かなえ」经 variant-fold 成「眞实かなえ」后，
    与 actors 表键「眞実かなえ」字符串不等 → 旧逻辑漏删。

    ⚠️ 返回 **frozenset** 且**记忆化**：本函数在 `_clean_tags` 的标签循环里
    被每个标签调 4 次（`s_raw` / 去括号基名 / 映射后名 / 去括号映射名），
    第九轮实测单番号 46783 次调用 → 每次现算 4 次折叠。纯函数（只依赖入参），
    缓存后语义不变；返回不可变类型也避免调用方原地改到缓存值。
    """
    raw = str(name or "").strip()
    if not raw:
        return frozenset()
    forms = {raw, _fold_variant(raw), _kana_fold(raw), _kana_fold(_fold_variant(raw))}
    return frozenset(f.casefold() for f in forms if f)


def _in_actor_ban(name: str, ban: set[str]) -> bool:
    if not ban:
        return False
    # `isdisjoint` 不构造交集集合；`_name_ban_forms` 已记忆化，同串零重算。
    return not _name_ban_forms(name).isdisjoint(ban)


_VARIANT_INDEX: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}


def _variant_index(table: dict[str, Any]) -> dict[str, Any]:
    """折叠索引：键与标准名（value）都折叠后建索引，供模糊兜底命中。

    先索引键（原始/折叠/假名折叠），再索引标准名——故「键」优先级始终高于
    「别的条目的标准名」，不会误改既有正确结果。
    """
    tid = id(table)
    hit = _VARIANT_INDEX.get(tid)
    if hit is not None and hit[0] is table:
        return hit[1]
    idx: dict[str, Any] = {}
    for k in table:
        raw = str(k).strip()
        if not raw:
            continue
        v = table[k]
        idx.setdefault(raw.casefold(), v)
        idx.setdefault(_fold_variant(raw).casefold(), v)
        idx.setdefault(_kana_fold(_fold_variant(raw)).casefold(), v)
    # 标准名（如 `继母` 是 `義母` 的目标）也纳入，使 繁/日 写法都能收敛
    for v in table.values():
        name = v
        if isinstance(v, dict):
            name = v.get("name") or v.get("zh") or v.get("title") or ""
        if isinstance(name, str) and name.strip():
            idx.setdefault(_fold_variant(name).casefold(), v)
            idx.setdefault(_kana_fold(_fold_variant(name)).casefold(), v)
    _VARIANT_INDEX[tid] = (table, idx)
    return idx


def _paren_name_candidates(raw: str) -> list[str]:
    """从 `别名(标准名)` / `A（B）` 中取出括号内的名字，作为末位兜底候选。

    只剥**结尾**的括号组（与 `_clean_actor_raw` 的剥离位置逐一对应，可连续多层）；
    括号里是备注（`着エロ` / `HEYZO・天然むすめ`）时会查不中表，自然被忽略。
    """
    s = str(raw or "").strip()
    out: list[str] = []
    while True:
        m = re.search(r"[\(（]([^)）]+)[\)）]\s*$", s)
        if m is None:
            break
        inner = str(m.group(1) or "").strip()
        if inner and inner not in out:
            out.append(inner)
        s = s[: m.start()].strip()
    return out


def _lookup_actor_hit(raw_name: str, table: dict[str, Any]) -> Any:
    key = str(raw_name or "").strip()
    if not key:
        return None
    cleaned = _clean_actor_raw(key)
    variants: list[str] = []
    for cand in (key, cleaned, _kana_fold(key), _kana_fold(cleaned)):
        c = str(cand or "").strip()
        if c and c not in variants:
            variants.append(c)
    for cand in variants:
        hit = table.get(cand)
        if hit is not None:
            return hit
    low = _casefold_index(table)
    for cand in variants:
        hit = low.get(cand.casefold())
        if hit is not None:
            return hit
    # 繁/日 折叠兜底：表里只有 `藤宮櫻花` 时，`藤宫樱花` 也能命中（解女优名繁简分裂）
    vidx = _variant_index(table)
    for cand in variants:
        hit = vidx.get(_fold_variant(cand).casefold())
        if hit is not None:
            return hit
    # 末位兜底：`别名(标准名)` 写法。部分源（如 airav_io `小那海绫(佐佐波绫)`）把
    # **标准中文名放在括号里**、别名放前面；_clean_actor_raw 会把括号剥掉只留别名，
    # 于是永远漏映射。此处把括号内名字也当候选再查一次——**只在前面全部落空时**才走，
    # 故不会改变任何已能命中的结果（零回归），属通用规则而非逐条补表。
    for inner in _paren_name_candidates(key):
        for cand in (inner, _kana_fold(inner)):
            c = str(cand or "").strip()
            if not c:
                continue
            hit = table.get(c) or low.get(c.casefold()) or vidx.get(_fold_variant(c).casefold())
            if hit is not None:
                return hit
    return None


def _actor_should_drop(hit: Any) -> bool:
    """映射表标记男优 / 导演 / 原作等非女优 → 丢弃。"""
    if hit is None or isinstance(hit, str):
        return False
    if not isinstance(hit, dict):
        return False
    if hit.get("drop") is True or hit.get("exclude") is True:
        return True
    role = str(hit.get("role") or hit.get("type") or "").strip().casefold()
    if role in {
        "director",
        "导演",
        "監督",
        "male",
        "男优",
        "男優",
        "author",
        "writer",
        "原作",
        "漫画家",
        "artist",
        "作画",
        "staff",
    }:
        return True
    sex = str(hit.get("sex") or hit.get("gender") or "").strip().casefold()
    if sex in {"m", "male", "man", "男"}:
        return True
    return False


def _map_actor_entry(raw_name: str, table: dict[str, Any]) -> tuple[str, str]:
    """返回 (显示名, javdb链接)。drop 条目返回空名。"""
    key = str(raw_name or "").strip()
    if not key:
        return "", ""
    cleaned = _clean_actor_raw(key)
    display_fallback = cleaned or key
    hit = _lookup_actor_hit(key, table)
    if _actor_should_drop(hit):
        return "", ""
    if hit is None:
        return display_fallback, ""
    if isinstance(hit, str):
        return (hit.strip() or display_fallback), ""
    if isinstance(hit, dict):
        name = str(
            hit.get("name") or hit.get("zh") or hit.get("title") or ""
        ).strip()
        link = str(
            hit.get("javdb")
            or hit.get("javdbUrl")
            or hit.get("url")
            or hit.get("link")
            or ""
        ).strip()
        return (name or display_fallback), link
    return display_fallback, ""


def _actor_identity_key(name: str) -> str:
    """同人身份键：NFKC + 繁简/假名折叠；不强制中文，只收敛别名写法。"""
    import unicodedata

    s = unicodedata.normalize("NFKC", str(name or "").strip())
    if not s:
        return ""
    return _kana_fold(_fold_variant(s)).casefold()


def polish_actress_names(
    names: list[str] | None,
    *,
    exclude: list[str] | None = None,
    lang: str | None = None,
    enable_mapping: bool | None = None,
) -> list[str]:
    """女优名单优化：身份/别名收敛 + 排除导演/男优/映射 drop。

    有映射表则落到 canon（可中可日）；无表则折叠字形去重。不强制输出中文。
    """
    raw_list = [str(a).strip() for a in (names or []) if str(a or "").strip()]
    if not raw_list:
        return []

    ban = {
        str(x).strip().casefold()
        for x in (exclude or [])
        if str(x or "").strip()
    }
    ban_id = {_actor_identity_key(x) for x in ban if _actor_identity_key(x)}

    use_map = True if enable_mapping is None else bool(enable_mapping)
    if enable_mapping is None:
        use_map = _actor_mapping_enabled()

    table = _actor_maps(lang or mapping_language_from_settings()) if use_map else {}
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_list:
        cleaned = _clean_actor_raw(raw) or raw
        if cleaned.casefold() in ban or _actor_identity_key(cleaned) in ban_id:
            continue
        hit = None
        if use_map and table:
            # 传 **raw**（而非已剥括号的 cleaned）：`别名(标准名)` 只在 raw 上才看得到
            # 括号，_lookup_actor_hit 的末位兜底才有机会命中标准名。
            hit = _lookup_actor_hit(raw, table)
            if _actor_should_drop(hit):
                continue
            name, _ = _map_actor_entry(raw, table)
            if hit is None:
                # 未入表 → 输出按 繁/日 → 简 折叠字形。
                # 中文源与日文源对同一人常只差一个字形（BMW-311 `乃木蛍`+`乃木萤`、
                # KMHR-050 `水樹璃子`+`水树璃子`），不折叠就会在同号里出两条 → 人数虚高。
                # 注意：未命中时先折；命中后再统一对纯汉字 fold（见下）
                name = _fold_variant(name) or name
                key = _actor_identity_key(name)
            else:
                # 已映射：以 canon 展示键去重（同人别名已落到同一 name）
                key = str(name or "").strip().casefold() or _actor_identity_key(name)
        else:
            name = cleaned
            key = _actor_identity_key(name)
        name = str(name or "").strip()
        # 表内 canon 偶有繁体（青葉春）；展示统一折简，避免标题简/女优繁打架
        if name and not re.search(r"[\u3040-\u30ff]", name):
            folded = _fold_variant(name) or name
            if folded != name:
                name = folded
                if use_map and table and hit is not None:
                    key = name.casefold() or _actor_identity_key(name)
                else:
                    key = _actor_identity_key(name)
        if not name or name.casefold() in ban or _actor_identity_key(name) in ban_id:
            continue
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _normalize_tag_separators(s: str) -> str:
    """统一标签分隔符：`&`/`＆`/`･`/`·`/`/`/`、` → `・`，便于命中表内 `淫乱・ハード系` 类键。"""
    out = str(s or "")
    for ch in ("&", "＆", "･", "·", "/", "／", "、", ","):
        out = out.replace(ch, "・")
    return out


def _map_tag(raw: str, table: dict[str, Any]) -> str:
    key = str(raw or "").strip()
    if not key:
        return ""
    import unicodedata

    key_n = unicodedata.normalize("NFKC", key)
    key_sep = _normalize_tag_separators(key_n)
    hit = table.get(key)
    if hit is None and key_n != key:
        hit = table.get(key_n)
    if hit is None and key_sep not in (key, key_n):
        hit = table.get(key_sep)
    if hit is None:
        low = _casefold_index(table)
        hit = (
            low.get(key.casefold())
            or low.get(key_n.casefold())
            or low.get(key_sep.casefold())
        )
    if hit is None:
        # 繁/日 折叠兜底：映射表只写了繁体键时，简体/日文写法也能命中（解繁简分裂）
        vidx = _variant_index(table)
        hit = (
            vidx.get(_fold_variant(key).casefold())
            or vidx.get(_fold_variant(key_n).casefold())
            or vidx.get(_fold_variant(key_sep).casefold())
            or vidx.get(_kana_fold(_fold_variant(key)).casefold())
            # 半角片假名要先 NFKC 再折平假名（EKDV-583：`縛ﾘ･緊縛` NFKC 后是
            # `縛リ・緊縛`，只有折了片假名才命得中表里的 `縛り・緊縛`）
            or vidx.get(_kana_fold(_fold_variant(key_n)).casefold())
            or vidx.get(_kana_fold(_fold_variant(key_sep)).casefold())
        )
    if hit is None:
        return key_n or key
    if isinstance(hit, dict) and (
        hit.get("drop") is True or hit.get("exclude") is True
    ):
        return ""
    if isinstance(hit, str):
        return hit.strip() or key_n
    if isinstance(hit, dict):
        return (
            str(hit.get("name") or hit.get("zh") or hit.get("title") or "").strip()
            or key_n
        )
    return key_n


_PAREN_SUFFIX_RE = re.compile(r"[（(][^）)]{0,40}[）)]\s*$")


def _strip_paren_suffix(s: str) -> str:
    """去掉末尾的（别名）/(别名)：用于识别「女优名（旧名）」类 bleed。"""
    return _PAREN_SUFFIX_RE.sub("", str(s or "")).strip()


def polish_tag_names(
    tags: list[str] | None,
    *,
    lang: str | None = None,
    enable_mapping: bool | None = None,
    exclude: list[str] | None = None,
    prefix: str = "",
) -> list[str]:
    """标签优化：映射简中标准名 + 同义合并 + drop 噪声/女优名串入/番号前缀/促销词。"""
    raw_list = [str(t).strip() for t in (tags or []) if str(t or "").strip()]
    if not raw_list:
        return []

    ban = set()
    for x in exclude or []:
        ban |= _name_ban_forms(str(x))

    use_map = True if enable_mapping is None else bool(enable_mapping)
    if enable_mapping is None:
        try:
            import app.core.settings_store as settings_store

            raw = settings_store.get_setting(settings_store.LIBRARY_KEY) or settings_store.get_setting("scrape") or {}
            if isinstance(raw, dict):
                opt = normalize_metadata_optimize(
                    raw.get("metadataOptimize") or raw.get("metadata_optimize")
                )
                use_map = bool(opt["enableTagMapping"])
        except Exception:
            use_map = True

    table = _tag_maps(lang or mapping_language_from_settings()) if use_map else {}
    try:
        a_table = _actor_maps(lang or mapping_language_from_settings())
        extra_ban: set[str] = set()
        for x in exclude or []:
            hit = _lookup_actor_hit(str(x), a_table)
            if isinstance(hit, dict) and hit.get("name"):
                extra_ban |= _name_ban_forms(str(hit.get("name") or ""))
                extra_ban |= _name_ban_forms(str(hit.get("zh") or ""))
            elif isinstance(hit, str) and hit:
                extra_ban |= _name_ban_forms(hit)
            extra_ban |= _name_ban_forms(str(x))
        # 映射表里指向同一人的键也禁（含折叠形）——用反向索引，避免每次 O(全表)
        canons = {b for b in extra_ban if b}
        if canons and a_table:
            rev = _actor_canon_alias_index(a_table)
            for c in canons:
                extra_ban |= rev.get(c) or set()
        ban |= {b for b in extra_ban if b}
    except Exception:
        pass
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_list:
        s_raw = str(raw).strip()
        if _in_actor_ban(s_raw, ban):
            continue
        # 「女优名（别名）」串入标签（如「日高ゆりあ（青山ひより）」）→ 按女优名 drop
        _base = _strip_paren_suffix(s_raw)
        if _base and _base != s_raw and _in_actor_ban(_base, ban):
            continue
        # 过短噪声（如「高」）
        if len(s_raw) <= 1:
            continue
        # 促销/活动词、番号前缀（源站常误当 genre）→ 通用丢弃
        if tag_is_noise(s_raw, prefix=prefix):
            continue
        name = _map_tag(raw, table) if table else raw
        name = str(name or "").strip()
        if not name or _in_actor_ban(name, ban):
            continue
        _nbase = _strip_paren_suffix(name)
        if _nbase and _nbase != name and _in_actor_ban(_nbase, ban):
            continue
        if len(name) <= 1:
            continue
        if tag_is_noise(name, prefix=prefix):
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def compact_outline(text: str) -> str:
    s = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not s:
        return ""
    s = _MULTI_NL_RE.sub("\n", s)
    return s.strip()
