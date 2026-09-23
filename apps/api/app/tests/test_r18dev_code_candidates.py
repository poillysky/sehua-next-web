# -*- coding: utf-8 -*-
"""R18.dev 番号候选与详情匹配。"""

from __future__ import annotations

import unittest

from app.scrape_details.r18dev import (
    _r18_detail_matches_code,
    r18dev_code_candidates,
)


class R18devCodeCandidatesTests(unittest.TestCase):
    def test_peel_board(self) -> None:
        cands = r18dev_code_candidates("259LUXU-001")
        self.assertIn("259LUXU-001", cands)
        self.assertIn("LUXU-001", cands)

    def test_pad(self) -> None:
        cands = r18dev_code_candidates("SONE-15")
        self.assertTrue(any(c.endswith("-015") or c.endswith("-0015") for c in cands))


class R18devMatchTests(unittest.TestCase):
    def test_reject_empty_for_board_code(self) -> None:
        self.assertFalse(_r18_detail_matches_code({}, "259LUXU-001"))
        self.assertFalse(_r18_detail_matches_code({"content_id": None}, "259LUXU-001"))

    def test_dvd_code_equiv(self) -> None:
        self.assertTrue(
            _r18_detail_matches_code({"dvd_id": "SSIS-001"}, "SSIS-001")
        )
        self.assertTrue(
            _r18_detail_matches_code({"dvd_id": "SONE-015"}, "SONE-15")
        )

    def test_content_id_series(self) -> None:
        self.assertTrue(
            _r18_detail_matches_code({"content_id": "ssis00001"}, "SSIS-001")
        )
        self.assertFalse(
            _r18_detail_matches_code({"content_id": "sone00105"}, "SONE-015")
        )

    def test_board_peel_content_id(self) -> None:
        self.assertTrue(
            _r18_detail_matches_code({"content_id": "luxu00001"}, "259LUXU-001")
        )


if __name__ == "__main__":
    unittest.main()
