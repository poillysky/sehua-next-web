"""OutboundScheduler：全局 + 按 host 闸门行为，以及取消令牌（早停回收在飞源）。"""

from __future__ import annotations

import threading
import time
import unittest

from app.core.outbound_scheduler import (
    OutboundCancelled,
    OutboundScheduler,
    reset_scheduler_for_tests,
)


class OutboundSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_scheduler_for_tests()
        self.sched = OutboundScheduler(global_limit=8)

    def tearDown(self) -> None:
        reset_scheduler_for_tests()

    def test_same_host_serializes_under_limit(self) -> None:
        """同 host 超过 per_host 限额时要排队（限额从代码读，避免测试与常量脱节）。"""
        url = "https://cdn.example.com/a.jpg"
        per_host, _ = self.sched._limits_for(  # noqa: SLF001
            self.sched.host_key(url), "cover"
        )
        self.assertGreaterEqual(per_host, 2)

        release = threading.Event()
        entered: list[int] = []
        lock = threading.Lock()
        ready = threading.Semaphore(0)

        def hold() -> None:
            with self.sched.slot(url, kind="cover", timeout=5):
                with lock:
                    entered.append(1)
                ready.release()
                release.wait(5)

        threads = [
            threading.Thread(target=hold, daemon=True) for _ in range(per_host)
        ]
        for t in threads:
            t.start()
        for _ in range(per_host):
            self.assertTrue(ready.acquire(timeout=3), "占位线程未全部就绪")
        with lock:
            self.assertEqual(len(entered), per_host)

        fifth_in = threading.Event()

        def fifth() -> None:
            with self.sched.slot(
                "https://cdn.example.com/b.jpg", kind="cover", timeout=5
            ):
                fifth_in.set()

        t5 = threading.Thread(target=fifth, daemon=True)
        t5.start()
        time.sleep(0.2)
        self.assertFalse(
            fifth_in.is_set(), f"第 {per_host + 1} 路同 host 应排队"
        )
        release.set()
        for t in threads:
            t.join(timeout=2)
        t5.join(timeout=2)
        self.assertTrue(fifth_in.is_set())

    def test_different_hosts_parallel(self) -> None:
        barrier = threading.Barrier(3)
        ok = []

        def one(host: str) -> None:
            with self.sched.slot(f"https://{host}/x", kind="cover", timeout=5):
                barrier.wait(timeout=5)
                ok.append(host)

        ts = [
            threading.Thread(target=one, args=("a.example.com",)),
            threading.Thread(target=one, args=("b.example.com",)),
            threading.Thread(target=one, args=("c.example.com",)),
        ]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=3)
        self.assertEqual(
            sorted(ok), ["a.example.com", "b.example.com", "c.example.com"]
        )

    def test_throttle_pauses_host(self) -> None:
        self.sched.note_status("https://slow.example/x", 429)
        t0 = time.monotonic()
        with self.sched.slot("https://slow.example/y", kind="cover", timeout=5):
            pass
        self.assertGreaterEqual(time.monotonic() - t0, 0.5)


class OutboundCancelTests(unittest.TestCase):
    """早停/暂停后回收「僵尸在飞请求」：等槽期间可被取消，且永不发请求。"""

    def setUp(self) -> None:
        reset_scheduler_for_tests()
        self.sched = OutboundScheduler(global_limit=8)

    def tearDown(self) -> None:
        reset_scheduler_for_tests()

    def _saturate_global(self, kind: str) -> tuple[threading.Event, list]:
        """占满某 kind 的全局槽；返回 (释放事件, 线程列表)。"""
        global_n = int(self.sched.stats()["kindGlobal"][kind])
        release = threading.Event()
        ready = threading.Semaphore(0)
        threads: list[threading.Thread] = []

        def hold(i: int) -> None:
            with self.sched.slot(f"https://hold{i}.example/a", kind=kind, timeout=10):
                ready.release()
                release.wait(8)

        for i in range(global_n):
            t = threading.Thread(target=hold, args=(i,), daemon=True)
            threads.append(t)
            t.start()
        for _ in range(global_n):
            self.assertTrue(ready.acquire(timeout=5), "未占满全局槽")
        return release, threads

    def test_cancel_exits_waiter_without_acquiring(self) -> None:
        """令牌置位后：等待者 ≤ 轮询步长×2 内退出，且从未取得槽。"""
        release, holders = self._saturate_global("ui")
        ev = threading.Event()
        outcome: dict[str, object] = {}

        def waiter() -> None:
            try:
                with self.sched.slot(
                    "https://wait.example/a", kind="ui", timeout=6, cancel=ev
                ):
                    outcome["acquired"] = True
                outcome["kind"] = "acquired"
            except OutboundCancelled:
                outcome["kind"] = "cancelled"
            except TimeoutError:
                outcome["kind"] = "timeout"
            outcome["at"] = time.perf_counter()

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        time.sleep(0.4)  # 让它确实堵在等槽上
        t_cancel = time.perf_counter()
        ev.set()
        t.join(timeout=3)

        self.assertEqual(outcome.get("kind"), "cancelled")
        self.assertNotIn("acquired", outcome)
        self.assertLessEqual(
            float(outcome["at"]) - t_cancel,
            0.55,
            "置位后应立刻退出，不该等到单源超时",
        )
        release.set()
        for th in holders:
            th.join(timeout=1)

    def test_cancel_before_acquire_is_immediate(self) -> None:
        """令牌事先已置位：直接拒绝，连全局槽都不申请。"""
        ev = threading.Event()
        ev.set()
        t0 = time.monotonic()
        with self.assertRaises(OutboundCancelled):
            with self.sched.slot(
                "https://now.example/a", kind="ui", timeout=5, cancel=ev
            ):
                pass
        self.assertLess(time.monotonic() - t0, 0.5)

    def test_no_token_keeps_legacy_blocking(self) -> None:
        """无令牌：保持旧语义（等不到槽就 TimeoutError），行为不被改写。"""
        release, holders = self._saturate_global("ui")
        t0 = time.monotonic()
        with self.assertRaises(TimeoutError):
            with self.sched.slot(
                "https://legacy.example/a", kind="ui", timeout=1.0
            ):
                pass
        elapsed = time.monotonic() - t0
        self.assertGreaterEqual(elapsed, 0.9)
        release.set()
        for th in holders:
            th.join(timeout=1)

    def test_cancelled_counter_visible(self) -> None:
        release, holders = self._saturate_global("ui")
        ev = threading.Event()
        ev.set()
        with self.assertRaises(OutboundCancelled):
            with self.sched.slot(
                "https://count.example/a", kind="ui", timeout=5, cancel=ev
            ):
                pass
        self.assertGreaterEqual(int(self.sched.stats()["cancelledWaiters"]), 1)
        release.set()
        for th in holders:
            th.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
