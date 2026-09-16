# -*- coding: utf-8 -*-
"""Compat shim — use app.makers.catalog_routes."""
from importlib import import_module

_src = import_module("app.makers.catalog_routes")
globals().update({k: v for k, v in vars(_src).items() if not k.startswith("__")})
__all__ = [k for k in globals() if not k.startswith("_")]
del import_module, _src
