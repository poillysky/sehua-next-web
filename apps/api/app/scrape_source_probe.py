"""数据源连通性定时探测：每天测一次已启用源（串行，避免打满过盾）。"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger("sns.scrape_source_probe")

_INTERVAL_SEC = 24 * 60 * 60  # 1 day
_stop = threading.Event()
_thread: threading.Thread | None = None
_busy = threading.Lock()


def _tick_once() -> None:
    if not _busy.acquire(blocking=False):
        log.debug("source probe skip: already running")
        return
    try:
        from . import conn_settings_routes

        _data, message = conn_settings_routes.run_scrape_sources_test(
            None, auto=True
        )
        log.info("source auto-test done %s", message)
    except Exception:
        log.exception("source auto-test failed")
    finally:
        _busy.release()


def _scheduler_loop() -> None:
    log.info(
        "source probe scheduler started (interval=%.0fs / 1d)",
        _INTERVAL_SEC,
    )
    # 启动后先等一轮间隔，避免冷启动立刻打满过盾
    if _stop.wait(_INTERVAL_SEC):
        return
    while not _stop.is_set():
        try:
            _tick_once()
        except Exception:
            log.exception("source probe tick failed")
        if _stop.wait(_INTERVAL_SEC):
            break


def start_source_probe_scheduler() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_scheduler_loop,
        name="scrape-source-probe",
        daemon=True,
    )
    _thread.start()


def stop_source_probe_scheduler() -> None:
    _stop.set()
