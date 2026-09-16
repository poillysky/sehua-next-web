# -*- coding: utf-8 -*-
"""番号目录 {CODE}.log 旁路读写。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.scrap_library import enrich as E


class EnrichSidecarTests(unittest.TestCase):
    def test_write_read_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "SONE-999"
            folder.mkdir()
            ok = E.write_enrich_sidecar(
                folder,
                {
                    "code": "SONE-999",
                    "source": "javbus",
                    "status": "done",
                    "detailTitle": "测试标题",
                    "sourceTimings": [
                        {"id": "javbus", "ms": 120, "ok": True, "status": "done"},
                        {"id": "dmm", "ms": 80, "ok": False, "status": "fail"},
                    ],
                    "fields": [
                        {"id": "title", "label": "标题", "ok": True, "source": "javbus"},
                    ],
                    "totalMs": 200,
                    "partialOk": False,
                },
            )
            self.assertTrue(ok)
            self.assertTrue((folder / "SONE-999.log").is_file())
            self.assertFalse((folder / "enrich.log").exists())
            data = E.read_enrich_sidecar(folder, code="SONE-999")
            assert data is not None
            self.assertEqual(data.get("code"), "SONE-999")
            self.assertEqual(len(data.get("sourceTimings") or []), 2)
            self.assertEqual(data.get("source"), "javbus")

    def test_read_legacy_enrich_log(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "ABP-001"
            folder.mkdir()
            (folder / "enrich.log").write_text(
                '{"code":"ABP-001","source":"dmm","sourceTimings":[{"id":"dmm","ms":1}]}',
                encoding="utf-8",
            )
            data = E.read_enrich_sidecar(folder, code="ABP-001")
            assert data is not None
            self.assertEqual(data.get("source"), "dmm")

    def test_merge_into_local_scan_item(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "ABP-002"
            folder.mkdir()
            E.write_enrich_sidecar(
                folder,
                {
                    "code": "ABP-002",
                    "source": "mgstage",
                    "sourceTimings": [{"id": "mgstage", "ms": 50, "ok": True}],
                    "fields": [{"id": "title", "ok": True, "source": "mgstage"}],
                    "detailTitle": "来自旁路",
                },
            )
            item = {
                "code": "ABP-002",
                "source": "local_scan",
                "status": "done",
                "itemId": "日本有码/ABP/ABP-002",
            }
            merged = E._merge_enrich_sidecar_into_item(item, folder=folder)
            self.assertEqual(merged.get("source"), "mgstage")
            self.assertEqual(len(merged.get("sourceTimings") or []), 1)
            self.assertEqual(merged.get("detailTitle"), "来自旁路")

    def test_skip_empty_payload(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "X-001"
            folder.mkdir()
            self.assertFalse(E.write_enrich_sidecar(folder, {"code": "X-001"}))
            self.assertFalse((folder / "X-001.log").exists())


if __name__ == "__main__":
    unittest.main()
