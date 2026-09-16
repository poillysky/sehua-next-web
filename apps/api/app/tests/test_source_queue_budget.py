"""第十轮：把「排队等出站槽」从「单源超时」里摘出去。

背景（第八轮取证）：`enrich._one()` 用 `th.join(timeout=单源超时)` 等源结果，
而线程第一件事是**抢出站槽** → 排队时间被算进单源超时 → 源 3.4s 能返回，
生产 p50 却恰好等于策略上限（mgstage 433 次假 `down` + 误挂补抓标记）。

本文件锁住三件事，任何一件退化都会红：
1. `_src_give_up_reason`：放弃判据区分「真超时(down)」与「没轮到(busy)」；
2. `SlotWaitMeter` + `slot()`：等槽时间被记账，排队超时抛 `OutboundBusy` 而非裸 `TimeoutError`；
3. `_classify_source_failure`：把 `busy` 与 `down` 分开（busy 不是源故障）。
"""

from __future__ import annotations

import threading
import time
import unittest

from app.core.outbound_http import source_queue_budget
from app.core.outbound_scheduler import (
    OutboundBusy,
    OutboundScheduler,
    SlotWaitMeter,
    reset_scheduler_for_tests,
    set_thread_slot_meter,
)
from app.scrap_library.enrich import (
    _CancelPair,
    _classify_source_failure,
    _src_give_up_reason,
)

# 单源超时（策略默认）与由此推出的排队预算
WORK = 15.0


class SourceQueueBudgetTests(unittest.TestCase):
    def test_not_a_flat_addend(self) -> None:
        """第十一轮收紧「代价」：排队预算 = `clamp(工作预算, 12, 30)`。

        旧版是 `min(45, max(20, 工作预算))` —— 与工作预算**无关的固定加项**，
        于是最坏单源墙钟 = 工作预算 + 20~45s（工作预算 5s 时是 5×）。
        """
        self.assertEqual(source_queue_budget(15.0), 15.0)  # 旧 20
        self.assertEqual(source_queue_budget(28.0), 28.0)  # 生产默认：与旧值相同，无回归
        self.assertEqual(source_queue_budget(5.0), 12.0)  # 地板：小预算不再被 20s 拖着走
        self.assertEqual(source_queue_budget(1000.0), 30.0)  # 上限 45 → 30
        # 无线程内超时（封面路径 / 交互请求）→ 沿用历史的 90s 槽位预算
        self.assertEqual(source_queue_budget(None), 90.0)

    def test_queue_never_exceeds_work_above_floor(self) -> None:
        """不变式：工作预算 ≥ 下限时「排队 ≤ 工作」→ 最坏单源墙钟 ≤ 2× 工作预算。"""
        for w in (12.0, 15.0, 18.0, 28.0, 30.0, 45.0, 600.0):
            self.assertLessEqual(source_queue_budget(w), w)
        self.assertEqual(28.0 + source_queue_budget(28.0), 56.0)
        self.assertEqual(18.0 + source_queue_budget(18.0), 36.0)  # 旧 18+20=38

    def test_worst_clock_shrinks_for_small_budgets(self) -> None:
        """小工作预算最坏墙钟显著下降：旧 = w + 20，新 = w + 12。"""
        self.assertEqual(5.0 + source_queue_budget(5.0), 17.0)  # 旧 25.0


class GiveUpReasonTests(unittest.TestCase):
    """放弃判据真值表：waited=等槽秒数，elapsed=墙钟。"""

    def _r(self, elapsed: float, waited: float) -> str:
        return _src_give_up_reason(
            elapsed=elapsed, waited=waited, work_budget=WORK, queue_budget=30.0
        )

    def test_no_give_up_within_budget(self) -> None:
        self.assertEqual(self._r(5.0, 0.0), "")
        # 排队 25s、工作才 3s → 仍在预算内（旧实现这里已经被 join 杀掉）
        self.assertEqual(self._r(28.0, 25.0), "")

    def test_queue_wait_is_not_a_source_failure(self) -> None:
        """核心回归：墙钟远超单源超时，但耗的全是排队 → busy，不是 down。"""
        self.assertEqual(self._r(44.0, 44.0), "")
        self.assertEqual(self._r(WORK + 30.0 + 0.1, 44.0), "busy")
        # 排队把预算吃光、工作耗时仍未超 → 依旧是 busy（**旧实现记成 down**）
        self.assertEqual(self._r(50.0, 45.0), "busy")

    def test_real_work_overrun_is_down(self) -> None:
        self.assertEqual(self._r(WORK + 0.1, 0.0), "down")
        self.assertEqual(self._r(WORK + 20.0, 20.0), "down")

    def test_work_overrun_wins_when_both_exceeded(self) -> None:
        """两者都超 → down（确实干活干太久，不是没轮到）。"""
        self.assertEqual(self._r(80.0, 45.0), "down")


class SlotWaitMeterTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_scheduler_for_tests()
        self.sched = OutboundScheduler(global_limit=4)

    def tearDown(self) -> None:
        reset_scheduler_for_tests()

    def _saturate(self, kind: str) -> tuple[threading.Event, list]:
        n = int(self.sched.stats()["kindGlobal"][kind])
        release = threading.Event()
        ready = threading.Semaphore(0)
        threads: list[threading.Thread] = []

        def hold(i: int) -> None:
            with self.sched.slot(f"https://hold{i}.example/a", kind=kind, timeout=10):
                ready.release()
                release.wait(8)

        for i in range(n):
            t = threading.Thread(target=hold, args=(i,), daemon=True)
            threads.append(t)
            t.start()
        for _ in range(n):
            self.assertTrue(ready.acquire(timeout=5), "未占满全局槽")
        return release, threads

    def test_acquired_slot_records_zero_wait(self) -> None:
        meter = SlotWaitMeter()
        set_thread_slot_meter(meter)
        try:
            with self.sched.slot("https://free.example/a", kind="ui", timeout=5):
                pass
        finally:
            set_thread_slot_meter(None)
        self.assertEqual(meter.acquired, 1)
        self.assertEqual(meter.waiting_since, 0.0)
        self.assertLess(meter.total, 0.5)

    def test_queue_timeout_raises_outbound_busy_and_records_wait(self) -> None:
        """等槽超时：抛 OutboundBusy（TimeoutError 子类）+ 记满等槽时间 + 从未取得槽。"""
        release, threads = self._saturate("ui")
        meter = SlotWaitMeter()
        out: dict[str, object] = {}

        def waiter() -> None:
            set_thread_slot_meter(meter)
            try:
                with self.sched.slot("https://busy.example/a", kind="ui", timeout=0.8):
                    out["acquired"] = True
            except BaseException as e:  # noqa: BLE001
                out["err"] = e
            finally:
                set_thread_slot_meter(None)

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        t.join(timeout=5)
        release.set()
        for th in threads:
            th.join(timeout=1)

        err = out.get("err")
        self.assertIsInstance(err, OutboundBusy)
        # 兼容性：既有 `except TimeoutError` 分支必须照样接得住
        self.assertIsInstance(err, TimeoutError)
        self.assertIn("outbound busy", str(err))
        self.assertNotIn("acquired", out)
        self.assertEqual(meter.acquired, 0)
        self.assertEqual(meter.waiting_since, 0.0, "结算后不该还标着「正在等」")
        self.assertGreaterEqual(meter.total, 0.5)

    def test_wait_now_counts_live_waiting(self) -> None:
        """`wait_now()` 要含「此刻正在等」的部分，否则池线程永远看到 0。"""
        release, threads = self._saturate("ui")
        meter = SlotWaitMeter()
        seen: list[float] = []

        def waiter() -> None:
            set_thread_slot_meter(meter)
            try:
                with self.sched.slot("https://live.example/a", kind="ui", timeout=4):
                    pass
            except BaseException:  # noqa: BLE001
                pass
            finally:
                set_thread_slot_meter(None)

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        time.sleep(1.0)
        seen.append(meter.wait_now())
        release.set()
        for th in threads:
            th.join(timeout=1)
        t.join(timeout=5)
        self.assertGreaterEqual(seen[0], 0.5, "等槽期间 wait_now() 应持续增长")


class ClassifyBusyTests(unittest.TestCase):
    def test_outbound_busy_class_is_busy(self) -> None:
        e = OutboundBusy("outbound busy: no global slot (20.0s) kind=page host=x")
        self.assertEqual(_classify_source_failure(e), "busy")

    def test_busy_message_survives_rewrapping(self) -> None:
        """中间层可能包成 RuntimeError(str(e)) 丢掉类名 → 消息标记必须兜住。"""
        self.assertEqual(
            _classify_source_failure(RuntimeError("RuntimeError: outbound busy: pacing host=x")),
            "busy",
        )

    def test_flare_congestion_is_busy_not_down(self) -> None:
        """过盾通道排满 = 没轮到，不是过盾站坏了。"""
        self.assertEqual(
            _classify_source_failure(RuntimeError("curl/直连失败 · 过盾繁忙跳过")),
            "busy",
        )

    def test_real_timeout_still_down(self) -> None:
        self.assertEqual(_classify_source_failure(TimeoutError("timeout:28s")), "down")
        self.assertEqual(
            _classify_source_failure(RuntimeError("read timed out")), "down"
        )

    def test_miss_unchanged(self) -> None:
        self.assertEqual(_classify_source_failure(RuntimeError("未找到该番号")), "miss")
        self.assertEqual(_classify_source_failure(RuntimeError("HTTP 404")), "miss")


class CancelPairTests(unittest.TestCase):
    def test_union_semantics(self) -> None:
        pool, src = threading.Event(), threading.Event()
        pair = _CancelPair(pool, src)
        self.assertFalse(pair.is_set())
        src.set()
        self.assertTrue(pair.is_set(), "本源令牌置位即视为取消")

    def test_pool_token_still_works(self) -> None:
        pool, src = threading.Event(), threading.Event()
        pair = _CancelPair(pool, src)
        pool.set()
        self.assertTrue(pair.is_set())

    def test_none_tokens_ignored(self) -> None:
        pair = _CancelPair(None, None)
        self.assertFalse(pair.is_set())


if __name__ == "__main__":
    unittest.main()
