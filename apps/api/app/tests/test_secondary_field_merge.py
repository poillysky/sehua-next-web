# -*- coding: utf-8 -*-
"""次要字段跨源补齐：series / publisher / trailer / website。"""

from __future__ import annotations

import unittest

from app.scrap_library.enrich_extras import pick_secondary_fields


class SecondaryFieldMergeTests(unittest.TestCase):
    def test_later_source_fills_series_publisher_website(self) -> None:
        details = [
            (
                "airav_io",
                {
                    "title": "测试",
                    "director": "导演A",
                    "runtime": "120",
                    "score": "8.4",
                },
            ),
            (
                "dmm",
                {
                    "series": "もちもちシリーズ",
                    "publisher": "AROMA",
                    "label": "AROMA",
                    "website": "https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=aarm00015/",
                    "trailerUrl": "https://example.com/aarm015.mp4",
                },
            ),
        ]
        out = pick_secondary_fields(details)
        self.assertEqual(out.get("director"), "导演A")
        self.assertEqual(out.get("series"), "もちもちシリーズ")
        self.assertEqual(out.get("publisher"), "AROMA")
        self.assertEqual(out.get("label"), "AROMA")
        self.assertTrue(str(out.get("website") or "").startswith("https://"))
        self.assertTrue(str(out.get("trailer") or "").endswith(".mp4"))

    def test_primary_keeps_existing_series(self) -> None:
        details = [
            ("mgstage", {"series": "系列甲", "publisher": "LABEL1"}),
            ("dmm", {"series": "系列乙", "publisher": "LABEL2"}),
        ]
        out = pick_secondary_fields(details)
        self.assertEqual(out.get("series"), "系列甲")
        self.assertEqual(out.get("publisher"), "LABEL1")


if __name__ == "__main__":
    unittest.main()
