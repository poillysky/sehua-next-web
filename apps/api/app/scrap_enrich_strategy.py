# -*- coding: utf-8 -*-
"""Compat shim — use app.scrap_library.enrich_strategy."""
from importlib import import_module

_src = import_module("app.scrap_library.enrich_strategy")
globals().update({k: v for k, v in vars(_src).items() if not k.startswith("__")})
# Keep package path stable for reload helpers
__all__ = [k for k in globals() if not k.startswith("_")]
del import_module, _src
