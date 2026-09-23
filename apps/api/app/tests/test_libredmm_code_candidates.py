# -*- coding: utf-8 -*-
"""LibreDMM 番号候选 + std 分集剥壳回归。"""

from __future__ import annotations

import unittest

from app.scrape_details.libredmm import libredmm_code_candidates
from app.search.av import parse_maker_code


class LibreDmmCandidatesTests(unittest.TestCase):
    def test_strip_disc_suffix(self) -> None:
        cands = libredmm_code_candidates("IPZZ-599C")
        self.assertIn("IPZZ-599", cands)

    def test_pad_variants(self) -> None:
        cands = libredmm_code_candidates("SONE-15")
        self.assertIn("SONE-15", cands)
        self.assertIn("SONE-015", cands)

    def test_amateur_digit_head(self) -> None:
        cands = libredmm_code_candidates("259LUXU-001")
        self.assertIn("LUXU-001", cands)
        self.assertTrue(any(c.startswith("259LUXU") for c in cands))

    def test_add_board(self) -> None:
        cands = libredmm_code_candidates("LUXU-001")
        self.assertTrue(any(c.startswith("259LUXU") for c in cands))
        cands2 = libredmm_code_candidates("HMDN-332")
        self.assertTrue(any(c.startswith("328HMDN") for c in cands2))


class ParseStdEpisodeStripTests(unittest.TestCase):
    def test_short_serial_not_stripped(self) -> None:
        p = parse_maker_code("SONE-15")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.canonical, "SONE-15")

    def test_episode_suffix_still_stripped(self) -> None:
        p = parse_maker_code("MDSR-0002-EP3")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.canonical, "MDSR-0002")
        p2 = parse_maker_code("MDSR-0002-4")
        self.assertIsNotNone(p2)
        assert p2 is not None
        self.assertEqual(p2.canonical, "MDSR-0002")


if __name__ == "__main__":
    unittest.main()
