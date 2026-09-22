# -*- coding: utf-8 -*-
"""Shim — 实现已迁至 app.scrap_library.actress.store"""
from __future__ import annotations

from app.scrap_library.actress.store import *  # noqa: F403
from app.scrap_library.actress.store import (  # noqa: F401
    ACTRESS_TABLE,
    actress_ages_for_names,
    collect_library_actress_names,
    ensure_actress_schema,
    get_actress_row,
    sync_actresses_to_vector_db,
    upsert_actress_profile,
)
