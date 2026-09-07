"""七区元数据与番号前缀规范化（供 prefix 扫库 / 搜索共用）。"""

from __future__ import annotations

import re

# 稳定 id → 展示名；db_region 供 prefix_service / 白名单查询
REGION_META: dict[str, dict[str, str]] = {
    "japan_censored": {
        "id": "japan_censored",
        "label": "日本有码",
        "db_region": "japan_censored",
        "navPath": "片区/日本/有码",
    },
    "japan_gravure": {
        "id": "japan_gravure",
        "label": "日本写真",
        "db_region": "japan",
        "navPath": "片区/日本/写真",
    },
    "japan_uncensored": {
        "id": "japan_uncensored",
        "label": "日本无码",
        "db_region": "japan_uncensored",
        "navPath": "片区/日本/无码",
    },
    "japan_amateur": {
        "id": "japan_amateur",
        "label": "日本素人",
        "db_region": "japan_amateur",
        "navPath": "片区/日本/素人",
    },
    "fc2": {
        "id": "fc2",
        "label": "FC2",
        "db_region": "fc2",
        "navPath": "片区/日本/FC2",
    },
    "china": {
        "id": "china",
        "label": "国产无码",
        "db_region": "china",
        "navPath": "片区/国产/无码",
    },
    "western": {
        "id": "western",
        "label": "欧美无码",
        "db_region": "western",
        "navPath": "片区/欧美/无码",
    },
}

REGION_ORDER = list(REGION_META.keys())

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
