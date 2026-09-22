"""第十一轮：直连 API 路径纳入出站调度 + 收敛排队预算（代价）。

第八轮记的「10 个源里 4 个完全不占出站槽」在本轮补掉。三件事：

1. `kind="api"` 通道：`common.fetch_json` / `common.fetch_post_form` /
   `dmm._post_graphql` 以前**完全不走调度器** —— 不受并发上限约束、
   不进 `SlotWaitMeter`；顺带把 r18.dev 的「单线程 + ≥0.45s」约定落到调度器上。
2. `_give_up_kind`：直连源 `acquired` 恒为 0 → 真超时被「acquired==0 → busy」
   兜底改写成 busy（与第八轮假 down 方向相反的同型缺陷）。
3. `_refine_kind_with_meter`：源自己的 `except Exception: return None` 会把
   `OutboundBusy` 吞成「未找到」→ 假 miss（明确不补抓 → 数据静默丢失）。
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest import mock

from app.core import outbound_http
from app.core.outbound_scheduler import (
    OutboundBusy,
    OutboundScheduler,
    SlotWaitMeter,
    get_scheduler,
    reset_scheduler_for_tests,
    set_thread_slot_meter,
)
from app.scrap_library.enrich import _give_up_kind, _refine_kind_with_meter


class ApiChannelTests(unittest.TestCase):
    """`kind="api"` 必须真注册（否则 `slot()` 会静默降级成 page 通道）。"""

    def setUp(self) -> None:
        self.sched = OutboundScheduler()

    def test_registered_not_silently_downgraded_to_page(self) -> None:
        stats = self.sched.stats()["kindGlobal"]
        self.assertIn("api", stats)
        self.assertEqual(stats["api"], 12)
        # 未注册的 kind 会被 slot() 强制成 page（见 slot() 的 kind_n 兜底），
        # 所以「限额 = page」就是「没注册」的信号
        api_per_host, api_gap = self.sched._limits_for("example.com", "api")  # noqa: SLF001
        page_per_host, page_gap = self.sched._limits_for("example.com", "page")  # noqa: SLF001
        self.assertNotEqual((api_per_host, api_gap), (page_per_host, page_gap))

    def test_r18dev_single_flight_and_pacing(self) -> None:
        """r18.dev：同站 1 路 + ≥0.45s 间距（官方约定，原来只在手动探针里遵守）。"""
        per_host, gap = self.sched._limits_for("r18.dev", "api")  # noqa: SLF001
        self.assertEqual(per_host, 1)
        self.assertGreaterEqual(gap, 0.45)
        t0 = time.monotonic()
        for _ in range(2):
            with self.sched.slot("https://r18.dev/videos/x", kind="api", timeout=5):
                pass
        self.assertGreaterEqual(
            time.monotonic() - t0, 0.40, "两次 r18.dev 请求之间没有拉开间距"
        )

    def test_api_slot_enters_api_gate_and_raises_busy(self) -> None:
        """api 通道被占满 → 抛 OutboundBusy（不是裸 TimeoutError，也不是源故障）。

        `api_slot` 用的是**进程级**调度器（`get_scheduler()`），所以这里占的是它。
        """
        reset_scheduler_for_tests()
        sched = get_scheduler()
        n = int(sched.stats()["kindGlobal"]["api"])
        release = threading.Event()
        ready = threading.Semaphore(0)
        threads: list[threading.Thread] = []

        def hold(i: int) -> None:
            with sched.slot(f"https://hold{i}.example/a", kind="api", timeout=10):
                ready.release()
                release.wait(8)

        for i in range(n):
            t = threading.Thread(target=hold, args=(i,), daemon=True)
            threads.append(t)
            t.start()
        for _ in range(n):
            self.assertTrue(ready.acquire(timeout=5), "未占满 api 全局槽")

        meter = SlotWaitMeter()
        set_thread_slot_meter(meter)
        try:
            with self.assertRaises(OutboundBusy):
                with outbound_http.api_slot("https://r18.dev/videos/x", timeout=0.8):
                    pass
        finally:
            set_thread_slot_meter(None)
            release.set()
            for th in threads:
                th.join(timeout=1)
            reset_scheduler_for_tests()

        self.assertIsInstance(
            OutboundBusy("outbound busy: x"), TimeoutError
        )  # 既有 except TimeoutError 分支必须照样接得住
        self.assertEqual(meter.acquired, 0)
        self.assertEqual(meter.slot_timeout, 1, "排队预算耗尽必须留痕（供假 miss 修正）")

    def test_successful_api_slot_records_acquired(self) -> None:
        self.sched = OutboundScheduler()
        meter = SlotWaitMeter()
        set_thread_slot_meter(meter)
        try:
            with outbound_http.api_slot("https://libredmm.example/a"):
                pass
        finally:
            set_thread_slot_meter(None)
        self.assertEqual(meter.acquired, 1)
        self.assertEqual(meter.slot_timeout, 0)


class DirectFetchBudgetTests(unittest.TestCase):
    """直连请求超时必须跟随线程本地单源预算（原来硬编码 28s / 20s）。"""

    def setUp(self) -> None:
        reset_scheduler_for_tests()
        self.seen: dict[str, object] = {}

        class _Resp:
            text = '{"ok": 1}'
            status_code = 200

        def _fake_curl(method: str, url: str, **kw):
            self.seen["method"] = method
            self.seen["url"] = url
            self.seen["timeout"] = kw.get("timeout")
            return _Resp()

        self._patch = mock.patch.object(outbound_http, "curl_request", _fake_curl)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        outbound_http.set_thread_request_timeout(None)
        reset_scheduler_for_tests()

    def test_fetch_json_reads_thread_budget(self) -> None:
        from app.scrape_details.common import fetch_json

        set_thread_slot_meter(SlotWaitMeter())
        outbound_http.set_thread_request_timeout(7.0)
        try:
            self.assertEqual(fetch_json("https://r18.dev/api/x"), {"ok": 1})
        finally:
            set_thread_slot_meter(None)
        self.assertEqual(self.seen["timeout"], 7.0)

    def test_fetch_json_defaults_to_28s_without_budget(self) -> None:
        from app.scrape_details.common import fetch_json

        fetch_json("https://r18.dev/api/x")
        self.assertEqual(self.seen["timeout"], 28.0)

    def test_fetch_post_form_holds_api_slot(self) -> None:
        import curl_cffi.requests as creq

        class _R:
            status_code = 200
            text = "x" * 400

        meter = SlotWaitMeter()
        set_thread_slot_meter(meter)
        try:
            with mock.patch.object(creq, "post", lambda url, **kw: _R()):
                from app.scrape_details.common import fetch_post_form

                html = fetch_post_form("https://jav321.example/search", "q=1")
        finally:
            set_thread_slot_meter(None)
        self.assertEqual(len(html), 400)
        self.assertEqual(meter.acquired, 1, "直连 POST 也必须进出站槽（不然记账/限额失效）")


class GiveUpKindTests(unittest.TestCase):
    """`_give_up_kind` 真值表 —— 第八轮假 down 的镜像缺陷（假 busy）就锁在这里。"""

    def test_real_timeout_with_slot_is_down(self) -> None:
        self.assertEqual(
            _give_up_kind(give_up="down", acquired=1, cancelled=False), "down"
        )

    def test_direct_source_real_timeout_is_down_not_busy(self) -> None:
        """核心回归：直连源拿到过槽后真超时 → down。

        第十一轮之前直连源不占槽（`acquired` 恒为 0），这条路会被兜底改写成 busy。
        """
        self.assertEqual(
            _give_up_kind(give_up="down", acquired=1, cancelled=False), "down"
        )

    def test_never_got_slot_is_busy(self) -> None:
        self.assertEqual(
            _give_up_kind(give_up="down", acquired=0, cancelled=False), "busy"
        )
        self.assertEqual(
            _give_up_kind(give_up="busy", acquired=0, cancelled=False), "busy"
        )

    def test_cancelled_wins(self) -> None:
        self.assertEqual(
            _give_up_kind(give_up="down", acquired=1, cancelled=True), "cancelled"
        )
        self.assertEqual(
            _give_up_kind(give_up="busy", acquired=0, cancelled=True), "cancelled"
        )


class RefineKindWithMeterTests(unittest.TestCase):
    """源把 OutboundBusy 吞成「未找到」时，用记账痕迹把假 miss 改回 busy。"""

    def test_without_slot_timeout_nothing_changes(self) -> None:
        for k in ("miss", "down", "hit", "busy", "cancelled"):
            self.assertEqual(_refine_kind_with_meter(k, slot_timeout=0), k)

    def test_slot_timeout_turns_fake_miss_into_busy(self) -> None:
        self.assertEqual(_refine_kind_with_meter("miss", slot_timeout=1), "busy")
        self.assertEqual(_refine_kind_with_meter("down", slot_timeout=2), "busy")

    def test_success_still_hit(self) -> None:
        """拿到数据就是拿到 —— 不能因为中途排过一次队就把命中改掉。"""
        self.assertEqual(_refine_kind_with_meter("hit", slot_timeout=3), "hit")
        self.assertEqual(_refine_kind_with_meter("cancelled", slot_timeout=3), "cancelled")


class CallSiteWiringTests(unittest.TestCase):
    """静态接线：纯函数测不出「有没有被调用」。这里按 AST 钉住调用点。

    改动前请想清楚：把 `_one()` 里的判据换回内联字面量、或把某条直连路径的
    `api_slot()` 摘掉，都会在这里红。

    注意：`path` 是 **glob**（按 enrich 家族整体搜索），且调用名取末段 ——
    模块拆分（如 `enrich.py` → `enrich_detail.py`、调用点写成 `_enrich.NAME`）
    不应让本测试误红；被钉住的是「有没有调用这个判据」，不是它写在哪个文件。
    """

    @staticmethod
    def _calls_in(path: str, func_name: str) -> set[str]:
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        out: set[str] = set()
        for f in sorted(root.glob(path)):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == func_name:
                    for sub in ast.walk(node):
                        if not isinstance(sub, ast.Call):
                            continue
                        fn = sub.func
                        if isinstance(fn, ast.Name):
                            out.add(fn.id)
                        elif isinstance(fn, ast.Attribute):
                            # 拆分后调用点形如 `_enrich.NAME` → 取末段名字
                            out.add(fn.attr)
        return out

    def test_one_uses_both_judgements(self) -> None:
        calls = self._calls_in("scrap_library/enrich*.py", "_one")
        self.assertIn("_give_up_kind", calls, "放弃分类必须走纯函数（别内联回去）")
        self.assertIn("_refine_kind_with_meter", calls, "假 miss 修正没接线")

    def test_direct_paths_hold_api_slot(self) -> None:
        for path, fn in (
            ("scrape_details/common.py", "fetch_json"),
            ("scrape_details/common.py", "fetch_post_form"),
            ("scrape_details/dmm.py", "_post_graphql"),
        ):
            with self.subTest(f"{path}::{fn}"):
                self.assertIn(
                    "api_slot",
                    self._calls_in(path, fn),
                    "直连路径必须进出站槽（不然限额与记账都失效）",
                )


if __name__ == "__main__":
    unittest.main()
