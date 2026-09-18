# -*- coding: utf-8 -*-
"""FC2 / FC2-PPV：磁盘前缀与厂牌墙均分开。"""

from __future__ import annotations

import unittest

from app.core.region_meta import fc2_prefix_from_code, normalize_fc2_code
from app.scrap_library import embed as E
from app.scrap_library.studio_display_names import (
    prefixes_for_studio_query,
    resolve_studio_canon_key,
    resolve_studio_display,
    resolve_studio_for_prefix,
)


class Fc2FolderSplitTests(unittest.TestCase):
    def test_studio_wall_is_split(self) -> None:
        self.assertNotEqual(
            resolve_studio_canon_key("FC2"), resolve_studio_canon_key("FC2PPV")
        )
        self.assertEqual(resolve_studio_display("FC2PPV"), "FC2-PPV")
        self.assertEqual(resolve_studio_display("FC2"), "FC2")

    def test_build_studio_facets_keeps_fc2_and_ppv(self) -> None:
        from app.scrap_library.embed import (
            _build_studio_facets_by_prefix,
            _merge_studio_facets,
            _studio_match_key,
        )

        # 不依赖真实库：用 resolve 键确认不会并回同一 canon
        self.assertNotEqual(
            _studio_match_key("FC2"), _studio_match_key("FC2-PPV")
        )
        # 若本地有 FC2 区数据，厂牌墙应能同时给出两张卡
        rows = _merge_studio_facets(_build_studio_facets_by_prefix(region="fc2"))
        names = {str(r.get("name") or "") for r in rows}
        if names & {"FC2", "FC2-PPV"}:
            self.assertIn("FC2", names)
            self.assertIn("FC2-PPV", names)

    def test_prefix_to_studio(self) -> None:
        self.assertEqual(resolve_studio_for_prefix("FC2", region="fc2"), "FC2")
        self.assertEqual(resolve_studio_for_prefix("FC2PPV", region="fc2"), "FC2-PPV")

    def test_studio_query_scopes_per_wall(self) -> None:
        fc2_prefs = {p.upper() for p in prefixes_for_studio_query("FC2", region="fc2")}
        ppv_prefs = {
            p.upper() for p in prefixes_for_studio_query("FC2-PPV", region="fc2")
        }
        self.assertIn("FC2", fc2_prefs)
        self.assertNotIn("FC2PPV", fc2_prefs)
        self.assertIn("FC2PPV", ppv_prefs)
        self.assertNotIn("FC2", ppv_prefs)

    def test_folder_prefixes_are_separate(self) -> None:
        self.assertEqual(E._folder_prefix_aliases("FC2-PPV"), ["FC2PPV"])
        self.assertEqual(E._canonical_folder_prefix("FC2PPV"), "FC2PPV")
        self.assertEqual(E._canonical_folder_prefix("FC2"), "FC2")
        self.assertEqual(E._folder_prefix_aliases("AARM"), ["AARM"])

    def test_shell_rel_path_three_level(self) -> None:
        self.assertEqual(
            E._shell_rel_path("FC2", "FC2", "FC2-123456"),
            "FC2/FC2/FC2-123456",
        )
        self.assertEqual(
            E._shell_rel_path("FC2", "FC2PPV", "FC2-PPV-123456"),
            "FC2/FC2-PPV/FC2-PPV-123456",
        )

    def test_canonical_fc2_scrap_rel(self) -> None:
        self.assertEqual(
            E.canonical_fc2_scrap_rel("FC2/FC2-1166302"),
            "FC2/FC2/FC2-1166302",
        )
        self.assertEqual(
            E.canonical_fc2_scrap_rel("FC2/FC2-PPV-1"),
            "FC2/FC2-PPV/FC2-PPV-1",
        )
        self.assertEqual(
            E.canonical_fc2_scrap_rel("FC2/FC2PPV/FC2-PPV-1"),
            "FC2/FC2-PPV/FC2-PPV-1",
        )
        self.assertEqual(
            E.canonical_fc2_scrap_rel("FC2/FC2/FC2-1"),
            "FC2/FC2/FC2-1",
        )
        self.assertEqual(
            E.canonical_fc2_scrap_rel("日本有码/AARM/AARM-001"),
            "日本有码/AARM/AARM-001",
        )

    def test_fc2_prefix_from_code(self) -> None:
        self.assertEqual(fc2_prefix_from_code("FC2-121816"), "FC2")
        self.assertEqual(fc2_prefix_from_code("FC2-PPV-1234567"), "FC2PPV")
        self.assertEqual(fc2_prefix_from_code("FC2PPV-999"), "FC2PPV")
        self.assertEqual(normalize_fc2_code("FC2PPV-999"), "FC2-PPV-999")
        from app.core.region_meta import fc2_fs_prefix

        self.assertEqual(fc2_fs_prefix("FC2PPV"), "FC2-PPV")
        self.assertEqual(fc2_fs_prefix(code="FC2-PPV-1"), "FC2-PPV")

    def test_fc2_poster_path_aliases(self) -> None:
        from app.scrap_library.embed import (
            _fc2_rel_path_aliases,
            resolve_existing_media_rel,
        )

        flat = _fc2_rel_path_aliases(
            ["scrap-library", "FC2", "FC2-1166302", "poster.jpg"]
        )
        self.assertEqual(
            flat[0],
            ["scrap-library", "FC2", "FC2", "FC2-1166302", "poster.jpg"],
        )
        old_ppv = _fc2_rel_path_aliases(
            ["scrap-library", "FC2", "FC2PPV", "FC2-PPV-1", "poster.jpg"]
        )
        self.assertEqual(
            old_ppv[0],
            ["scrap-library", "FC2", "FC2-PPV", "FC2-PPV-1", "poster.jpg"],
        )
        # 本地有库时：扁平路径应改写到现行三层
        got = resolve_existing_media_rel(
            "scrap-library/FC2/FC2-1166302/poster.jpg"
        )
        if got:
            self.assertIn("/FC2/FC2/", got.replace("\\", "/"))

    def test_enrich_strategy_keeps_single_fc2_category(self) -> None:
        from app.scrap_library import enrich_strategy as strat

        ids = strat.enrich_region_ids()
        self.assertIn("fc2", ids)
        self.assertNotIn("fc2_ppv", ids)
        pub = strat.strategy_public(strat.default_strategy())
        labels = {r["id"]: r["label"] for r in pub.get("regions") or []}
        self.assertEqual(labels.get("fc2"), "FC2 番号")
        self.assertNotIn("fc2_ppv", labels)
        from app.scrap_library import enrich_strategy as strat

        ids = strat.enrich_region_ids()
        self.assertIn("fc2", ids)
        self.assertNotIn("fc2_ppv", ids)
        pub = strat.strategy_public(strat.default_strategy())
        labels = {r["id"]: r["label"] for r in pub.get("regions") or []}
        self.assertEqual(labels.get("fc2"), "FC2 番号")
        self.assertNotIn("fc2_ppv", labels)


if __name__ == "__main__":
    unittest.main()
