# -*- coding: utf-8 -*-
"""软成功判定：仅封面/标题硬失败；其余缺口进软成功。"""

from __future__ import annotations

import unittest

from app.scrap_library import enrich as E


class EnrichSoftSuccessTests(unittest.TestCase):
    def test_block_gaps_only_cover_title(self) -> None:
        self.assertEqual(set(E._SUCCESS_BLOCK_GAPS), {"no_local", "thin_title"})
        self.assertIn("no_plot", E._SOFT_SUCCESS_GAPS)
        self.assertIn("no_actress", E._SOFT_SUCCESS_GAPS)
        self.assertNotIn("no_local", E._SOFT_SUCCESS_GAPS)

    def test_soft_remain_error(self) -> None:
        self.assertTrue(E._is_soft_remain_error("仍缺:剧情"))
        self.assertTrue(E._is_soft_remain_error("仍缺:剧情 · 女优"))
        self.assertTrue(E._is_soft_remain_error("次成功 · 仍缺:女优"))
        self.assertTrue(E._is_soft_remain_error("软成功 · 仍缺:片商"))
        self.assertFalse(E._is_soft_remain_error("仍缺:封面"))
        self.assertFalse(E._is_soft_remain_error("仍缺:标题"))
        self.assertFalse(E._is_soft_remain_error("仍缺:封面 · 剧情"))
        self.assertFalse(E._is_soft_remain_error("封面失败:封面空图"))

    def test_format_and_detect_soft_ok(self) -> None:
        msg = E._format_soft_ok_error(["剧情", "女优"])
        self.assertTrue(msg.startswith("软成功"))
        self.assertTrue(E._is_soft_ok_error(msg))
        self.assertTrue(E._is_soft_ok_error("次成功 · 仍缺:女优"))
        self.assertEqual(
            E._strip_soft_ok_prefix("软成功 · 仍缺:剧情"), "仍缺:剧情"
        )

    def test_queue_counts_split_soft(self) -> None:
        rows = [
            {"status": "done", "partialOk": False, "error": ""},
            {"status": "done", "partialOk": True, "error": "软成功 · 仍缺:剧情"},
            {"status": "done", "error": "次成功 · 仍缺:女优"},
            {"status": "fail", "error": "仍缺:封面"},
            {"status": "pending"},
        ]
        c = E._queue_counts_of(rows)
        self.assertEqual(c["done"], 1)
        self.assertEqual(c["soft"], 2)
        self.assertEqual(c["fail"], 1)
        self.assertEqual(c["pending"], 1)

    def test_progress_includes_soft(self) -> None:
        prog = E._progress_from_queue_counts(
            {"pending": 10, "running": 0, "done": 2, "soft": 3, "fail": 1}
        )
        self.assertEqual(prog["ok"], 5)
        self.assertEqual(prog["failed"], 1)
        self.assertEqual(prog["done"], 6)
        self.assertEqual(prog["total"], 16)


if __name__ == "__main__":
    unittest.main()
