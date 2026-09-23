# -*- coding: utf-8 -*-
"""7MMTV 番号候选与详情 href 挑选。"""

from __future__ import annotations

import unittest

from app.scrape_details.sevenmmtv import (
    pick_sevenmmtv_detail_href,
    sevenmmtv_code_candidates,
)


class SevenmmtvCodeCandidatesTests(unittest.TestCase):
    def test_peel_board(self) -> None:
        cands = sevenmmtv_code_candidates("259LUXU-001")
        self.assertIn("259LUXU-001", cands)
        self.assertIn("LUXU-001", cands)

    def test_fc2_bare_id(self) -> None:
        cands = sevenmmtv_code_candidates("FC2-976194")
        self.assertIn("976194", cands)
        self.assertTrue(any("PPV" in c.upper() or "ppv" in c for c in cands))

    def test_date6(self) -> None:
        cands = sevenmmtv_code_candidates("1PON-062014-830")
        self.assertIn("062014_830", cands)
        self.assertTrue(any("1pondo" in c.lower() for c in cands))


class SevenmmtvPickHrefTests(unittest.TestCase):
    def test_board_prefix_slug(self) -> None:
        html = (
            '<a href="https://7mmtv.sx/zh/amateurjav_content/20041/328HMDN-332.html">'
            "x</a>"
        )
        href = pick_sevenmmtv_detail_href(html, "HMDN-332")
        self.assertIn("328HMDN-332", href)

    def test_fc2_ppv_slug(self) -> None:
        html = (
            '<a href="https://7mmtv.sx/zh/uncensored_content/12004/fc2-ppv-976194.html">'
            "x</a>"
        )
        href = pick_sevenmmtv_detail_href(html, "FC2-976194")
        self.assertIn("fc2-ppv-976194", href)

    def test_prefer_censored_over_reducing(self) -> None:
        html = """
        <a href="/zh/reducing-mosaic_content/1/SSIS-001.html">a</a>
        <a href="/zh/censored_content/2/SSIS-001.html">b</a>
        """
        href = pick_sevenmmtv_detail_href(html, "SSIS-001")
        self.assertIn("censored_content", href)

    def test_reject_content_html_without_code(self) -> None:
        html = '<a href="/zh/amateur_content/117703/content.html">x</a>'
        self.assertEqual(pick_sevenmmtv_detail_href(html, "MDSR-0002"), "")


if __name__ == "__main__":
    unittest.main()
