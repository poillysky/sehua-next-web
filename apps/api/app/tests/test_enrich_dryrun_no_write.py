"""预览（dryRun）不得写 enrich_queue_log —— 回归护栏。

背景：预览会把处理过的行在 enrich_queue_log 标成 done，之后
`_queue_log_prune_open_if_done` 会按「同番号已有成功」删掉真正的 pending 行，
导致待刮条目凭空消失（假成功）。这里用桩替换落库函数，断言 persist=False
时一次写库都不发生。
"""

from __future__ import annotations

import unittest
from unittest import mock

import app.scrap_library.enrich as enrich


class DryRunNoWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        # 清掉可能残留的 halt，确保走的不是早退分支
        with enrich._enrich_lock:  # noqa: SLF001
            enrich._enrich_job["halt"] = None  # noqa: SLF001
            enrich._enrich_job["queue"] = []  # noqa: SLF001

    def test_patch_queue_item_persist_false_skips_db(self) -> None:
        row = {"itemId": "日本有码/ABP/ABP-594", "code": "ABP-594", "region": "japan_censored"}
        with mock.patch.object(
            enrich, "_queue_log_update_row", return_value=1234
        ) as m_upd:
            enrich._patch_queue_item(  # noqa: SLF001
                0, match=row, persist=False, status="done", error=""
            )
            self.assertEqual(
                m_upd.call_count, 0, "预览（persist=False）不应写 enrich_queue_log"
            )

            enrich._patch_queue_item(  # noqa: SLF001
                0, match=row, persist=True, status="done", error=""
            )
            self.assertEqual(
                m_upd.call_count, 1, "真实运行（persist=True）应写 enrich_queue_log"
            )

    def test_patch_queue_item_persist_false_keeps_memory_state(self) -> None:
        """不落库，但内存队列必须照改（UI 要看到预览结果）。"""
        row = {"itemId": "日本有码/ABP/ABP-596", "code": "ABP-596", "region": "japan_censored"}
        with enrich._enrich_lock:  # noqa: SLF001
            enrich._enrich_job["queue"] = [  # noqa: SLF001
                {"itemId": row["itemId"], "code": row["code"], "status": "pending"}
            ]
        with mock.patch.object(enrich, "_queue_log_update_row", return_value=0):
            enrich._patch_queue_item(  # noqa: SLF001
                0, match=row, persist=False, status="done"
            )
        with enrich._enrich_lock:  # noqa: SLF001
            q = enrich._enrich_job["queue"]  # noqa: SLF001
        self.assertEqual(str(q[0].get("status")), "done")

    def test_ensure_queue_log_ids_persist_false_is_readonly(self) -> None:
        """预览只复用已存在的 pending 行（只读），绝不 INSERT / UPDATE。"""
        rows = [
            {"itemId": "日本有码/ABP/ABP-594", "code": "ABP-594", "region": "japan_censored"},
        ]
        with mock.patch.object(
            enrich, "_queue_log_insert_many", return_value=[999]
        ) as m_ins:
            out = enrich._ensure_queue_log_ids(  # noqa: SLF001
                "japan_censored", rows, persist=False
            )
            self.assertEqual(m_ins.call_count, 0, "预览不应插入队列表行")
            self.assertEqual(len(out), 1)
            # 复用已存在的 pending 行（正 logId）是允许且正确的：
            # 只读匹配，不改变库里那一行。未匹配上则应为 0。
            self.assertGreaterEqual(
                int(enrich._queue_log_int_id(out[0])), 0  # noqa: SLF001
            )

    def test_persist_result_to_queue_log_dry_guard(self) -> None:
        with mock.patch.object(
            enrich, "_queue_log_update_row", return_value=1
        ) as m_upd:
            n = enrich._persist_enrich_result_to_queue_log(  # noqa: SLF001
                {"sourceTimings": [{"id": "airav_io"}], "fields": []},
                row={"code": "ABP-594"},
                region="japan_censored",
                dry_run=True,
            )
        self.assertEqual(n, 0)
        self.assertEqual(m_upd.call_count, 0)


if __name__ == "__main__":
    unittest.main()
