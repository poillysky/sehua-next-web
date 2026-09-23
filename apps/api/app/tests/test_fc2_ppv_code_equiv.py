# -*- coding: utf-8 -*-
"""FC2 / FC2-PPV 番号等价与 MissAV 标题剥壳。"""

from __future__ import annotations

import unittest

from app.scrape_details.common import code_equiv, fc2_slug_variants, parse_fc2_id
from app.scrape_details.miss_av import _parse_title


class Fc2CodeEquivTests(unittest.TestCase):
    def test_parse_and_equiv(self) -> None:
        self.assertEqual(parse_fc2_id("FC2-PPV-976194"), ("976194", "FC2-976194"))
        self.assertEqual(parse_fc2_id("FC2-976194"), ("976194", "FC2-976194"))
        self.assertTrue(code_equiv("FC2-976194", "FC2-PPV-976194"))
        self.assertFalse(code_equiv("FC2-976194", "FC2-976195"))

    def test_slug_variants_prefer_ppv(self) -> None:
        slugs = fc2_slug_variants("FC2-976194")
        self.assertEqual(slugs[0], "fc2-ppv-976194")
        self.assertIn("fc2-976194", slugs)


class MissAvFc2TitleTests(unittest.TestCase):
    def test_strip_ppv_prefix_when_query_is_canon(self) -> None:
        html = (
            '<html><body><h1 class="text-base">'
            "FC2-PPV-976194 美丽温柔的牙医小姐姐中出【完全原创个人拍摄】"
            "</h1>"
            '<meta property="og:type" content="video.other"/>'
            "<span>番号:</span><span>FC2-PPV-976194</span>"
            "FC2-PPV-976194"
            "</body></html>"
        )
        # 目录归一后查询码是 FC2-{n}；旧逻辑会裁成「FC2-PPV」
        title = _parse_title(html, "FC2-976194")
        self.assertIn("美丽温柔", title)
        self.assertNotEqual(title.strip().upper(), "FC2-PPV")


if __name__ == "__main__":
    unittest.main()
