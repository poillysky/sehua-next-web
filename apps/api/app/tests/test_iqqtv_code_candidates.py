# -*- coding: utf-8 -*-
"""iQQTV 番号候选与标题匹配。"""

from __future__ import annotations

import unittest

from app.scrape_details.iqqtv import (
    get_iqqtv_real_url,
    iqqtv_code_candidates,
    match_iqqtv_number,
)


class IqqtvCodeCandidatesTests(unittest.TestCase):
    def test_peel_board(self) -> None:
        cands = iqqtv_code_candidates("259LUXU-001")
        self.assertIn("259LUXU-001", cands)
        self.assertIn("LUXU-001", cands)

    def test_fc2_variants(self) -> None:
        cands = iqqtv_code_candidates("FC2-976194")
        self.assertTrue(any("PPV" in c.upper() for c in cands))
        self.assertIn("976194", cands)

    def test_date6(self) -> None:
        cands = iqqtv_code_candidates("1PON-062014-830")
        self.assertIn("062014_830", cands)
        self.assertTrue(any("1pondo" in c.lower() for c in cands))


class IqqtvMatchTests(unittest.TestCase):
    def test_board_equiv(self) -> None:
        self.assertTrue(match_iqqtv_number("高贵正妹TV LUXU-001", "259LUXU-001"))

    def test_fc2_ppv(self) -> None:
        self.assertTrue(
            match_iqqtv_number("直播 FC2-PPV-4564537", "FC2-4564537")
        )
        self.assertTrue(
            match_iqqtv_number("直播 FC2PPV-4977720", "FC2-4977720")
        )

    def test_date6_title(self) -> None:
        self.assertTrue(
            match_iqqtv_number(
                "可爱的羞耻性爱 _1pondo_062014_830", "1PON-062014-830"
            )
        )

    def test_reject_prefix_false_positive(self) -> None:
        self.assertFalse(match_iqqtv_number("ABF-002 标题", "BF-002"))

    def test_pick_url(self) -> None:
        html = """
        <span class="title"><a href="/cn/player.php?uuid=abc&cat=19"
          title="高贵正妹TV LUXU-001">x</a></span>
        """
        href = get_iqqtv_real_url(html, "259LUXU-001")
        self.assertIn("uuid=abc", href)


if __name__ == "__main__":
    unittest.main()
