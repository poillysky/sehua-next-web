"""按容器内存收紧并发。

NAS 上 `os.cpu_count()` 是宿主机核数，cgroup 限 1G 时按核数开线程/进程会把 API 打爆。
Linux 默认线程栈约 8MB，多进程还会再复制一份解释器和映射表。
无 cgroup（本机 Windows / 未限内存）保持原并发。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

# Docker / cgroup v1 的「不限制」是一个接近 2^63 的数
_UNLIMITED = 1 << 60
_TIGHT = 1536 * 1024 * 1024  # ≤ 1.5 GiB
_SMALL = 3 * 1024 * 1024 * 1024  # ≤ 3 GiB


@lru_cache(maxsize=1)
def memory_limit_bytes() -> int | None:
    """cgroup 内存上限；读不到或未限制则 None。"""
    for raw in (
        "/sys/fs/cgroup/memory.max",
        "/sys/fs/cgroup/memory.high",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",
    ):
        try:
            text = Path(raw).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not text or text == "max":
            continue
        try:
            n = int(text)
        except ValueError:
            continue
        if n <= 0 or n >= _UNLIMITED:
            continue
        return n
    return None


def memory_class() -> str:
    """tight | small | host。Windows 与未限内存视为 host。"""
    if os.name == "nt":
        return "host"
    limit = memory_limit_bytes()
    if limit is None:
        return "host"
    if limit <= _TIGHT:
        return "tight"
    if limit <= _SMALL:
        return "small"
    return "host"


def io_threads(*, floor: int = 2, host_max: int = 8) -> int:
    """磁盘 / 小文件线程数。紧内存固定 2，避免线程栈把 1G 容器吃光。"""
    kind = memory_class()
    if kind == "tight":
        return 2
    if kind == "small":
        return max(2, min(4, host_max))
    cpus = os.cpu_count() or 4
    return max(int(floor), min(int(host_max), cpus))


def cap_parallel(n: int, *, tight: int, small: int, hard: int) -> int:
    """把请求的并发夹到容器能承受的上限。n=0 保持 0（表示「不开这路」）。"""
    if int(n or 0) <= 0:
        return 0
    capped = max(1, min(int(hard), int(n)))
    kind = memory_class()
    if kind == "tight":
        return min(capped, max(1, int(tight)))
    if kind == "small":
        return min(capped, max(1, int(small)))
    return capped
