# -*- coding: utf-8 -*-
"""成功/软成功/失败：无封面→失败；有封面无标题→软成功；其余缺失→成功。"""

from __future__ import annotations

import unittest

from app.scrap_library import enrich as E


class EnrichSoftSuccessTests(unittest.TestCase):
    def test_block_and_soft_gaps(self) -> None:
        self.assertEqual(set(E._SUCCESS_BLOCK_GAPS), {"no_local"})
        self.assertEqual(set(E._SOFT_SUCCESS_GAPS), {"thin_title"})
        self.assertNotIn("thin_title", E._SUCCESS_BLOCK_GAPS)
        self.assertNotIn("no_actress", E._SOFT_SUCCESS_GAPS)
        self.assertNotIn("no_studio", E._SOFT_SUCCESS_GAPS)
        self.assertNotIn("no_zh_title", E._SOFT_SUCCESS_GAPS)
        self.assertNotIn("no_plot", E._SOFT_SUCCESS_GAPS)

    def test_classify_disk_gaps(self) -> None:
        self.assertEqual(E._classify_disk_gaps([]), "done")
        self.assertEqual(E._classify_disk_gaps(["no_plot"]), "done")
        self.assertEqual(E._classify_disk_gaps(["no_media"]), "done")
        self.assertEqual(E._classify_disk_gaps(["no_actress"]), "done")
        self.assertEqual(E._classify_disk_gaps(["no_studio"]), "done")
        self.assertEqual(E._classify_disk_gaps(["no_actress", "no_studio"]), "done")
        self.assertEqual(E._classify_disk_gaps(["no_zh_title"]), "done")
        self.assertEqual(E._classify_disk_gaps(["thin_title"]), "soft")
        self.assertEqual(E._classify_disk_gaps(["thin_title", "no_actress"]), "soft")
        self.assertEqual(E._classify_disk_gaps(["no_local"]), "fail")
        self.assertEqual(E._classify_disk_gaps(["no_local", "thin_title"]), "fail")

    def test_soft_remain_error(self) -> None:
        self.assertTrue(E._is_soft_remain_error("软成功 · 仍缺:标题"))
        self.assertTrue(E._is_soft_remain_error("仍缺:标题"))
        self.assertFalse(E._is_soft_remain_error("仍缺:剧情"))
        self.assertFalse(E._is_soft_remain_error("次成功 · 仍缺:女优"))
        self.assertFalse(E._is_soft_remain_error("软成功 · 仍缺:片商"))
        self.assertFalse(E._is_soft_remain_error("仍缺:女优 · 片商"))
        self.assertFalse(E._is_soft_remain_error("仍缺:中文标题"))
        self.assertFalse(E._is_soft_remain_error("仍缺:封面"))
        self.assertFalse(E._is_soft_remain_error("封面失败:封面空图"))

    def test_format_and_detect_soft_ok(self) -> None:
        msg = E._format_soft_ok_error(["标题"])
        self.assertTrue(msg.startswith("软成功"))
        self.assertTrue(E._is_soft_ok_error(msg))
        self.assertTrue(E._is_soft_remain_error(msg))
        self.assertEqual(E._strip_soft_ok_prefix(msg), "仍缺:标题")

    def test_queue_counts_split_soft(self) -> None:
        rows = [
            {"status": "done", "partialOk": False, "error": ""},
            {"status": "done", "partialOk": True, "error": "软成功 · 仍缺:标题"},
            {"status": "done", "error": "软成功 · 仍缺:女优"},
            {"status": "done", "error": "次成功 · 仍缺:片商"},
            {"status": "fail", "error": "仍缺:封面"},
            {"status": "pending"},
        ]
        c = E._queue_counts_of(rows)
        self.assertEqual(c["done"], 3)
        self.assertEqual(c["soft"], 1)
        self.assertEqual(c["fail"], 1)
        self.assertEqual(c["pending"], 1)

    def test_normalize_helper_exists(self) -> None:
        self.assertTrue(callable(E._queue_log_normalize_soft_to_full_success))
        self.assertEqual(E._SOFT_PROMOTE_RULE_VER, 8)


if __name__ == "__main__":
    unittest.main()
