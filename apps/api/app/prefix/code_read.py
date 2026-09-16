# -*- coding: utf-8 -*-
"""按前缀定制的番号读取标准（双库扫描抽取/截断/验收）。"""

from __future__ import annotations

import re
from typing import Any
from app.core.maps_paths import load_json_map

# 预设：扫描时只认该前缀 resolved profile，不再混用一套逻辑

_CODE_READ_DOC = load_json_map("prefix-code-read.json")
CODE_READ_PRESETS: dict[str, dict[str, Any]] = dict(_CODE_READ_DOC.get("presets") or {})
VALID_CODE_READ_IDS = frozenset(CODE_READ_PRESETS.keys())
_STD3_OPEN = frozenset(_CODE_READ_DOC.get("groups", {}).get("std3_open") or [])
_AMATEUR4 = frozenset(_CODE_READ_DOC.get("groups", {}).get("amateur4") or [])
_SHAPE_TO_READ = dict(_CODE_READ_DOC.get("shapeToPreset") or {})
_DIGIT_HEAD_RE = re.compile(r"^(\d{2,3})([A-Z]{2,14})$")


def _prefix_key(prefix: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(prefix or "").strip().upper())


def _letter_core(prefix: str) -> str:
    """259LUXU → LUXU；CLUB → CLUB。"""
    key = _prefix_key(prefix)
    m = _DIGIT_HEAD_RE.match(key)
    return m.group(2) if m else key


def infer_code_read(prefix: str, entry: dict[str, Any] | None = None) -> str:
    """为前缀推断 code_read 预设 ID。"""
    ent = dict(entry or {})
    key = _prefix_key(prefix or ent.get("prefix") or "")
    core = _letter_core(key)

    try:
        from app.search.av import resolve_maker_shape

        shape = resolve_maker_shape(key or str(prefix or ""))
    except Exception:
        shape = "std"
    mapped = _SHAPE_TO_READ.get(shape)
    if mapped:
        return mapped

    if key in _STD3_OPEN or core in _STD3_OPEN:
        return "std3_open"
    if key in _AMATEUR4 or core in _AMATEUR4:
        return "amateur4"

    pad = int(ent.get("pad") or 3)
    if pad >= 4:
        return "std4"
    return "std3_dmm"


def resolve_code_read(
    prefix: str = "",
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """解析前缀最终读取配置（预设 + 目录覆盖）。"""
    ent = dict(entry or {})
    pref = str(prefix or ent.get("prefix") or "").strip()
    raw_id = str(ent.get("code_read") or "").strip()
    if raw_id not in VALID_CODE_READ_IDS:
        raw_id = infer_code_read(pref, ent)
    base = dict(CODE_READ_PRESETS.get(raw_id) or CODE_READ_PRESETS["std3_dmm"])
    out: dict[str, Any] = {
        "id": raw_id,
        "pad": int(base.get("pad") or 3),
        "cid_width": int(base.get("cid_width") or 0),
        "leading_zero": str(base.get("leading_zero") or "int"),
        "max_serial": base.get("max_serial"),
        "prefer_digit_len": base.get("prefer_digit_len"),
        "outlier": str(base.get("outlier") or "robust"),
        "measure_glue": bool(base.get("measure_glue")),
    }
    # 目录覆盖
    if ent.get("code_read_max") is not None and str(ent.get("code_read_max")).strip() != "":
        try:
            out["max_serial"] = int(ent["code_read_max"])
        except (TypeError, ValueError):
            pass
    if ent.get("code_read_cid") is not None and str(ent.get("code_read_cid")).strip() != "":
        try:
            out["cid_width"] = max(0, min(8, int(ent["code_read_cid"])))
        except (TypeError, ValueError):
            pass
    # pad 与目录 pad 对齐（目录显式 pad 优先）
    try:
        ent_pad = int(ent.get("pad") or 0)
        if ent_pad > 0:
            out["pad"] = max(1, min(8, ent_pad))
    except (TypeError, ValueError):
        pass
    return out


def ensure_code_read_on_entry(prefix: str, entry: dict[str, Any]) -> dict[str, Any]:
    """保证 entry 带 code_read；返回可能更新后的副本。"""
    ent = dict(entry or {})
    rid = str(ent.get("code_read") or "").strip()
    if rid not in VALID_CODE_READ_IDS:
        ent["code_read"] = infer_code_read(prefix or ent.get("prefix") or "", ent)
    return ent
