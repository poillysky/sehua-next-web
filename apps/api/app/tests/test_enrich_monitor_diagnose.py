# -*- coding: utf-8 -*-
"""enrich_monitor.diagnose：勿把已结束的 timeout 钉成永久卡顿。"""

from __future__ import annotations

import time
import unittest

from app.scrap_library import enrich_monitor as mon


class DiagnoseStallTests(unittest.TestCase):
    def test_finished_timeout_not_stall(self) -> None:
        now = time.time()
        stall = mon.diagnose(
            {
                "phase": "fetch",
                "startedAt": now - 16,
                "phaseStartedAt": now - 16,
                "lastBeatAt": now,
                "sources": [
                    {
                        "id": "iqqtv",
                        "status": "fail",
                        "ms": 15000,
                        "ok": False,
                        "error": "timeout:15s",
                    },
                    {
                        "id": "dmm",
                        "status": "running",
                        "ms": 200,
                        "ok": False,
                        "error": "",
                    },
                ],
            },
            per_source_timeout_sec=15,
            now=now,
        )
        self.assertIsNone(stall)

    def test_running_slow_is_stall(self) -> None:
        now = time.time()
        stall = mon.diagnose(
            {
                "phase": "fetch",
                "startedAt": now - 14,
                "phaseStartedAt": now - 14,
                "lastBeatAt": now,
                "sources": [
                    {
                        "id": "iqqtv",
                        "status": "running",
                        "ms": 14000,
                        "ok": False,
                        "error": "",
                    },
                ],
            },
            per_source_timeout_sec=15,
            now=now,
        )
        self.assertIsNotNone(stall)
        assert stall is not None
        self.assertEqual(stall.get("kind"), "source_slow")
        self.assertIn("iqqtv", str(stall.get("label") or ""))

    def test_cover_phase_ignores_old_timeout(self) -> None:
        now = time.time()
        stall = mon.diagnose(
            {
                "phase": "cover",
                "startedAt": now - 20,
                "phaseStartedAt": now - 3,
                "lastBeatAt": now,
                "sources": [
                    {
                        "id": "iqqtv",
                        "status": "fail",
                        "ms": 15000,
                        "ok": False,
                        "error": "timeout:15s",
                    },
                ],
            },
            per_source_timeout_sec=15,
            now=now,
        )
        self.assertIsNone(stall)


if __name__ == "__main__":
    unittest.main()
