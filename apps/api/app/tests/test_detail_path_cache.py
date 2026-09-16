# -*- coding: utf-8 -*-
"""detail_path_cache 单测（第十六轮）。

钉语义：
- 命中/未命中/跨源跨码隔离；
- 落盘持久化（模拟新进程 _load_disk）；
- 损坏文件抢救（trailing garbage → raw_decode 首段）；
- 更新覆盖。
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from app.core import detail_path_cache as dpc

FUTURE_MS = int(time.time() * 1000) + 60_000


class DetailPathCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._store = Path(self._tmp.name) / "detail-paths.json"
        self._orig = dpc._store_path
        dpc._store_path = lambda: self._store  # type: ignore[assignment]
        dpc._memory.clear()
        dpc._loaded = False

    def tearDown(self) -> None:
        dpc._store_path = self._orig  # type: ignore[assignment]
        dpc._memory.clear()
        dpc._loaded = False
        self._tmp.cleanup()

    def test_miss_returns_none(self) -> None:
        self.assertIsNone(dpc.lookup("iqqtv", "ABP-658"))

    def test_roundtrip_and_case_insensitive_code(self) -> None:
        dpc.remember("iqqtv", "ABP-658", "player.php?uuid=BTbAdShCT8g&cat=19")
        self.assertEqual(
            dpc.lookup("iqqtv", "abp-658"), "player.php?uuid=BTbAdShCT8g&cat=19"
        )

    def test_isolation_across_sources_and_codes(self) -> None:
        dpc.remember("iqqtv", "ABP-658", "player.php?uuid=A")
        dpc.remember("airav_io", "ABP-658", "/cn/video?hid=167224")
        self.assertEqual(dpc.lookup("iqqtv", "ABP-658"), "player.php?uuid=A")
        self.assertEqual(dpc.lookup("airav_io", "ABP-658"), "/cn/video?hid=167224")
        self.assertIsNone(dpc.lookup("iqqtv", "ABP-659"))

    def test_persists_across_fake_process_restart(self) -> None:
        dpc.remember("iqqtv", "ABP-658", "player.php?uuid=A")
        self.assertTrue(self._store.is_file())
        # 模拟新进程：清内存重读盘
        dpc._memory.clear()
        dpc._loaded = False
        self.assertEqual(dpc.lookup("iqqtv", "ABP-658"), "player.php?uuid=A")

    def test_update_overwrites(self) -> None:
        dpc.remember("iqqtv", "ABP-658", "old")
        dpc.remember("iqqtv", "ABP-658", "new")
        self.assertEqual(dpc.lookup("iqqtv", "ABP-658"), "new")

    def test_same_value_no_rewrite(self) -> None:
        dpc.remember("iqqtv", "ABP-658", "p")
        mtime1 = self._store.stat().st_mtime_ns
        dpc.remember("iqqtv", "ABP-658", "p")  # 未变更 → 不落盘
        self.assertEqual(self._store.stat().st_mtime_ns, mtime1)

    def test_damaged_file_salvaged(self) -> None:
        payload = {
            "version": 1,
            "entries": {
                "iqqtv:ABP-658": {"path": "player.php?uuid=A", "expiresAt": FUTURE_MS}
            },
        }
        self._store.write_text(
            json.dumps(payload, ensure_ascii=False) + "\n<<<trailing garbage>>>",
            encoding="utf-8",
        )
        self.assertEqual(dpc.lookup("iqqtv", "ABP-658"), "player.php?uuid=A")

    def test_expired_entry_not_returned(self) -> None:
        payload = {
            "version": 1,
            "entries": {"iqqtv:ABP-658": {"path": "p", "expiresAt": 1}},
        }
        self._store.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIsNone(dpc.lookup("iqqtv", "ABP-658"))

    def test_remember_empty_path_is_noop(self) -> None:
        dpc.remember("iqqtv", "ABP-658", "  ")
        self.assertIsNone(dpc.lookup("iqqtv", "ABP-658"))
        self.assertFalse(self._store.exists())


if __name__ == "__main__":
    unittest.main()
