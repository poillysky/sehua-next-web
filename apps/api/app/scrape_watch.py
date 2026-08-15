"""刮削任务监控：定期对 watchEnabled 且已武装的任务做增量导出。

武装条件：用户对该现有任务点「开始」并正常跑完一轮后；暂停/取消后解除。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from . import scrape_export, scrape_profiles, settings_store

log = logging.getLogger("sns.scrape_watch")

# 约 10 分钟一轮
_INTERVAL_SEC = 600.0
_stop = threading.Event()
_thread: threading.Thread | None = None


def _watched_tasks() -> list[dict[str, Any]]:
    raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
    tasks = scrape_profiles.normalize_scrape_tasks(
        raw.get("scrapeTasks") or raw.get("scrape_tasks")
    )
    return [
        t
        for t in tasks
        if t.get("watchEnabled")
        and t.get("watchArmed")
        and (t.get("regions") or [])
    ]


def _tick_once() -> None:
    tasks = _watched_tasks()
    if not tasks:
        return
    st = scrape_export.export_status(event_limit=0)
    # 暂停 / 断点续跑抑制：禁止监控自动再开
    if (
        st.get("watchHold")
        or st.get("pauseSaved")
        or st.get("paused")
        or str(st.get("message") or "") == "paused"
    ):
        log.debug("scrape watch skip: user pause / watchHold")
        return
    # 已有导出在跑或排队：本轮不重复塞，等下次
    if st.get("running") or (st.get("queue") or []):
        log.debug("scrape watch skip: export busy")
        return
    submitted = 0
    for task in tasks:
        regions = list(task.get("regions") or [])
        if not regions:
            continue
        try:
            scrape_export.submit_export_job(
                task_id=str(task.get("id") or "") or None,
                task_name=str(task.get("name") or "") or None,
                regions=regions,
                maker=str(task.get("maker") or "").strip() or None,
                prefix=str(task.get("prefix") or "").strip() or None,
                mode="incremental",
                force=False,
                fields=list(task.get("fields") or []) or None,
                local_fields=list(task.get("localFields") or []) or None,
                from_watch=True,
            )
            submitted += 1
        except Exception:
            log.exception(
                "scrape watch enqueue failed task=%s",
                task.get("name") or task.get("id"),
            )
    if submitted:
        log.info("scrape watch enqueued %s task(s)", submitted)


def _scheduler_loop() -> None:
    log.info("scrape watch scheduler started (interval=%.0fs)", _INTERVAL_SEC)
    # 启动后稍等再跑，避免与冷启动其它初始化抢锁
    if _stop.wait(20.0):
        return
    while not _stop.is_set():
        try:
            _tick_once()
        except Exception:
            log.exception("scrape watch tick failed")
        if _stop.wait(_INTERVAL_SEC):
            break


def start_watch_scheduler() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_scheduler_loop,
        name="scrape-watch",
        daemon=True,
    )
    _thread.start()


def stop_watch_scheduler() -> None:
    _stop.set()
