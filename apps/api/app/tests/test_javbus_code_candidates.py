# -*- coding: utf-8 -*-
"""JavBus 详情路径候选：有码补零 + 无码 date6 slug。"""

from __future__ import annotations

import unittest

from app.scrape_details.common import javbus_code_candidates


class JavbusCodeCandidatesTests(unittest.TestCase):
    def test_censored_pad_variants(self) -> None:
        cands = javbus_code_candidates("SONE-15")
        self.assertIn("SONE-015", cands)
        self.assertIn("SONE-15", cands)
        # 过长补零也能回到三位等价形
        cands2 = javbus_code_candidates("NAMH-0028")
        self.assertIn("NAMH-028", cands2)
        self.assertIn("NAMH-28", cands2)

    def test_date6_1pondo_slugs(self) -> None:
        cands = javbus_code_candidates("1PON-062014-830")
        self.assertIn("062014_830", cands)
        self.assertIn("1pondo-062014_830", cands)
        self.assertIn("1PON-062014-830", cands)

    def test_date6_carib_slugs(self) -> None:
        cands = javbus_code_candidates("CARIB-011317-002")
        self.assertIn("011317-002", cands)
        self.assertIn("caribbeancom-011317-002", cands)
        self.assertIn("CARIB-011317-002", cands)

    def test_heyzo_pad4(self) -> None:
        cands = javbus_code_candidates("HEYZO-34")
        self.assertIn("HEYZO-0034", cands)
        self.assertIn("HEYZO-34", cands)


if __name__ == "__main__":
    unittest.main()
