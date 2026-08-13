"""刮削后元数据优化（色花堂中文标题 / 演员·标签映射 / 简介换行）。"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .db import ROOT

MAPPING_LANGS = frozenset({"zh-CN", "zh-TW", "ja", "en"})
_MULTI_NL_RE = re.compile(r"\n{2,}")
# 色花堂字段偶发装饰：首尾 +/-/~ / 全角～
_ACTOR_DIRTY_RE = re.compile(r"^[\+\-\~\～\s　]+|[\+\-\~\～\s　]+$")

DEFAULT_METADATA_OPTIMIZE: dict[str, Any] = {
    "useForumZhTitle": False,
    "enableActorMapping": True,
    "enableTagMapping": True,
    "compactOutlineNewlines": True,
    "mappingLanguage": "zh-CN",
}

_MAPS_DIR = ROOT / "data" / "scrape_maps"


def _clean_actor_raw(name: str) -> str:
    s = str(name or "").strip()
    if not s:
        return ""
    s = _ACTOR_DIRTY_RE.sub("", s).strip()
    return re.sub(r"\s+", " ", s)


def mapping_language_from_settings() -> str:
    """读刮削配置里的 mappingLanguage，失败则 zh-CN。"""
    try:
        from . import settings_store

        raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
        if not isinstance(raw, dict):
            return str(DEFAULT_METADATA_OPTIMIZE["mappingLanguage"])
        opt = normalize_metadata_optimize(
            raw.get("metadataOptimize") or raw.get("metadata_optimize")
        )
        return str(opt["mappingLanguage"])
    except Exception:
        return str(DEFAULT_METADATA_OPTIMIZE["mappingLanguage"])


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
            from . import settings_store

            raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
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

    table = _actor_maps(lang or mapping_language_from_settings())
    mapped: list[str] = []
    seen_m: set[str] = set()
    for a in raw_list:
        name, _ = _map_actor_entry(a, table)
        name = name.strip()
        if not name or name in seen_m:
            continue
        seen_m.add(name)
        mapped.append(name)
    return mapped


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


def clear_map_cache() -> None:
    _load_json_map.cache_clear()


def _actor_maps(lang: str) -> dict[str, Any]:
    stem = _lang_file_stem(lang)
    # 优先语言文件，再回退 actors.json
    for name in (f"actors.{stem}.json", "actors.json"):
        m = _load_json_map(str(_MAPS_DIR / name))
        if m:
            return m
    return {}


def _tag_maps(lang: str) -> dict[str, Any]:
    stem = _lang_file_stem(lang)
    for name in (f"tags.{stem}.json", "tags.json"):
        m = _load_json_map(str(_MAPS_DIR / name))
        if m:
            return m
    return {}


def _map_actor_entry(raw_name: str, table: dict[str, Any]) -> tuple[str, str]:
    """返回 (显示名, javdb链接)。"""
    key = str(raw_name or "").strip()
    if not key:
        return "", ""
    cleaned = _clean_actor_raw(key)
    hit = table.get(key)
    if hit is None and cleaned and cleaned != key:
        hit = table.get(cleaned)
    if hit is None:
        # 大小写不敏感兜底
        low = {str(k).strip().lower(): v for k, v in table.items()}
        hit = low.get(key.lower())
        if hit is None and cleaned:
            hit = low.get(cleaned.lower())
    display_fallback = cleaned or key
    if hit is None:
        return display_fallback, ""
    if isinstance(hit, str):
        return (hit.strip() or display_fallback), ""
    if isinstance(hit, dict):
        name = str(hit.get("name") or hit.get("zh") or hit.get("title") or "").strip()
        link = str(
            hit.get("javdb")
            or hit.get("javdbUrl")
            or hit.get("url")
            or hit.get("link")
            or ""
        ).strip()
        return (name or display_fallback), link
    return display_fallback, ""


def _map_tag(raw: str, table: dict[str, Any]) -> str:
    key = str(raw or "").strip()
    if not key:
        return ""
    hit = table.get(key)
    if hit is None:
        low = {str(k).strip().lower(): v for k, v in table.items()}
        hit = low.get(key.lower())
    if hit is None:
        return key
    if isinstance(hit, str):
        return hit.strip() or key
    if isinstance(hit, dict):
        return str(hit.get("name") or hit.get("zh") or hit.get("title") or key).strip() or key
    return key


def compact_outline(text: str) -> str:
    s = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not s:
        return ""
    s = _MULTI_NL_RE.sub("\n", s)
    return s.strip()


def apply_metadata_optimize(
    meta: dict[str, Any],
    cfg: dict[str, Any] | None,
    *,
    forum_title: str = "",
    forum_actors: list[str] | None = None,
) -> dict[str, Any]:
    """就地优化副本后返回。"""
    opt = normalize_metadata_optimize(cfg)
    out = dict(meta or {})
    lang = str(opt["mappingLanguage"])

    # 色花堂帖题/女优：字段优先级已在 scrape 阶段按配置选取；此处不再强制盖题
    forum = str(forum_title or "").strip()

    # 色花堂女优：帖内【出演女优】优先覆盖
    forum_acts = [
        str(a).strip()
        for a in (forum_actors or [])
        if str(a or "").strip()
    ]
    if forum_acts:
        out["actors"] = forum_acts
        fs = out.get("fieldSources") if isinstance(out.get("fieldSources"), dict) else {}
        fs = dict(fs)
        fs["actors"] = "forum"
        out["fieldSources"] = fs

    # 简介换行
    if opt["compactOutlineNewlines"]:
        for key in ("outline", "plot"):
            if key in out and out[key]:
                out[key] = compact_outline(str(out[key]))

    # 演员映射
    if opt["enableActorMapping"]:
        table = _actor_maps(lang)
        actors = out.get("actors") if isinstance(out.get("actors"), list) else []
        if actors:
            mapped: list[str] = []
            links: list[str] = []
            seen: set[str] = set()
            for a in actors:
                name, link = _map_actor_entry(str(a), table)
                if not name or name in seen:
                    continue
                seen.add(name)
                mapped.append(name)
                links.append(link)
            out["actors"] = mapped
            if any(links):
                out["actorLinks"] = links

    # 标题不再剥末尾女优名（女优只认描述字段）
    # actors 映射已在上方完成；title/titleZh 保持原清洗结果

    # 标签映射
    if opt["enableTagMapping"]:
        table = _tag_maps(lang)
        for key in ("genres", "tags"):
            vals = out.get(key) if isinstance(out.get(key), list) else None
            if not vals:
                continue
            mapped_tags: list[str] = []
            seen_t: set[str] = set()
            for g in vals:
                name = _map_tag(str(g), table)
                if not name or name in seen_t:
                    continue
                seen_t.add(name)
                mapped_tags.append(name)
            out[key] = mapped_tags

    out["metadataOptimize"] = {
        "useForumZhTitle": opt["useForumZhTitle"],
        "enableActorMapping": opt["enableActorMapping"],
        "enableTagMapping": opt["enableTagMapping"],
        "compactOutlineNewlines": opt["compactOutlineNewlines"],
        "mappingLanguage": lang,
    }
    return out
