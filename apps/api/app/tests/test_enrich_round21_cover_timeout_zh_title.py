"""第二十一轮回归：封面抢槽超时收敛 + `no_zh_title` 早停语义对齐。

## 为什么查这两件事（生产现场取证，见 `_gap_reports/_pipeline_audit_2026-09-15.md` §二十一）

管线跑到 SUJI/SUKE 段时逐帧观测到 **封面阶段 7~15 秒**，是拉详情（0.25~5s）的
3~10 倍，占番号墙钟约 **70%**。追下去是**两个各自独立的缺陷**叠在一起：

1. **抢槽超时设成了 5.0s**（`download_best_cover`），而下层
   `_fetch_bytes_for_enrich` 的 docstring 明写「timeout 为抢槽上限（批量应传 1～3s，
   勿再等 45s 把封面预算拖死）」—— 调用方直接违背了被调用方写下的契约。
   5 候选 / 4 路 = **2 波** ⇒ 最坏 2 × 5.0s = **10s 纯抢槽干等**，
   这就是 `coverMs` 平台状分布的来源，跟图床快慢无关。
   而抢不到槽后的 retry 分支还把它**抬高到 7.0s**（现场日志 `retry after slot pressure`）
   —— 方向是反的：`slot_heavy >= 2` 恰恰说明槽不够用，此时期更久只会更糟。

2. **`no_zh_title` 的语义三处不一致**：`_detail_satisfies_gaps` 拿它当**硬闸门**
   （标题非中文一律不许早停），而 dmm / avbase 这类源给的就是含假名的日文标题
   （`_zh_prefer_bonus` 见假名即返回 0），**永远不可能**满足这条 ⇒ 这些番号必然
   等到**全部源**回或超时。与此同时 `_may_early_stop` / `_run_pool` 的中文等待
   集合却只认 `thin_title`/`no_plot` —— 于是这些号既不享受「中文源跑完就放行」，
   也不被允许早停（现场约 12% 的号吃这个亏）。修法是把硬闸门换成
   「等中文源，跑完即放行」，并把三个集合对齐到同一语义。

## 反证方式（每条都实际做过：回退实现 → 必须 FAILED → 还原 → PASS）

  - 抢槽超时改回 5.0 → `test_batch_slot_timeout_within_contract` FAILED。
  - retry 分支加回 `url_timeout = max(url_timeout, 7.0)` →
    `test_retry_does_not_raise_slot_timeout` FAILED（真跑一次 `download_best_cover`，
    用 mock 记录每次传入的 `slot_timeout`）。
  - 把 `no_zh_title` 硬闸门加回 `_detail_satisfies_gaps` →
    `test_no_zh_title_is_not_a_hard_gate` FAILED。
  - 把 `no_zh_title` 从 `_may_early_stop` 的 need_zh 集合移走 →
    `test_no_zh_title_waits_for_cn_sources` / `..._releases_after_cn_sources_done`
    至少一条 FAILED（前者会因为不再等待而误放行）。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app.scrape.source_catalog as catalog
from app.scrap_library import cover_download as cd
from app.scrap_library import embed as embed_svc
from app.scrap_library import enrich as E

# 一个真实的「含假名日文标题」样本：`_zh_prefer_bonus` 对它返回 0
_JP_TITLE = "新人NO.1STYLE えんじぇる特集"
_CODE = "SSIS-031"


class CoverSlotTimeoutTests(unittest.TestCase):
    """封面抢槽超时必须守下层契约（批量 1~3s），且不得在拥塞时被反向放大。"""

    def test_batch_slot_timeout_within_contract(self) -> None:
        """反证锚点：改回 5.0 即 FAILED。

        契约来源：`cover_focus_routes._fetch_bytes_for_enrich` 的 docstring
        「timeout 为抢槽上限（批量应传 1～3s）」。
        """
        self.assertLessEqual(
            float(cd.COVER_SLOT_TIMEOUT_BATCH),
            3.0,
            "批量抢槽超时超出下层契约（1~3s）—— 每个番号会白等这么久",
        )
        self.assertGreater(
            float(cd.COVER_SLOT_TIMEOUT_BATCH), 0.0, "抢槽超时必须是正数"
        )

    def test_single_not_shorter_than_batch(self) -> None:
        """单刷没有并发同伴，可以比批量宽 —— 但方向不能反。"""
        self.assertLessEqual(
            float(cd.COVER_SLOT_TIMEOUT_BATCH),
            float(cd.COVER_SLOT_TIMEOUT_SINGLE),
        )

    def test_retry_does_not_raise_slot_timeout(self) -> None:
        """真行为验证：全槽阻塞走到 retry 分支时，超时**不得**被抬高。

        反证：把 `url_timeout = max(url_timeout, 7.0)` 加回去 →
        retry 那几次记录的 `slot_timeout` 变成 7.0 → FAILED。
        """
        seen: list[float] = []

        def _fake_fetch(url: str, *, slot_timeout: float | None = None):
            seen.append(float(slot_timeout or 0.0))
            raise TimeoutError("slot busy")  # `_fetch` 会记成 slot_blocked

        entries = [
            {"source": "dmm", "url": f"https://pics.dmm.co.jp/mono/movie/adult/s{ i }/x{i}pl.jpg"}
            for i in range(6)
        ]
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(
                embed_svc, "_fetch_cover_bytes", side_effect=_fake_fetch
            ):
                cd.download_best_cover(
                    Path(td),
                    entries,
                    region="japan_censored",
                    batch_mode=True,
                    field_priority=["dmm"],
                    region_sources=["dmm"],
                )
        self.assertTrue(seen, "应当至少发起过一次封面取图")
        # 全部槽阻塞 → 必然走到 slot_heavy >= 2 的 retry 分支，调用数 > 一轮
        self.assertGreater(
            len(seen), 5, "未触发 retry 分支，本用例失去意义（应 >1 轮候选）"
        )
        self.assertLessEqual(
            max(seen),
            float(cd.COVER_SLOT_TIMEOUT_BATCH) + 1e-6,
            f"retry 把抢槽超时抬高了：观测到 {sorted(set(seen))}，"
            f"契约上限 {cd.COVER_SLOT_TIMEOUT_BATCH}",
        )


class NoZhTitleEarlyStopTests(unittest.TestCase):
    """`no_zh_title` 既不是硬闸门，也不该被无视 —— 归「等中文源」管。"""

    def _detail(self, title: str | None = None) -> dict[str, object]:
        return {
            "code": _CODE,
            "title": _JP_TITLE if title is None else title,
            # 让 `_detail_meta_incomplete` 为 False，避免 meta 有界等待干扰本用例
            "series": "新人NO.1STYLE",
            "publisher": "S1",
            "website": f"https://example.com/{_CODE.lower()}",
        }

    @staticmethod
    def _cn_source_id() -> str:
        """找一个「canonicalize 之后仍在中文源集合里」的源 id。"""
        for cand in sorted(E._CN_TEXT_SOURCE_IDS):
            sid = catalog.canonicalize_id(cand)
            if sid in E._CN_TEXT_SOURCE_IDS:
                return sid
        raise AssertionError("没有可用的中文源样本")

    def test_jp_title_really_lacks_zh(self) -> None:
        """前置校验：样本标题确实被判为「没中文」，否则下面几条都是空转。"""
        self.assertTrue(E._title_lacks_zh(_JP_TITLE, _CODE))

    def test_no_zh_title_is_not_a_hard_gate(self) -> None:
        """反证锚点：把硬闸门加回 `_detail_satisfies_gaps` → FAILED。

        修前这里返回 False（标题非中文一律不许早停）→ 番号只能等全部源超时。
        """
        self.assertTrue(
            E._detail_satisfies_gaps(
                self._detail(), ["no_zh_title"], code=_CODE
            ),
            "`no_zh_title` 不该是早停硬闸门（日文源永远给不出中文标题）",
        )

    def test_no_zh_title_waits_for_cn_sources(self) -> None:
        """中文源还在飞 → 不许早停（否则等于白丢中文标题）。**反证锚点**。

        反证：把 `no_zh_title` 从 need_zh 集合移走 →
        这里会因为「不等待」而返回 True → FAILED。
        """
        sid = self._cn_source_id()
        batch = [{"id": sid}, {"id": "dmm"}]
        self.assertFalse(
            E._may_early_stop(
                self._detail(),
                ["no_zh_title"],
                code=_CODE,
                batch=batch,
                finished=set(),
                meta_wait={},
            ),
            "中文源未回就放行早停，会丢中文标题",
        )

    def test_cn_wait_budget_expires_then_allows(self) -> None:
        """中文源迟迟不回也不能无限等（iqqtv 搜无结果可拖 12~20s）。"""
        import time

        self.assertGreater(E._CN_WAIT_BUDGET_SEC, 0)
        self.assertLessEqual(E._CN_WAIT_BUDGET_SEC, 6.0)
        sid = self._cn_source_id()
        batch = [{"id": sid}, {"id": "dmm"}]
        w: dict = {}
        self.assertFalse(
            E._may_early_stop(
                self._detail(),
                ["no_zh_title"],
                code=_CODE,
                batch=batch,
                finished=set(),
                meta_wait=w,
            )
        )
        self.assertIn("cn_since", w)
        time.sleep(float(E._CN_WAIT_BUDGET_SEC) + 0.05)
        self.assertTrue(
            E._may_early_stop(
                self._detail(),
                ["no_zh_title"],
                code=_CODE,
                batch=batch,
                finished=set(),
                meta_wait=w,
            ),
            "中文源预算用尽应放行早停",
        )

    def test_no_zh_title_releases_after_cn_sources_done(self) -> None:
        """中文源全跑完 → **放行**早停 —— 这就是相对旧行为的净收益。"""
        sid = self._cn_source_id()
        batch = [{"id": sid}, {"id": "dmm"}]
        self.assertTrue(
            E._may_early_stop(
                self._detail(),
                ["no_zh_title"],
                code=_CODE,
                batch=batch,
                finished={sid},
                meta_wait={},
            ),
            "中文源已全部结束，标题仍非中文就该放行（否则等到 dmm 超时也一样）",
        )

    def test_gap_field_priority_knows_no_zh_title(self) -> None:
        """缺中文标题与「标题太薄」同源 → 都要提权 title 字段源。"""
        self.assertEqual(
            E._GAP_FIELD_PRIORITY_KEYS.get("no_zh_title"), ("title",)
        )


if __name__ == "__main__":
    unittest.main()
