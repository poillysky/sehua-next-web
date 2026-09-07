# -*- coding: utf-8 -*-
"""双库本地索引：封装 scripts/index_codes_from_local_dbs.py 供 API 调用。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable


def _load_script():
    path = Path(__file__).resolve().parent.parent / "scripts" / "index_codes_from_local_dbs.py"
    spec = importlib.util.spec_from_file_location(
        "prefix_catalog_index_codes_script", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载双库扫描脚本: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_local_db_index(
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    mod = _load_script()
    return mod.run_local_db_index(on_progress=on_progress)
