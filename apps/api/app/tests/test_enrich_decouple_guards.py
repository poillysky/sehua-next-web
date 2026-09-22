# -*- coding: utf-8 -*-
"""解耦守卫：锁住 enrich 门面契约，避免拆模块后再「修 A 坏 B」。

覆盖三条最容易连环回归的路径：
  1) 门面 re-export 仍可达（拆文件后符号从 enrich 消失会静默炸路由）
  2) pause / stop 对运行态队列与检查点的语义
  3) 单条重刮的互斥与入参校验
  4) 角标计数（done/soft）与进度公式一致
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.scrap_library import enrich as E
from app.scrap_library.enrich_runtime import _enrich_job


def _save_job(*keys: str) -> dict:
    return {k: _enrich_job.get(k) for k in keys}


def _restore_job(saved: dict) -> None:
    for k, v in saved.items():
        _enrich_job[k] = v


class FacadeExportTests(unittest.TestCase):
    """拆包后路由仍从 `enrich` 取符号；缺任何一个都会 500。"""

    def test_job_control_exports(self) -> None:
        for name in (
            "request_enrich_pause",
            "request_enrich_stop",
            "request_enrich_cancel",
            "_fill_mode_to_job_mode",
            "_next_budget",
            "_clear_runtime_queue",
        ):
            self.assertTrue(callable(getattr(E, name, None)), name)

    def test_pipeline_exports(self) -> None:
        for name in (
            "enrich_one_row",
            "run_enrich",
            "start_enrich_job",
            "enrich_one_by_item_id",
            "save_item_plot",
            "retry_enrich_fails",
            "retry_enrich_softs",
            "get_enrich_status",
        ):
            self.assertTrue(callable(getattr(E, name, None)), name)

    def test_badge_helpers_share_truth(self) -> None:
        self.assertTrue(callable(getattr(E, "_queue_counts_of", None)))
        self.assertTrue(callable(getattr(E, "_progress_from_queue_counts", None)))
        self.assertTrue(callable(getattr(E, "_queue_row_status", None)))
        self.assertIn("no_actress", E._SOFT_SUCCESS_GAPS)
        self.assertIn("no_local", E._SUCCESS_BLOCK_GAPS)


class PauseStopContractTests(unittest.TestCase):
    """暂停：进行中退回 pending + 写检查点；停止：清检查点/队列。"""

    def setUp(self) -> None:
        self._saved = _save_job(
            "running",
            "halt",
            "cancel",
            "phase",
            "queue",
            "queueCounts",
            "current",
            "currentRegion",
            "checkpoints",
            "progress",
            "jobMode",
            "jobKinds",
            "jobDryRun",
            "result",
        )

    def tearDown(self) -> None:
        _restore_job(self._saved)

    def test_pause_when_idle_without_checkpoint(self) -> None:
        _enrich_job["running"] = False
        _enrich_job["checkpoints"] = {}
        out = E.request_enrich_pause()
        self.assertTrue(out.get("ok"))
        self.assertFalse(out.get("paused"))
        self.assertFalse(out.get("running"))

    def test_pause_when_idle_with_checkpoint_reports_paused(self) -> None:
        _enrich_job["running"] = False
        _enrich_job["checkpoints"] = {"japan_censored": {"queue": []}}
        out = E.request_enrich_pause()
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("paused"))
        self.assertFalse(out.get("running"))

    @mock.patch("app.scrap_library.enrich_job_control._persist_enrich_runtime")
    @mock.patch("app.scrap_library.enrich_job_control.notify_enrich_watchers")
    def test_pause_demotes_running_and_writes_checkpoint(
        self, _notify: mock.MagicMock, _persist: mock.MagicMock
    ) -> None:
        _enrich_job.update(
            {
                "running": True,
                "halt": None,
                "cancel": False,
                "currentRegion": "japan_censored",
                "jobMode": "incremental",
                "jobKinds": ["no_local"],
                "jobDryRun": False,
                "checkpoints": {},
                "current": {"code": "ABC-001", "status": "running"},
                "queue": [
                    {"code": "ABC-001", "itemId": "a/1", "status": "running"},
                    {"code": "ABC-002", "itemId": "a/2", "status": "pending"},
                    {"code": "ABC-003", "itemId": "a/3", "status": "done"},
                    {"code": "ABC-004", "itemId": "a/4", "status": "fail"},
                ],
                "queueCounts": {
                    "pending": 1,
                    "running": 1,
                    "done": 1,
                    "soft": 0,
                    "fail": 1,
                },
            }
        )

        with mock.patch.object(E, "_queue_log_int_id", return_value=0), mock.patch.object(
            E, "_queue_log_status_counts", return_value={"pending": 2}
        ), mock.patch.object(E, "_queue_log_mark_pending"), mock.patch.object(
            E, "_queue_log_reopen_running"
        ), mock.patch.object(E, "_push_log"):
            out = E.request_enrich_pause()

        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("paused"))
        self.assertFalse(out.get("running"))
        self.assertFalse(_enrich_job.get("running"))
        self.assertEqual(_enrich_job.get("halt"), "pause")
        self.assertEqual(_enrich_job.get("phase"), "paused")
        self.assertIsNone(_enrich_job.get("current"))

        statuses = [str(r.get("status")) for r in (_enrich_job.get("queue") or [])]
        self.assertEqual(statuses.count("running"), 0)
        self.assertGreaterEqual(statuses.count("pending"), 2)
        self.assertIn("done", statuses)
        self.assertIn("fail", statuses)

        cp = (_enrich_job.get("checkpoints") or {}).get("japan_censored") or {}
        self.assertEqual(cp.get("region"), "japan_censored")
        self.assertEqual(int(cp.get("remainingCount") or 0), 2)
        rem_codes = {str(r.get("code")) for r in (cp.get("queue") or [])}
        self.assertEqual(rem_codes, {"ABC-001", "ABC-002"})
        self.assertEqual(int((_enrich_job.get("queueCounts") or {}).get("running", -1)), 0)

    @mock.patch("app.scrap_library.enrich_job_control._persist_enrich_runtime")
    @mock.patch("app.scrap_library.enrich_job_control.notify_enrich_watchers")
    def test_stop_while_running_sets_halt(
        self, _notify: mock.MagicMock, _persist: mock.MagicMock
    ) -> None:
        _enrich_job.update(
            {
                "running": True,
                "halt": None,
                "cancel": False,
                "phase": "enrich",
                "progress": {"label": "刮削中"},
                "checkpoints": {"japan_censored": {"queue": [{"code": "X"}]}},
            }
        )
        with mock.patch.object(E, "_queue_log_reopen_running"):
            out = E.request_enrich_stop(region="japan_censored")
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("stopped"))
        self.assertTrue(out.get("running"))
        self.assertEqual(_enrich_job.get("halt"), "stop")
        self.assertEqual(_enrich_job.get("phase"), "stopping")
        # 运行中 stop 不立刻清检查点（留给 worker 收尾）；空闲 stop 才清
        self.assertIn("japan_censored", _enrich_job.get("checkpoints") or {})

    @mock.patch("app.scrap_library.enrich_job_control._persist_enrich_runtime")
    @mock.patch("app.scrap_library.enrich_job_control.notify_enrich_watchers")
    @mock.patch("app.scrap_library.enrich_job_control.enrich_mon.clear_job")
    def test_stop_while_idle_clears_checkpoint(
        self,
        _clear_mon: mock.MagicMock,
        _notify: mock.MagicMock,
        _persist: mock.MagicMock,
    ) -> None:
        _enrich_job.update(
            {
                "running": False,
                "halt": None,
                "queue": [{"code": "ABC-001", "status": "pending"}],
                "current": {"code": "ABC-001"},
                "checkpoints": {"japan_censored": {"queue": [{"code": "X"}]}},
                "progress": {"label": "paused"},
                "phase": "paused",
                "result": {"ok": 1},
            }
        )
        with mock.patch.object(E, "_queue_log_reopen_running"):
            out = E.request_enrich_stop(region="japan_censored")
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("stopped"))
        self.assertFalse(out.get("running"))
        self.assertNotIn("japan_censored", _enrich_job.get("checkpoints") or {})
        self.assertEqual(_enrich_job.get("queue"), [])
        self.assertIsNone(_enrich_job.get("current"))
        self.assertEqual(_enrich_job.get("phase"), "stopped")

    def test_cancel_aliases_pause(self) -> None:
        # cancel 在 enrich_job_control 内直接调用同模块 pause，不能只 patch E.request_enrich_pause
        with mock.patch(
            "app.scrap_library.enrich_job_control.request_enrich_pause",
            return_value={"ok": True, "paused": True},
        ) as m:
            out = E.request_enrich_cancel()
        m.assert_called_once()
        self.assertEqual(out.get("paused"), True)


class EnrichOneGuardTests(unittest.TestCase):
    """单条重刮：入参与互斥必须在进库/进网之前挡住。"""

    def setUp(self) -> None:
        self._saved = _save_job("running", "phase", "progress", "log", "result", "error")

    def tearDown(self) -> None:
        _restore_job(self._saved)
        _enrich_job["running"] = False

    def test_empty_item_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            E.enrich_one_by_item_id(item_id="")
        with self.assertRaises(ValueError):
            E.enrich_one_by_item_id(item_id="   ")

    def test_rejects_when_enrich_already_running(self) -> None:
        _enrich_job["running"] = True
        with self.assertRaises(RuntimeError) as ctx:
            E.enrich_one_by_item_id(item_id="japan_censored/ABC/ABC-001")
        self.assertIn("已在运行", str(ctx.exception))

    def test_rejects_when_embed_job_running(self) -> None:
        _enrich_job["running"] = False
        with mock.patch(
            "app.scrap_library.enrich_job_api.embed_svc.get_job_status",
            return_value={"running": True},
        ):
            with self.assertRaises(RuntimeError) as ctx:
                E.enrich_one_by_item_id(item_id="japan_censored/ABC/ABC-001")
        self.assertIn("向量同步", str(ctx.exception))


class BadgeContractTests(unittest.TestCase):
    """角标：soft 从 done 拆出；进度 ok = done + soft。"""

    def test_queue_counts_split_soft_from_done(self) -> None:
        rows = [
            {"status": "done", "partialOk": False},
            {"status": "done", "partialOk": True, "error": "软成功 · 仍缺:女优"},
            {"status": "done", "error": "次成功 · 仍缺:片商"},
            {"status": "fail"},
            {"status": "pending"},
            {"status": "running"},
        ]
        c = E._queue_counts_of(rows)
        self.assertEqual(c["done"], 1)
        self.assertEqual(c["soft"], 2)
        self.assertEqual(c["fail"], 1)
        self.assertEqual(c["pending"], 1)
        self.assertEqual(c["running"], 1)

    def test_progress_ok_includes_soft(self) -> None:
        prog = E._progress_from_queue_counts(
            {"pending": 4, "running": 1, "done": 2, "soft": 3, "fail": 1}
        )
        self.assertEqual(prog["ok"], 5)
        self.assertEqual(prog["failed"], 1)
        self.assertEqual(prog["done"], 6)
        self.assertEqual(prog["total"], 11)

    def test_fill_mode_aliases(self) -> None:
        self.assertEqual(E._fill_mode_to_job_mode("overwrite"), "overwrite")
        self.assertEqual(E._fill_mode_to_job_mode("refresh_weak"), "refresh_weak")
        self.assertEqual(E._fill_mode_to_job_mode(""), "incremental")


if __name__ == "__main__":
    unittest.main()
