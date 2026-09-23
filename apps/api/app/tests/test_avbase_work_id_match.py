# -*- coding: utf-8 -*-
"""AVBase work_id 匹配。"""

from __future__ import annotations

import unittest

from app.scrape_details.avbase import match_avbase_work_id


class AvbaseWorkIdMatchTests(unittest.TestCase):
    def test_exact_and_pad(self) -> None:
        self.assertTrue(match_avbase_work_id("SSIS-001", "SSIS-001"))
        self.assertTrue(match_avbase_work_id("SONE-015", "SONE-15"))

    def test_amateur_board(self) -> None:
        self.assertTrue(match_avbase_work_id("LUXU-001", "259LUXU-001"))

    def test_prefixed_foreign_id_rejected(self) -> None:
        # 搜索噪声：secondface:SSIS-001 不得当成正牌 SSIS-001
        self.assertFalse(match_avbase_work_id("secondface:SSIS-001", "SSIS-001"))


if __name__ == "__main__":
    unittest.main()
