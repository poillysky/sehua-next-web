# -*- coding: utf-8 -*-
"""NJAV / 123AV 番号候选。"""

from __future__ import annotations

import unittest

from app.scrape_details.njav import njav_code_candidates, _path_slugs, _pick_detail_href


class NjavCodeCandidatesTests(unittest.TestCase):
    def test_fc2_ppv(self) -> None:
        cands = njav_code_candidates("FC2-976194")
        self.assertTrue(any("PPV" in c.upper() for c in cands))
        paths = _path_slugs("FC2-976194")
        self.assertIn("fc2-ppv-976194", paths)

    def test_board_expand(self) -> None:
        cands = njav_code_candidates("HMDN-332")
        self.assertIn("HMDN-332", cands)
        self.assertTrue(any(c.upper().startswith("328HMDN") for c in cands))
        paths = _path_slugs("HMDN-332")
        self.assertIn("328hmdn-332", paths)

    def test_date6(self) -> None:
        cands = njav_code_candidates("1PON-062014-830")
        self.assertIn("062014_830", cands)
        paths = _path_slugs("1PON-062014-830")
        self.assertIn("062014_830", paths)

    def test_pick_fc2_from_search(self) -> None:
        html = """
        <a href="/ja/v/fc2-ppv-976194">x</a>
        <a href="/ja/v/fc2-ppv-2257439">y</a>
        """
        href = _pick_detail_href(html, "FC2-976194")
        self.assertIn("fc2-ppv-976194", href)

    def test_pick_board(self) -> None:
        html = """
        <a href="/ja/v/328hmdn-332">x</a>
        <a href="/ja/v/259luxu-332">y</a>
        """
        href = _pick_detail_href(html, "HMDN-332")
        self.assertIn("328hmdn-332", href)


if __name__ == "__main__":
    unittest.main()
