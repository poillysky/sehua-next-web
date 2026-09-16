# -*- coding: utf-8 -*-
"""第九轮回归：运行日志**批量落库**缓冲。

背景（实测）：原实现「一行日志 = 一次事务」，单次 p50 32ms / max 96ms，
单番号 13 行 ≈ 552ms；纯 `SELECT 1` 只要 7.4ms → 瓶颈是往返次数。
同样 20 行：504ms（各自事务）→ 74ms（一个事务 + 一次裁剪）。

本文件锁住三件事：
1. `LogBatcher` 的正确性（攒批、顺序、上限丢最旧、discard、close/flush）；
2. 批量写库 SQL 的**事务语义**（一批 = 1 次 commit、每个 region 只裁一次）；
3. `_clear_enrich_logs` 必须先丢弃未落库缓冲（否则清完又被灌回）。

全部用 fake 连接，**不碰真库**。
"""

from __future__ import annotations

import contextlib
import threading
import time
import unittest
from unittest import mock

from app.scrap_library import enrich_log_sink as sink


class _FakeConn:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.params: list[object] = []
        self.commits = 0

    def execute(self, sql: str, params: object = None) -> "_FakeConn":
        self.sql.append(" ".join(str(sql).split()))
        self.params.append(params)
        return self

    def fetchall(self) -> list:
        return []

    def commit(self) -> None:
        self.commits += 1


def _fake_connect(conn: _FakeConn):
    @contextlib.contextmanager
    def _cm():
        yield conn

    return _cm


class BatcherBehaviourTest(unittest.TestCase):
    """攒批语义。"""

    def _mk(self, **kw) -> tuple[sink.LogBatcher, list[list[tuple[str, str]]]]:
        batches: list[list[tuple[str, str]]] = []
        defaults = dict(flush_sec=0.02, max_delay=0.08, min_rows=100, label="test")
        defaults.update(kw)
        b = sink.LogBatcher(lambda rows: batches.append(list(rows)), **defaults)
        self.addCleanup(b.close)
        return b, batches

    def test_push_never_writes_inline(self):
        """`push()` 绝不能自己写库 —— 否则又变回「一行一次事务」。"""
        b, batches = self._mk()
        for i in range(5):
            b.push("r1", f"line{i}")
        # 立刻检查：还没到 max_delay，不应有任何批次
        self.assertEqual(batches, [], "push() 后立刻出现了写库 —— 攒批被破坏")

    def test_batches_accumulate_then_flush_once(self):
        """达到 max_delay 后应**一次性**写出全部积压行，且保持 FIFO 顺序。"""
        b, batches = self._mk(max_delay=0.08, min_rows=100)
        for i in range(6):
            b.push("r1", f"line{i}")
        deadline = time.monotonic() + 2.0
        while not batches and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(batches, "max_delay 到期后仍没有写出")
        flat = [row for batch in batches for row in batch]
        self.assertEqual([r[1] for r in flat], [f"line{i}" for i in range(6)])
        self.assertEqual(len(batches), 1, f"应合并成 1 批，实际 {len(batches)} 批")

    def test_min_rows_triggers_early_flush(self):
        """攒够 min_rows 立即写，不等 max_delay。"""
        b, batches = self._mk(flush_sec=0.02, max_delay=30.0, min_rows=4)
        for i in range(4):
            b.push("r1", f"line{i}")
        deadline = time.monotonic() + 2.0
        while not batches and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(batches, "攒够 min_rows 后未提前写出")

    def test_flush_is_synchronous(self):
        b, batches = self._mk(max_delay=30.0)
        b.push("r1", "a")
        b.push("r1", "b")
        b.flush()
        self.assertEqual(len(batches), 1)
        self.assertEqual([r[1] for r in batches[0]], ["a", "b"])
        self.assertEqual(b.stats()["pending"], 0)

    def test_close_writes_tail(self):
        b, batches = self._mk(max_delay=30.0)
        b.push("r1", "tail")
        b.close()
        self.assertEqual([r[1] for r in batches[0]], ["tail"])

    def test_blank_lines_dropped(self):
        b, batches = self._mk(max_delay=30.0)
        self.assertFalse(b.push("r1", "   "))
        self.assertFalse(b.push("r1", ""))
        b.flush()
        self.assertEqual(batches, [])

    def test_max_rows_drops_oldest_keeps_order(self):
        """超上限丢**最旧**（旧日志本来就会被裁掉），保留最新的有序尾部。"""
        b, batches = self._mk(max_rows=16, min_rows=100, max_delay=30.0)
        for i in range(40):
            b.push("r1", f"l{i}")
        b.flush()
        flat = [r[1] for batch in batches for r in batch]
        self.assertEqual(len(flat), 16, "上限未生效")
        self.assertEqual(flat, [f"l{i}" for i in range(24, 40)], "丢的不是最旧/顺序被破坏")
        self.assertEqual(b.stats()["dropped"], 24)

    def test_discard_by_region_only_affects_that_region(self):
        b, batches = self._mk(max_delay=30.0)
        b.push("keep", "k1")
        b.push("drop", "d1")
        b.push("keep", "k2")
        b.discard("drop")
        b.flush()
        flat = [r for batch in batches for r in batch]
        self.assertEqual(flat, [("keep", "k1"), ("keep", "k2")])

    def test_discard_all(self):
        b, batches = self._mk(max_delay=30.0)
        b.push("a", "1")
        b.push("b", "2")
        b.discard(None)
        b.flush()
        self.assertEqual(batches, [])

    def test_concurrent_push_keeps_order_and_no_loss(self):
        """并发 push 不得丢行、不得乱序（单写者 + FIFO 缓冲）。"""
        b, batches = self._mk(max_delay=30.0, max_rows=100_000)
        n_threads, per = 8, 200

        def worker(tid: int) -> None:
            for i in range(per):
                b.push("r", f"{tid:02d}-{i:04d}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        b.flush()
        flat = [r[1] for batch in batches for r in batch]
        self.assertEqual(len(flat), n_threads * per, "有行丢失")
        for t in range(n_threads):
            seq = [x for x in flat if x.startswith(f"{t:02d}-")]
            self.assertEqual(seq, [f"{t:02d}-{i:04d}" for i in range(per)], f"线程 {t} 乱序")

    def test_write_failure_does_not_raise(self):
        """写库失败不能把异常抛给 push 调用方（源抓取线程）。"""
        b = sink.LogBatcher(
            lambda rows: (_ for _ in ()).throw(RuntimeError("boom")),
            flush_sec=0.02,
            max_delay=0.05,
            min_rows=1,
            label="fail",
        )
        self.addCleanup(b.close)
        b.push("r", "x")
        time.sleep(0.3)  # 不应炸


class BatchWriteSqlTest(unittest.TestCase):
    """`_write_enrich_log_batch` 的事务语义（fake 连接，不碰真库）。"""

    def _run(self, rows: list[tuple[str, str]], regions_expected: int):
        from app.scrap_library import enrich

        conn = _FakeConn()
        with mock.patch("app.core.db.connect", _fake_connect(conn)), mock.patch(
            "app.core.db.init_db", lambda: None
        ):
            enrich._write_enrich_log_batch(rows)
        inserts = [s for s in conn.sql if s.upper().startswith("INSERT")]
        deletes = [s for s in conn.sql if s.upper().startswith("DELETE")]
        self.assertEqual(len(inserts), len(rows), "INSERT 数应等于行数")
        self.assertEqual(conn.commits, 1, f"必须只 commit 一次，实际 {conn.commits}")
        self.assertEqual(
            len(deletes), regions_expected, "每个 region 只应裁剪一次（不是每行一次）"
        )
        return conn, inserts, deletes

    def test_one_txn_and_one_prune_per_region(self):
        rows = [("japan_censored", f"l{i}") for i in range(13)]
        _, inserts, deletes = self._run(rows, 1)
        # 裁剪 SQL 的 keep 参数沿用原语义
        self.assertIn("OFFSET", deletes[0])

    def test_multi_region_prunes_each_once(self):
        rows = [("r1", "a"), ("r2", "b"), ("r1", "c"), ("r2", "d"), ("r1", "e")]
        self._run(rows, 2)


class ClearDiscardsBufferTest(unittest.TestCase):
    """清空日志必须先丢弃未落库缓冲，否则清完又被写回。"""

    def test_clear_enrich_logs_discards_pending(self):
        from app.scrap_library import enrich

        pushed: list[tuple[str, str]] = []
        with mock.patch.object(
            enrich._enrich_log_sink, "push", side_effect=lambda r, l: pushed.append((r, l))
        ):
            enrich._persist_enrich_log("japan_censored", "pending-line")
        self.assertEqual(pushed, [("japan_censored", "pending-line")])

        conn = _FakeConn()
        with mock.patch("app.core.db.connect", _fake_connect(conn)), mock.patch(
            "app.core.db.init_db", lambda: None
        ):
            enrich._enrich_log_sink.push("japan_censored", "pending-line")
            enrich._clear_enrich_logs(region="japan_censored", wipe_all_tail=True)
            self.assertEqual(
                enrich._enrich_log_sink.stats()["pending"],
                0,
                "清空后缓冲里仍有待写行 → 会被后台线程写回库里",
            )
            # 清空后新产生的日志仍应能入缓冲（不能把缓冲一起永久关掉）
            self.assertTrue(enrich._enrich_log_sink.push("japan_censored", "after-clear"))
            enrich._enrich_log_sink.discard(None)


class WaterfallProbeContractTest(unittest.TestCase):
    """`_persist_enrich_log` 现在只入缓冲：必须存在同步落库的出口。"""

    def test_flush_api_exists(self):
        from app.scrap_library import enrich

        self.assertTrue(callable(getattr(enrich, "flush_enrich_logs", None)))
        self.assertTrue(callable(getattr(enrich, "enrich_log_sink_stats", None)))

    def test_persist_does_not_touch_db(self):
        from app.scrap_library import enrich

        with mock.patch("app.core.db.connect") as connect:
            enrich._persist_enrich_log("japan_censored", "no-db-here")
            connect.assert_not_called()
        # 别 flush（会真写库）——直接丢掉这行探针数据
        enrich._enrich_log_sink.discard("japan_censored")


if __name__ == "__main__":
    unittest.main()
