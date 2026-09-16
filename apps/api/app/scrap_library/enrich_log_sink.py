# -*- coding: utf-8 -*-
"""刮削运行日志的**批量落库缓冲**。

## 为什么需要

第九轮实测（`_gap_reports/_diag_round9_costs.py`）：原实现是
**一行日志 = 一次事务**（`connect` + `INSERT` + 带 `OFFSET` 的裁剪 `DELETE` + `commit`），
单次 p50 **32 ms**、max **96 ms**；而单番号要写 **13 行**（每源一行）
→ **552 ms / 番号**。对照纯 `SELECT 1` 只要 **7.4 ms**，说明瓶颈是**往返次数**，
不是元库慢。12.3 万番号外推 ≈ **19 小时**纯等待。

实测同样 20 行：**504 ms（各自事务）→ 74 ms（一个事务 + 一次裁剪）**。

## 怎么做

进程内 FIFO 缓冲 + 后台线程按 `flush_sec` 节拍把整批合并成**一次事务**
（多行 `INSERT` + 每个 region 一次裁剪）。

## 取舍（都是有意为之）

- **允许丢最后 ≤flush_sec 的日志**：日志是辅助产物（用途是「重启后仍可查」），
  实时展示走内存里的 `_enrich_job["log"]`，**不经过这里**。
- **`push()` 永不阻塞调用线程**：缓冲有硬上限 `max_rows`，超了丢**最旧**的
  —— 日志本身只保留 `keep` 行，旧行本来就要被裁掉，丢它零损失。
  绝不在 `push()` 里写库（否则又变回「每行一次事务」）。
- **单写者**：只有后台线程 + 显式 `flush()` 会写，且「取缓冲 + 写」在同
  一把 `_io_lock` 内完成 → 天然保序，不需要额外同步。
- **`discard()` 给「清空日志」用**：必须先丢掉未落库的行，否则清完又被灌回来。
- 进程退出（`atexit`）会 `close()` 一次，尽量少丢。
"""

from __future__ import annotations

import atexit
import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)

WriteBatch = Callable[[list[tuple[str, str]]], None]


class LogBatcher:
    """把「一行一事务」的日志落库改造成「一批一事务」。

    攒批策略是**双阈值**：攒够 `min_rows` 立即写；否则最多等 `max_delay` 秒。
    为什么不是「固定每 X 秒写一次」：日志行是**稀疏**产生的（每源完成一行，
    间隔几百 ms 到几秒），固定短节拍会退化成「一行一批」。实测生产是
    约 3.3 s/番号 × 13 行 ≈ 4 行/s，所以 2 s 窗口能攒到 6-8 行，
    再叠加「`push()` 从『同步等 32 ms』变成『不阻塞』」，收益最大。
    """

    def __init__(
        self,
        write_batch: WriteBatch,
        *,
        flush_sec: float = 0.25,
        max_delay: float = 3.0,
        min_rows: int = 24,
        max_rows: int = 4000,
        idle_wait: float = 1.0,
        label: str = "log",
        autostart: bool = True,
    ) -> None:
        self._write_batch = write_batch
        self._flush_sec = max(0.02, float(flush_sec))
        self._max_ticks = max(1, int(round(max(0.1, float(max_delay)) / self._flush_sec)))
        self._min_rows = max(1, int(min_rows))
        self._max_rows = max(16, int(max_rows))
        # 空闲（缓冲区为空）时拉长等待，避免没任务时每秒 4 次空唤醒。
        self._idle_wait = max(self._flush_sec, float(idle_wait))
        self._label = label

        self._cv = threading.Condition()
        self._io_lock = threading.Lock()
        self._buf: list[tuple[str, str]] = []
        self._closed = False
        self._dropped = 0
        self._written = 0
        self._thread: threading.Thread | None = None

        if autostart:
            self._thread = threading.Thread(
                target=self._loop, name=f"{label}-batcher", daemon=True
            )
            self._thread.start()
            atexit.register(self.close)

    # ------------------------------------------------------------------ 写入侧
    def push(self, region: str, line: str) -> bool:
        """入缓冲。返回 False 表示已被丢弃/关闭。**不做任何 IO。**"""
        text = str(line or "").strip()
        if not text:
            return False
        row = (str(region or ""), text)
        with self._cv:
            if self._closed:
                return False
            self._buf.append(row)
            over = len(self._buf) - self._max_rows
            if over > 0:
                # 丢最旧（日志有 keep 上限，旧行本来也要被裁掉）
                del self._buf[:over]
                self._dropped += over
            return True

    def flush(self) -> None:
        """同步把缓冲写完（供收尾/探针用）。可在任意线程调用。"""
        self._drain_and_write()

    def discard(self, region: str | None = None) -> None:
        """丢弃未落库的行；`region=None` 清全部。"""
        target = None if region is None else str(region)
        with self._io_lock:
            with self._cv:
                if target is None:
                    self._buf = []
                else:
                    self._buf = [x for x in self._buf if x[0] != target]

    def close(self) -> None:
        """停线程 + 把剩余行写完（幂等）。"""
        with self._cv:
            if self._closed:
                return
            self._closed = True
            self._cv.notify_all()
        th = self._thread
        if th is not None and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=2.0)
        self._drain_and_write()

    # ------------------------------------------------------------------ 统计
    def stats(self) -> dict[str, int]:
        with self._cv:
            pending = len(self._buf)
        return {"pending": pending, "written": self._written, "dropped": self._dropped}

    # ------------------------------------------------------------------ 内部
    def _loop(self) -> None:
        ticks = 0
        while True:
            with self._cv:
                if self._closed:
                    return
                # ⚠️ `push()` 故意**不 notify** —— 否则每来一行就把这里唤醒，
                # 立刻 drain 成「一行一批」，白改。这里只按 tick 醒来。
                # 空闲（无待写行）时等久一点，别在没任务时每秒空转 4 次。
                self._cv.wait(self._flush_sec if self._buf else self._idle_wait)
                if self._closed:
                    return
                if not self._buf:
                    ticks = 0
                    continue
                ticks += 1
                if len(self._buf) < self._min_rows and ticks < self._max_ticks:
                    continue
            self._drain_and_write()
            ticks = 0

    def _drain_and_write(self) -> None:
        # 「取缓冲 + 写库」必须原子，否则显式 flush 与后台线程可能乱序。
        with self._io_lock:
            with self._cv:
                rows, self._buf = self._buf, []
            if not rows:
                return
            try:
                self._write_batch(rows)
            except Exception as e:  # noqa: BLE001
                self._dropped += len(rows)
                log.warning("%s batch write failed n=%d: %s", self._label, len(rows), e)
            else:
                self._written += len(rows)
