"""第十九轮修复回归：封面全局槽必须随 itemWorkers 缩放。

背景（第十九轮体检发现）：第十八轮把 page/api 槽改成由 itemWorkers 推导，
但 `_KIND_GLOBAL["cover"]` 仍是**写死的 20**，`apply_item_workers()` 不管它。
而封面是在番号工人里**同步** `.result()` 等结果的（`enrich._download_covers`
→ `_get_cover_job_pool().submit(_run).result()`），所以真实峰值并发是**乘起来**的：

    itemWorkers=4  → 4 × COVER_BATCH_WORKERS(4) = 16  ≤ 20  ✅ 刚好不挤兑
    itemWorkers=8  → 32 > 20  ❌ 超订 1.6×
    itemWorkers=16 → 64 > 20  ❌ 超订 3.2×

后果不是「变慢」而是**误判**：抢不到槽抛 TimeoutError，被 `cover_download._fetch`
写成 `slot_blocked`，看起来像图床故障。所以顺序必须是「先让 cover 进公式，
再抬 itemWorkers」。

反证方式（每条都做过，回退实现后必须 FAILED，还原后 PASS）：
  - 公式里去掉 cover（回到固定 20）→ `test_cover_cap_covers_peak_demand`
    与 `test_peak_covers_do_not_slot_block` FAILED（n=8 第 21 次抢槽超时）。
  - `apply_item_workers` 不应用 cover → `test_apply_scales_cover_slot` FAILED。
  - 把 `_cover_batch_workers()` 写死返回常量（不惰性读）→
    `test_cover_batch_workers_follows_source` FAILED（把源常量临时改掉即暴露）。

第二十一轮更新：`COVER_SLOT_HEADROOM` 1.25 → 1.5，**基线槽 20 → 24**。
理由见 `outbound_scheduler.COVER_SLOT_HEADROOM` 上方注释 —— 现场实测到
`slot_blocked`，原余量漏算了同样取 cover 全局槽的旁路调用方。本文件所有
基线哨兵（20→24、40→48、19→23）已同步。⚠️ 此改动会**同时**作用于
`itemWorkers=4`（当前生产值），所以它不是「零行为变更」—— 这是刻意的。
"""

from __future__ import annotations

import math
import unittest

from app.core import outbound_scheduler as sched_mod
from app.scrap_library import cover_download as cd

# 覆盖「基线 → 上限」的整段（_ITEM_WORKERS_MAX=16）
_ITEM_WORKERS_SAMPLES = (1, 2, 3, 4, 5, 6, 8, 12, 16)


class CoverSlotScalingTests(unittest.TestCase):
    """封面全局槽 = ceil(max(itemWorkers, 基线) × 候选数 × 余量)。"""

    def test_baseline_matches_historical_constant(self) -> None:
        """n=4 的基线槽 —— **故意**硬编码的哨兵（第二十一轮起为 24）。

        为什么是 24 而不是历史值 20：现场实测到 `slot_blocked`（报告 §二十一），
        说明 1.25 的余量不够 —— 它只算了「本进程 itemWorkers × 批并发」这一路，
        漏掉同样取 cover 全局槽的旁路调用方（列表/详情封面代理）。第二十一轮
        把余量调到 1.5 ⇒ 4 × 4 × 1.5 = **24**。

        这是**故意**硬编码的哨兵：如果哪天改了 `COVER_BATCH_WORKERS` 或余量，
        这里会红，逼你确认「是故意改的还是顺手改崩的」，再连同
        `_KIND_GLOBAL["cover"]` 一起更新。
        """
        self.assertEqual(
            sched_mod.cover_cap_for_item_workers(
                sched_mod.CAPS_BASELINE_ITEM_WORKERS
            ),
            24,
        )

    def test_default_dict_matches_formula(self) -> None:
        """`_KIND_GLOBAL["cover"]` 是「未 apply 时」的默认值，不许与公式脱节。"""
        self.assertEqual(
            int(sched_mod._KIND_GLOBAL["cover"]),
            sched_mod.cover_cap_for_item_workers(
                sched_mod.CAPS_BASELINE_ITEM_WORKERS
            ),
        )

    def test_cover_cap_covers_peak_demand(self) -> None:
        """核心不变量：槽位 ≥ 峰值并发。**反证锚点**（去掉 cover 后 n=8 必红）。"""
        for n in _ITEM_WORKERS_SAMPLES:
            cap = sched_mod.caps_for_item_workers(n)["cover"]
            peak = n * int(cd.COVER_BATCH_WORKERS)
            self.assertGreaterEqual(
                cap, peak, f"itemWorkers={n}: 峰值 {peak} 路封面 > 槽位 {cap}"
            )

    def test_below_baseline_is_clamped(self) -> None:
        """小于基线不缩容：单刷/小任务时封面槽保持基线 24，避免被饿死。"""
        for n in (1, 2):
            self.assertEqual(sched_mod.cover_cap_for_item_workers(n), 24)

    def test_cover_batch_workers_follows_source(self) -> None:
        """槽位推导必须**惰性读**源常量，别在两处各写一份（D5 的老坑）。

        反证：把推导里的惰性读换成硬编码常量 → 这里临时把源常量改成 6 后
        仍返回 4 → FAILED。
        """
        self.assertEqual(
            sched_mod._cover_batch_workers(), int(cd.COVER_BATCH_WORKERS)
        )
        old = cd.COVER_BATCH_WORKERS
        try:
            cd.COVER_BATCH_WORKERS = int(old) + 2
            self.assertEqual(sched_mod._cover_batch_workers(), int(old) + 2)
            # 槽位必须跟着源常量走：改一处自动同步，不用手改 _KIND_GLOBAL
            # 基线 4 番号 × (old+2) 候选 × 1.5 = 6 × (old+2)
            self.assertEqual(
                sched_mod.cover_cap_for_item_workers(
                    sched_mod.CAPS_BASELINE_ITEM_WORKERS
                ),
                (int(old) + 2) * 6,
            )
        finally:
            cd.COVER_BATCH_WORKERS = old

    def test_headroom_is_what_makes_baseline_identity(self) -> None:
        """余量的定义：基线槽 = ceil(基线番号数 × 候选数 × 余量)，且余量 ≥ 1。

        余量 < 1 等于「设计性超订」——峰值必然抢不到槽。
        """
        base = int(sched_mod.CAPS_BASELINE_ITEM_WORKERS)
        batch = int(cd.COVER_BATCH_WORKERS)
        self.assertEqual(
            sched_mod.cover_cap_for_item_workers(base),
            math.ceil(base * batch * float(sched_mod.COVER_SLOT_HEADROOM)),
        )
        self.assertGreaterEqual(float(sched_mod.COVER_SLOT_HEADROOM), 1.0)


class ApplyItemWorkersCoverTests(unittest.TestCase):
    """`apply_item_workers()` 必须同时换掉 cover 信号量。"""

    def setUp(self) -> None:
        sched_mod.reset_scheduler_for_tests()
        self.s = sched_mod.get_scheduler()

    def tearDown(self) -> None:
        sched_mod.reset_scheduler_for_tests()

    def test_apply_scales_cover_slot(self) -> None:
        """反证锚点：不应用 cover 时这里仍是 20 → FAILED。"""
        self.s.apply_item_workers(8)
        self.assertEqual(
            self.s._globals["cover"]._value,
            sched_mod.cover_cap_for_item_workers(8),
        )
        # 8 × 4 候选 = 32 峰值，×1.5 余量 → 48
        self.assertEqual(self.s._globals["cover"]._value, 48)

    def test_apply_keeps_host_limits_untouched(self) -> None:
        """扩容只动全局槽；站点保护（per_host / min_interval）必须原样。"""
        cov = self.s._limits_for("pics.dmm.co.jp", "cover")
        self.s.apply_item_workers(16)
        self.assertEqual(self.s._limits_for("pics.dmm.co.jp", "cover"), cov)

    def test_peak_covers_do_not_slot_block(self) -> None:
        """真行为验证：itemWorkers=8 时 32 路封面必须都能抢到槽。

        反证：cover 固定 20 → 第 21 次 acquire 超时 → FAILED。
        """
        n = 8
        self.s.apply_item_workers(n)
        peak = n * int(cd.COVER_BATCH_WORKERS)
        got = 0
        for _ in range(peak):
            if self.s._globals["cover"].acquire(timeout=0.05):
                got += 1
        self.assertEqual(got, peak, f"只抢到 {got}/{peak} 个封面槽 → 会写成 slot_blocked")

    def test_apply_is_idempotent_for_cover(self) -> None:
        """同值不得重建信号量（否则许可被重置，计数漂移）。"""
        self.s.apply_item_workers(4)
        sem = self.s._globals["cover"]
        sem.acquire()
        self.s.apply_item_workers(4)
        self.assertIs(self.s._globals["cover"], sem)
        self.assertEqual(self.s._globals["cover"]._value, 23)


if __name__ == "__main__":
    unittest.main()
