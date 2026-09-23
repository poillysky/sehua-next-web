# -*- coding: utf-8 -*-
"""AirAV.io 番号候选与标题匹配。"""

from __future__ import annotations

import unittest

from app.scrape_details.airav_io import (
    airav_detail_code_ok,
    airav_io_code_candidates,
    match_airav_number,
    pick_airav_hid_from_search,
)


class AiravIoCodeCandidatesTests(unittest.TestCase):
    def test_fc2_ppv(self) -> None:
        cands = airav_io_code_candidates("FC2-976194")
        self.assertTrue(any("PPV" in c.upper() for c in cands))

    def test_date6(self) -> None:
        cands = airav_io_code_candidates("1PON-062014-830")
        self.assertIn("062014_830", cands)
        self.assertTrue(any("1pondo" in c.lower() for c in cands))

    def test_peel_board(self) -> None:
        cands = airav_io_code_candidates("259LUXU-001")
        self.assertIn("LUXU-001", cands)

    def test_match_date6_title(self) -> None:
        self.assertTrue(
            match_airav_number("1pondo_062014_830 タイトル", "1PON-062014-830")
        )

    def test_pick_hid_fc2(self) -> None:
        html = """
        <div class="col oneVideo">
          <a href="/cn/video?hid=1">x</a>
          <h5>FC2-PPV-976194 テスト</h5>
        </div></div>
        """
        href = pick_airav_hid_from_search(html, "FC2-976194")
        self.assertIn("hid=1", href or "")

    def test_detail_ok_date6(self) -> None:
        html = "番号：<span>062014_830</span><h1>062014_830 xxx</h1>"
        self.assertTrue(airav_detail_code_ok(html, "1PON-062014-830"))


if __name__ == "__main__":
    unittest.main()
