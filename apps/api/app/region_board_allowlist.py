"""片区 board_fid 放行（完全以论坛地区配置为准）。

历史 ``REGION_BOARD_ALLOWLIST`` 仅作空壳保留，避免旧 import 崩溃；索引/搜索不再读其 primary/optional。

现行规则（``forum_region_tags``）：
- 国产无码 ← 论坛「国产」+「混合」
- 欧美无码 ← 论坛「欧美」+「混合」
- 日本五区 ← 论坛「日本」+「混合」
- 「其他」不参与任一区
"""

from __future__ import annotations

from typing import Any, Literal

SearchRegion = Literal[
    "japan",
    "japan_censored",
    "japan_uncensored",
    "japan_amateur",
    "fc2",
    "china",
    "western",
]

REGION_ALIASES: dict[str, SearchRegion] = {
    "japan": "japan",
    "jp": "japan",
    "gravure": "japan",
    "japan_censored": "japan_censored",
    "yc": "japan_censored",
    "censored": "japan_censored",
    "japan_uncensored": "japan_uncensored",
    "uncensored": "japan_uncensored",
    "japan_amateur": "japan_amateur",
    "amateur": "japan_amateur",
    "素人": "japan_amateur",
    "fc2": "fc2",
    "fc2ppv": "fc2",
    "china": "china",
    "domestic": "china",
    "western": "western",
    "europe": "western",
}

# 已废弃：放行逻辑见 forum_region_tags
GLOBAL_EXCLUDE: list[str] = []
REGION_BOARD_ALLOWLIST: dict[str, dict[str, Any]] = {
    "japan": {"label": "日本", "primary": [], "optional": [], "exclude": []},
    "japan_censored": {
        "label": "日本有码",
        "primary": [],
        "optional": [],
        "exclude": [],
    },
    "japan_uncensored": {
        "label": "日本无码",
        "primary": [],
        "optional": [],
        "exclude": [],
    },
    "japan_amateur": {
        "label": "日本素人",
        "primary": [],
        "optional": [],
        "exclude": [],
    },
    "fc2": {"label": "FC2", "primary": [], "optional": [], "exclude": []},
    "china": {"label": "国产", "primary": [], "optional": [], "exclude": []},
    "western": {"label": "欧美", "primary": [], "optional": [], "exclude": []},
}


def normalize_region(raw: str | None) -> SearchRegion | None:
    key = str(raw or "").strip().lower()
    if not key:
        return None
    return REGION_ALIASES.get(key)


def _parse_spec(spec: str) -> tuple[str, bool]:
    """返回 (fid, tree)。``37*`` → ('37', True)；``103:480`` → ('103:480', False)。"""
    s = str(spec or "").strip()
    if not s:
        return "", False
    tree = s.endswith("*")
    fid = s[:-1] if tree else s
    if not tree and ":" not in fid and fid.isdigit():
        tree = True
    return fid, tree


def _fid_sql(fid: str) -> str:
    if not fid:
        return "FALSE"
    return (
        f"(rs.board_fid = '{fid}'"
        f" OR rs.board_fid LIKE '{fid}:%%')"
    )


def _spec_sql(spec: str) -> str:
    fid, _tree = _parse_spec(spec)
    return _fid_sql(fid) if fid else "FALSE"


def _resolve_key(region: SearchRegion | str | None) -> SearchRegion | None:
    if region in REGION_BOARD_ALLOWLIST:
        return region  # type: ignore[return-value]
    return normalize_region(region)


def _specs_or_sql(specs: list[str]) -> str:
    parts = [_spec_sql(s) for s in specs if _parse_spec(s)[0]]
    if not parts:
        return "FALSE"
    return "(" + " OR ".join(parts) + ")"


def _fid_matches_spec(fid: str, spec: str) -> bool:
    root, _tree = _parse_spec(spec)
    if not root or not fid:
        return False
    return fid == root or fid.startswith(root + ":")


def region_allowlist_sql(
    region: SearchRegion | str | None,
    *,
    include_optional: bool = True,
) -> str:
    """生成 ``AND (…)`` 片段；完全按论坛地区配置。"""
    del include_optional  # 不再区分 primary/optional
    key = _resolve_key(region)
    if not key:
        return ""

    from .forum_region_tags import (
        forum_allow_specs_for_search,
        forum_exclude_specs_for_search,
    )

    allow_specs = forum_allow_specs_for_search(key)
    if not allow_specs:
        return "AND FALSE"
    exclude_specs = forum_exclude_specs_for_search(key)
    allow_sql = _specs_or_sql(allow_specs)
    if not exclude_specs:
        return f"AND {allow_sql}"
    return f"AND (({allow_sql}) AND (NOT {_specs_or_sql(exclude_specs)}))"


def board_fid_allowed(
    board_fid: str | None,
    region: SearchRegion | str | None,
    *,
    include_optional: bool = True,
) -> bool:
    """是否属于该区：只看论坛地区（本区/混合；其他排除）。"""
    del include_optional
    key = _resolve_key(region)
    if not key:
        return True

    from .forum_region_tags import forum_region_allows_search

    fid = str(board_fid or "").strip()
    if not fid:
        return False
    return forum_region_allows_search(fid, key)
