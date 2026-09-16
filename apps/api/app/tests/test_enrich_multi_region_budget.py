"""多区刮削的跨区 limit 预算必须按「实际处理条数」扣减。

背景：增量模式下 `run_enrich()` 返回的 `queued` 取的是**库内待处理预估**
（`_region_library_progress()["incomplete"]`，有码区十万级），而不是本次实际
处理条数。而多区调度原先拿它扣减跨区 limit：

    budget = max(0, budget - int(one.get("queued") or 0))
    ...
    if budget is not None and budget <= 0 and not cp:
        break        # 日志：「跳过 XX（预览额度已用完）」

后果：`limit=300` 的多区预览，第一个分区一跑完就把 30 万预算吃光，后面所有
分区直接跳过 —— 哪怕那个分区实际只处理了 5 条。

修法：用 `run_enrich()` 新增的 `processed`（= ok + failed）扣减，
某区实际无待处理（processed=0）时预算原样顺延给下一区。
"""

from __future__ import annotations

import unittest

from app.scrap_library.enrich import _next_budget


class NextBudgetTest(unittest.TestCase):
    def test_deducts_by_processed_not_by_library_estimate(self):
        """首区实际处理 5 条、库内预估 123000 → 预算应只扣 5。"""
        part = {"queued": 123000, "processed": 5}
        self.assertEqual(_next_budget(300, part), 295)

    def test_regression_old_metric_would_starve_next_regions(self):
        """回归守卫：旧口径（按 queued 扣）会把预算打到 0，后续分区被跳过。"""
        part = {"queued": 123000, "processed": 5}
        old_style = max(0, 300 - int(part["queued"]))
        self.assertEqual(old_style, 0)
        self.assertNotEqual(_next_budget(300, part), 0)

    def test_zero_processed_carries_budget_over(self):
        """该区没有待处理条目 → 预算顺延，不该白白消耗。"""
        self.assertEqual(_next_budget(30, {"queued": 123000, "processed": 0}), 30)

    def test_full_run_has_no_budget_cap(self):
        """正式全量（limit<=0 → budget=None）不受任何扣减影响。"""
        self.assertIsNone(_next_budget(None, {"processed": 999}))

    def test_overrun_clamps_to_zero(self):
        self.assertEqual(_next_budget(10, {"processed": 50}), 0)

    def test_missing_processed_treated_as_zero(self):
        """老检查点 / 老返回结构缺 `processed` 时按 0 处理，退化为不扣减。"""
        self.assertEqual(_next_budget(10, {}), 10)
        self.assertEqual(_next_budget(10, {"queued": 123000}), 10)


if __name__ == "__main__":
    unittest.main()
