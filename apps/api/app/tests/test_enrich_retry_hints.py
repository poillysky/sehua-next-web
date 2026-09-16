"""有界重试（封面 / 源故障降级）的语义锁。

修的是两个此前被静默吞掉的问题：

① **封面永久失败的番号没有重试上限**。NFO 已写好、只差海报时本地缺口恒为
   `no_local`，于是每轮增量都重新入队、把全部源再抓一遍，而且永远清不掉。
② **「源挂了」与「源没有这条番号」没区分**。两者此前都只落进 `errors` 字符串，
   高优先源瞬时抖动会静默退化为低优先源的值，之后再也不会回头补抓。

修法：队列表 `enrich_retry_hint` 记「本该更好但没拿到」的番号（**有界**），
达到上限后 giveup=True → 增量队列不再自动入队；覆盖模式重扫可解除。
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.scrap_library import enrich as E


class SrcRetryItemTest(unittest.TestCase):
    """源故障补抓项的契约：必须能定位目录、并且允许覆盖写回。"""

    def test_builds_from_hint(self):
        item = E._src_retry_item(
            {"code": "abc-001", "itemId": "日本有码/ABC/ABC-001"}, region="japan_censored"
        )
        assert item is not None
        self.assertEqual(item["code"], "ABC-001")
        self.assertEqual(item["relPath"], "日本有码/ABC/ABC-001")
        self.assertEqual(item["retryKind"], E._RETRY_KIND_SRC_DOWN)
        self.assertEqual(item["gaps"], list(E._ENRICH_KINDS))
        # 关键：不带 overwrite 的话 `merge_nfo_with_detail` 只补空字段，
        # 之前被低优先源写死的差字段永远修不回来 → 补抓等于白跑
        self.assertTrue(item["overwrite"])

    def test_relpath_only_still_usable(self):
        item = E._src_retry_item(
            {"code": "ABC-001", "relPath": "日本有码/ABC/ABC-001"},
            region="japan_censored",
        )
        assert item is not None
        self.assertEqual(item["itemId"], "日本有码/ABC/ABC-001")

    def test_missing_path_is_dropped(self):
        self.assertIsNone(E._src_retry_item({"code": "ABC-001"}, region="r"))
        self.assertIsNone(E._src_retry_item({"itemId": "x"}, region="r"))


class ClassifySourceFailureTest(unittest.TestCase):
    """只有 down 值得补抓；miss 说明源侧确实没这条，重抓纯属浪费出站槽。"""

    def test_not_found_is_miss(self):
        for msg in ("未找到", "搜索无结果", "番号格式无效", "无法解析"):
            with self.subTest(msg=msg):
                # 最后一条是未知错误 → 保守按 down（可重试），不在这里断言
                if msg == "无法解析":
                    continue
                self.assertEqual(E._classify_source_failure(RuntimeError(msg)), "miss")

    def test_timeout_and_network_are_down(self):
        for msg in ("timeout:20s", "请求失败: connection reset", "搜索无响应", "页面过短"):
            with self.subTest(msg=msg):
                self.assertEqual(E._classify_source_failure(RuntimeError(msg)), "down")

    def test_rejected_is_miss(self):
        """源页面拿到了但不是这条番号 → 源侧没有，不该记成源故障。"""
        self.assertEqual(
            E._classify_source_failure(RuntimeError("rejected:别的标题")), "miss"
        )

    def test_http_status_code_wins(self):
        e404 = RuntimeError("boom")
        e404.status_code = 404  # type: ignore[attr-defined]
        e503 = RuntimeError("boom")
        e503.status_code = 503  # type: ignore[attr-defined]
        self.assertEqual(E._classify_source_failure(e404), "miss")
        self.assertEqual(E._classify_source_failure(e503), "down")

    def test_cancelled_is_its_own_kind(self):
        """早停/暂停被主动放弃的源不是「源故障」，否则每次早停都会挂上补抓标记。"""

        class OutboundCancelled(Exception):
            pass

        self.assertEqual(E._classify_source_failure(OutboundCancelled("x")), "cancelled")


class RetryCapTest(unittest.TestCase):
    def test_cap_reached_flags_giveup(self):
        cap = E._COVER_RETRY_MAX
        n, giveup = E._retry_next_state(0, cap=cap)
        self.assertEqual((n, giveup), (1, False))
        n, giveup = E._retry_next_state(cap - 1, cap=cap)
        self.assertEqual((n, giveup), (cap, True))

    def test_src_down_cap_is_smaller_than_cover(self):
        """源故障更可能是自己恢复的，重试窗口应更短。"""
        self.assertLess(E._SRC_DOWN_RETRY_MAX, E._COVER_RETRY_MAX)


class CoverOnlyGapsTest(unittest.TestCase):
    def test_cover_only(self):
        self.assertTrue(E._is_cover_only_gaps(["no_local"]))
        self.assertTrue(E._is_cover_only_gaps(["no_local", "no_media"]))

    def test_mixed_gaps_not_cover_only(self):
        """同时缺剧情/女优 → 不能放弃封面重试，否则等于把半成品永久钉死。"""
        self.assertFalse(E._is_cover_only_gaps(["no_local", "no_plot"]))
        self.assertFalse(E._is_cover_only_gaps(["no_local", "no_actress"]))

    def test_empty_is_false(self):
        self.assertFalse(E._is_cover_only_gaps([]))
        self.assertFalse(E._is_cover_only_gaps(None))


class GiveupSkipTest(unittest.TestCase):
    def test_skip_only_cover_only_rows_from_giveup_set(self):
        codes = {"ABC-001"}
        self.assertTrue(
            E._should_skip_for_giveup(
                code_u="ABC-001", gaps=["no_local"], giveup_codes=codes
            )
        )
        self.assertFalse(
            E._should_skip_for_giveup(
                code_u="ABC-001", gaps=["no_plot"], giveup_codes=codes
            )
        )
        self.assertFalse(
            E._should_skip_for_giveup(
                code_u="XYZ-009", gaps=["no_local"], giveup_codes=codes
            )
        )

    def test_shell_rows_with_all_gaps_are_not_skipped(self):
        """骨架空壳的 gaps 是全集，绝不能被封面放弃标记误杀。"""
        self.assertFalse(
            E._should_skip_for_giveup(
                code_u="ABC-001",
                gaps=list(E._ENRICH_KINDS),
                giveup_codes={"ABC-001"},
            )
        )


class NoteRetryHintsTest(unittest.TestCase):
    """`_note_retry_hints` 的调用矩阵（用 mock 隔离 DB）。"""

    def _calls(self, one: dict, row: dict | None = None) -> list[dict]:
        with mock.patch.object(
            E, "_retry_hint_note", return_value=(1, False)
        ) as note, mock.patch.object(E, "_push_log"):
            E._note_retry_hints(
                region="japan_censored",
                code="ABC-001",
                row=row or {"itemId": "日本有码/ABC/ABC-001", "rel_path": "日本有码/ABC/ABC-001"},
                one=one,
            )
            return [c.kwargs for c in note.call_args_list]

    def test_cover_fail_with_cover_only_gaps_counts(self):
        calls = self._calls(
            {"coverFail": "all_failed", "localCoverOk": False, "gapsAfter": ["no_local"]}
        )
        cover = [c for c in calls if c["kind"] == E._RETRY_KIND_COVER][0]
        self.assertTrue(cover["need"])
        self.assertEqual(cover["error"], "all_failed")
        self.assertEqual(cover["cap"], E._COVER_RETRY_MAX)
        # 无降级 → 源故障提示清零
        src = [c for c in calls if c["kind"] == E._RETRY_KIND_SRC_DOWN][0]
        self.assertFalse(src["need"])

    def test_cover_fail_with_other_gaps_does_not_count(self):
        """还缺剧情 → 既不累计也不放弃（只有「仅剩封面」才算封面型失败）。"""
        calls = self._calls(
            {
                "coverFail": "all_failed",
                "localCoverOk": False,
                "gapsAfter": ["no_local", "no_plot"],
            }
        )
        cover = [c for c in calls if c["kind"] == E._RETRY_KIND_COVER][0]
        self.assertFalse(cover["need"])

    def test_cover_ok_clears_hint(self):
        calls = self._calls({"localCoverOk": True, "ok": True})
        cover = [c for c in calls if c["kind"] == E._RETRY_KIND_COVER][0]
        self.assertFalse(cover["need"])

    def test_degraded_success_enters_recheck_queue(self):
        calls = self._calls(
            {
                "ok": True,
                "localCoverOk": True,
                "degradedByDown": ["javdb", "airav"],
            }
        )
        src = [c for c in calls if c["kind"] == E._RETRY_KIND_SRC_DOWN][0]
        self.assertTrue(src["need"])
        self.assertEqual(src["error"], "javdb,airav")
        self.assertEqual(src["cap"], E._SRC_DOWN_RETRY_MAX)

    def test_failed_row_does_not_enter_recheck(self):
        """失败的行本来就会按本地缺口重新入队，不需要再挂源故障提示。"""
        calls = self._calls(
            {"ok": False, "localCoverOk": True, "degradedByDown": ["javdb"]}
        )
        src = [c for c in calls if c["kind"] == E._RETRY_KIND_SRC_DOWN][0]
        self.assertFalse(src["need"])

    def test_empty_code_is_noop(self):
        with mock.patch.object(E, "_retry_hint_note") as note:
            E._note_retry_hints(region="japan_censored", code="", row={}, one={})
            note.assert_not_called()


if __name__ == "__main__":
    unittest.main()
