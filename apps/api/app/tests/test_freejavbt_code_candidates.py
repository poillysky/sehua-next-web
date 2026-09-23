# -*- coding: utf-8 -*-
"""FreeJavBT 番号候选（素人剥板号）。"""

from __future__ import annotations

import unittest

from app.scrape_details.freejavbt import freejavbt_code_candidates


class FreejavbtCodeCandidatesTests(unittest.TestCase):
    def test_peel_board(self) -> None:
        cands = freejavbt_code_candidates("259LUXU-001")
        self.assertIn("259LUXU-001", cands)
        self.assertIn("LUXU-001", cands)

    def test_fc2(self) -> None:
        cands = freejavbt_code_candidates("FC2-976194")
        self.assertTrue(any(c.startswith("FC2-PPV-") for c in cands))

    def test_date6(self) -> None:
        cands = freejavbt_code_candidates("1PON-062014-830")
        self.assertIn("062014_830", cands)
        self.assertTrue(any("1pondo" in c.lower() for c in cands))

    def test_add_board(self) -> None:
        cands = freejavbt_code_candidates("HMDN-332")
        self.assertTrue(any(c.upper().startswith("328HMDN") for c in cands))


if __name__ == "__main__":
    unittest.main()
