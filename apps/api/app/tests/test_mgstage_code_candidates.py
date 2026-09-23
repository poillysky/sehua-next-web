# -*- coding: utf-8 -*-
"""MGStage 番号候选（素人板号）。"""

from __future__ import annotations

import unittest

from app.scrape_details.mgstage import mgstage_code_candidates


class MgstageCodeCandidatesTests(unittest.TestCase):
    def test_luxu_gets_board(self) -> None:
        cands = mgstage_code_candidates("LUXU-001")
        self.assertIn("LUXU-001", cands)
        self.assertTrue(any(c.startswith("259LUXU") for c in cands), cands)

    def test_board_kept(self) -> None:
        cands = mgstage_code_candidates("259LUXU-001")
        self.assertIn("259LUXU-001", cands)
        self.assertIn("LUXU-001", cands)

    def test_abp_no_digit_board(self) -> None:
        cands = mgstage_code_candidates("ABP-001")
        self.assertIn("ABP-001", cands)
        self.assertFalse(any(c[:1].isdigit() for c in cands if "-" in c))


if __name__ == "__main__":
    unittest.main()
