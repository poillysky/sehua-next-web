"""Keyword extraction + WHERE / ORDER builders — Bitmagnet-style match + optional enrich."""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from .jieba_cut import jieba_cut
from .search_av import build_av_code_ilike_patterns, is_av_code_keyword
from .search_constants import (
    FUZZY_STOPWORDS,
    QUOTED_KEYWORD_REGEX,
    SEARCH_KEYWORD_SPLIT_REGEX,
    SEARCH_KEYWORD_SPLIT_REGEX_EXACT,
    escape_ilike,
)
from .search_prefer import SEARCH_NAME_EXPR

# PostgreSQL: ESCAPE '\' — backslash quotes % / _
_ILIKE_ESC = "ESCAPE '\\'"

MatchField = Literal["both", "filename", "title"]


def split_chinese_bigrams(text: str) -> list[dict[str, Any]]:
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    return [
        {"keyword": chars[i] + chars[i + 1], "required": False}
        for i in range(len(chars) - 1)
    ]


def extract_keywords(
    keyword: str, match_mode: str = "smart"
) -> list[dict[str, Any]]:
    keywords: list[dict[str, Any]] = []
    for m in QUOTED_KEYWORD_REGEX.finditer(keyword):
        keywords.append({"keyword": m.group(1), "required": True})

    remaining = QUOTED_KEYWORD_REGEX.sub("", keyword)
    plain = remaining.strip()
    split_re = (
        SEARCH_KEYWORD_SPLIT_REGEX_EXACT
        if match_mode == "exact"
        else SEARCH_KEYWORD_SPLIT_REGEX
    )
    keywords.extend(
        {"keyword": k, "required": match_mode == "exact"}
        for k in split_re.split(plain)
        if k
    )

    if match_mode == "fuzzy" and len(plain) >= 2:
        keywords.extend(jieba_cut(plain))
    elif match_mode == "smart" and len(keywords) == 1 and len(plain) >= 4:
        keywords.extend(jieba_cut(plain))

    if match_mode == "fuzzy" and len(plain) >= 4:
        keywords.extend(split_chinese_bigrams(plain))

    min_len = 1 if match_mode == "fuzzy" else 2
    seen: dict[str, dict[str, Any]] = {}
    for item in keywords:
        kw = str(item["keyword"]).strip()
        if len(kw) < min_len:
            continue
        if kw.lower() in FUZZY_STOPWORDS:
            continue
        seen[kw] = {"keyword": kw, "required": bool(item["required"])}
    keywords = list(seen.values())

    if match_mode == "fuzzy":
        return keywords or [{"keyword": plain or keyword, "required": False}]

    if match_mode == "exact":
        if not keywords:
            return [{"keyword": plain or keyword, "required": True}]
        return [{"keyword": x["keyword"], "required": True} for x in keywords]

    if keywords and not any(x["required"] for x in keywords):
        n = max(1, math.ceil(len(keywords) / 3))
        for k in sorted(keywords, key=lambda x: len(x["keyword"]), reverse=True)[
            :n
        ]:
            k["required"] = True

    full = keyword.replace('"', "")
    if not any(x["keyword"] == full for x in keywords):
        keywords.insert(0, {"keyword": full, "required": False})
    return keywords


def _token_match_clause(field: MatchField = "both") -> str:
    """Bitmagnet: single-column ILIKE；勿 COALESCE(title)，否则吃不到 gin_trgm。"""
    if field == "filename":
        return f"(r.filename ILIKE %s {_ILIKE_ESC})"
    if field == "title":
        return f"(rs.title ILIKE %s {_ILIKE_ESC})"
    return (
        f"(r.filename ILIKE %s {_ILIKE_ESC} "
        f"OR rs.title ILIKE %s {_ILIKE_ESC})"
    )


def _params_for_like(like: str, field: MatchField) -> list[str]:
    return [like] if field != "both" else [like, like]


def _like_contains(keyword: str) -> str:
    return f"%{escape_ilike(keyword)}%"


def build_exact_keyword_clause(
    keywords: list[dict[str, Any]],
    *,
    field: MatchField = "both",
) -> tuple[str, list[Any], list[str]]:
    """Returns (sql, params, code_bound_keywords)."""
    if not keywords:
        return "FALSE", [], []
    parts: list[str] = []
    params: list[Any] = []
    code_bound: list[str] = []
    clause = _token_match_clause(field)
    for item in keywords:
        kw = str(item["keyword"])
        if is_av_code_keyword(kw):
            patterns = build_av_code_ilike_patterns(kw)
            or_parts = []
            for pat in patterns:
                or_parts.append(clause)
                params.extend(_params_for_like(pat, field))
            parts.append("(" + " OR ".join(or_parts) + ")")
            code_bound.append(kw)
        else:
            parts.append(clause)
            like = _like_contains(kw)
            params.extend(_params_for_like(like, field))
    return " AND ".join(parts), params, code_bound


def build_keyword_filter(
    keywords: list[dict[str, Any]],
    match_mode: str,
    *,
    full_keyword: str | None = None,
    use_trgm: bool = False,
    field: MatchField = "both",
) -> tuple[str, list[Any], list[str]]:
    """Return (sql, params, code_bound_keywords)."""
    if not keywords:
        return "FALSE", [], []

    if match_mode == "exact":
        return build_exact_keyword_clause(keywords, field=field)

    clause = _token_match_clause(field)

    if match_mode == "fuzzy":
        case_parts: list[str] = []
        params: list[Any] = []
        for item in keywords:
            case_parts.append(f"(CASE WHEN {clause} THEN 1 ELSE 0 END)")
            like = _like_contains(str(item["keyword"]))
            params.extend(_params_for_like(like, field))
        min_matches = max(1, math.ceil(len(keywords) * 0.5))
        expr = " + ".join(case_parts)
        token_match = f"(({expr}) >= {min_matches})"
        if use_trgm and full_keyword and field == "both":
            sql = (
                f"({token_match}"
                f" OR word_similarity(%s, {SEARCH_NAME_EXPR}) > 0.25"
                f" OR similarity({SEARCH_NAME_EXPR}, %s) > 0.15)"
            )
            params.extend([full_keyword, full_keyword])
            return sql, params, []
        if use_trgm and full_keyword and field == "filename":
            sql = (
                f"({token_match}"
                f" OR word_similarity(%s, r.filename) > 0.25"
                f" OR similarity(r.filename, %s) > 0.15)"
            )
            params.extend([full_keyword, full_keyword])
            return sql, params, []
        if use_trgm and full_keyword and field == "title":
            sql = (
                f"({token_match}"
                f" OR word_similarity(%s, rs.title) > 0.25"
                f" OR similarity(rs.title, %s) > 0.15)"
            )
            params.extend([full_keyword, full_keyword])
            return sql, params, []
        return token_match, params, []

    # smart — Bitmagnet: required AND + optional OR
    required: list[str] = []
    optional: list[str] = []
    params: list[Any] = []
    for item in keywords:
        like = _like_contains(str(item["keyword"]))
        params.extend(_params_for_like(like, field))
        if item["required"]:
            required.append(clause)
        else:
            optional.append(clause)
    parts = list(required)
    if optional:
        optional.append("TRUE")
        parts.append("(" + " OR ".join(optional) + ")")
    return (" AND ".join(parts) if parts else "FALSE"), params, []


def build_relevance_order_by(
    keywords: list[dict[str, Any]],
    full_keyword: str,
    *,
    use_trgm: bool,
) -> tuple[str, list[Any]]:
    parts: list[str] = []
    params: list[Any] = []
    for i, item in enumerate(keywords):
        weight = 10 if i == 0 else (3 if item["required"] else 1)
        parts.append(
            f"(CASE WHEN {_token_match_clause('both')} THEN {weight} ELSE 0 END)"
        )
        like = _like_contains(str(item["keyword"]))
        params.extend([like, like])

    parts.append(
        f"(CASE WHEN lower({SEARCH_NAME_EXPR}) = lower(%s) THEN 100 ELSE 0 END)"
    )
    parts.append(
        f"(CASE WHEN lower({SEARCH_NAME_EXPR}) LIKE lower(%s) || '%%' THEN 40 ELSE 0 END)"
    )
    params.extend([full_keyword, full_keyword])

    if use_trgm:
        parts.append(
            f"(COALESCE(word_similarity(%s, {SEARCH_NAME_EXPR}), 0) * 60"
            f" + COALESCE(similarity({SEARCH_NAME_EXPR}, %s), 0) * 40)"
        )
        params.extend([full_keyword, full_keyword])

    order = f"({' + '.join(parts)}) DESC, r.size DESC NULLS LAST, r.created_at DESC"
    return order, params
