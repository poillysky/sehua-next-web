"""七区元数据与番号前缀规范化（供 prefix 扫库 / 搜索共用）。"""

from __future__ import annotations

import re

from app.core.maps_paths import regions_doc

_REGION_DOC = regions_doc()
REGION_META: dict[str, dict[str, str]] = {
    str(k): {str(sk): str(sv) for sk, sv in dict(v).items()}
    for k, v in dict(_REGION_DOC.get("regions") or {}).items()
}
_ORDER = [str(x) for x in (_REGION_DOC.get("order") or [])]
REGION_ORDER = [x for x in _ORDER if x in REGION_META] or list(REGION_META.keys())

# 仅这两区把女优名写入索引副文案；其它区只保留标题
FORUM_ACTORS_INDEX_REGIONS = frozenset({"japan_censored", "japan_gravure"})


def std_prefix(prefix: str) -> str:
    return str(prefix or "").strip().upper().replace("_", "-")


def resolve_fs_region(region: str | None) -> str | None:
    """前端 / 白名单 region → 七区 id。"""
    key = str(region or "").strip().lower()
    if not key:
        return None
    if key in ("japan", "gravure", "jp"):
        return "japan_gravure"
    if key in ("amateur", "素人"):
        return "japan_amateur"
    if key in ("fc2ppv",):
        return "fc2"
    if key in REGION_META:
        return key
    return None


def indexes_forum_actors(region: str | None) -> bool:
    """是否索引女优（仅日本有码 / 日本写真）。"""
    rid = resolve_fs_region(region)
    return bool(rid and rid in FORUM_ACTORS_INDEX_REGIONS)


def is_fc2_plate_maker_name(name: str) -> bool:
    """论坛板名/前缀壳，不是真实 FC2 作者名。"""
    s = re.sub(r"[\s·\-_/=]+", "", str(name or "").strip().lower())
    if not s:
        return True
    return s in {"fc2", "fc2ppv", "fc2ppvfc2"} or s.startswith("fc2fc2") or bool(
        re.fullmatch(r"fc2(ppv)?", s)
    )


def db_region_for(fs_region: str | None) -> str | None:
    meta = REGION_META.get(str(fs_region or ""))
    if not meta:
        return None
    return str(meta.get("db_region") or "").strip() or None
