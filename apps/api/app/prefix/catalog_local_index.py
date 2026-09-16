# -*- coding: utf-8 -*-
"""双库本地索引：封装 scripts/index_codes_from_local_dbs.py 供 API 调用。"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable

# 长驻 API 进程里脚本每次热加载，但 app.* 可能仍是旧模块；扫描前强制 reload。
_RELOAD_DEPS = (
    "app.prefix.code_read",
    "app.prefix.ranges",
    "app.search.av",
    "app.prefix.catalog_store",
)


def _reload_scan_deps() -> None:
    for name in _RELOAD_DEPS:
        try:
            if name in sys.modules:
                importlib.reload(sys.modules[name])
            else:
                importlib.import_module(name)
        except Exception:  # noqa: BLE001
            # 个别依赖失败不阻断；脚本 import 时再暴露真实错误
            pass


def _load_script():
    _reload_scan_deps()
    # app/prefix/… → apps/api/scripts/…
    path = Path(__file__).resolve().parents[2] / "scripts" / "index_codes_from_local_dbs.py"
    spec = importlib.util.spec_from_file_location(
        "prefix_catalog_index_codes_script", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载双库扫描脚本: {path}")
    # 丢弃上次同名模块，避免绑到旧函数对象
    sys.modules.pop("prefix_catalog_index_codes_script", None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["prefix_catalog_index_codes_script"] = mod
    spec.loader.exec_module(mod)
    return mod


def run_local_db_index(
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    mod = _load_script()
    return mod.run_local_db_index(on_progress=on_progress)
