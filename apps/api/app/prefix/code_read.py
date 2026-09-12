# -*- coding: utf-8 -*-
"""按前缀定制的番号读取标准（双库扫描抽取/截断/验收）。"""

from __future__ import annotations

import re
from typing import Any

# 预设：扫描时只认该前缀 resolved profile，不再混用一套逻辑
CODE_READ_PRESETS: dict[str, dict[str, Any]] = {
    # 大多数有码三位数（CLUB 等）：硬顶 999，DMM 五位补零还原 int
    "std3_dmm": {
        "pad": 3,
        "cid_width": 5,
        "leading_zero": "int",
        "max_serial": 999,
        "prefer_digit_len": 3,
        "outlier": "robust",
        "measure_glue": True,
    },
    # 已过千的主流有码（SSIS 等）
    "std3_open": {
        "pad": 3,
        "cid_width": 5,
        "leading_zero": "int",
        "max_serial": None,
        "prefer_digit_len": None,
        "outlier": "robust",
        "measure_glue": True,
    },
    "std4": {
        "pad": 4,
        "cid_width": 5,
        "leading_zero": "int",
        "max_serial": 9999,
        "prefer_digit_len": 4,
        "outlier": "robust",
        "measure_glue": True,
    },
    # 素人四位主号：不要按三位数主簇砍四位
    "amateur4": {
        "pad": 4,
        "cid_width": 5,
        "leading_zero": "int",
        "max_serial": 9999,
        "prefer_digit_len": 4,
        "outlier": "robust",
        "measure_glue": False,
    },
    "fc2": {
        "pad": 0,
        "cid_width": 0,
        "leading_zero": "int",
        "max_serial": None,
        "prefer_digit_len": None,
        "outlier": "none",
        "measure_glue": False,
    },
    "fc2ppv": {
        "pad": 0,
        "cid_width": 0,
        "leading_zero": "int",
        "max_serial": None,
        "prefer_digit_len": None,
        "outlier": "none",
        "measure_glue": False,
    },
    "date6": {
        "pad": 0,
        "cid_width": 0,
        "leading_zero": "int",
        "max_serial": None,
        "prefer_digit_len": None,
        "outlier": "none",
        "measure_glue": False,
    },
    "alnum": {
        "pad": 0,
        "cid_width": 0,
        "leading_zero": "int",
        "max_serial": None,
        "prefer_digit_len": None,
        "outlier": "none",
        "measure_glue": False,
    },
    "western_date": {
        "pad": 0,
        "cid_width": 0,
        "leading_zero": "int",
        "max_serial": None,
        "prefer_digit_len": None,
        "outlier": "none",
        "measure_glue": False,
    },
    "western_ep": {
        "pad": 0,
        "cid_width": 0,
        "leading_zero": "int",
        "max_serial": None,
        "prefer_digit_len": None,
        "outlier": "none",
        "measure_glue": False,
    },
}

VALID_CODE_READ_IDS = frozenset(CODE_READ_PRESETS.keys())

# 已过千的 pad=3 主流有码
_STD3_OPEN = frozenset(
    {
        "SSIS",
        "SONE",
        "MIDV",
        "MIDE",
        "PRED",
        "STARS",
        "WAAA",
        "CAWD",
        "MVSD",
        "MIAA",
        "MIMK",
        "PPPE",
        "HMN",
        "ABF",
        "START",
        "DASS",
        "FSDSS",
        "DLDSS",
        "MSFH",
        "JUQ",
        "JUY",
        "JUL",
        "ADN",
        "ATID",
        "RBD",
        "SHKD",
        "SAME",
        "NSFS",
        "NGOD",
        "MEYD",
        "NACR",
        "VEC",
        "VENX",
        "SSNI",
        "SNIS",
        "OFJE",
        "OVG",
        "SDDE",
        "SDNM",
        "SDJS",
        "SOE",
        "ONSG",
        "IPX",
        "IPZ",
        "IPZZ",
    }
)

# 素人四位主号（含数字头别名）
_AMATEUR4 = frozenset(
    {
        "SIRO",
        "LUXU",
        "MIUM",
        "MAAN",
        "MYWIFE",
        "GANA",
        "ARA",
        "DCV",
        "JKZ",
        "SCUTE",
        "NTK",
        "NAMH",
        "OREX",
        "ORE",
        "200GANA",
        "259LUXU",
        "300MIUM",
        "300MAAN",
        "390JAC",
        "428SUKE",
    }
)

_DIGIT_HEAD_RE = re.compile(r"^(\d{2,3})([A-Z]{2,14})$")
_SHAPE_TO_READ = {
    "fc2": "fc2",
    "fc2ppv": "fc2ppv",
    "date6": "date6",
    "alnum_id": "alnum",
    "western_date": "western_date",
    "western_ep": "western_ep",
    "western_ym": "western_date",
    "western_year": "western_date",
}


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
