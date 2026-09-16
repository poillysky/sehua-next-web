# -*- coding: utf-8 -*-
"""原子写盘工具（同目录临时文件 + `os.replace`）。

为什么需要：`path.write_bytes()` / `write_text()` 是「截断 + 写」，进程被杀、
磁盘满、或两个进程同时写同一文件时，读者会看到**半截文件**。对于会被解析的
文件（`site-mirrors.json`、NFO）后果不是"少一段"而是"整份读不出来"：

- `site-mirrors.json` 半截 → `Extra data: line N column 1`（合法 JSON 挂了尾巴）；
- NFO 半截 → `ET.fromstring()` 抛错，`merge_nfo_with_detail` 回落到空的
  `<movie/>` 根，只写本次 detail 有的字段 → **其余元数据静默丢失**。

原子替换后读者只会看到「旧内容」或「新内容」，不存在中间态。
"""

from __future__ import annotations

import os
import time
from pathlib import Path


def _atomic_replace(tmp: Path, path: Path) -> None:
    """`os.replace`，Windows 下目标被短暂占用时小退避重试。"""
    for attempt in range(4):
        try:
            os.replace(tmp, path)
            return
        except OSError:
            if attempt == 3:
                raise
            time.sleep(0.05 * (attempt + 1))


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """原子写二进制（同目录 tmp + `os.replace`）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        _atomic_replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def atomic_write_text(path: Path, text: str) -> None:
    """原子写文本（UTF-8）。"""
    atomic_write_bytes(Path(path), str(text).encode("utf-8"))
