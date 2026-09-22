# -*- coding: utf-8 -*-
"""enrich_sidecar —— 自 scrap_library/enrich.py 拆出（机械搬移，行为不变）。"""

from __future__ import annotations
import json
import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from fastapi import HTTPException
import app.scrap_library.embed as embed_svc
from app.ai.config import resolve_embed_config
from app.ai.embed import encode_texts_sync
from app.core.db import get_meta_pool, media_dir
from app.scrap_library import enrich_log_sink
from app.scrap_library.nfo import (
    build_mdcx_nfo_root,
    fields_from_movie_root,
    format_nfo_xml,
    parse_nfo,
    write_nfo,
)
from app.scrap_library import enrich_monitor as enrich_mon

from app.scrap_library.enrich import (log)


def _file_stamp(p: "Path | None") -> tuple[str, int, int]:
    """(路径, mtime_ns, size)；文件不在则全零。"""
    if p is None:
        return ("", 0, 0)
    try:
        st = p.stat()
    except OSError:
        return (str(p), 0, 0)
    return (
        str(p),
        int(getattr(st, "st_mtime_ns", 0) or 0),
        int(getattr(st, "st_size", 0) or 0),
    )


_ENRICH_SIDECAR_LEGACY = "enrich.log"


_ENRICH_SIDECAR_VER = 1


def _enrich_sidecar_code(folder: Path, code: str = "") -> str:
    raw = str(code or "").strip().upper()
    if not raw:
        raw = str(folder.name or "").strip().upper()
    # 文件名安全：去掉路径分隔等
    for ch in ("/", "\\", ":", "*", "?", '"', "<", ">", "|"):
        raw = raw.replace(ch, "_")
    return raw


def _enrich_sidecar_path(folder: Path, code: str = "") -> Path:
    name = _enrich_sidecar_code(folder, code)
    if name:
        return folder / f"{name}.log"
    return folder / _ENRICH_SIDECAR_LEGACY


def write_enrich_sidecar(folder: Path, payload: dict[str, Any]) -> bool:
    """刮削结果写入番号目录 {CODE}.log（JSON）。"""
    if not folder or not isinstance(payload, dict):
        return False
    try:
        if not folder.is_dir():
            return False
    except OSError:
        return False
    timings = list(payload.get("sourceTimings") or [])
    fields = list(payload.get("fields") or [])
    if not timings and not fields:
        return False
    code_u = _enrich_sidecar_code(folder, str(payload.get("code") or ""))
    body = {
        "v": _ENRICH_SIDECAR_VER,
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "code": code_u,
        "source": str(payload.get("source") or "").strip(),
        "error": str(payload.get("error") or "")[:500],
        "partialOk": bool(payload.get("partialOk")),
        "status": str(payload.get("status") or "").strip(),
        "gapsAfter": list(payload.get("gapsAfter") or payload.get("gaps") or []),
        "fields": fields,
        "sourceTimings": timings,
        "detailTitle": str(payload.get("detailTitle") or "")[:300],
        "posterDownloaded": payload.get("posterDownloaded"),
        "vectorSynced": payload.get("vectorSynced"),
        "vectorSkipped": payload.get("vectorSkipped"),
        "coverMs": payload.get("coverMs"),
        "actressMs": payload.get("actressMs"),
        "vectorMs": payload.get("vectorMs"),
        "fetchMs": payload.get("fetchMs"),
        "totalMs": payload.get("totalMs"),
    }
    path = _enrich_sidecar_path(folder, code_u)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        raw = json.dumps(body, ensure_ascii=False, indent=2)
        tmp.write_text(raw, encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception as e:  # noqa: BLE001
        log.debug("write enrich sidecar failed %s: %s", path, e)
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return False


def read_enrich_sidecar(
    folder: Path, *, code: str = ""
) -> dict[str, Any] | None:
    """读取番号目录 {CODE}.log；兼容 enrich.log。损坏/缺失返回 None。"""
    if not folder:
        return None
    code_u = _enrich_sidecar_code(folder, code)
    candidates: list[Path] = []
    if code_u:
        candidates.append(folder / f"{code_u}.log")
        # 大小写变体：目录名可能是 SONE-999
        folder_name = str(folder.name or "").strip()
        if folder_name and folder_name.upper() != code_u:
            candidates.append(folder / f"{folder_name}.log")
    candidates.append(folder / _ENRICH_SIDECAR_LEGACY)
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict):
            return data
    return None
