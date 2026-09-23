# -*- coding: utf-8 -*-
"""欧美点分日候选：YYYY ↔ YY（不依赖厂牌白名单）。"""

from __future__ import annotations

import unittest

from app.scrape_details.common import western_code_candidates


class WesternCodeCandidatesTests(unittest.TestCase):
    def test_yyyy_to_yy(self) -> None:
        cands = western_code_candidates("BLACKED.2026.01.15")
        self.assertIn("BLACKED.2026.01.15", cands)
        self.assertIn("BLACKED.26.01.15", cands)

    def test_yy_to_yyyy(self) -> None:
        cands = western_code_candidates("BrazzersExxtra.26.07.09")
        self.assertIn("BrazzersExxtra.26.07.09", cands)
        self.assertIn("BrazzersExxtra.2026.07.09", cands)

    def test_unknown_studio_welive(self) -> None:
        cands = western_code_candidates("WeLiveTogether.12.02.23")
        self.assertIn("WeLiveTogether.12.02.23", cands)
        self.assertIn("WeLiveTogether.2012.02.23", cands)


if __name__ == "__main__":
    unittest.main()
