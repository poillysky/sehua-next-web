"""第十八轮修复回归：P0 未定义符号 / 早停有界等待 / cooldown 独立 kind。

反证方式（每条都做过）：
  - P0     ：把 `_queue_row_status` 换回未定义名 → `test_paused_status_*` FAILED（NameError）。
  - 有界等待：把 `meta_wait` 传参去掉（回到「无限等」）→ `test_meta_budget_*` FAILED。
  - cooldown：把 `kind="cooldown"` 改回 `kind="busy"` → `test_cooldown_*` FAILED。
"""

from __future__ import annotations

import inspect
import time
import unittest

from app.core import outbound_scheduler as sched_mod
from app.scrap_library import enrich as E


class QueueRowStatusTests(unittest.TestCase):
    """P0：`_queue_row_status` 曾在 enrich.py 里「只被调用、从未定义」。

    lite 路径 `queue=[]` 不进循环，刚好把这个 NameError 藏住了；
    只要任务处于暂停/停止态且走非 lite 分支，状态接口就 500。
    """

    def test_symbol_is_defined(self) -> None:
        self.assertTrue(callable(getattr(E, "_queue_row_status", None)))

    def test_normalizes_like_counts(self) -> None:
        """与 `_queue_counts_of` 同一真相源：strip + lower。"""
        self.assertEqual(E._queue_row_status({"status": "  Running "}), "running")
        self.assertEqual(E._queue_row_status({"status": "DONE"}), "done")
        self.assertEqual(E._queue_row_status({}), "")
        self.assertEqual(E._queue_row_status(None), "")
        self.assertEqual(E._queue_row_status("running"), "")

    def test_counts_and_status_agree(self) -> None:
        """两处读法必须一致：计数把 ' Running ' 当 running，展示层也必须。"""
        rows = [{"status": " Running "}, {"status": "pending"}, {"status": "done"}]
        counts = E._queue_counts_of(rows)
        self.assertEqual(counts["running"], 1)
        self.assertEqual(counts["pending"], 1)
        self.assertEqual(counts["done"], 1)

    def test_paused_status_does_not_raise(self) -> None:
        """真回归：暂停态 + 非空队列 + 非 lite → 必须能取到状态而不是 500。"""
        job = E._enrich_job
        saved = {k: job.get(k) for k in ("phase", "queue", "queueCounts", "halt")}
        try:
            job["phase"] = "paused"
            job["queue"] = [
                {"code": "AARM-010", "itemId": "x1", "status": "running"},
                {"code": "AARM-018", "itemId": "x2", "status": "running"},
                {"code": "AARM-037", "itemId": "x3", "status": "done"},
            ]
            job["queueCounts"] = {
                "pending": 1,
                "running": 2,
                "done": 1,
                "soft": 0,
                "fail": 0,
            }
            st = E.get_enrich_status()
        finally:
            for k, v in saved.items():
                job[k] = v
        # 暂停态对外一律非 running；展示行也全部降级为 pending
        self.assertFalse(st.get("running"))
        self.assertEqual(int((st.get("queueCounts") or {}).get("running") or 0), 0)
        for row in st.get("queue") or []:
            self.assertNotEqual(str(row.get("status") or ""), "running")


class MetaWaitBudgetTests(unittest.TestCase):
    """早停的「元数据未齐」闸门必须有界：series 对很多番号本就拿不到。"""

    def _detail(self, **over: object) -> dict:
        d = {
            "code": "AARM-010",
            "title": "某标题",
            "studio": "某社",
            "series": "",
            "publisher": "某社",
            "website": "https://x.example/a",
        }
        d.update(over)
        return d

    GAPS = ["no_studio"]
    BATCH = [{"id": "dmm"}, {"id": "avbase"}]

    def test_budget_is_positive_and_bounded(self) -> None:
        self.assertGreater(E._META_WAIT_BUDGET_SEC, 0)
        # 上界：不该把单番号预算抬到与单源超时同量级
        self.assertLessEqual(E._META_WAIT_BUDGET_SEC, 5.0)

    def test_legacy_none_keeps_old_behaviour(self) -> None:
        """meta_wait=None = 旧行为（无限等），A/B 与反证要用。"""
        self.assertFalse(
            E._may_early_stop(
                self._detail(), self.GAPS, code="AARM-010",
                batch=self.BATCH, finished=set(),
            )
        )

    def test_budget_expires_then_allows_early_stop(self) -> None:
        w: dict = {}
        self.assertFalse(
            E._may_early_stop(
                self._detail(), self.GAPS, code="AARM-010",
                batch=self.BATCH, finished=set(), meta_wait=w,
            )
        )
        self.assertIn("since", w, "首次应起表")
        time.sleep(float(E._META_WAIT_BUDGET_SEC) + 0.05)
        self.assertTrue(
            E._may_early_stop(
                self._detail(), self.GAPS, code="AARM-010",
                batch=self.BATCH, finished=set(), meta_wait=w,
            )
        )

    def test_meta_complete_allows_immediately(self) -> None:
        """元数据齐了就该立刻放行，一分钟都不等。"""
        self.assertTrue(
            E._may_early_stop(
                self._detail(series="某系列"), self.GAPS, code="AARM-010",
                batch=self.BATCH, finished=set(), meta_wait={},
            )
        )

    def test_new_sources_cannot_rearm_budget(self) -> None:
        """预算起表后不得因新源到达而重置（否则会退化成无限等）。"""
        w: dict = {}
        E._may_early_stop(
            self._detail(), self.GAPS, code="AARM-010",
            batch=self.BATCH, finished=set(), meta_wait=w,
        )
        first = w["since"]
        E._may_early_stop(
            self._detail(), self.GAPS, code="AARM-010",
            batch=self.BATCH, finished={"dmm"}, meta_wait=w,
        )
        self.assertEqual(w["since"], first)

    def test_non_meta_sources_do_not_block(self) -> None:
        self.assertTrue(
            E._may_early_stop(
                self._detail(), self.GAPS, code="X",
                batch=[{"id": "iqqtv"}], finished=set(), meta_wait={},
            )
        )

    def test_production_call_sites_pass_holder(self) -> None:
        """生产路径必须传 meta_wait，否则有界等待形同虚设。"""
        src = inspect.getsource(E._fetch_detail)
        self.assertIn("meta_wait=_meta_wait", src)
        self.assertEqual(src.count("meta_wait=_meta_wait"), 2)


class CooldownKindTests(unittest.TestCase):
    """cooldown ≠ busy：前者是源健康度结论，后者是「我们没轮到」。"""

    def test_cooldown_branch_uses_own_kind(self) -> None:
        src = inspect.getsource(E._fetch_detail)
        self.assertIn('"cooldown:源暂避"', src)
        self.assertIn('kind="cooldown"', src)
        self.assertIn('return sid, None, err_c, "cooldown"', src)

    def test_cooldown_not_recorded_as_busy(self) -> None:
        """反证锚点：冷却分支里不得再出现 kind="busy"。"""
        src = inspect.getsource(E._fetch_detail)
        idx = src.index('"cooldown:源暂避"')
        window = src[idx - 200 : idx + 500]
        self.assertNotIn('kind="busy"', window)

    def test_run_pool_returns_cooldown_bucket(self) -> None:
        src = inspect.getsource(E._fetch_detail)
        self.assertIn("cooldown_ids", src)
        self.assertIn('kind == "cooldown"', src)

    def test_cooldown_enters_degraded_set(self) -> None:
        """cooldown 与 down 同源，必须进 degradedByDown 才会被回头补抓。"""
        src = inspect.getsource(E._fetch_detail)
        self.assertIn("down_all | busy_all | cooldown_all", src)
        self.assertIn('merged["sourcesCooldown"]', src)

    def test_cooldown_state_machine(self) -> None:
        """冷却由 down 连击触发、hit 清空 —— 与 kind 拆分无关（基线不回归）。"""
        sid = "unittest-cooldown-src"
        E._SOURCE_COOLDOWN_UNTIL.pop(sid, None)
        E._SOURCE_DOWN_STREAK.pop(sid, None)
        try:
            self.assertFalse(E._source_in_cooldown(sid))
            for _ in range(int(E._SOURCE_COOLDOWN_STREAK)):
                E._note_source_fetch_outcome(sid, kind="down")
            self.assertTrue(E._source_in_cooldown(sid))
            E._note_source_fetch_outcome(sid, kind="hit")
            self.assertFalse(E._source_in_cooldown(sid))
        finally:
            E._SOURCE_COOLDOWN_UNTIL.pop(sid, None)
            E._SOURCE_DOWN_STREAK.pop(sid, None)


class OutboundCapsScaleTests(unittest.TestCase):
    """出站槽必须由 itemWorkers 推导，别再手工凑两处常量。"""

    def test_baseline_reproduces_historical_values(self) -> None:
        """n=4 必须逐字等于 page=24 / api=12（历史常量，不许漂）。

        cover 是例外：第二十一轮由 20 调到 **24**（余量 1.25→1.5，理由见
        `outbound_scheduler.COVER_SLOT_HEADROOM`）。那是**刻意**的行为变更，
        不是漂移 —— 所以它仍在本断言里，只是值更新了。
        """
        caps = sched_mod.caps_for_item_workers(
            sched_mod.CAPS_BASELINE_ITEM_WORKERS
        )
        self.assertEqual(caps, {"page": 24, "api": 12, "cover": 24})

    def test_scales_linearly_with_ratio(self) -> None:
        for n, page, api in ((2, 12, 6), (6, 36, 18), (8, 48, 24)):
            caps = sched_mod.caps_for_item_workers(n)
            self.assertEqual(
                {k: caps[k] for k in ("page", "api")}, {"page": page, "api": api}
            )

    def test_apply_changes_only_global_caps(self) -> None:
        """per_host 是站点保护，扩容不许碰它。"""
        sched_mod.reset_scheduler_for_tests()
        s = sched_mod.get_scheduler()
        host_cov = s._limits_for("pics.dmm.co.jp", "cover")
        try:
            s.apply_item_workers(6)
            self.assertEqual(s.applied_item_workers(), 6)
            self.assertEqual(s._globals["page"]._value, 36)
            self.assertEqual(s._globals["api"]._value, 18)
            # 第十九轮：cover 也进公式了；第二十一轮余量 1.25→1.5
            # （6 × 4 候选 × 1.5 = 36）
            self.assertEqual(s._globals["cover"]._value, 36)
            self.assertEqual(s._limits_for("pics.dmm.co.jp", "cover"), host_cov)
        finally:
            sched_mod.reset_scheduler_for_tests()

    def test_apply_is_idempotent(self) -> None:
        sched_mod.reset_scheduler_for_tests()
        s = sched_mod.get_scheduler()
        try:
            s.apply_item_workers(4)
            sem = s._globals["page"]
            s._globals["page"].acquire()
            s.apply_item_workers(4)  # 同值 → 不得重建（否则许可被重置）
            self.assertIs(s._globals["page"], sem)
            self.assertEqual(s._globals["page"]._value, 23)
        finally:
            sched_mod.reset_scheduler_for_tests()

    def test_invalid_value_falls_back_to_baseline(self) -> None:
        sched_mod.reset_scheduler_for_tests()
        s = sched_mod.get_scheduler()
        try:
            s.apply_item_workers(0)
            self.assertEqual(
                s.applied_item_workers(),
                int(sched_mod.CAPS_BASELINE_ITEM_WORKERS),
            )
        finally:
            sched_mod.reset_scheduler_for_tests()


class CoverBatchWorkersTests(unittest.TestCase):
    """封面批量并发：3 波 → 2 波（第十七轮 D1）。"""

    def test_batch_workers_beats_wave_count(self) -> None:
        from app.scrap_library import cover_download as cd

        self.assertGreaterEqual(cd.COVER_BATCH_WORKERS, 3)
        # 5 个候选必须能在 2 波内跑完（ceil(5/n) <= 2）
        self.assertLessEqual(-(-5 // int(cd.COVER_BATCH_WORKERS)), 2)

    def test_batch_workers_fit_cover_global_slot(self) -> None:
        """批量并发不得越过 cover 全局槽，否则会挤兑成 slot_blocked。

        第十九轮起槽位随 itemWorkers 缩放，所以这里要对**整段** itemWorkers 校验，
        而不是只看基线那一格（原来只锁 baseline=4，提值时是裸的）。
        """
        from app.scrap_library import cover_download as cd

        for n in (1, 2, 4, 6, 8, 12, 16):
            cap = sched_mod.caps_for_item_workers(n)["cover"]
            self.assertLessEqual(
                int(cd.COVER_BATCH_WORKERS) * n,
                cap,
                f"itemWorkers={n}: {cd.COVER_BATCH_WORKERS}×{n} 超出 cover 全局槽 {cap}",
            )

    def test_single_mode_unchanged(self) -> None:
        from app.scrap_library import cover_download as cd

        self.assertEqual(int(cd.COVER_SINGLE_WORKERS), 6)


if __name__ == "__main__":
    unittest.main()
