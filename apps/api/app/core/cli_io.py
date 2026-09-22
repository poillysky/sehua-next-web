# -*- coding: utf-8 -*-
"""独立脚本入口的 stdio 兜底（`scrap_library/embed_job` 与 `search/sehua_embed_job` 共用）。

这两个 job 脚本既被 CLI 直接跑，也被 API 以子进程方式拉起 —— Windows 控制台
默认 cp936，直接 `print` 中日文会 `UnicodeEncodeError` 打断整条 ingest。所以约
定：进程入口先 `configure_stdio()` 把 stdout/stderr 切到 UTF-8，之后所有输出
一律走 `safe_print()`（编码仍失败时退化为写 bytes）。
"""

from __future__ import annotations

import sys


def configure_stdio() -> None:
    """把 stdout/stderr 切到 UTF-8（reconfigure 不可用时静默跳过）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def safe_print(msg: str) -> None:
    """打印；控制台编码吃不下时退化为 UTF-8 bytes 直写。"""
    try:
        print(msg)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))
