# -*- coding: utf-8 -*-
"""软成功判定：缺女优/片商；封面/空标题硬失败；中文标题不算软成功。"""

from __future__ import annotations

import unittest

from app.scrap_library import enrich as E


class EnrichSoftSuccessTests(unittest.TestCase):
    def test_block_and_soft_gaps(self) -> None:
        self.assertEqual(set(E._SUCCESS_BLOCK_GAPS), {"no_local", "thin_title"})
        self.assertEqual(
            set(E._SOFT_SUCCESS_GAPS),
            {"no_actress", "no_studio"},
        )
        self.assertNotIn("no_zh_title", E._SOFT_SUCCESS_GAPS)
        self.assertNotIn("no_plot", E._SOFT_SUCCESS_GAPS)
        self.assertNotIn("no_media", E._SOFT_SUCCESS_GAPS)
        self.assertNotIn("no_local", E._SOFT_SUCCESS_GAPS)

    def test_classify_disk_gaps(self) -> None:
        self.assertEqual(E._classify_disk_gaps([]), "done")
        self.assertEqual(E._classify_disk_gaps(["no_plot"]), "done")
        self.assertEqual(E._classify_disk_gaps(["no_media"]), "done")
        self.assertEqual(E._classify_disk_gaps(["no_actress"]), "soft")
        self.assertEqual(E._classify_disk_gaps(["no_studio", "no_plot"]), "soft")
        self.assertEqual(E._classify_disk_gaps(["no_zh_title"]), "done")
        self.assertEqual(E._classify_disk_gaps(["no_zh_title", "no_actress"]), "soft")
        self.assertEqual(E._classify_disk_gaps(["no_local"]), "fail")
        self.assertEqual(E._classify_disk_gaps(["thin_title", "no_plot"]), "fail")

    def test_title_lacks_zh(self) -> None:
        self.assertTrue(E._title_lacks_zh("YSN-661 妹を育成中～両親も", "YSN-661"))
        self.assertTrue(E._title_lacks_zh("Hello World Title", "ABC-001"))
        self.assertFalse(E._title_lacks_zh("YSN-664 被头脑不好但性慾强的新义姐饲养着。", "YSN-664"))
        self.assertFalse(E._title_lacks_zh("", "ABC-001"))
        self.assertFalse(E._title_lacks_zh("ABC-001", "ABC-001"))

    def test_soft_remain_error(self) -> None:
        self.assertFalse(E._is_soft_remain_error("仍缺:剧情"))
        self.assertFalse(E._is_soft_remain_error("仍缺:剧情 · 女优"))
        self.assertTrue(E._is_soft_remain_error("次成功 · 仍缺:女优"))
        self.assertTrue(E._is_soft_remain_error("软成功 · 仍缺:片商"))
        self.assertTrue(E._is_soft_remain_error("仍缺:女优 · 片商"))
        self.assertFalse(E._is_soft_remain_error("软成功 · 仍缺:中文标题"))
        self.assertFalse(E._is_soft_remain_error("仍缺:中文标题 · 女优"))
        self.assertFalse(E._is_soft_remain_error("仍缺:封面"))
        self.assertFalse(E._is_soft_remain_error("仍缺:标题"))
        self.assertFalse(E._is_soft_remain_error("仍缺:封面 · 剧情"))
        self.assertFalse(E._is_soft_remain_error("封面失败:封面空图"))

    def test_format_and_detect_soft_ok(self) -> None:
        msg = E._format_soft_ok_error(["女优", "片商"])
        self.assertTrue(msg.startswith("软成功"))
        self.assertTrue(E._is_soft_ok_error(msg))
        self.assertTrue(E._is_soft_ok_error("次成功 · 仍缺:女优"))
        self.assertEqual(
            E._strip_soft_ok_prefix("软成功 · 仍缺:女优"), "仍缺:女优"
        )
        msg2 = E._format_soft_ok_error(["女优"])
        self.assertIn("女优", msg2)

    def test_queue_counts_split_soft(self) -> None:
        rows = [
            {"status": "done", "partialOk": False, "error": ""},
            {"status": "done", "partialOk": True, "error": "软成功 · 仍缺:女优"},
            {"status": "done", "error": "次成功 · 仍缺:片商"},
            {"status": "done", "partialOk": False, "error": ""},
            {"status": "fail", "error": "仍缺:封面"},
            {"status": "pending"},
        ]
        c = E._queue_counts_of(rows)
        self.assertEqual(c["done"], 2)
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

    def test_normalize_helper_exists(self) -> None:
        self.assertTrue(callable(E._queue_log_normalize_soft_to_full_success))
        self.assertEqual(E._SOFT_PROMOTE_RULE_VER, 5)


if __name__ == "__main__":
    unittest.main()
