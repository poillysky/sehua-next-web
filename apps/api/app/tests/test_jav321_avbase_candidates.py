# -*- coding: utf-8 -*-
"""Jav321 / AVBase 番号候选。"""

from __future__ import annotations

import unittest

from app.scrape_details.avbase import avbase_code_candidates
from app.scrape_details.jav321 import jav321_code_candidates


class Jav321CandidatesTests(unittest.TestCase):
    def test_pad_and_board(self) -> None:
        cands = jav321_code_candidates("HMDN-332")
        self.assertIn("HMDN-332", cands)
        self.assertTrue(any(c.upper().startswith("328HMDN") for c in cands))

    def test_date6(self) -> None:
        cands = jav321_code_candidates("1PON-062014-830")
        self.assertIn("062014_830", cands)

    def test_fc2(self) -> None:
        cands = jav321_code_candidates("FC2-976194")
        self.assertTrue(any("PPV" in c.upper() for c in cands))


class AvbaseCandidatesTests(unittest.TestCase):
    def test_pad(self) -> None:
        cands = avbase_code_candidates("SONE-15")
        self.assertTrue(any(c.upper() == "SONE-015" for c in cands))

    def test_add_board(self) -> None:
        cands = avbase_code_candidates("LUXU-001")
        self.assertTrue(any(c.upper().startswith("259LUXU") for c in cands))

    def test_date6(self) -> None:
        cands = avbase_code_candidates("1PON-062014-830")
        self.assertIn("062014_830", cands)


if __name__ == "__main__":
    unittest.main()
