# -*- coding: utf-8 -*-
"""Shim — 实现已迁至 app.scrap_library.actress.bio"""
from __future__ import annotations

from app.scrap_library.actress.bio import *  # noqa: F403
from app.scrap_library.actress.bio import (  # noqa: F401
    age_from_birthday,
    actress_db_candidates,
    bio_cache_path,
    expand_actress_query_names,
    fold_key,
    lookup_actress_db,
    resolve_actress_bio,
)
