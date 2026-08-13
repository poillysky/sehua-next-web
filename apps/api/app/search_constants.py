"""Search constants aligned with sehua-search config/constant.ts."""

from __future__ import annotations

import re

SEARCH_PARAMS = {
    "sortType": ("default", "size", "count", "date"),
    "filterTime": ("all", "gt-1day", "gt-7day", "gt-31day", "gt-365day"),
    "filterSize": (
        "all",
        "lt100mb",
        "gt100mb-lt500mb",
        "gt500mb-lt1gb",
        "gt1gb-lt5gb",
        "gt5gb",
    ),
    "matchMode": ("smart", "exact", "fuzzy"),
}

DEFAULT_SORT_TYPE = "date"
DEFAULT_FILTER_TIME = "all"
DEFAULT_FILTER_SIZE = "all"
DEFAULT_MATCH_MODE = "smart"

SEARCH_KEYWORD_LENGTH_MIN = 2
SEARCH_KEYWORD_LENGTH_MAX = 100
SEARCH_PAGE_SIZE = 10
MAX_SEARCH_OFFSET = 2000

# 智能/模糊：连字符也拆（SONE-001 → SONE + 001）
SEARCH_KEYWORD_SPLIT_REGEX = re.compile(
    r"""[.,!?;—()\[\]{}<>@#%^&*~`"'|\-，。！？；“”‘’「」『』《》、【】……（）·　\s]"""
)

# 精确：不拆 - / _
SEARCH_KEYWORD_SPLIT_REGEX_EXACT = re.compile(
    r"""[.,!?;—()\[\]{}<>@#%^&*~`"'|，。！？；“”‘’「」『』《》、【】……（）·　\s]"""
)

FUZZY_STOPWORDS = frozenset(
    {
        "的",
        "了",
        "和",
        "与",
        "之",
        "在",
        "是",
        "the",
        "a",
        "an",
        "of",
        "and",
        "or",
    }
)

QUOTED_KEYWORD_REGEX = re.compile(r'"([^"]+)"')


def escape_ilike(value: str) -> str:
    """Escape \\ % _ for ILIKE … ESCAPE '\\' (user keywords / literal AV segments)."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def normalize_match_mode(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in SEARCH_PARAMS["matchMode"]:
        return v
    return DEFAULT_MATCH_MODE


def normalize_sort_type(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in SEARCH_PARAMS["sortType"]:
        return v
    return DEFAULT_SORT_TYPE


def resolve_sort_type_for_query(sort_type: str) -> str:
    """Bitmagnet：default = created_at DESC（不做 relevance 全量打分）。"""
    return sort_type
