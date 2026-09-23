# -*- coding: utf-8 -*-
"""MissAV 番号候选 / 详情校验。"""

from __future__ import annotations

import unittest

from app.scrape_details.miss_av import (
    _is_detail_html,
    _path_codes,
    miss_av_code_candidates,
)


class MissAvCodeCandidatesTests(unittest.TestCase):
    def test_peel_board(self) -> None:
        cands = miss_av_code_candidates("259LUXU-001")
        self.assertIn("259LUXU-001", cands)
        self.assertIn("LUXU-001", cands)
        paths = _path_codes("259LUXU-001")
        self.assertIn("luxu-001", paths)
        self.assertIn("259luxu-001", paths)

    def test_pad(self) -> None:
        cands = miss_av_code_candidates("SONE-15")
        self.assertIn("SONE-015", cands)
        paths = _path_codes("SONE-15")
        self.assertIn("sone-015", paths)

    def test_fc2_ppv_first(self) -> None:
        paths = _path_codes("FC2-976194")
        self.assertEqual(paths[0], "fc2-ppv-976194")

    def test_date6_bare(self) -> None:
        cands = miss_av_code_candidates("1PON-062014-830")
        self.assertIn("062014_830", cands)
        paths = _path_codes("1PON-062014-830")
        self.assertIn("062014_830", paths)


class MissAvDetailHtmlTests(unittest.TestCase):
    def test_board_page_code_equiv(self) -> None:
        html = (
            "<html><head>"
            '<meta property="og:type" content="video.other"/>'
            "</head><body>"
            + ("x" * 6000)
            + "<span>番号:</span><span>LUXU-001</span>"
            "</body></html>"
        )
        self.assertTrue(_is_detail_html(html, "259LUXU-001"))
        self.assertTrue(_is_detail_html(html, "LUXU-001"))
        self.assertFalse(_is_detail_html(html, "SSIS-001"))

    def test_date6_bare_page(self) -> None:
        html = (
            "<html><head>"
            '<meta property="og:type" content="video.other"/>'
            "</head><body>"
            + ("x" * 6000)
            + "<span>番号:</span><span>062014_830</span>"
            "</body></html>"
        )
        self.assertTrue(_is_detail_html(html, "1PON-062014-830"))
        self.assertTrue(_is_detail_html(html, "062014_830"))

    def test_china_mdx_not_short_pad(self) -> None:
        from app.scrape_details.common import code_equiv

        self.assertFalse(code_equiv("MDX-0001", "MDX-001"))
        html = (
            "<html><head>"
            '<meta property="og:type" content="video.other"/>'
            "</head><body>"
            + ("x" * 6000)
            + "<span>番号:</span><span>MDX-001</span>"
            "</body></html>"
        )
        self.assertFalse(_is_detail_html(html, "MDX-0001"))


if __name__ == "__main__":
    unittest.main()
