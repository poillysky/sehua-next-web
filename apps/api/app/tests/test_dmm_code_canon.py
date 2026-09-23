# -*- coding: utf-8 -*-
"""DMM CID / 番号基号规范化。"""

from __future__ import annotations

import unittest

from app.scrape_details.dmm import _dmm_base_code, guess_dmm_cids


class DmmCodeCanonTests(unittest.TestCase):
    def test_strip_disc_suffix(self) -> None:
        self.assertEqual(_dmm_base_code("IPZZ-599C"), "IPZZ-599")
        self.assertEqual(_dmm_base_code("SSNI-123A"), "SSNI-123")

    def test_pad_and_glue(self) -> None:
        # pad=0 保留源串位数；CID 构造时再 int→zfill(5)
        self.assertEqual(_dmm_base_code("SSNI-015"), "SSNI-015")
        self.assertEqual(_dmm_base_code("ssni00123"), "SSNI-00123")
        self.assertIn("ssni00015", guess_dmm_cids("SSNI-015"))
        self.assertIn("ssni00123", guess_dmm_cids("ssni00123"))

    def test_cid_from_suffix_code(self) -> None:
        cids = guess_dmm_cids("IPZZ-599C")
        self.assertTrue(cids)
        self.assertTrue(any(c.endswith("ipzz00599") for c in cids))

    def test_short_serial_ok(self) -> None:
        cids = guess_dmm_cids("SSNI-1")
        self.assertIn("ssni00001", cids)


if __name__ == "__main__":
    unittest.main()
