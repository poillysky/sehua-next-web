"""每日自动：增量 maker-fs 索引 + 物化本地片库目录。"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
from typing import Any

from . import library_materialize, maker_fs, settings_store

log = logging.getLogger(__name__)

SETTING_KEY = "maker_fs_auto_daily"

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_running = False


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def get_config() -> dict[str, Any]:
    raw = settings_store.get_setting(SETTING_KEY)
    src = raw if isinstance(raw, dict) else {}
    return {
        "enabled": bool(src.get("enabled")),
        "lastRunDate": str(src.get("lastRunDate") or "")[:10],
        "lastRunAt": str(src.get("lastRunAt") or ""),
        "lastError": str(src.get("lastError") or ""),
        "lastResult": src.get("lastResult")
        if isinstance(src.get("lastResult"), dict)
        else None,
    }


def set_enabled(enabled: bool) -> dict[str, Any]:
    cfg = get_config()
    cfg["enabled"] = bool(enabled)
    settings_store.put_setting(SETTING_KEY, cfg)
    return cfg


def _save(cfg: dict[str, Any]) -> None:
    settings_store.put_setting(SETTING_KEY, cfg)


def needs_daily_run() -> bool:
    cfg = get_config()
    if not cfg.get("enabled"):
        return False
    return str(cfg.get("lastRunDate") or "") != date.today().isoformat()


def _seconds_until_next_midnight() -> float:
    now = datetime.now().astimezone()
    tomorrow = now.date() + timedelta(days=1)
    nxt = datetime.combine(tomorrow, datetime.min.time(), tzinfo=now.tzinfo)
    return max(1.0, (nxt - now).total_seconds())


def run_daily_sync(*, reason: str = "scheduled") -> dict[str, Any]:
    """增量索引（跳过 24h 内新鲜前缀）+ 同步本地片库。"""
    global _running
    cfg = get_config()
    if not cfg.get("enabled"):
        return {"ok": False, "skipped": True, "reason": "disabled"}

    with _lock:
        if _running:
            return {"ok": False, "skipped": True, "reason": "busy"}
        _running = True

    result: dict[str, Any] = {
        "ok": False,
        "reason": reason,
        "startedAt": _now_iso(),
    }
    try:
        # 先刷新番号上限（与 00:00 任务对齐；已跑过则很快）
        try:
            from . import prefix_ranges

            if prefix_ranges.needs_daily_refresh():
                prefix_ranges.refresh_from_db(incremental=True)
        except Exception:
            log.exception("auto daily: prefix ranges refresh failed")

        if not maker_fs.claim_build():
            # 用户正在手动构建：不记 lastRunDate，稍后补跑
            result["skipped"] = True
            result["reason"] = "build_busy"
            return result

        try:
            build = maker_fs.build_maker_fs(
                skip_fresh_hours=maker_fs.DEFAULT_SKIP_FRESH_HOURS,
                workers=maker_fs.DEFAULT_EXPORT_WORKERS,
                from_claim=True,
            )
            result["build"] = {
                "prefixes": (build.get("manifest") or {}).get("prefixCount"),
                "covers": (build.get("manifest") or {}).get("coverCount"),
                "skipped": build.get("skipped"),
            }
        except Exception:
            maker_fs.abort_claim("auto-daily failed")
            raise

        mat = library_materialize.materialize_library()
        result["materialize"] = {
            "written": mat.get("written"),
            "updated": mat.get("updated"),
            "skipped": mat.get("skipped"),
            "total": mat.get("total"),
        }
        result["ok"] = True
        result["finishedAt"] = _now_iso()

        cfg = get_config()
        cfg["lastRunDate"] = date.today().isoformat()
        cfg["lastRunAt"] = result["finishedAt"]
        cfg["lastError"] = ""
        cfg["lastResult"] = {
            "build": result.get("build"),
            "materialize": result.get("materialize"),
        }
        _save(cfg)
        log.info(
            "auto daily sync ok reason=%s build=%s mat=%s",
            reason,
            result.get("build"),
            result.get("materialize"),
        )
        return result
    except Exception as e:
        log.exception("auto daily sync failed")
        cfg = get_config()
        cfg["lastError"] = str(e)[:400]
        cfg["lastRunAt"] = _now_iso()
        # 失败不写 lastRunDate，便于稍后补跑
        _save(cfg)
        result["ok"] = False
        result["error"] = str(e)
        result["finishedAt"] = _now_iso()
        return result
    finally:
        with _lock:
            _running = False


def _scheduler_loop() -> None:
    log.info("maker-fs auto daily scheduler started (next run ~00:05 local)")
    # 启动补跑：已开启且今天未跑
    try:
        if needs_daily_run():
            log.info("maker-fs auto daily stale → catch-up")
            run_daily_sync(reason="startup")
    except Exception:
        log.exception("maker-fs auto daily catch-up failed")

    while not _stop.is_set():
        # 略晚于 prefix-ranges 的 00:00，减少抢库
        wait = _seconds_until_next_midnight() + 300.0
        log.info("maker-fs auto daily next run in %.0fs", wait)
        if _stop.wait(wait):
            break
        try:
            if needs_daily_run():
                run_daily_sync(reason="midnight")
        except Exception:
            log.exception("maker-fs auto daily midnight run failed")


def start_daily_scheduler() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_scheduler_loop,
        name="maker-fs-auto-daily",
        daemon=True,
    )
    _thread.start()


def stop_daily_scheduler() -> None:
    _stop.set()
