# -*- coding: utf-8 -*-
"""MGStage 搜索结果选链：素人板号等价。"""

from __future__ import annotations

import unittest

from app.scrape_details.mgstage import _pick_detail_href


class MgstagePickHrefTests(unittest.TestCase):
    def test_board_prefix_equiv(self) -> None:
        html = (
            '<a href="/product/product_detail/259LUXU-001/">x</a>'
            '<a href="/product/product_detail/OTHER-001/">y</a>'
        )
        self.assertEqual(
            _pick_detail_href(html, "LUXU-001"),
            "/product/product_detail/259LUXU-001/",
        )

    def test_exact(self) -> None:
        html = '<a href="/product/product_detail/ABP-001/">x</a>'
        self.assertEqual(
            _pick_detail_href(html, "ABP-001"),
            "/product/product_detail/ABP-001/",
        )

    def test_no_false_first(self) -> None:
        html = (
            '<a href="/product/product_detail/WRONG-999/">a</a>'
            '<a href="/product/product_detail/ABP-001/">b</a>'
        )
        self.assertEqual(
            _pick_detail_href(html, "ABP-001"),
            "/product/product_detail/ABP-001/",
        )


if __name__ == "__main__":
    unittest.main()
