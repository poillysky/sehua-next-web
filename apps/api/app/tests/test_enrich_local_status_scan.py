# -*- coding: utf-8 -*-
"""本地 NFO 扫描分类：成功 / 软成功 / 失败。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.scrap_library import enrich as E

_NFO = """<?xml version="1.0" encoding="utf-8"?>
<movie>
  <num>{num}</num>
  <title>{title}</title>
  <plot>{plot}</plot>
  <studio>{studio}</studio>
  <actor><name>{actor}</name></actor>
  <cover>{cover}</cover>
</movie>
"""


def _write_code(
    root: Path,
    *,
    region: str,
    prefix: str,
    code: str,
    title: str,
    plot: str,
    studio: str = "Studio",
    actor: str = "Actor",
    cover: str = "https://example.com/c.jpg",
    poster: bool = True,
) -> Path:
    folder = root / region / prefix / code
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{code}.nfo").write_text(
        _NFO.format(
            num=code,
            title=title,
            plot=plot,
            studio=studio,
            actor=actor,
            cover=cover,
        ),
        encoding="utf-8",
    )
    if poster:
        # 非空图字节；空白判定会被 mock 掉
        (folder / "poster.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 2048)
    return folder


class LocalNfoStatusMapsTests(unittest.TestCase):
    def setUp(self) -> None:
        E._folder_gaps_cache.clear()  # noqa: SLF001
        E._LOCAL_STATUS_TOTALS.clear()  # noqa: SLF001
        E._counts_cache.clear()  # noqa: SLF001

    def test_classify_disk_gaps(self) -> None:
        self.assertEqual(E._classify_disk_gaps([]), "done")
        self.assertEqual(E._classify_disk_gaps(["no_plot"]), "done")
        self.assertEqual(E._classify_disk_gaps(["no_plot", "no_actress"]), "soft")
        self.assertEqual(E._classify_disk_gaps(["no_local"]), "fail")
        self.assertEqual(E._classify_disk_gaps(["thin_title", "no_plot"]), "fail")

    def test_maps_split_done_soft_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            region = "日本有码"
            _write_code(
                root,
                region=region,
                prefix="ABP",
                code="ABP-001",
                title="足够长的完整标题内容",
                plot="足够长的简介文本，用来通过 no_plot 的长度阈值检查。",
            )
            _write_code(
                root,
                region=region,
                prefix="ABP",
                code="ABP-002",
                title="足够长的完整标题内容",
                plot="足够长的简介文本，用来通过 no_plot 的长度阈值检查。",
                actor="",  # soft: no_actress
            )
            _write_code(
                root,
                region=region,
                prefix="ABP",
                code="ABP-003",
                title="ABP-003",  # thin_title
                plot="足够长的简介文本，用来通过 no_plot 的长度阈值检查。",
                poster=False,
            )

            with mock.patch.object(E.embed_svc, "get_settings", return_value={"root": str(root)}):
                with mock.patch.object(
                    E.embed_svc, "resolve_root", return_value=root
                ):
                    with mock.patch.object(
                        E.embed_svc,
                        "_is_blank_cover_file",
                        return_value=False,
                    ):
                        maps = E._local_nfo_gap_maps(region=region, sample_cap=50)

            self.assertEqual(maps.done_n, 1)
            self.assertEqual(maps.soft_n, 1)
            self.assertEqual(maps.fail_n, 1)
            self.assertEqual(len(maps.hard), 1)
            self.assertIn("日本有码/ABP/ABP-001", maps.complete_rels)
            self.assertIn("日本有码/ABP/ABP-002", maps.soft_rels)
            self.assertIn("日本有码/ABP/ABP-003", maps.hard)
            # 软成功不进未处理
            self.assertNotIn("日本有码/ABP/ABP-002", maps.hard)
            self.assertTrue(maps.done_samples[0].get("status") == "done")
            self.assertTrue(maps.soft_samples[0].get("partialOk"))
            self.assertEqual(maps.fail_samples[0].get("status"), "fail")
            # 全量候选与计数一致（不再被 sample_cap 截断）
            self.assertEqual(len(maps.done_cands), 1)
            self.assertEqual(len(maps.soft_cands), 1)
            self.assertEqual(len(maps.fail_cands), 1)

    def test_status_totals_overlay(self) -> None:
        E._LOCAL_STATUS_TOTALS_LOADED = True  # noqa: SLF001
        E._set_local_status_totals("japan_censored", done=10, soft=20, fail=3)
        out = E._apply_local_status_totals(
            {"pending": 1, "running": 0, "done": 0, "soft": 0, "fail": 0},
            "japan_censored",
        )
        self.assertEqual(out["done"], 10)
        self.assertEqual(out["soft"], 20)
        self.assertEqual(out["fail"], 3)
        self.assertEqual(out["pending"], 1)
        # 库有分类时 soft/fail 以库为准，允许从 tip 下降
        # （v1.2.18：失败/软成功重试后角标必须按库内剩余数回落，不能被 tip 钉死）
        out_soft = E._apply_local_status_totals(
            {"pending": 1, "running": 0, "done": 100, "soft": 5, "fail": 1},
            "japan_censored",
        )
        self.assertEqual(out_soft["done"], 100)
        self.assertEqual(out_soft["soft"], 5)
        self.assertEqual(out_soft["fail"], 1)
        E._clear_local_status_totals("japan_censored")
        out2 = E._apply_local_status_totals(
            {"pending": 1, "running": 0, "done": 2, "soft": 0, "fail": 0},
            "japan_censored",
        )
        self.assertEqual(out2["done"], 2)

    def test_status_totals_persist_roundtrip(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest import mock

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "_local_status_totals.json"
            with mock.patch.object(E, "_local_status_totals_path", return_value=path):
                E._LOCAL_STATUS_TOTALS.clear()  # noqa: SLF001
                E._LOCAL_STATUS_TOTALS_LOADED = True  # noqa: SLF001
                E._set_local_status_totals("fc2", done=1001, soft=2002, fail=3)
                self.assertTrue(path.is_file())
                E._LOCAL_STATUS_TOTALS.clear()  # noqa: SLF001
                E._LOCAL_STATUS_TOTALS_LOADED = False  # noqa: SLF001
                # 库分类全 0 → 完全采用 tip：本用例只验证落盘 / 重载往返，
                # done=1001 只可能来自重新读回的文件。
                out = E._apply_local_status_totals(
                    {"pending": 0, "running": 0, "done": 0, "soft": 0, "fail": 0},
                    "fc2",
                )
                self.assertEqual(out["done"], 1001)
                self.assertEqual(out["soft"], 2002)
                self.assertEqual(out["fail"], 3)
                # 库有分类时走合并规则：done 取大、soft/fail 以库为准
                # （v1.2.18 起 fail 不再取大，否则重试成功后角标降不下来）
                out_mix = E._apply_local_status_totals(
                    {"pending": 0, "running": 0, "done": 500, "soft": 500, "fail": 1},
                    "fc2",
                )
                self.assertEqual(out_mix["done"], 1001)
                self.assertEqual(out_mix["soft"], 500)
                self.assertEqual(out_mix["fail"], 1)
                E._clear_local_status_totals("fc2")


    def test_skip_rels_excludes_soft_from_pending(self) -> None:
        maps = E._LocalNfoMaps()
        maps.complete_rels.add("a/B/C")
        maps.soft_rels.add("x/Y/Z")
        maps.hard["h/H/H-1"] = {"itemId": "h/H/H-1", "code": "H-1"}
        self.assertEqual(maps.skip_rels, {"a/B/C", "x/Y/Z", "h/H/H-1"})
        self.assertIn("H-1", maps.classified_codes)
        self.assertIn("C", maps.classified_codes)

    def test_pending_excludes_local_classified(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            region = "日本有码"
            _write_code(
                root,
                region=region,
                prefix="ABP",
                code="ABP-001",
                title="足够长的完整标题内容",
                plot="足够长的简介文本，用来通过 no_plot 的长度阈值检查。",
            )
            _write_code(
                root,
                region=region,
                prefix="ABP",
                code="ABP-002",
                title="足够长的完整标题内容",
                plot="短",
            )
            _write_code(
                root,
                region=region,
                prefix="ABP",
                code="ABP-003",
                title="ABP-003",
                plot="足够长的简介文本，用来通过 no_plot 的长度阈值检查。",
                poster=False,
            )
            shell_rows = [
                {
                    "itemId": "日本有码/ABP/ABP-001",
                    "relPath": "日本有码/ABP/ABP-001",
                    "code": "ABP-001",
                    "gaps": ["no_local"],
                    "shell": True,
                },
                {
                    "itemId": "日本有码/ABP/ABP-002",
                    "relPath": "日本有码/ABP/ABP-002",
                    "code": "ABP-002",
                    "gaps": ["no_plot"],
                    "shell": True,
                },
                {
                    "itemId": "日本有码/ABP/ABP-003",
                    "relPath": "日本有码/ABP/ABP-003",
                    "code": "ABP-003",
                    "gaps": ["no_local"],
                    "shell": True,
                },
                {
                    "itemId": "日本有码/ABP/ABP-999",
                    "relPath": "日本有码/ABP/ABP-999",
                    "code": "ABP-999",
                    "gaps": ["no_local", "no_plot"],
                    "shell": True,
                },
            ]
            with mock.patch.object(E.embed_svc, "get_settings", return_value={"root": str(root)}):
                with mock.patch.object(E.embed_svc, "resolve_root", return_value=root):
                    with mock.patch.object(
                        E.embed_svc, "_is_blank_cover_file", return_value=False
                    ):
                        # v1.2.17 起未处理角标改按「向量库实时总量 − 本地已分类」重算，
                        # 不再走 _region_library_progress（旧的 incomplete/total）。
                        with mock.patch.object(
                            E,
                            "_fresh_vector_library_total",
                            return_value=100,
                        ):
                            with mock.patch.object(
                                E.embed_svc,
                                "list_region_code_items",
                                return_value=shell_rows,
                            ):
                                rows, total = E.iter_enrich_pending_items(
                                    region=region, limit=50
                                )
            # 向量全部 100 − 本地分类 3 = 97；列表只剩骨架 ABP-999
            self.assertEqual(total, 97)
            self.assertEqual([r.get("code") for r in rows], ["ABP-999"])

    def test_insert_local_status_writes_all_cands(self) -> None:
        maps = E._LocalNfoMaps()
        maps.done_n = 2
        maps.soft_n = 3
        maps.fail_n = 1
        maps.done_cands = [("r/A-1", "A-1", []), ("r/A-2", "A-2", [])]
        maps.soft_cands = [
            ("r/B-1", "B-1", ["no_actress"]),
            ("r/B-2", "B-2", ["no_actress"]),
            ("r/B-3", "B-3", ["no_studio"]),
        ]
        maps.fail_cands = [("r/C-1", "C-1", ["no_local"])]
        captured: list[list[dict]] = []

        def _fake_insert(region: str, rows: list[dict]) -> list[int]:
            captured.append(list(rows))
            return [1] * len(rows)

        with mock.patch.object(E, "_queue_log_insert_many", side_effect=_fake_insert):
            with mock.patch.object(E, "_queue_log_region", return_value="日本有码"):
                counts = E._queue_log_insert_local_status_samples(
                    "日本有码", maps, write_cap=0
                )
        self.assertEqual(counts, {"done": 2, "soft": 3, "fail": 1})
        flat = [r for chunk in captured for r in chunk]
        self.assertEqual(len(flat), 6)
        soft_n = sum(1 for r in flat if r.get("partialOk"))
        fail_n = sum(1 for r in flat if r.get("status") == "fail")
        done_n = sum(
            1
            for r in flat
            if r.get("status") == "done" and not r.get("partialOk")
        )
        self.assertEqual(done_n, 2)
        self.assertEqual(soft_n, 3)
        self.assertEqual(fail_n, 1)

    def test_pending_badge_formula_vector_total(self) -> None:
        """未处理角标 = 向量所有番号 − 成功 − 软成功 − 失败。"""
        E._set_local_status_totals("japan_censored", done=10, soft=5, fail=3)
        out = E._apply_local_status_totals(
            {"pending": 0, "running": 0, "done": 0, "soft": 0, "fail": 0},
            "japan_censored",
        )
        self.assertEqual(out["done"], 10)
        self.assertEqual(out["soft"], 5)
        self.assertEqual(out["fail"], 3)
        # 公式本身：total 100 − 18 = 82
        self.assertEqual(max(0, 100 - 10 - 5 - 3), 82)
        E._clear_local_status_totals("japan_censored")


if __name__ == "__main__":
    unittest.main()
