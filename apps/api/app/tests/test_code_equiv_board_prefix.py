# -*- coding: utf-8 -*-
"""code_equiv：素人板号 / pad / 国产前缀保留。"""

from __future__ import annotations

import unittest

from app.scrape_details.common import code_equiv


class CodeEquivBoardPrefixTests(unittest.TestCase):
    def test_amateur_board_prefix(self) -> None:
        self.assertTrue(code_equiv("259LUXU-001", "LUXU-001"))
        self.assertTrue(code_equiv("259LUXU-001", "luxu-001"))

    def test_pad_still_ok(self) -> None:
        self.assertTrue(code_equiv("SONE-15", "SONE-015"))
        self.assertTrue(code_equiv("NAMH-0028", "NAMH-028"))

    def test_china_digit_prefix_kept(self) -> None:
        # 91CM 不得剥成 CM
        self.assertFalse(code_equiv("91CM-001", "CM-001"))

    def test_digit_continuation_rejected(self) -> None:
        self.assertFalse(code_equiv("ABF-005", "ABF0051"))


if __name__ == "__main__":
    unittest.main()
