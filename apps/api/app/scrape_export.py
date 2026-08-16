"""从 maker-fs 清单调用刮削服务，写出本站目录库。

落盘（同目录两文件、互不合并）：
  meta.json   — 本地索引物化（maker-fs 种子，仅物化任务写入）
  scrape.json — 刮削结果（仅刮削任务写入）
  + poster.jpg / 封面.url
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait as futures_wait
from concurrent.futures.thread import _threads_queues, _worker  # type: ignore[attr-defined]
import weakref
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from . import (
    maker_fs,
    scrape_export_log_store,
    scrape_metadata_optimize,
    scrape_naming,
    scrape_profiles,
    settings_store,
)
from .db import ROOT
from .scrape_forum_title import is_likely_chinese, is_quality_chinese_title

log = logging.getLogger(__name__)

DEFAULT_LIBRARY = ROOT / "data" / "library"
# 同目录双文件：索引物化 vs 刮削结果，禁止互相覆盖/合并落盘
INDEX_META_FILE = "meta.json"
SCRAPE_META_FILE = "scrape.json"
EXPORT_FIELDS = (
    "cover",
    "titleZh",
    "publisher",
    "studio",
    "actors",
    "tags",
    "series",
)
DEFAULT_EXPORT_FIELDS = list(EXPORT_FIELDS)


class _DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """daemon worker：进程退出/热重载时不被线程池拖死（Windows）。"""

    def _adjust_thread_count(self) -> None:  # type: ignore[override]
        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_: Any, q: Any = self._work_queue) -> None:
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = "%s_%d" % (self._thread_name_prefix or self, num_threads)
            t = threading.Thread(
                name=thread_name,
                target=_worker,
                args=(
                    weakref.ref(self, weakref_cb),
                    self._work_queue,
                    self._initializer,
                    self._initargs,
                ),
                daemon=True,
            )
            t.start()
            self._threads.add(t)
            _threads_queues[t] = self._work_queue


def _normalize_export_concurrency(raw: Any) -> int:
    """单通道并发：默认 2，上限 4（整容器持续 <1G）。"""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 2
    if n <= 0:
        n = 2
    return max(1, min(4, n))


def _resolve_channel_concurrency(cfg: dict[str, Any]) -> tuple[int, int]:
    """快/慢通道并发；缺省回落安全默认（快 2 / 慢 1）。"""
    leg = _normalize_export_concurrency(
        cfg.get("exportConcurrency") or cfg.get("export_concurrency")
    )
    fast_raw = cfg.get("exportFastConcurrency")
    if fast_raw is None:
        fast_raw = cfg.get("export_fast_concurrency")
    slow_raw = cfg.get("exportSlowConcurrency")
    if slow_raw is None:
        slow_raw = cfg.get("export_slow_concurrency")
    if fast_raw is None and slow_raw is None:
        return min(leg, 2), min(leg, 1)
    fast = _normalize_export_concurrency(
        fast_raw if fast_raw is not None else leg
    )
    slow = _normalize_export_concurrency(
        slow_raw if slow_raw is not None else 1
    )
    return fast, slow


# 与 sources.access=proxy_flare / 高概率过盾对齐：占过盾锁 / 慢通道
# mgstage 虽为 proxy_adaptive，出口不稳时仍常走 Flare，保留慢通道
_FLARE_BOUND_SOURCES = frozenset(
    {
        "javdb",
        "javlibrary",
        "miss_av",
        "avmoo",
        "avsox",
        "mgstage",
        "fd2ppv",
        "fc2_hub",
    }
)


def _target_needs_flare_titlezh(
    t: dict[str, Any],
    *,
    export_fields: list[str],
    local_fields: list[str],
    profiles: dict[str, Any],
    cfg: dict[str, Any],
) -> bool:
    """开跑预分通道：仅「纯过盾」进慢源；不过盾/混合先进快源。

    混合链在快源跑不过盾源；若仍不够且需过盾，由刮削服务返回 needs_flare，
    导出侧再转入慢源队列（见 defer_slow）。
    """
    if "titleZh" not in set(export_fields):
        return False
    code = _std_code(str(t.get("code") or ""))
    if not code:
        return False
    rid = str(t.get("region") or "")
    kind = scrape_profiles.detect_scrape_kind(code, rid)
    try:
        prof = scrape_profiles.resolve_kind_profile(
            kind,
            profiles=profiles,
            global_library=cfg.get("libraryRoot") or "",
            global_write_tree=bool(cfg.get("writeTree")),
            global_write_emby=bool(cfg.get("writeEmby")),
        )
        fp = scrape_profiles.filter_field_priority_for_export(
            prof.get("fieldPriority") or {},
            export_fields,
        )
        title_srcs = [
            str(x or "").strip().lower() for x in (fp.get("titleZh") or [])
        ]
    except Exception:
        title_srcs = ["iqqtv", "airav_io", "sevenmmtv"]
    has_flare = any(s in _FLARE_BOUND_SOURCES for s in title_srcs)
    has_fast = any(s and s not in _FLARE_BOUND_SOURCES for s in title_srcs)
    # 纯过盾 → 慢；有不过盾（含混合）→ 快
    if has_flare and not has_fast:
        return True
    return False


def _partition_targets_fast_slow(
    targets: list[dict[str, Any]],
    *,
    export_fields: list[str],
    local_fields: list[str],
    profiles: dict[str, Any],
    cfg: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fast: list[dict[str, Any]] = []
    slow: list[dict[str, Any]] = []
    for t in targets:
        if _target_needs_flare_titlezh(
            t,
            export_fields=export_fields,
            local_fields=local_fields,
            profiles=profiles,
            cfg=cfg,
        ):
            slow.append(t)
        else:
            fast.append(t)
    return fast, slow


_EXPORT_LOCK_PATH = ROOT / "data" / "scrape-export.lock"
_STATUS_PATH = ROOT / "data" / "scrape-export-status.json"
_RESUME_PATH = ROOT / "data" / "scrape-export-resume.json"

_lock = threading.Lock()
_meta_lock = threading.RLock()
_pause_cv = threading.Condition(_meta_lock)
_export_worker: threading.Thread | None = None
_STUCK_BUSY_MESSAGES = frozenset(
    {"building", "queued", "scraping", "cancelling"}
)
_MAX_EVENTS = 400
_MAX_EVENTS_PER_CODE = 500
# 内存只缓存「当前热番号」日志；全量在 SQLite scrape_export_events
_MAX_CODE_EVENT_CACHE = 32
# 番号列表上限：过小会导致去重列表被裁掉、成功计数再次累加
_MAX_RESULT_CODES = 100000
# 轮询默认不下发完整番号列表（点开列表走专用接口 / DB）
_STATUS_CODE_LIST_CAP = 500

# 按番号保留刮削日志（换片清空的是实时 events，成功队列点进去仍能看）
_events_by_code: dict[str, list[dict[str, Any]]] = {}
_events_by_code_order: list[str] = []
_events_by_code_lock = threading.Lock()
# 本轮任务已计入终态的番号（不随列表裁剪丢失）
_result_seen: set[str] = set()


def _empty_code_lists() -> dict[str, list[str]]:
    return {
        "doneCodes": [],
        "skippedCodes": [],
        "failedCodes": [],
        "emptyCodes": [],
        "activeCodes": [],
        "activeFastCodes": [],
        "activeSlowCodes": [],
    }


def _append_result_code(bucket: str, code: str) -> None:
    """调用方须已持有 _meta_lock。"""
    c = str(code or "").strip()
    if not c:
        return
    lst = list(_state.get(bucket) or [])
    if c not in lst:
        lst.append(c)
    if len(lst) > _MAX_RESULT_CODES:
        lst = lst[-_MAX_RESULT_CODES:]
    _state[bucket] = lst


def _code_already_counted(code: str) -> bool:
    """调用方须已持有 _meta_lock。同一番号只计入成功/空号/失败/跳过一次。"""
    c = str(code or "").strip()
    if not c:
        return True
    if c in _result_seen:
        return True
    for bucket in ("doneCodes", "emptyCodes", "failedCodes", "skippedCodes"):
        if c in list(_state.get(bucket) or []):
            _result_seen.add(c)
            return True
    return False


def _reconcile_result_counts_locked() -> None:
    """用去重列表回写计数；若仍超过合计则钳制成功数。调用方须持锁。"""
    done_n = len(list(_state.get("doneCodes") or []))
    empty_n = len(list(_state.get("emptyCodes") or []))
    skip_n = len(list(_state.get("skippedCodes") or []))
    fail_n = len(list(_state.get("failedCodes") or []))
    # 计数不得小于列表长度（防止历史虚高被列表裁剪后仍显示更大）
    done = max(done_n, 0)
    empty = max(empty_n, 0)
    skipped = max(skip_n, 0)
    failed = max(fail_n, 0)
    # 若内存计数被旧逻辑抬高，以唯一列表为准
    if int(_state.get("done") or 0) != done:
        _state["done"] = done
    if int(_state.get("empty") or 0) != empty:
        _state["empty"] = empty
    if int(_state.get("skipped") or 0) != skipped:
        _state["skipped"] = skipped
    if int(_state.get("failed") or 0) != failed:
        _state["failed"] = failed
    total = int(_state.get("total") or 0)
    processed = done + empty + skipped + failed
    if total > 0 and processed > total:
        room = max(0, total - empty - skipped - failed)
        _state["done"] = min(done, room)


def _remove_from_result_buckets(code: str, *buckets: str) -> None:
    """调用方须已持有 _meta_lock。从若干结果桶移除番号并同步计数键。"""
    c = str(code or "").strip()
    if not c:
        return
    count_key = {
        "doneCodes": "done",
        "emptyCodes": "empty",
        "skippedCodes": "skipped",
        "failedCodes": "failed",
    }
    for bucket in buckets:
        lst = list(_state.get(bucket) or [])
        if c not in lst:
            continue
        _state[bucket] = [x for x in lst if x != c]
        ck = count_key.get(bucket)
        if ck:
            _state[ck] = len(list(_state.get(bucket) or []))


def _record_terminal_result(result: str, code: str) -> None:
    """调用方须已持有 _meta_lock。去重后累加计数，避免暂停重入导致成功>合计。

    特例：先前误记为失败的 not_found 可迁到空号；
    已刮成功的可从跳过/空号/失败升级为成功。
    """
    global _result_seen
    c = str(code or "").strip()
    if not c:
        return
    r = str(result or "done").strip().lower()
    if r in {"skip", "skipped"}:
        # 兼容旧路径：已存在完整条目记成功，不再进「跳过」
        r = "done"
    if r in {"not_found", "notfound"}:
        r = "empty"
    tid = str(_state.get("taskId") or "").strip()
    if r == "failed":
        in_soft = c in list(_state.get("skippedCodes") or []) or c in list(
            _state.get("emptyCodes") or []
        )
        if in_soft:
            _remove_from_result_buckets(c, "skippedCodes", "emptyCodes")
            fail_lst = list(_state.get("failedCodes") or [])
            if c not in fail_lst:
                _append_result_code("failedCodes", c)
            _state["failed"] = len(list(_state.get("failedCodes") or []))
            _result_seen.add(c)
            _reconcile_result_counts_locked()
            if tid:
                scrape_export_log_store.move_result_code(tid, c, to_bucket="failed")
            return
    if r == "empty":
        # 旧任务把全源无详情记成失败 → 迁到空号
        if c in list(_state.get("failedCodes") or []) or c in list(
            _state.get("skippedCodes") or []
        ):
            _remove_from_result_buckets(c, "failedCodes", "skippedCodes")
            if c not in list(_state.get("emptyCodes") or []):
                _append_result_code("emptyCodes", c)
            _state["empty"] = len(list(_state.get("emptyCodes") or []))
            _result_seen.add(c)
            _reconcile_result_counts_locked()
            if tid:
                scrape_export_log_store.move_result_code(tid, c, to_bucket="empty")
            return
    if r == "done":
        in_soft = (
            c in list(_state.get("skippedCodes") or [])
            or c in list(_state.get("emptyCodes") or [])
            or c in list(_state.get("failedCodes") or [])
        )
        if in_soft and c not in list(_state.get("doneCodes") or []):
            _remove_from_result_buckets(
                c, "skippedCodes", "emptyCodes", "failedCodes"
            )
            _append_result_code("doneCodes", c)
            _state["done"] = len(list(_state.get("doneCodes") or []))
            _result_seen.add(c)
            _reconcile_result_counts_locked()
            if tid:
                scrape_export_log_store.move_result_code(tid, c, to_bucket="done")
            return
    if _code_already_counted(c):
        return
    _result_seen.add(c)
    if r == "empty":
        _append_result_code("emptyCodes", c)
        _state["empty"] = len(list(_state.get("emptyCodes") or []))
        bucket = "empty"
    elif r == "failed":
        _append_result_code("failedCodes", c)
        _state["failed"] = len(list(_state.get("failedCodes") or []))
        bucket = "failed"
    else:
        _append_result_code("doneCodes", c)
        _state["done"] = len(list(_state.get("doneCodes") or []))
        bucket = "done"
    _reconcile_result_counts_locked()
    if tid:
        scrape_export_log_store.upsert_result_code(tid, bucket, c)


def _remove_active_code(code: str) -> None:
    """调用方须已持有 _meta_lock。"""
    c = str(code or "").strip()
    if not c:
        return
    for bucket in ("activeCodes", "activeFastCodes", "activeSlowCodes"):
        _state[bucket] = [
            x for x in list(_state.get(bucket) or []) if x != c
        ]


def _rebuild_active_from_inflight(
    inflight: dict[Any, tuple[str, dict[str, Any]]],
) -> None:
    """调用方须已持有 _meta_lock。用真实 inflight 重建进行中列表，避免串号/超槽。"""
    active: list[str] = []
    fast: list[str] = []
    slow: list[str] = []
    for kind, t in inflight.values():
        if not isinstance(t, dict):
            continue
        c = str(t.get("code") or "").strip()
        if not c:
            continue
        if c not in active:
            active.append(c)
        if kind == "slow":
            if c not in slow:
                slow.append(c)
        elif c not in fast:
            fast.append(c)
    _state["activeCodes"] = active
    _state["activeFastCodes"] = fast
    _state["activeSlowCodes"] = slow
    _state["active"] = len(active)


_state: dict[str, Any] = {
    "running": False,
    "paused": False,
    "startedAt": "",
    "finishedAt": "",
    "message": "",
    "total": 0,
    "done": 0,
    "failed": 0,
    "skipped": 0,
    "empty": 0,
    "active": 0,
    "doneCodes": [],
    "skippedCodes": [],
    "failedCodes": [],
    "emptyCodes": [],
    "activeCodes": [],
    "activeFastCodes": [],
    "activeSlowCodes": [],
    "pendingFast": 0,
    "pendingSlow": 0,
    "fastSlots": 0,
    "slowSlots": 0,
    "current": "",
    "region": "",
    "maker": "",
    "prefix": "",
    "codeFilter": "",
    "taskId": "",
    "taskName": "",
    "force": False,
    "mode": "incremental",
    "queue": [],
    "events": [],
    "currentDetail": None,
    # 用户暂停后阻止监控调度自动开刮（重启仍有效）
    "watchHold": False,
    "resumable": False,
    "pauseSaved": False,
    "allTargets": [],
}
_control: dict[str, bool] = {
    "cancel": False,
    "clearOnStop": False,
    # 暂停时立即打断进行中的 HTTP，worker 回队等待继续
    "pause_abort": False,
}
# 重置任务后：丢弃 worker 收尾 / persist_state 对任务卡的 max 合并写回
_discard_finish_persist_task_id = ""

# 进行中的刮削 HTTP 客户端，暂停/取消时 close 以立刻打断
_http_clients: set[Any] = set()
_http_clients_lock = threading.Lock()
# run_export 收尾时写入，供 finally 决定是否接下一项
_end_flags: dict[str, Any] = {
    "message": "",
    "clearOnStop": False,
    "hadError": False,
}
_persist_lock = threading.Lock()
_last_persist_mono = 0.0
# 进度心跳：用于识别「线程还活着但已空转」的假死
_last_progress_mono = 0.0


def _touch_progress() -> None:
    global _last_progress_mono
    _last_progress_mono = time.monotonic()


def _register_http_client(client: Any) -> None:
    with _http_clients_lock:
        _http_clients.add(client)


def _unregister_http_client(client: Any) -> None:
    with _http_clients_lock:
        _http_clients.discard(client)


def _abort_inflight_http() -> int:
    """关闭进行中的 httpx 客户端，打断阻塞的 scrape POST。"""
    with _http_clients_lock:
        clients = list(_http_clients)
        _http_clients.clear()
    n = 0
    for client in clients:
        try:
            client.close()
            n += 1
        except Exception:
            pass
    return n


def _abort_scrape_flare(origin: str | None = None) -> int:
    """通知 :9210 立刻打断排队/进行中的 FlareSolverr 请求。"""
    try:
        raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
        base = str(
            origin
            or raw.get("origin")
            or "http://127.0.0.1:9210"
        ).strip().rstrip("/")
        if not base.startswith("http"):
            base = f"http://{base}"
        with httpx.Client(timeout=3.0, trust_env=False) as client:
            r = client.post(f"{base}/api/scrape/abort")
        if r.status_code >= 400:
            return 0
        body = r.json() if r.content else {}
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, dict):
            return int(data.get("aborted") or 0)
        return 0
    except Exception as e:
        log.debug("abort scrape flare: %s", e)
        return 0


def _abort_all_inflight(*, origin: str | None = None) -> tuple[int, int]:
    """先打断 API→刮削 HTTP，再打断刮削侧过盾。返回 (http_n, flare_n)。"""
    http_n = _abort_inflight_http()
    flare_n = _abort_scrape_flare(origin)
    return http_n, flare_n


def _work_abort_kind() -> str | None:
    """cancel | paused | None。调用方可在任意阶段轮询。"""
    with _meta_lock:
        if _control.get("cancel"):
            return "cancel"
        if _state.get("paused") or _control.get("pause_abort"):
            return "paused"
    return None


def _clear_active_progress_locked() -> int:
    """清空进行中展示；调用方须已持有 _meta_lock。返回原 active 数。"""
    n = int(_state.get("active") or 0)
    _state["active"] = 0
    _state["activeCodes"] = []
    _state["activeFastCodes"] = []
    _state["activeSlowCodes"] = []
    _state["current"] = ""
    return n


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, 0, int(pid))
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _release_export_file_lock() -> None:
    try:
        if not _EXPORT_LOCK_PATH.is_file():
            return
        old = int(
            (_EXPORT_LOCK_PATH.read_text(encoding="utf-8") or "").strip() or "0"
        )
        if old in (0, os.getpid()):
            _EXPORT_LOCK_PATH.unlink()
    except OSError:
        pass


def _force_clear_export_file_lock() -> None:
    """丢弃残留锁文件（热重载/崩溃后内存已 idle，但磁盘锁仍在）。"""
    try:
        if _EXPORT_LOCK_PATH.is_file():
            _EXPORT_LOCK_PATH.unlink()
    except OSError:
        pass


def _export_worker_alive() -> bool:
    t = _export_worker
    return t is not None and t.is_alive()


def _reset_export_mutex_if_stale() -> None:
    """热重载/崩溃后 worker 已死但 threading.Lock 未 release 时重建。"""
    global _lock
    if _export_worker_alive():
        return
    try:
        if _lock.acquire(blocking=False):
            _lock.release()
            return
    except RuntimeError:
        pass
    _lock = threading.Lock()
    log.warning("scrape export: reset stale in-process mutex")


def _user_pause_hold_locked() -> bool:
    """用户暂停 / 监控抑制：不可当假死强行打断。"""
    msg = str(_state.get("message") or "")
    return bool(
        _state.get("paused")
        or _control.get("pause_abort")
        or _state.get("watchHold")
        or _state.get("pauseSaved")
        or msg == "paused"
    )


def _reconcile_stuck_export_state(*, persist: bool = False) -> None:
    """内存仍标记 running/building 但导出线程已不存在 → 清为 interrupted。
    另：worker 仍 alive 但 active=0 且长时间无进度（写完后假死 / 取消挂死）也强制解开。

    注意：用户「暂停」必须排除在外——否则约 45s 后会清掉 paused，
    等待中的 worker 会误以为已继续，自动恢复刮削（并被监控再次入队）。
    """
    global _last_progress_mono
    changed = False
    force_zombie = False
    with _meta_lock:
        running = bool(_state.get("running"))
        msg = str(_state.get("message") or "")
        active = int(_state.get("active") or 0)
        worker_alive = _export_worker_alive()
        user_pause = _user_pause_hold_locked()

        # 用户暂停中：worker 活着就原样保留；线程已死则固化为可续跑的暂停态
        if user_pause:
            if worker_alive:
                return
            _state.update(
                {
                    "running": False,
                    "paused": False,
                    "watchHold": True,
                    "pauseSaved": True,
                    "resumable": True,
                    "active": 0,
                    "activeCodes": [],
                    "activeFastCodes": [],
                    "activeSlowCodes": [],
                    "pendingFast": 0,
                    "pendingSlow": 0,
                    "finishedAt": str(_state.get("finishedAt") or "") or _now_iso(),
                    "message": "paused",
                }
            )
            _control["pause_abort"] = False
            _control["cancel"] = False
            changed = True
        else:
            # 假死：还在 scraping/cancelling，但无人在刮且超过 45s 无事件
            # 切勿把 paused 算进来（暂停本就是 active=0 长期等待）
            if (
                worker_alive
                and running
                and active <= 0
                and msg in ("scraping", "cancelling")
                and _last_progress_mono > 0
                and (time.monotonic() - _last_progress_mono) > 45.0
            ):
                force_zombie = True
                log.warning(
                    "scrape export: zombie progress (msg=%s active=0 idle=%.0fs) → interrupt",
                    msg,
                    time.monotonic() - _last_progress_mono,
                )

            # 取消中且已无活动番号：不必再等被卡死的 future
            if (
                worker_alive
                and running
                and msg == "cancelling"
                and active <= 0
                and _last_progress_mono > 0
                and (time.monotonic() - _last_progress_mono) > 8.0
            ):
                force_zombie = True
                log.warning("scrape export: cancelling with active=0 → force stop")

            if worker_alive and not force_zombie:
                return
            # 已 idle 但残留进行中展示（中断后未清 active）
            if (
                not running
                and not force_zombie
                and msg not in _STUCK_BUSY_MESSAGES
            ):
                ghost_active = (
                    int(_state.get("active") or 0) > 0
                    or bool(_state.get("activeCodes"))
                    or bool(_state.get("activeFastCodes"))
                    or bool(_state.get("activeSlowCodes"))
                )
                if not (ghost_active and not worker_alive):
                    return
                _clear_active_progress_locked()
                _state["pendingFast"] = 0
                _state["pendingSlow"] = 0
                changed = True
            else:
                _state.update(
                    {
                        "running": False,
                        "paused": False,
                        "active": 0,
                        "activeCodes": [],
                        "activeFastCodes": [],
                        "activeSlowCodes": [],
                        "pendingFast": 0,
                        "pendingSlow": 0,
                        "finishedAt": str(_state.get("finishedAt") or "") or _now_iso(),
                        "message": (
                            "cancelled"
                            if msg == "cancelling" or _control.get("clearOnStop")
                            else "interrupted"
                        ),
                    }
                )
                _control["cancel"] = False
                changed = True
    if changed:
        _force_clear_export_file_lock()
        _reset_export_mutex_if_stale()
        if persist:
            _persist_state(force=True)
        _touch_progress()
    else:
        _reset_export_mutex_if_stale()


def _export_boot_stuck() -> bool:
    """building/queued 长时间未进入 scraping，或 worker 已消失。"""
    with _meta_lock:
        if not _state.get("running"):
            return False
        msg = str(_state.get("message") or "")
        if msg not in ("building", "queued"):
            return False
        if not _export_worker_alive():
            return True
        active = int(_state.get("active") or 0)
        # 已有 total 仍可能卡在预跳过；active=0 且久无进度视为卡住
        if (
            active <= 0
            and _last_progress_mono > 0
            and (time.monotonic() - _last_progress_mono) > 45.0
        ):
            return True
        started = str(_state.get("startedAt") or "").strip()
        if not started:
            return False
        try:
            dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - dt).total_seconds()
        except Exception:
            return False
        # building 超过 90s 仍无人在刮
        return age > 90.0 and active <= 0


def _force_unstick_export(*, wait_dead: float = 5.0) -> bool:
    """强制解除卡住的导出（同任务重开 / 热重载后）。返回 True 表示可立刻开新任务。"""
    global _lock, _export_worker
    with _meta_lock:
        _control["cancel"] = True
        _control["clearOnStop"] = False
        _state.update(
            {
                "running": False,
                "paused": False,
                "active": 0,
                "activeCodes": [],
                "activeFastCodes": [],
                "activeSlowCodes": [],
                "pendingFast": 0,
                "pendingSlow": 0,
                "finishedAt": _now_iso(),
                "message": "interrupted",
            }
        )
    _force_clear_export_file_lock()
    if _export_worker_alive():
        deadline = time.monotonic() + wait_dead
        while time.monotonic() < deadline:
            if not _export_worker_alive():
                break
            time.sleep(0.05)
    if _export_worker_alive():
        log.warning("scrape export: force-unstick but worker still alive")
        return False
    with _meta_lock:
        _export_worker = None
    _reset_export_mutex_if_stale()
    log.warning("scrape export: force-unstick stuck boot state")
    return True


def _acquire_export_file_lock(*, steal_if_idle: bool = False) -> bool:
    """跨进程互斥：防止多开 uvicorn 时幽灵任务继续写盘。"""
    ok = _try_acquire_export_file_lock()
    if ok:
        return True
    if steal_if_idle:
        _force_clear_export_file_lock()
        return _try_acquire_export_file_lock()
    return False


def _try_acquire_export_file_lock() -> bool:
    _EXPORT_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    my = str(os.getpid())
    for _ in range(3):
        try:
            fd = os.open(
                str(_EXPORT_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY
            )
            try:
                os.write(fd, my.encode("utf-8"))
            finally:
                os.close(fd)
            return True
        except FileExistsError:
            try:
                old = int(
                    (_EXPORT_LOCK_PATH.read_text(encoding="utf-8") or "").strip()
                    or "0"
                )
            except Exception:
                old = 0
            if old == os.getpid() or not _pid_alive(old):
                try:
                    _EXPORT_LOCK_PATH.unlink()
                except OSError:
                    pass
                continue
            # uvicorn --reload 残留的 multiprocessing 子进程：父死后仍占锁
            parent_dead = False
            is_spawn = False
            try:
                import subprocess

                raw = subprocess.check_output(
                    [
                        "wmic",
                        "process",
                        "where",
                        f"ProcessId={old}",
                        "get",
                        "ParentProcessId,CommandLine",
                        "/value",
                    ],
                    text=True,
                    timeout=3,
                    stderr=subprocess.DEVNULL,
                )
                low = raw.lower()
                is_spawn = "multiprocessing.spawn" in low or "spawn_main" in low
                for line in raw.splitlines():
                    if line.startswith("ParentProcessId="):
                        try:
                            ppid = int(line.split("=", 1)[1].strip() or "0")
                        except ValueError:
                            ppid = 0
                        parent_dead = bool(ppid) and not _pid_alive(ppid)
                        break
            except Exception:
                pass
            if parent_dead or is_spawn:
                log.warning(
                    "scrape export: steal orphan lock pid=%s spawn=%s parent_dead=%s",
                    old,
                    is_spawn,
                    parent_dead,
                )
                try:
                    _EXPORT_LOCK_PATH.unlink()
                except OSError:
                    pass
                continue
            log.warning(
                "scrape export locked by pid=%s (this=%s)", old, os.getpid()
            )
            return False
    return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _queue_public(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("taskId") or "").strip()
        name = str(item.get("taskName") or item.get("name") or "").strip()
        out.append({"taskId": tid, "name": name})
    return out


def _snapshot_state() -> dict[str, Any]:
    with _meta_lock:
        _reconcile_result_counts_locked()
        detail = _state.get("currentDetail")
        mode = str(_state.get("mode") or "").strip().lower()
        if mode not in ("incremental", "force"):
            mode = "force" if _state.get("force") else "incremental"
        base = {
            "running": bool(_state.get("running")),
            "paused": bool(_state.get("paused")),
            "startedAt": _state.get("startedAt") or "",
            "finishedAt": _state.get("finishedAt") or "",
            "message": _state.get("message") or "",
            "total": int(_state.get("total") or 0),
            "done": int(_state.get("done") or 0),
            "failed": int(_state.get("failed") or 0),
            "skipped": int(_state.get("skipped") or 0),
            "empty": int(_state.get("empty") or 0),
            "active": int(_state.get("active") or 0),
            "doneCodes": list(_state.get("doneCodes") or []),
            "skippedCodes": list(_state.get("skippedCodes") or []),
            "failedCodes": list(_state.get("failedCodes") or []),
            "emptyCodes": list(_state.get("emptyCodes") or []),
            "activeCodes": list(_state.get("activeCodes") or []),
            "activeFastCodes": list(_state.get("activeFastCodes") or []),
            "activeSlowCodes": list(_state.get("activeSlowCodes") or []),
            "pendingFast": int(_state.get("pendingFast") or 0),
            "pendingSlow": int(_state.get("pendingSlow") or 0),
            "fastSlots": int(_state.get("fastSlots") or 0),
            "slowSlots": int(_state.get("slowSlots") or 0),
            "current": _state.get("current") or "",
            "region": _state.get("region") or "",
            "maker": _state.get("maker") or "",
            "prefix": _state.get("prefix") or "",
            "codeFilter": _state.get("codeFilter") or "",
            "taskId": _state.get("taskId") or "",
            "taskName": _state.get("taskName") or "",
            "force": bool(_state.get("force")),
            "mode": mode,
            "queue": _queue_public(_state.get("queue")),
            "events": list(_state.get("events") or []),
            "currentDetail": dict(detail) if isinstance(detail, dict) else None,
            "watchHold": bool(_state.get("watchHold")),
            "resumable": bool(_state.get("resumable")),
            "pauseSaved": bool(_state.get("pauseSaved")),
        }
    # 日志已落 SQLite，status.json 不再塞 eventsByCode
    return base


def _checkpoint_finished_codes() -> set[str]:
    with _meta_lock:
        out: set[str] = set()
        for bucket in ("doneCodes", "emptyCodes", "skippedCodes", "failedCodes"):
            for c in list(_state.get(bucket) or []):
                s = str(c or "").strip()
                if s:
                    out.add(s)
        return out


def _write_resume_checkpoint(
    *,
    all_targets: list[dict[str, Any]] | None = None,
    reason: str = "progress",
) -> None:
    """落盘断点：服务重启后可按已完成番号跳过，接着刮剩余。"""
    with _meta_lock:
        tid = str(_state.get("taskId") or "").strip()
        if not tid:
            return
        targets = list(all_targets or _state.get("allTargets") or [])
        if not targets:
            return
        finished = set()
        for bucket in ("doneCodes", "emptyCodes", "skippedCodes", "failedCodes"):
            for c in list(_state.get(bucket) or []):
                s = str(c or "").strip()
                if s:
                    finished.add(s)
        remaining = [
            t
            for t in targets
            if isinstance(t, dict)
            and str(t.get("code") or "").strip()
            and str(t.get("code") or "").strip() not in finished
        ]
        job = _state.get("currentJob")
        payload = {
            "version": 1,
            "reason": reason,
            "savedAt": _now_iso(),
            "taskId": tid,
            "taskName": str(_state.get("taskName") or ""),
            "paused": bool(_state.get("paused")) or reason == "paused",
            "message": "paused" if reason == "paused" else str(_state.get("message") or ""),
            "total": int(_state.get("total") or len(targets)),
            "done": int(_state.get("done") or 0),
            "empty": int(_state.get("empty") or 0),
            "skipped": int(_state.get("skipped") or 0),
            "failed": int(_state.get("failed") or 0),
            "doneCodes": list(_state.get("doneCodes") or []),
            "emptyCodes": list(_state.get("emptyCodes") or []),
            "skippedCodes": list(_state.get("skippedCodes") or []),
            "failedCodes": list(_state.get("failedCodes") or []),
            "allTargets": targets,
            "remainingTargets": remaining,
            "force": bool(_state.get("force")),
            "mode": str(_state.get("mode") or "incremental"),
            "exportFields": list(_state.get("exportFields") or []),
            "localFields": list(_state.get("localFields") or []),
            "region": str(_state.get("region") or ""),
            "maker": str(_state.get("maker") or ""),
            "prefix": str(_state.get("prefix") or ""),
            "codeFilter": str(_state.get("codeFilter") or ""),
            "currentJob": dict(job) if isinstance(job, dict) else None,
            "watchHold": True if reason == "paused" else bool(_state.get("watchHold")),
        }
        _state["allTargets"] = targets
        _state["resumable"] = len(remaining) > 0
        _state["pauseSaved"] = bool(payload["paused"])
    try:
        _RESUME_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _RESUME_PATH.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(_RESUME_PATH)
    except Exception as e:
        log.debug("write resume checkpoint: %s", e)


def _clear_resume_checkpoint() -> None:
    with _meta_lock:
        _state["resumable"] = False
        _state["pauseSaved"] = False
        _state["allTargets"] = []
    try:
        if _RESUME_PATH.is_file():
            _RESUME_PATH.unlink()
    except OSError:
        pass


def clear_task_resume(task_id: str) -> dict[str, Any]:
    """重置任务卡时清该任务断点 + 日志/结果，并清内存计数避免写回。"""
    global _result_seen, _discard_finish_persist_task_id
    tid = str(task_id or "").strip()
    if not tid:
        raise RuntimeError("缺少 taskId")
    resume = _load_resume_checkpoint()
    cleared = False
    if resume and str(resume.get("taskId") or "").strip() == tid:
        _clear_resume_checkpoint()
        cleared = True
    # 重置：结果桶 + 过程日志一并清掉
    scraped = scrape_export_log_store.purge_task_logs(tid)
    with _meta_lock:
        # 丢弃本轮 worker 收尾的旧计数 max 写回（暂停后重置竞态）
        _discard_finish_persist_task_id = tid
        same = str(_state.get("taskId") or "").strip() == tid
        running = bool(_state.get("running"))
        if same:
            # 必须清内存，否则随后 _persist_state 会把旧 skipped/failed 写回任务卡
            _result_seen = set()
            _state["done"] = 0
            _state["skipped"] = 0
            _state["empty"] = 0
            _state["failed"] = 0
            _state["total"] = 0
            _state["doneCodes"] = []
            _state["skippedCodes"] = []
            _state["emptyCodes"] = []
            _state["failedCodes"] = []
            _state["active"] = 0
            _state["activeCodes"] = []
            _state["activeFastCodes"] = []
            _state["activeSlowCodes"] = []
            _state["pendingFast"] = 0
            _state["pendingSlow"] = 0
            _state["current"] = ""
            _state["currentDetail"] = None
            _state["events"] = []
            _state["resumable"] = False
            _state["pauseSaved"] = False
            _state["allTargets"] = []
            if not running:
                if str(_state.get("message") or "") in {
                    "paused",
                    "scraping",
                    "building",
                    "cancelling",
                    "ok",
                    "interrupted",
                }:
                    _state["message"] = ""
    # 任务卡计数立刻置零（勿走 max 合并）
    _replace_task_result_counts(tid)
    # 只落 status 快照；带 discard 标记时勿再 max 抬高任务卡
    _persist_state(force=True)
    if cleared:
        _push_event(
            phase="job",
            text=f"已清除断点续跑 · {tid}",
            level="info",
            archive=False,
        )
    if scraped.get("events") or scraped.get("codes"):
        _push_event(
            phase="job",
            text=(
                f"已清理任务日志 · 事件 {scraped.get('events') or 0}"
                f" · 番号 {scraped.get('codes') or 0}"
            ),
            level="info",
            archive=False,
        )
    return export_status()


def purge_task_logs(task_id: str) -> dict[str, Any]:
    """删除任务卡：清该任务 SQLite 日志与结果番号。"""
    tid = str(task_id or "").strip()
    if not tid:
        raise RuntimeError("缺少 taskId")
    stats = scrape_export_log_store.purge_task_logs(tid)
    # 顺带清断点
    resume = _load_resume_checkpoint()
    if resume and str(resume.get("taskId") or "").strip() == tid:
        _clear_resume_checkpoint()
    return {"taskId": tid, **stats}


def _load_resume_checkpoint() -> dict[str, Any] | None:
    if not _RESUME_PATH.is_file():
        return None
    try:
        data = json.loads(_RESUME_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.debug("load resume checkpoint: %s", e)
        return None
    if not isinstance(data, dict):
        return None
    if not str(data.get("taskId") or "").strip():
        return None
    return data


def _apply_resume_checkpoint_to_state(data: dict[str, Any]) -> None:
    """服务重启后：恢复计数与可续跑标记，界面显示已暂停/已中断。"""
    paused = bool(data.get("paused")) or str(data.get("message") or "") == "paused"
    remaining = [
        t
        for t in list(data.get("remainingTargets") or [])
        if isinstance(t, dict) and str(t.get("code") or "").strip()
    ]
    all_targets = [
        t
        for t in list(data.get("allTargets") or [])
        if isinstance(t, dict) and str(t.get("code") or "").strip()
    ]
    with _meta_lock:
        _state.update(
            {
                "running": False,
                "paused": False,
                "resumable": bool(remaining) or bool(all_targets),
                "pauseSaved": paused,
                "watchHold": bool(data.get("watchHold")) or paused,
                "startedAt": str(data.get("savedAt") or data.get("startedAt") or ""),
                "finishedAt": _now_iso(),
                "message": "paused" if paused else "interrupted",
                "total": int(data.get("total") or 0),
                "done": int(data.get("done") or 0),
                "empty": int(data.get("empty") or 0),
                "skipped": int(data.get("skipped") or 0),
                "failed": int(data.get("failed") or 0),
                "active": 0,
                "doneCodes": list(data.get("doneCodes") or [])[-_MAX_RESULT_CODES:],
                "emptyCodes": list(data.get("emptyCodes") or [])[
                    -_MAX_RESULT_CODES:
                ],
                "skippedCodes": list(data.get("skippedCodes") or [])[
                    -_MAX_RESULT_CODES:
                ],
                "failedCodes": list(data.get("failedCodes") or [])[
                    -_MAX_RESULT_CODES:
                ],
                "activeCodes": [],
                "activeFastCodes": [],
                "activeSlowCodes": [],
                "pendingFast": len(remaining),
                "pendingSlow": 0,
                "current": "",
                "region": str(data.get("region") or ""),
                "maker": str(data.get("maker") or ""),
                "prefix": str(data.get("prefix") or ""),
                "codeFilter": str(data.get("codeFilter") or ""),
                "taskId": str(data.get("taskId") or ""),
                "taskName": str(data.get("taskName") or ""),
                "force": bool(data.get("force")),
                "mode": (
                    "force"
                    if str(data.get("mode") or "").strip().lower() == "force"
                    or data.get("force")
                    else "incremental"
                ),
                "exportFields": list(data.get("exportFields") or []),
                "localFields": list(data.get("localFields") or []),
                "allTargets": all_targets or remaining,
                "currentJob": (
                    dict(data["currentJob"])
                    if isinstance(data.get("currentJob"), dict)
                    else None
                ),
            }
        )
    # 同步到任务卡存档，避免刷新后变「待开始 / 全 0」
    try:
        _persist_task_result(
            str(data.get("taskId") or ""),
            message="已暂停" if paused else "已中断",
            done=int(data.get("done") or 0),
            empty=int(data.get("empty") or 0),
            skipped=int(data.get("skipped") or 0),
            failed=int(data.get("failed") or 0),
            total=int(data.get("total") or 0),
            done_codes=list(data.get("doneCodes") or []),
            empty_codes=list(data.get("emptyCodes") or []),
            skipped_codes=list(data.get("skippedCodes") or []),
            failed_codes=list(data.get("failedCodes") or []),
        )
    except Exception:
        log.exception("persist paused task after hydrate failed")


def peek_resume_for_task(task_id: str) -> dict[str, Any] | None:
    """若磁盘断点属于该 taskId，返回摘要（前端决定是否续跑）。"""
    data = _load_resume_checkpoint()
    if not data:
        return None
    if str(data.get("taskId") or "").strip() != str(task_id or "").strip():
        return None
    remaining = data.get("remainingTargets") or []
    return {
        "taskId": str(data.get("taskId") or ""),
        "paused": bool(data.get("paused")),
        "done": int(data.get("done") or 0),
        "empty": int(data.get("empty") or 0),
        "skipped": int(data.get("skipped") or 0),
        "failed": int(data.get("failed") or 0),
        "total": int(data.get("total") or 0),
        "remaining": len(remaining) if isinstance(remaining, list) else 0,
        "mode": str(data.get("mode") or ""),
    }


def _coerce_force_mode(
    *,
    force: bool = False,
    mode: str | None = None,
    task_id: str | None = None,
) -> tuple[bool, str]:
    """统一解析强制/增量。显式 mode 优先；否则看 force；再回退已存任务配置。"""
    mode_key = str(mode or "").strip().lower()
    if mode_key == "force":
        return True, "force"
    if mode_key == "incremental":
        return False, "incremental"
    if force:
        return True, "force"
    tid = str(task_id or "").strip()
    if tid:
        try:
            raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
            for t in scrape_profiles.normalize_scrape_tasks(
                raw.get("scrapeTasks") or raw.get("scrape_tasks")
            ):
                if str(t.get("id") or "").strip() != tid:
                    continue
                if str(t.get("mode") or "").strip().lower() == "force":
                    return True, "force"
                break
        except Exception:
            pass
    return False, "incremental"


def _find_scrape_task(task_id: str) -> dict[str, Any] | None:
    tid = str(task_id or "").strip()
    if not tid:
        return None
    try:
        raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
        for t in scrape_profiles.normalize_scrape_tasks(
            raw.get("scrapeTasks") or raw.get("scrape_tasks")
        ):
            if str(t.get("id") or "").strip() == tid:
                return t
    except Exception:
        log.exception("find scrape task failed")
    return None


def _task_export_opts(task: dict[str, Any]) -> dict[str, Any]:
    """从任务卡解析可热更新项：字段 / 本地复用 / 模式 / 名称 / 范围展示。"""
    fields = scrape_profiles.normalize_export_fields(task.get("fields"))
    local = [
        f
        for f in scrape_profiles.normalize_local_fields(task.get("localFields"))
        if f in set(fields)
    ]
    is_force, mode_key = _coerce_force_mode(
        force=False,
        mode=str(task.get("mode") or "") or None,
        task_id=str(task.get("id") or "") or None,
    )
    regions = [str(r).strip() for r in (task.get("regions") or []) if str(r).strip()]
    region_label = ",".join(regions)
    return {
        "fields": fields,
        "localFields": local,
        "force": bool(is_force),
        "mode": mode_key,
        "taskName": str(task.get("name") or "").strip(),
        "maker": str(task.get("maker") or "").strip(),
        "prefix": str(task.get("prefix") or "").strip(),
        "code": str(task.get("code") or "").strip(),
        "regions": regions,
        "region": region_label,
    }


def sync_running_task_from_settings() -> bool:
    """任务卡保存后：若当前导出正是该任务（含暂停），立刻热更新字段/模式等到内存状态。

    范围（厂牌/前缀）变更只更新展示与 currentJob；已入队番号列表不重建，
    续跑仍按原队列，下一次「开始」才按新范围收集。
    """
    with _meta_lock:
        if not _state.get("running"):
            return False
        tid = str(_state.get("taskId") or "").strip()
    if not tid:
        return False
    task = _find_scrape_task(tid)
    if not task:
        return False
    opts = _task_export_opts(task)
    with _meta_lock:
        if str(_state.get("taskId") or "").strip() != tid:
            return False
        _state["exportFields"] = list(opts["fields"])
        _state["localFields"] = list(opts["localFields"])
        _state["force"] = bool(opts["force"])
        _state["mode"] = str(opts["mode"])
        if opts["taskName"]:
            _state["taskName"] = opts["taskName"]
        _state["maker"] = opts["maker"]
        _state["prefix"] = opts["prefix"]
        _state["codeFilter"] = opts["code"]
        if opts["region"]:
            _state["region"] = opts["region"]
        cur = _state.get("currentJob")
        if isinstance(cur, dict):
            cur = dict(cur)
            cur["fields"] = list(opts["fields"])
            cur["localFields"] = list(opts["localFields"])
            cur["force"] = bool(opts["force"])
            cur["mode"] = str(opts["mode"])
            cur["taskName"] = opts["taskName"] or cur.get("taskName")
            cur["maker"] = opts["maker"] or None
            cur["prefix"] = opts["prefix"] or None
            cur["code"] = opts["code"] or None
            cur["regions"] = list(opts["regions"]) or None
            _state["currentJob"] = cur
    _push_event(
        phase="job",
        text=(
            "已应用任务卡修改"
            + (f" · {opts['taskName']}" if opts["taskName"] else "")
            + f" · 模式 {'强制重刮' if opts['force'] else '增量'}"
            + (
                f" · 字段 {'/'.join(opts['fields'])}"
                if opts["fields"]
                else ""
            )
        ),
        level="info",
    )
    _persist_state(force=True)
    return True


# 任务勾选字段里：白名单不强制有值（站上常无）；其余勾选字段缺值 → 失败
_OPTIONAL_EXPORT_FIELDS = frozenset({"series", "outline", "studio", "publisher"})
_REQUIRED_VALUE_FIELDS = frozenset({"titleZh", "actors", "tags", "cover"})


def _field_labels_zh() -> dict[str, str]:
    return {
        "cover": "封面",
        "titleZh": "中文标题",
        "outline": "简介",
        "studio": "制片",
        "publisher": "发行",
        "actors": "女优",
        "tags": "标签",
        "series": "系列",
    }


def _meta_missing_required_fields(
    raw: dict[str, Any],
    *,
    entry_dir: Path | None,
    poster_name: str,
    need_cover: bool,
    export_fields: list[str] | None,
) -> list[str]:
    """对照任务勾选字段：返回缺值的强制字段（系列等白名单不计入）。"""
    want = set(_normalize_fields(export_fields))
    if not want:
        return []
    missing: list[str] = []
    for f in _normalize_fields(export_fields):
        if f in _OPTIONAL_EXPORT_FIELDS:
            continue
        if f == "cover":
            if not need_cover:
                continue
            ok_cover = False
            if entry_dir is not None and entry_dir.is_dir():
                ok_cover = (entry_dir / poster_name).is_file() or (
                    entry_dir / "poster.jpg"
                ).is_file()
            if not ok_cover and not str(
                raw.get("poster") or raw.get("coverUrl") or ""
            ).strip():
                missing.append(f)
            continue
        if f == "titleZh":
            zh = str(raw.get("titleZh") or raw.get("title_zh") or "").strip()
            code = str(raw.get("code") or "").strip()
            fs = (
                raw.get("fieldSources")
                if isinstance(raw.get("fieldSources"), dict)
                else {}
            )
            zh_src = str(fs.get("titleZh") or "").strip().lower()
            if zh_src and zh_src not in {
                "",
                "index",
                "forum",
                "maker-fs",
                "seed",
                "local",
            }:
                if not zh:
                    missing.append(f)
            elif not is_quality_chinese_title(zh, code):
                missing.append(f)
        elif f == "actors":
            actors = raw.get("actors") if isinstance(raw.get("actors"), list) else []
            if not actors:
                actress = (
                    raw.get("actress") if isinstance(raw.get("actress"), list) else []
                )
                if not actress:
                    missing.append(f)
        elif f == "tags":
            tags = raw.get("genres") if isinstance(raw.get("genres"), list) else []
            if not tags:
                tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
            if not tags:
                missing.append(f)
    return missing


def _entry_complete(
    entry_dir: Path | None,
    *,
    poster_name: str,
    need_cover: bool,
    export_fields: list[str] | None = None,
) -> bool:
    """增量跳过条件：对照任务勾选字段是否齐。

    - 只检查任务编辑里勾选的字段
    - 系列 / 简介 / 制片等白名单：不强制有值
    - 中文标题 / 女优 / 标签 / 封面：勾选了则必须有值
    - not_found 空号标记：算完成
    """
    if entry_dir is None or not entry_dir.is_dir():
        return False
    meta_path = entry_dir / SCRAPE_META_FILE
    if not meta_path.is_file():
        # 兼容旧目录：刮削曾写在 meta.json
        legacy = entry_dir / INDEX_META_FILE
        if legacy.is_file():
            try:
                raw = json.loads(legacy.read_text(encoding="utf-8"))
            except Exception:
                return False
            if not isinstance(raw, dict):
                return False
            if not (
                raw.get("scrapedAt")
                or raw.get("exportFields")
                or raw.get("sourceRuns")
            ):
                return False
            meta_path = legacy
        else:
            return False
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(raw, dict):
        return False

    def _prev_export_fields(data: dict[str, Any]) -> set[str]:
        out: set[str] = set()
        for x in data.get("exportFields") or []:
            key = str(x or "").strip()
            low = key.lower()
            if key in {
                "cover",
                "titleZh",
                "outline",
                "actors",
                "tags",
                "series",
                "studio",
                "publisher",
            }:
                out.add(key)
            elif low in {"title_zh", "titlezh"}:
                out.add("titleZh")
            elif low in {"plot"}:
                out.add("outline")
            elif low in {"genres", "genre"}:
                out.add("tags")
        return out

    want = set(_normalize_fields(export_fields))
    prev_norm = _prev_export_fields(raw)
    if _is_confirmed_empty_meta(raw):
        # 空号终态；新增强制字段才重刮，白名单变更不触发
        required_want = want - _OPTIONAL_EXPORT_FIELDS
        if not required_want or required_want <= prev_norm:
            return True
        return False

    # 新增勾选的强制字段 → 未完成；白名单不挡完成
    for f in want:
        if f in _OPTIONAL_EXPORT_FIELDS:
            continue
        if f not in prev_norm and f != "cover":
            return False

    return not _meta_missing_required_fields(
        raw,
        entry_dir=entry_dir,
        poster_name=poster_name,
        need_cover=need_cover,
        export_fields=export_fields,
    )

def _resolve_target_entry_dir(target: dict[str, Any], library: Path) -> Path | None:
    """按命名规则定位目标目录；不存在则回退扫描。"""
    code = _std_code(str(target.get("code") or ""))
    if not code:
        return None
    rid = str(target.get("region") or "")
    label = _region_label(rid)
    naming_cfg = scrape_naming.fixed_naming()
    kind_id = scrape_naming.resolve_kind(
        region=rid,
        code=code,
    )
    try:
        cand = scrape_naming.resolve_entry_dir(
            library,
            naming_cfg,
            code=code,
            meta={
                "code": code,
                "prefix": target.get("prefix"),
                "maker": target.get("maker"),
                "region": rid,
                "regionLabel": label,
            },
            target=target,
            category=label,
            kind=kind_id,
        )
        if cand.is_dir():
            return cand
    except Exception:
        pass
    return _find_library_entry_dir(code)


def _bulk_skip_complete_targets(
    targets: list[dict[str, Any]],
    *,
    library: Path,
    export_fields: list[str],
) -> list[dict[str, Any]]:
    """增量：按本地真实状态立刻入桶，只把「未完成」送进工作池。

    - 已刮成功 → done（成功）
    - 已落盘 not_found（全源确认无详情）→ empty（空号）
    - 未完成（含 maker-fs 补全空种子 / 无封面空洞）→ pending 进网刮；
      空号只能由 worker 全源无详情后写入，禁止预分类直接跳过进网
    """
    global _result_seen
    need_cover = "cover" in set(_normalize_fields(export_fields))
    poster_name = "poster.jpg"
    pending: list[dict[str, Any]] = []
    done_codes: list[str] = []
    empty_codes: list[str] = []
    for t in targets:
        if not isinstance(t, dict):
            continue
        c = str(t.get("code") or "").strip()
        if not c:
            continue
        entry = _resolve_target_entry_dir(t, library)
        if not _entry_complete(
            entry,
            poster_name=poster_name,
            need_cover=need_cover,
            export_fields=export_fields,
        ):
            # 未完成（含无封面补全种子）：进队刮削，勿当空号
            pending.append(t)
            continue
        rid = str(t.get("region") or "")
        kind_id = scrape_naming.resolve_kind(region=rid, code=_std_code(c) or c)
        # FC2 未分类：与单条路径一致，仍进队搬家/补刮
        if (
            kind_id == "fc2"
            and entry is not None
            and _path_has_uncategorized(entry)
        ):
            pending.append(t)
            continue
        existing = _load_scrape_meta(entry) if entry is not None else None
        if not existing and entry is not None:
            existing = _load_index_meta(entry)
        if _is_confirmed_empty_meta(existing):
            empty_codes.append(c)
        else:
            done_codes.append(c)

    tid = ""
    with _meta_lock:
        tid = str(_state.get("taskId") or "").strip()
        for c in done_codes:
            if _code_already_counted(c):
                # 允许从旧跳过/空号/失败升级为成功
                if c in list(_state.get("doneCodes") or []):
                    continue
                if c in list(_state.get("skippedCodes") or []) or c in list(
                    _state.get("emptyCodes") or []
                ) or c in list(_state.get("failedCodes") or []):
                    _remove_from_result_buckets(
                        c, "skippedCodes", "emptyCodes", "failedCodes"
                    )
                    _append_result_code("doneCodes", c)
                    _result_seen.add(c)
                continue
            _result_seen.add(c)
            _append_result_code("doneCodes", c)
        for c in empty_codes:
            # 允许从旧「失败」桶迁到空号（全源无详情本应为空号）
            if c in list(_state.get("failedCodes") or []) or c in list(
                _state.get("skippedCodes") or []
            ):
                _remove_from_result_buckets(c, "failedCodes", "skippedCodes")
                if c not in list(_state.get("emptyCodes") or []):
                    _append_result_code("emptyCodes", c)
                _result_seen.add(c)
                continue
            if _code_already_counted(c):
                continue
            _result_seen.add(c)
            _append_result_code("emptyCodes", c)
        _state["done"] = len(list(_state.get("doneCodes") or []))
        _state["empty"] = len(list(_state.get("emptyCodes") or []))
        _state["skipped"] = len(list(_state.get("skippedCodes") or []))
        _state["failed"] = len(list(_state.get("failedCodes") or []))
        _reconcile_result_counts_locked()

    if tid and (done_codes or empty_codes):
        try:
            scrape_export_log_store.bulk_upsert_result_codes(
                tid,
                done=done_codes,
                empty=empty_codes,
            )
        except Exception:
            log.exception("bulk classify persist codes failed")

    if done_codes or empty_codes or pending:
        _push_event(
            phase="job",
            text=(
                f"增量预分类 · 成功 {len(done_codes)}"
                + (f" · 空号 {len(empty_codes)}" if empty_codes else "")
                + f" · 待刮 {len(pending)}"
            ),
            level="info",
        )
        _touch_progress()
    return pending


def _write_not_found_marker(
    entry_dir: Path,
    *,
    code: str,
    export_fields: list[str],
    meta: dict[str, Any] | None = None,
    runs: list[Any] | None = None,
) -> None:
    """无数据空号落盘 scrape.json（快源识别不到）。"""
    if entry_dir is None or not entry_dir.is_dir():
        return
    run_list = list(runs or (meta or {}).get("sourceRuns") or [])
    # 有 runs 时须全是无详情；空 runs 允许（快源直接 not_found / 旧标记）
    if run_list and not _all_network_sources_no_detail(run_list):
        return
    want = _normalize_fields(export_fields)
    prev = _load_scrape_meta(entry_dir) or {}
    payload = {
        **{k: v for k, v in (prev or {}).items() if k not in ("fanart", "coverBase64")},
        **{k: v for k, v in (meta or {}).items() if k not in ("fanart", "coverBase64")},
        "code": _std_code(code) or code,
        "ok": False,
        "message": "not_found",
        "exportFields": want,
        "scrapedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sourceRuns": run_list,
    }
    if not str(payload.get("poster") or "").strip():
        payload.pop("poster", None)
        payload.pop("coverUrl", None)
    scrape_path = entry_dir / SCRAPE_META_FILE
    tmp = entry_dir / (SCRAPE_META_FILE + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(scrape_path)
    try:
        from . import library_materialize

        library_materialize.upsert_region_facet_entry(
            entry_dir,
            region=str(payload.get("region") or "") or None,
            studio=str(payload.get("studio") or payload.get("maker") or "") or None,
            prefix=str(payload.get("prefix") or "") or None,
            code=str(payload.get("code") or "") or None,
        )
    except Exception:
        log.debug("facet upsert after not_found failed", exc_info=True)


def _patch_scrape_meta_file(entry_dir: Path, meta: dict[str, Any]) -> None:
    """轻量写回 scrape.json（增量跳过时补本地女优等）。"""
    if entry_dir is None or not entry_dir.is_dir():
        return
    payload = {
        k: v
        for k, v in (meta or {}).items()
        if k not in ("fanart", "coverBase64")
    }
    if not payload:
        return
    scrape_path = entry_dir / SCRAPE_META_FILE
    tmp = entry_dir / (SCRAPE_META_FILE + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(scrape_path)
    try:
        from . import library_materialize

        library_materialize.upsert_region_facet_entry(
            entry_dir,
            region=str(payload.get("region") or "") or None,
            studio=str(payload.get("studio") or payload.get("maker") or "") or None,
            prefix=str(payload.get("prefix") or "") or None,
            code=str(payload.get("code") or "") or None,
        )
    except Exception:
        log.debug("facet upsert after patch failed", exc_info=True)


def _make_export_job(
    *,
    task_id: str | None = None,
    task_name: str | None = None,
    region: str | None = None,
    regions: list[str] | None = None,
    maker: str | None = None,
    prefix: str | None = None,
    code: str | None = None,
    codes: list[str] | None = None,
    force: bool = False,
    mode: str | None = None,
    fields: list[str] | None = None,
    local_fields: list[str] | None = None,
) -> dict[str, Any]:
    region_list = [str(r).strip() for r in (regions or []) if str(r).strip()]
    tid = str(task_id or "").strip()
    is_force, mode_key = _coerce_force_mode(force=force, mode=mode, task_id=tid)
    code_list = _parse_export_code_filters(code, codes)
    code_joined = "，".join(code_list) if code_list else ""
    name = str(task_name or "").strip()
    if not name:
        bits = [
            x
            for x in (
                ",".join(region_list) if region_list else (region or ""),
                (maker or "").strip(),
                (prefix or "").strip(),
                code_joined
                if len(code_list) <= 3
                else (f"{code_list[0]}…等{len(code_list)}个" if code_list else ""),
            )
            if x
        ]
        name = "/".join(bits) if bits else "刮削任务"
    export_fields = (
        scrape_profiles.normalize_export_fields(fields)
        if fields is not None
        else None
    )
    local_norm = scrape_profiles.normalize_local_fields(local_fields)
    if export_fields is not None:
        allow = set(export_fields)
        local_norm = [f for f in local_norm if f in allow]
    return {
        "taskId": tid,
        "taskName": name,
        "region": (region or "").strip() or None,
        "regions": region_list or None,
        "maker": (maker or "").strip() or None,
        "prefix": (prefix or "").strip() or None,
        "code": code_joined or None,
        "codes": code_list or None,
        "force": bool(is_force),
        "mode": mode_key,
        "fields": export_fields,
        "localFields": local_norm,
        "fromWatch": False,
    }


def _job_in_flight(job: dict[str, Any]) -> bool:
    tid = str(job.get("taskId") or "").strip()
    if not tid:
        return False
    if str(_state.get("taskId") or "").strip() == tid and _state.get("running"):
        return True
    for item in _state.get("queue") or []:
        if isinstance(item, dict) and str(item.get("taskId") or "").strip() == tid:
            return True
    return False


def _prime_state_for_job(job: dict[str, Any], *, keep_lock_message: str = "queued") -> None:
    """切换到下一队列任务（仍视为 running，文件锁不放）。"""
    global _result_seen
    regions = job.get("regions") or []
    region_label = ",".join(str(r) for r in regions if r) if regions else str(job.get("region") or "")
    is_force, mode_key = _coerce_force_mode(
        force=bool(job.get("force")),
        mode=str(job.get("mode") or "") or None,
        task_id=str(job.get("taskId") or "") or None,
    )
    _control["cancel"] = False
    _control["clearOnStop"] = False
    _control["pause_abort"] = False
    _result_seen = set()
    _state["currentJob"] = dict(job)
    _state.update(
        {
            "running": True,
            "paused": False,
            "startedAt": _now_iso(),
            "finishedAt": "",
            "message": keep_lock_message,
            "total": 0,
            "done": 0,
            "failed": 0,
            "skipped": 0,
            "empty": 0,
            "active": 0,
            "doneCodes": [],
            "skippedCodes": [],
            "failedCodes": [],
            "emptyCodes": [],
            "activeCodes": [],
            "activeFastCodes": [],
            "activeSlowCodes": [],
            "pendingFast": 0,
            "pendingSlow": 0,
            "current": "",
            "region": region_label,
            "maker": str(job.get("maker") or ""),
            "prefix": str(job.get("prefix") or ""),
            "codeFilter": str(job.get("code") or ""),
            "taskId": str(job.get("taskId") or ""),
            "taskName": str(job.get("taskName") or ""),
            "force": bool(is_force),
            "mode": mode_key,
            "exportFields": scrape_profiles.normalize_export_fields(
                job.get("fields")
            ),
            "localFields": scrape_profiles.normalize_local_fields(
                job.get("localFields") or job.get("local_fields")
            ),
            "events": [],
            "currentDetail": None,
            "resumable": False,
            "pauseSaved": False,
            "fromWatch": bool(job.get("fromWatch")),
        }
    )
    _clear_pending_detail_display()


def _spawn_export_thread(job: dict[str, Any]) -> None:
    global _export_worker

    def _runner() -> None:
        try:
            is_force, mode_key = _coerce_force_mode(
                force=bool(job.get("force")),
                mode=str(job.get("mode") or "") or None,
                task_id=str(job.get("taskId") or "") or None,
            )
            run_export(
                region=job.get("region"),
                regions=job.get("regions"),
                maker=job.get("maker"),
                prefix=job.get("prefix"),
                code=job.get("code"),
                codes=job.get("codes"),
                force=is_force,
                mode=mode_key,
                fields=job.get("fields"),
                local_fields=job.get("localFields") or job.get("local_fields"),
                task_id=str(job.get("taskId") or "") or None,
                task_name=str(job.get("taskName") or "") or None,
                from_claim=True,
            )
        except Exception:
            # run_export 的 finally 已负责结束态 / 转下一项
            log.exception("scrape export job failed task=%s", job.get("taskId") or "")
        finally:
            global _export_worker
            if threading.current_thread() is _export_worker:
                _export_worker = None

    t = threading.Thread(
        target=_runner,
        daemon=True,
        name=f"scrape-export-{job.get('taskId') or 'job'}",
    )
    _export_worker = t
    t.start()


def submit_export_job(
    *,
    task_id: str | None = None,
    task_name: str | None = None,
    region: str | None = None,
    regions: list[str] | None = None,
    maker: str | None = None,
    prefix: str | None = None,
    code: str | None = None,
    codes: list[str] | None = None,
    force: bool = False,
    mode: str | None = None,
    fields: list[str] | None = None,
    local_fields: list[str] | None = None,
    from_watch: bool = False,
) -> dict[str, Any]:
    """空闲则立刻开跑；忙碌则入队（同 taskId 去重并更新参数）。不再因忙碌 409。

    当前任务已暂停时：点另一任务「开始」可立刻切换开跑（暂停任务回队），仍保证同时只跑一个。
    """
    _reconcile_stuck_export_state()
    if _export_boot_stuck():
        _force_unstick_export()
        _reconcile_stuck_export_state()
    job = _make_export_job(
        task_id=task_id,
        task_name=task_name,
        region=region,
        regions=regions,
        maker=maker,
        prefix=prefix,
        code=code,
        codes=codes,
        force=force,
        mode=mode,
        fields=fields,
        local_fields=local_fields,
    )
    job["fromWatch"] = bool(from_watch)
    start_now = False
    notify_pause = False
    with _meta_lock:
        # 监控入队不得在用户暂停/抑制期间偷偷开跑
        if from_watch and _user_pause_hold_locked():
            return export_status()
        if not from_watch:
            _state["watchHold"] = False
        tid = str(job.get("taskId") or "").strip()
        cur_tid = str(_state.get("taskId") or "").strip()
        if _state.get("running"):
            same_task = bool(tid and cur_tid == tid)
            paused_now = bool(_state.get("paused") or _control.get("pause_abort"))
            if same_task:
                # 暂停中再点开始 → 继续本任务
                if paused_now and not _export_boot_stuck() and _export_worker_alive():
                    _control["pause_abort"] = False
                    _state["paused"] = False
                    _state["watchHold"] = False
                    _state["message"] = "scraping"
                    notify_pause = True
                    # fall through to notify outside lock
                else:
                    new_fields = scrape_profiles.normalize_export_fields(
                        job.get("fields")
                    )
                    cur_fields = scrape_profiles.normalize_export_fields(
                        _state.get("exportFields")
                    )
                    fields_changed = new_fields != cur_fields
                    force_codes = bool(job.get("force")) and bool(
                        job.get("codes") or job.get("code")
                    )
                    if not _export_boot_stuck() and _export_worker_alive():
                        if not fields_changed and not force_codes:
                            return export_status()
                        _state["pendingRestart"] = job
                        _control["cancel"] = True
                        return export_status()
                    if not _force_unstick_export():
                        _state["pendingRestart"] = job
                        return export_status()
                    # unstick 成功后继续下方开跑
            elif paused_now and _export_worker_alive():
                # 暂停中启动另一任务：当前任务回队首，新任务 pendingRestart 后取消切换
                cur_job = _state.get("currentJob")
                if not isinstance(cur_job, dict) or not str(
                    cur_job.get("taskId") or ""
                ).strip():
                    cur_job = _make_export_job(
                        task_id=cur_tid,
                        task_name=str(_state.get("taskName") or ""),
                        region=str(_state.get("region") or "") or None,
                        maker=str(_state.get("maker") or "") or None,
                        prefix=str(_state.get("prefix") or "") or None,
                        code=str(_state.get("codeFilter") or "") or None,
                        force=bool(_state.get("force")),
                        mode=str(_state.get("mode") or "") or None,
                        fields=list(_state.get("exportFields") or []),
                        local_fields=list(_state.get("localFields") or []),
                    )
                queue = list(_state.get("queue") or [])
                # 去掉队列里同 id 的旧项，再把暂停任务插到队首
                cur_id = str(cur_job.get("taskId") or "").strip()
                queue = [
                    x
                    for x in queue
                    if not (
                        isinstance(x, dict)
                        and str(x.get("taskId") or "").strip() == cur_id
                    )
                ]
                # 新任务若已在队列，先去掉（马上开跑）
                if tid:
                    queue = [
                        x
                        for x in queue
                        if not (
                            isinstance(x, dict)
                            and str(x.get("taskId") or "").strip() == tid
                        )
                    ]
                queue.insert(0, dict(cur_job))
                _state["queue"] = queue
                _state["pendingRestart"] = job
                _control["clearOnStop"] = False
                _control["pause_abort"] = False
                _state["paused"] = False
                _control["cancel"] = True
                _state["message"] = "cancelling"
                _clear_active_progress_locked()
                notify_pause = True
            else:
                queue = list(_state.get("queue") or [])
                if tid:
                    replaced = False
                    for i, item in enumerate(queue):
                        if (
                            isinstance(item, dict)
                            and str(item.get("taskId") or "").strip() == tid
                        ):
                            queue[i] = job
                            replaced = True
                            break
                    if replaced:
                        _state["queue"] = queue
                        return export_status()
                queue.append(job)
                _state["queue"] = queue
                return export_status()
            if same_task and not paused_now:
                pass  # handled above / unstick path may fall through
            elif same_task and paused_now and notify_pause:
                pass  # resume path
            elif not same_task and paused_now:
                pass  # switch path — abort below
            elif _state.get("running") and not (
                same_task and _export_boot_stuck()
            ):
                # still running after same_task unstick failure already returned
                if not start_now and not notify_pause:
                    return export_status()
        if not _state.get("running"):
            if not _acquire_export_file_lock(steal_if_idle=True):
                raise RuntimeError("刮削导出正在进行中")
            _prime_state_for_job(job)
            start_now = True
        elif same_task and _export_boot_stuck():
            # unreachable safety
            pass
    if notify_pause:
        _abort_all_inflight()
        with _pause_cv:
            _pause_cv.notify_all()
        if _state.get("pendingRestart"):
            _push_event(
                phase="job",
                text=(
                    f"已切换任务 · 暂停项回队 · 即将开始 "
                    f"{job.get('taskName') or job.get('taskId') or ''}"
                ),
                level="info",
            )
        else:
            _push_event(phase="job", text="已继续刮削", level="ok")
        _persist_state(force=True)
        return export_status()
    if start_now:
        _spawn_export_thread(job)
    return export_status()


def _uniq_result_codes(codes: list[str] | None) -> list[str]:
    out = list(
        dict.fromkeys(str(c).strip() for c in (codes or []) if str(c).strip())
    )
    if len(out) > _MAX_RESULT_CODES:
        # 保最新：超出上限时丢最旧
        out = out[-_MAX_RESULT_CODES:]
    return out


def _merge_lifetime_code_buckets(
    exist_done: list[str],
    exist_empty: list[str],
    exist_skip: list[str],
    exist_fail: list[str],
    new_done: list[str],
    new_empty: list[str],
    new_skip: list[str],
    new_fail: list[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """任务卡终身统计：按番号去重合并；成功 > 空号 > 失败 > 跳过。

    全源无详情记空号，可从历史失败桶迁出；真正失败（超时等）仍保留。
    """
    done = _uniq_result_codes([*exist_done, *new_done])
    done_set = set(done)
    empty = _uniq_result_codes(
        [c for c in [*exist_empty, *new_empty] if c not in done_set]
    )
    empty_set = set(empty)
    failed = _uniq_result_codes(
        [
            c
            for c in [*exist_fail, *new_fail]
            if c not in done_set and c not in empty_set
        ]
    )
    fail_set = set(failed)
    skipped = _uniq_result_codes(
        [
            c
            for c in [*exist_skip, *new_skip]
            if c not in done_set and c not in fail_set and c not in empty_set
        ]
    )
    return done, empty, skipped, failed


def _replace_task_result_counts(task_id: str) -> None:
    """重置任务：任务卡计数强制清零（不做 max 合并）。"""
    tid = str(task_id or "").strip()
    if not tid:
        return
    try:
        raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
        tasks = scrape_profiles.normalize_scrape_tasks(
            raw.get("scrapeTasks") or raw.get("scrape_tasks")
        )
        changed = False
        now = _now_iso()
        for t in tasks:
            if str(t.get("id") or "") != tid:
                continue
            t["done"] = 0
            t["empty"] = 0
            t["skipped"] = 0
            t["failed"] = 0
            t["total"] = 0
            t["doneCodes"] = []
            t["emptyCodes"] = []
            t["skippedCodes"] = []
            t["failedCodes"] = []
            t["lastStatus"] = ""
            t["updatedAt"] = now
            changed = True
            break
        if not changed:
            return
        next_raw = dict(raw)
        next_raw["scrapeTasks"] = tasks
        settings_store.put_setting(settings_store.SCRAPE_KEY, next_raw)
    except Exception:
        log.exception("replace scrape task counts failed task=%s", tid)


def _set_task_watch_armed(task_id: str, armed: bool) -> None:
    """任务级监控武装：仅手动跑完一轮后 True；暂停/取消后 False。"""
    tid = str(task_id or "").strip()
    if not tid:
        return
    try:
        raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
        tasks = scrape_profiles.normalize_scrape_tasks(
            raw.get("scrapeTasks") or raw.get("scrape_tasks")
        )
        changed = False
        want = bool(armed)
        for t in tasks:
            if str(t.get("id") or "") != tid:
                continue
            if bool(t.get("watchArmed")) != want:
                t["watchArmed"] = want
                t["updatedAt"] = _now_iso()
                changed = True
            break
        if not changed:
            return
        next_raw = dict(raw)
        next_raw["scrapeTasks"] = tasks
        settings_store.put_setting(settings_store.SCRAPE_KEY, next_raw)
    except Exception:
        log.debug("set watchArmed failed task=%s", tid, exc_info=True)


def _apply_watch_arm_after_finish(
    task_id: str,
    *,
    end_message: str,
    from_watch: bool,
) -> None:
    """手动开始并正常结束 → 武装监控；暂停/取消/中断 → 解除。监控自己跑完保持武装。"""
    tid = str(task_id or "").strip()
    if not tid:
        return
    msg = str(end_message or "").strip().lower()
    if msg in ("paused", "cancelled", "interrupted") or msg.startswith("已暂停") or msg.startswith(
        "已取消"
    ) or msg.startswith("已中断"):
        _set_task_watch_armed(tid, False)
        return
    if msg == "ok" or msg.startswith("完成"):
        if not from_watch:
            _set_task_watch_armed(tid, True)
        # from_watch 完成：保持已有 armed，不额外改
        return
    # 其它异常结束：解除，避免监控空转重开
    if not from_watch:
        _set_task_watch_armed(tid, False)


def _persist_task_result(
    task_id: str,
    *,
    message: str,
    done: int,
    empty: int = 0,
    skipped: int = 0,
    failed: int,
    total: int,
    done_codes: list[str] | None = None,
    empty_codes: list[str] | None = None,
    skipped_codes: list[str] | None = None,
    failed_codes: list[str] | None = None,
) -> None:
    """把本轮进度合并进任务卡终身计数（不清零；仅「重置任务」由前端显式清）。"""
    tid = str(task_id or "").strip()
    if not tid:
        return
    try:
        raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
        tasks = scrape_profiles.normalize_scrape_tasks(
            raw.get("scrapeTasks") or raw.get("scrape_tasks")
        )
        changed = False
        now = _now_iso()
        status = str(message or "").strip()
        incoming_done = _uniq_result_codes(done_codes)
        incoming_empty = _uniq_result_codes(empty_codes)
        incoming_skip = _uniq_result_codes(skipped_codes)
        incoming_fail = _uniq_result_codes(failed_codes)
        # 计数以传入的 done/empty/skipped/failed 为准；列表可能被截断，不能只信 len()
        incoming_done_n = max(
            len(incoming_done) if done_codes is not None else 0,
            max(0, int(done)),
        )
        incoming_empty_n = max(
            len(incoming_empty) if empty_codes is not None else 0,
            max(0, int(empty)),
        )
        incoming_skip_n = max(
            len(incoming_skip) if skipped_codes is not None else 0,
            max(0, int(skipped)),
        )
        incoming_fail_n = max(
            len(incoming_fail) if failed_codes is not None else 0,
            max(0, int(failed)),
        )
        incoming_total = max(0, int(total))
        if status == "cancelled":
            status = "已取消"
        for t in tasks:
            if str(t.get("id") or "") != tid:
                continue
            # 运行中番号已在 _record_terminal_result 逐条 upsert；此处只抬高计数
            db_counts = scrape_export_log_store.count_result_codes(tid)
            done_n = max(
                int(t.get("done") or 0),
                incoming_done_n,
                int(db_counts.get("done") or 0),
            )
            empty_n = max(
                int(t.get("empty") or 0),
                incoming_empty_n,
                int(db_counts.get("empty") or 0),
            )
            skipped_n = max(
                int(t.get("skipped") or 0),
                incoming_skip_n,
                int(db_counts.get("skipped") or 0),
            )
            failed_n = max(
                int(t.get("failed") or 0),
                incoming_fail_n,
                int(db_counts.get("failed") or 0),
            )
            processed = done_n + empty_n + skipped_n + failed_n
            total_n = max(
                int(t.get("total") or 0),
                incoming_total,
                processed,
            )
            if status == "ok":
                status = (
                    f"完成 · 成功 {done_n} · 空号 {empty_n} · 数据不全 {failed_n}"
                )
            t["lastStatus"] = status[:120]
            t["done"] = int(done_n)
            t["empty"] = int(empty_n)
            t["skipped"] = int(skipped_n)
            t["failed"] = int(failed_n)
            t["total"] = int(total_n)
            # 任务卡只留短预览；点开列表走 /scrape/export/codes
            preview_cap = 200
            t["doneCodes"] = incoming_done[-preview_cap:] if incoming_done else list(
                t.get("doneCodes") or []
            )[:preview_cap]
            t["emptyCodes"] = (
                incoming_empty[-preview_cap:]
                if incoming_empty
                else list(t.get("emptyCodes") or [])[:preview_cap]
            )
            t["skippedCodes"] = (
                incoming_skip[-preview_cap:]
                if incoming_skip
                else list(t.get("skippedCodes") or [])[:preview_cap]
            )
            t["failedCodes"] = (
                incoming_fail[-preview_cap:]
                if incoming_fail
                else list(t.get("failedCodes") or [])[:preview_cap]
            )
            t["updatedAt"] = now
            changed = True
            break
        if not changed:
            return
        next_raw = dict(raw)
        next_raw["scrapeTasks"] = tasks
        settings_store.put_setting(settings_store.SCRAPE_KEY, next_raw)
    except Exception:
        log.exception("persist scrape task result failed task=%s", tid)


def _take_next_job_after_finish() -> dict[str, Any] | None:
    """run_export finally：取消/清除则清空队列；否则弹出下一项并保持文件锁。"""
    finished_snap: dict[str, Any] | None = None
    next_job: dict[str, Any] | None = None
    with _meta_lock:
        end_message = str(_end_flags.get("message") or _state.get("message") or "")
        clear_on_stop = bool(_end_flags.get("clearOnStop"))
        _end_flags["message"] = ""
        _end_flags["clearOnStop"] = False
        _end_flags["hadError"] = False
        _control["cancel"] = False
        _control["clearOnStop"] = False

        finished_snap = {
            "taskId": str(_state.get("taskId") or ""),
            "message": end_message,
            "fromWatch": bool(_state.get("fromWatch")),
            "done": int(_state.get("done") or 0),
            "empty": int(_state.get("empty") or 0),
            "skipped": int(_state.get("skipped") or 0),
            "failed": int(_state.get("failed") or 0),
            "total": int(_state.get("total") or 0),
            "doneCodes": list(_state.get("doneCodes") or []),
            "emptyCodes": list(_state.get("emptyCodes") or []),
            "skippedCodes": list(_state.get("skippedCodes") or []),
            "failedCodes": list(_state.get("failedCodes") or []),
        }

        if clear_on_stop:
            _state["queue"] = []
            _reset_idle_state()
            finished_snap = None
        elif end_message == "cancelled":
            pending = _state.pop("pendingRestart", None)
            if isinstance(pending, dict):
                _prime_state_for_job(pending)
                next_job = pending
            else:
                # keep_queue 取消：继续跑后续排队任务；若已清队列则停
                queue = list(_state.get("queue") or [])
                if queue:
                    nxt_raw = queue.pop(0)
                    _state["queue"] = queue
                    if isinstance(nxt_raw, dict):
                        _prime_state_for_job(nxt_raw)
                        next_job = nxt_raw
                    else:
                        _state["queue"] = []
                        _state.update(
                            {
                                "running": False,
                                "paused": False,
                                "finishedAt": _now_iso(),
                                "message": end_message,
                                "current": "",
                                "active": 0,
                                "activeCodes": [],
                                "activeFastCodes": [],
                                "activeSlowCodes": [],
                                "pendingFast": 0,
                                "pendingSlow": 0,
                            }
                        )
                        _release_export_file_lock()
                else:
                    _state.update(
                        {
                            "running": False,
                            "paused": False,
                            "finishedAt": _now_iso(),
                            "message": end_message,
                            "current": "",
                            "active": 0,
                            "activeCodes": [],
                            "activeFastCodes": [],
                            "activeSlowCodes": [],
                            "pendingFast": 0,
                            "pendingSlow": 0,
                        }
                    )
                    _release_export_file_lock()
        else:
            queue = list(_state.get("queue") or [])
            if queue:
                nxt_raw = queue.pop(0)
                _state["queue"] = queue
                if isinstance(nxt_raw, dict):
                    _prime_state_for_job(nxt_raw)
                    next_job = nxt_raw
                else:
                    _state["queue"] = []
                    _state.update(
                        {
                            "running": False,
                            "paused": False,
                            "finishedAt": _now_iso(),
                            "message": end_message or "ok",
                            "current": "",
                            "active": 0,
                            "activeCodes": [],
                            "activeFastCodes": [],
                            "activeSlowCodes": [],
                            "pendingFast": 0,
                            "pendingSlow": 0,
                        }
                    )
                    _release_export_file_lock()
            else:
                _state.update(
                    {
                        "running": False,
                        "paused": False,
                        "finishedAt": _now_iso(),
                        "message": end_message or _state.get("message") or "ok",
                        "current": "",
                        "active": 0,
                        "activeCodes": [],
                        "activeFastCodes": [],
                        "activeSlowCodes": [],
                        "pendingFast": 0,
                        "pendingSlow": 0,
                    }
                )
                _release_export_file_lock()

    if finished_snap and finished_snap.get("taskId"):
        snap_tid = str(finished_snap.get("taskId") or "").strip()
        discard = False
        global _discard_finish_persist_task_id
        with _meta_lock:
            if (
                snap_tid
                and str(_discard_finish_persist_task_id or "").strip() == snap_tid
            ):
                discard = True
                _discard_finish_persist_task_id = ""
        if not discard:
            _persist_task_result(
                snap_tid,
                message=str(finished_snap.get("message") or ""),
                done=int(finished_snap.get("done") or 0),
                empty=int(finished_snap.get("empty") or 0),
                skipped=int(finished_snap.get("skipped") or 0),
                failed=int(finished_snap.get("failed") or 0),
                total=int(finished_snap.get("total") or 0),
                done_codes=list(finished_snap.get("doneCodes") or []),
                empty_codes=list(finished_snap.get("emptyCodes") or []),
                skipped_codes=list(finished_snap.get("skippedCodes") or []),
                failed_codes=list(finished_snap.get("failedCodes") or []),
            )
            _apply_watch_arm_after_finish(
                snap_tid,
                end_message=str(finished_snap.get("message") or ""),
                from_watch=bool(finished_snap.get("fromWatch")),
            )
    return next_job


def _persist_state(*, force: bool = False) -> None:
    """把进度快照落到磁盘；并同步任务卡计数/状态（重启后卡片不丢）。"""
    global _last_persist_mono
    now = time.monotonic()
    with _persist_lock:
        if not force and now - _last_persist_mono < 1.2:
            return
        _last_persist_mono = now
        snap = _snapshot_state()
        paused_now = bool(snap.get("paused")) or str(snap.get("message") or "") == "paused"
        # 落盘不写 running=true，避免重启误当成线程仍在跑；但保留暂停意图
        snap["running"] = False
        snap["paused"] = False
        if paused_now:
            snap["message"] = "paused"
            snap["pauseSaved"] = True
            snap["watchHold"] = True
        try:
            _STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _STATUS_PATH.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(snap, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp.replace(_STATUS_PATH)
        except Exception as e:
            log.debug("persist export status: %s", e)

    # 任务卡整体状态 + 计数落盘（与监控开关无关）
    try:
        with _meta_lock:
            tid = str(_state.get("taskId") or "").strip()
            running = bool(_state.get("running"))
            paused = bool(_state.get("paused")) or str(_state.get("message") or "") == "paused"
            done = int(_state.get("done") or 0)
            empty = int(_state.get("empty") or 0)
            skipped = int(_state.get("skipped") or 0)
            failed = int(_state.get("failed") or 0)
            total = int(_state.get("total") or 0)
            done_codes = list(_state.get("doneCodes") or [])
            empty_codes = list(_state.get("emptyCodes") or [])
            skipped_codes = list(_state.get("skippedCodes") or [])
            failed_codes = list(_state.get("failedCodes") or [])
            msg = str(_state.get("message") or "")
            has_progress = total > 0 or done > 0 or empty > 0 or skipped > 0 or failed > 0
            discard_tid = str(_discard_finish_persist_task_id or "").strip()
        # 刚重置的任务：禁止用 max 把旧卡数字抬回来
        if tid and discard_tid == tid:
            pass
        elif tid and (running or paused or has_progress):
            if paused or msg == "paused":
                label = "已暂停"
            elif running:
                label = "running"
            elif msg in ("interrupted", "cancelled"):
                label = "已中断" if msg == "interrupted" else "已取消"
            elif msg == "ok":
                label = "ok"
            else:
                label = msg or "running"
            _persist_task_result(
                tid,
                message=label,
                done=done,
                empty=empty,
                skipped=skipped,
                failed=failed,
                total=total,
                done_codes=done_codes,
                empty_codes=empty_codes,
                skipped_codes=skipped_codes,
                failed_codes=failed_codes,
            )
            if running or paused:
                _write_resume_checkpoint(
                    reason="paused" if (paused or msg == "paused") else "progress"
                )
    except Exception:
        log.debug("sync task card progress failed", exc_info=True)


def _hydrate_state() -> None:
    scrape_export_log_store.ensure_tables()
    # 优先断点文件（含剩余番号）；否则用 status 快照恢复计数
    resume = _load_resume_checkpoint()
    if resume:
        _apply_resume_checkpoint_to_state(resume)
        _force_clear_export_file_lock()
        _reset_export_mutex_if_stale()
        return

    if not _STATUS_PATH.is_file():
        return
    try:
        data = json.loads(_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.debug("hydrate export status: %s", e)
        return
    if not isinstance(data, dict):
        return
    with _meta_lock:
        was_running = bool(data.get("running"))
        msg = str(data.get("message") or "")
        events = list(data.get("events") or [])
        pause_hint = any(
            "已暂停" in str(e.get("text") or "")
            for e in events
            if isinstance(e, dict)
        ) or bool(data.get("pauseSaved")) or msg == "paused"
        watch_hold = bool(data.get("watchHold"))
        if was_running or msg in (
            "scraping",
            "building",
            "queued",
            "paused",
            "cancelling",
        ):
            if pause_hint:
                watch_hold = True
                msg = "paused"
            else:
                msg = "interrupted"
        _state.update(
            {
                "running": False,
                "paused": False,
                "watchHold": watch_hold,
                "resumable": bool(data.get("resumable"))
                or int(data.get("done") or 0) + int(data.get("empty") or 0) + int(data.get("skipped") or 0)
                < int(data.get("total") or 0),
                "pauseSaved": pause_hint,
                "startedAt": str(data.get("startedAt") or ""),
                "finishedAt": str(data.get("finishedAt") or "") or _now_iso(),
                "message": msg,
                "total": int(data.get("total") or 0),
                "done": int(data.get("done") or 0),
                "failed": int(data.get("failed") or 0),
                "skipped": int(data.get("skipped") or 0),
                "empty": int(data.get("empty") or 0),
                "active": 0,
                "doneCodes": list(data.get("doneCodes") or [])[-_MAX_RESULT_CODES:],
                "emptyCodes": list(data.get("emptyCodes") or [])[
                    -_MAX_RESULT_CODES:
                ],
                "skippedCodes": list(data.get("skippedCodes") or [])[
                    -_MAX_RESULT_CODES:
                ],
                "failedCodes": list(data.get("failedCodes") or [])[
                    -_MAX_RESULT_CODES:
                ],
                "activeCodes": [],
                "activeFastCodes": [],
                "activeSlowCodes": [],
                "pendingFast": 0,
                "pendingSlow": 0,
                "current": str(data.get("current") or ""),
                "region": str(data.get("region") or ""),
                "maker": str(data.get("maker") or ""),
                "prefix": str(data.get("prefix") or ""),
                "codeFilter": str(data.get("codeFilter") or ""),
                "taskId": str(data.get("taskId") or ""),
                "taskName": str(data.get("taskName") or ""),
                "force": bool(data.get("force")),
                "mode": (
                    "force"
                    if str(data.get("mode") or "").strip().lower() == "force"
                    or data.get("force")
                    else "incremental"
                ),
                "exportFields": list(data.get("exportFields") or []),
                "localFields": list(data.get("localFields") or []),
                "queue": [],
                "events": events[-_MAX_EVENTS:],
                "currentDetail": (
                    dict(data["currentDetail"])
                    if isinstance(data.get("currentDetail"), dict)
                    else None
                ),
            }
        )
    _hydrate_events_by_code(data.get("eventsByCode"))
    if not _events_by_code:
        for e in events:
            if isinstance(e, dict):
                _archive_event_for_code(e)
    # 把计数写回任务卡，避免重启后卡片归零
    tid = str(data.get("taskId") or "").strip()
    if tid and (
        int(data.get("total") or 0) > 0
        or int(data.get("done") or 0) > 0
        or int(data.get("empty") or 0) > 0
        or int(data.get("skipped") or 0) > 0
        or int(data.get("failed") or 0) > 0
    ):
        try:
            _persist_task_result(
                tid,
                message=(
                    "已暂停"
                    if pause_hint
                    else (
                        "已中断"
                        if msg == "interrupted"
                        else ("已取消" if msg == "cancelled" else msg or "ok")
                    )
                ),
                done=int(data.get("done") or 0),
                empty=int(data.get("empty") or 0),
                skipped=int(data.get("skipped") or 0),
                failed=int(data.get("failed") or 0),
                total=int(data.get("total") or 0),
                done_codes=list(data.get("doneCodes") or []),
                empty_codes=list(data.get("emptyCodes") or []),
                skipped_codes=list(data.get("skippedCodes") or []),
                failed_codes=list(data.get("failedCodes") or []),
            )
        except Exception:
            log.exception("hydrate sync task card failed")
    _force_clear_export_file_lock()
    _reset_export_mutex_if_stale()
    _reconcile_stuck_export_state(persist=True)


def _push_event(
    *,
    phase: str,
    text: str,
    level: str = "info",
    code: str = "",
    source: str = "",
    ms: int | None = None,
    archive: bool = True,
) -> None:
    ev: dict[str, Any] = {
        "ts": _now_iso(),
        "phase": phase,
        "level": level,
        "text": text,
        "code": code or "",
        "source": source or "",
    }
    if ms is not None:
        ev["ms"] = int(ms)
    with _meta_lock:
        events = list(_state.get("events") or [])
        events.append(ev)
        if len(events) > _MAX_EVENTS:
            events = events[-_MAX_EVENTS:]
        _state["events"] = events
    # 强制重刮会先清库再写；增量跳过可不落库，避免重复刷日志
    if archive:
        _archive_event_for_code(ev)
    _touch_progress()
    _persist_state()


def _snapshot_events_by_code(*, limit_codes: int | None = None) -> dict[str, list[dict[str, Any]]]:
    """limit_codes：落盘时只留最近 N 个番号，避免 status.json 涨到数 MB 拖死轮询。"""
    # 落盘每号只留尾部，内存归档仍可更长
    persist_events_cap = 24
    with _events_by_code_lock:
        if not _events_by_code:
            return {}
        if limit_codes is None or int(limit_codes) <= 0:
            keys = list(_events_by_code_order) or list(_events_by_code.keys())
            cap = None
        else:
            lim = max(1, int(limit_codes))
            keys = list(_events_by_code_order)[-lim:] if _events_by_code_order else list(
                _events_by_code.keys()
            )[-lim:]
            cap = persist_events_cap
        out: dict[str, list[dict[str, Any]]] = {}
        for k in keys:
            bucket = _events_by_code.get(k)
            if not bucket:
                continue
            out[k] = list(bucket[-cap:]) if cap else list(bucket)
        return out


def _hydrate_events_by_code(raw: Any) -> None:
    global _events_by_code, _events_by_code_order
    if not isinstance(raw, dict):
        return
    next_map: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for key, val in raw.items():
        c = _std_code(str(key or ""))
        if not c or not isinstance(val, list):
            continue
        bucket = [dict(e) for e in val if isinstance(e, dict)][-_MAX_EVENTS_PER_CODE:]
        if not bucket:
            continue
        next_map[c] = bucket
        order.append(c)
    with _events_by_code_lock:
        _events_by_code = next_map
        _events_by_code_order = order[-_MAX_CODE_EVENT_CACHE:]


def _archive_event_for_code(ev: dict[str, Any]) -> None:
    c = _std_code(str(ev.get("code") or ""))
    if not c:
        return
    snap = dict(ev)
    snap["code"] = c
    tid = ""
    with _meta_lock:
        tid = str(_state.get("taskId") or "").strip()
    # 持久化：SQLite 无限追加
    scrape_export_log_store.enqueue_event(
        task_id=tid,
        code=c,
        ts=str(snap.get("ts") or ""),
        phase=str(snap.get("phase") or ""),
        level=str(snap.get("level") or "info"),
        text=str(snap.get("text") or ""),
        source=str(snap.get("source") or ""),
        ms=int(snap["ms"]) if snap.get("ms") is not None else None,
    )
    # 内存只留热缓存，供当前片实时合并
    with _events_by_code_lock:
        bucket = list(_events_by_code.get(c) or [])
        bucket.append(snap)
        if len(bucket) > _MAX_EVENTS_PER_CODE:
            bucket = bucket[-_MAX_EVENTS_PER_CODE:]
        _events_by_code[c] = bucket
        if c in _events_by_code_order:
            try:
                _events_by_code_order.remove(c)
            except ValueError:
                pass
        _events_by_code_order.append(c)
        while len(_events_by_code_order) > _MAX_CODE_EVENT_CACHE:
            old = _events_by_code_order.pop(0)
            _events_by_code.pop(old, None)


def _clear_events_for_code(code: str) -> None:
    """强制重刮时覆盖该番号归档日志（不追加旧轮次）。"""
    c = _std_code(code)
    if not c:
        return
    tid = ""
    with _meta_lock:
        tid = str(_state.get("taskId") or "").strip()
    scrape_export_log_store.clear_code_events(c, task_id=tid or None)
    with _events_by_code_lock:
        _events_by_code.pop(c, None)
        if c in _events_by_code_order:
            try:
                _events_by_code_order.remove(c)
            except ValueError:
                pass


def lookup_export_events(code: str) -> list[dict[str, Any]]:
    """按番号取刮削过程日志（SQLite 全量 + 内存热缓存合并）。"""
    c = _std_code(code)
    if not c:
        return []
    archived = scrape_export_log_store.lookup_events(c, limit=5000)
    with _events_by_code_lock:
        hot = list(_events_by_code.get(c) or [])
    with _meta_lock:
        live = [
            dict(e)
            for e in list(_state.get("events") or [])
            if isinstance(e, dict) and _std_code(str(e.get("code") or "")) == c
        ]
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for e in archived + hot + live:
        if not isinstance(e, dict):
            continue
        key = f"{e.get('ts')}|{e.get('phase')}|{e.get('text')}|{e.get('source')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(e))
    return out


def _reset_title_events() -> None:
    """换片时清空实时日志流；按番号归档仍保留。"""
    with _meta_lock:
        _state["events"] = []
    _persist_state()


_DETAIL_TERMINAL_PHASES = frozenset({"done", "skipped", "failed", "empty"})


def _detail_display_ready(detail: dict[str, Any] | None) -> bool:
    """当前片详情是否已加载完（可切换展示下一片）。"""
    if not isinstance(detail, dict):
        return True
    phase = str(detail.get("phase") or "").strip().lower()
    if phase in _DETAIL_TERMINAL_PHASES:
        return True
    if phase == "write":
        return True
    runs = detail.get("sourceRuns")
    return isinstance(runs, list) and len(runs) > 0


_pending_detail: dict[str, dict[str, Any]] = {}
_pending_detail_order: list[str] = []


def _clear_pending_detail_display() -> None:
    _pending_detail.clear()
    _pending_detail_order.clear()


def _enqueue_pending_detail(code: str, detail: dict[str, Any]) -> None:
    c = _std_code(code)
    if not c:
        return
    _pending_detail[c] = detail
    if c not in _pending_detail_order:
        _pending_detail_order.append(c)


def _flush_pending_detail_display() -> None:
    if not _pending_detail:
        return
    cur = _state.get("currentDetail")
    if isinstance(cur, dict) and not _detail_display_ready(cur):
        return
    for c in list(_pending_detail_order):
        pending = _pending_detail.pop(c, None)
        try:
            _pending_detail_order.remove(c)
        except ValueError:
            pass
        if isinstance(pending, dict):
            _state["currentDetail"] = pending
            _cache_detail(c, pending)
            return


def _set_current_detail(detail: dict[str, Any] | None) -> None:
    persist = False
    with _meta_lock:
        if detail is None:
            _state["currentDetail"] = None
            _clear_pending_detail_display()
            persist = True
        else:
            code = _std_code(str(detail.get("code") or ""))
            cur = _state.get("currentDetail")
            if (
                isinstance(cur, dict)
                and code
                and _std_code(str(cur.get("code") or "")) != code
                and not _detail_display_ready(cur)
            ):
                _enqueue_pending_detail(code, detail)
                if code:
                    _cache_detail(code, detail)
                persist = True
            else:
                _state["currentDetail"] = detail
                if code:
                    _cache_detail(code, detail)
                    _pending_detail.pop(code, None)
                    try:
                        _pending_detail_order.remove(code)
                    except ValueError:
                        pass
                if _detail_display_ready(detail):
                    _flush_pending_detail_display()
                persist = True
    if persist:
        _persist_state()


_MAX_DETAIL_CACHE = 160
_detail_by_code: dict[str, dict[str, Any]] = {}
_detail_code_order: list[str] = []
_detail_cache_lock = threading.Lock()

# code → 绝对路径；避免详情/落盘每次 rglob 整库（十万级 meta.json 会卡数秒）
_MAX_ENTRY_DIR_CACHE = 4096
_entry_dir_by_code: dict[str, str] = {}
_entry_dir_code_order: list[str] = []
_entry_dir_cache_lock = threading.Lock()


def _cache_detail(code: str, detail: dict[str, Any]) -> None:
    c = _std_code(code)
    if not c or not isinstance(detail, dict):
        return
    snap = dict(detail)
    snap["code"] = c
    with _detail_cache_lock:
        if c in _detail_by_code:
            try:
                _detail_code_order.remove(c)
            except ValueError:
                pass
        _detail_by_code[c] = snap
        _detail_code_order.append(c)
        while len(_detail_code_order) > _MAX_DETAIL_CACHE:
            old = _detail_code_order.pop(0)
            _detail_by_code.pop(old, None)


def _resolve_library_root() -> Path:
    lib = Path(scrape_settings()["libraryRoot"])
    if not lib.is_absolute():
        lib = (ROOT / lib).resolve()
    else:
        lib = lib.resolve()
    return lib


def _remember_entry_dir(code: str, entry_dir: Path) -> None:
    c = _std_code(code)
    if not c:
        return
    try:
        key = str(entry_dir.resolve())
    except OSError:
        key = str(entry_dir)
    with _entry_dir_cache_lock:
        if c in _entry_dir_by_code:
            try:
                _entry_dir_code_order.remove(c)
            except ValueError:
                pass
        _entry_dir_by_code[c] = key
        _entry_dir_code_order.append(c)
        while len(_entry_dir_code_order) > _MAX_ENTRY_DIR_CACHE:
            old = _entry_dir_code_order.pop(0)
            _entry_dir_by_code.pop(old, None)


def _detail_from_entry_dir(
    entry_dir: Path,
    *,
    code: str,
    phase: str = "done",
    meta_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # 展示优先刮削 scrape.json，否则索引 meta.json；空字段用索引补（如女优）
    if isinstance(meta_override, dict) and meta_override:
        meta = dict(meta_override)
    else:
        scraped = _load_scrape_meta(entry_dir)
        meta = scraped if scraped else _load_index_meta(entry_dir)
    meta = _fill_meta_from_index(meta, entry_dir, display=True)
    rid = str(meta.get("region") or "")
    label = str(meta.get("regionLabel") or _region_label(rid) or "")
    kind = str(meta.get("scrapeKind") or meta.get("kind") or "")
    lib = _resolve_library_root()
    try:
        rel = str(entry_dir.resolve().relative_to(lib)).replace("\\", "/")
    except Exception:
        rel = str(entry_dir)
    poster_local = ""
    for cand in ("poster.jpg", "poster.jpeg", "poster.png", "poster.webp"):
        if (entry_dir / cand).is_file():
            poster_local = f"{rel}/{cand}".replace("\\", "/")
            break
    # naming 自定义文件名
    if not poster_local:
        for p in entry_dir.glob("*.jpg"):
            poster_local = f"{rel}/{p.name}".replace("\\", "/")
            break
    _remember_entry_dir(code, entry_dir)
    return _detail_payload(
        code=_std_code(code),
        kind=kind,
        region=rid,
        region_label=label,
        path=rel,
        phase=phase,
        meta=meta,
        source_runs=meta.get("sourceRuns")
        if isinstance(meta.get("sourceRuns"), list)
        else None,
        field_sources=meta.get("fieldSources")
        if isinstance(meta.get("fieldSources"), dict)
        else None,
        poster_local=poster_local,
        fallback_cover=str(meta.get("poster") or meta.get("coverUrl") or ""),
        # 读盘展示：不裁剪字段；任务勾选只影响刮削/写入
        export_fields=None,
    )


def _find_library_entry_dir(code: str) -> Path | None:
    """按 maker-fs 布局定位：library/{区域}/{厂牌}/{前缀}/{番号}/。

    禁止整库 rglob(meta.json)——本地库可达十万级，单次详情会卡数秒。
    """
    raw = str(code or "").strip().upper().replace("_", "-")
    c = _std_code(code)
    if not c:
        return None
    # FC2 等目录常保留前导零（FC2PPV-071713），与 _std_code 规范化后不一致
    code_names = []
    for name in (c, raw):
        if name and name not in code_names:
            code_names.append(name)
    m = re.fullmatch(r"([A-Z0-9]+)-(\d+)", raw)
    if m:
        pref_raw, digs = m.group(1), m.group(2)
        # 尝试常见补零宽度：原宽度 / 3~7 位
        widths = {len(digs), max(3, len(str(int(digs))))}
        for w in range(3, 8):
            widths.add(w)
        for w in sorted(widths):
            alt = f"{pref_raw}-{int(digs):0{w}d}"
            if alt not in code_names:
                code_names.append(alt)

    with _entry_dir_cache_lock:
        cached = _entry_dir_by_code.get(c)
    if cached:
        p = Path(cached)
        if p.is_dir() and (
            (p / INDEX_META_FILE).is_file()
            or (p / SCRAPE_META_FILE).is_file()
            or p.name.upper() in {x.upper() for x in code_names}
        ):
            return p

    lib = _resolve_library_root()
    if not lib.is_dir():
        return None

    prefixes = []
    for name in code_names:
        pref = name.split("-", 1)[0] if "-" in name else name
        if pref and pref not in prefixes:
            prefixes.append(pref)

    def _hit(cand: Path) -> Path | None:
        if not cand.is_dir():
            return None
        if (
            (cand / INDEX_META_FILE).is_file()
            or (cand / SCRAPE_META_FILE).is_file()
            or cand.name.upper() in {x.upper() for x in code_names}
        ):
            return cand
        return None

    preferred: Path | None = None
    fallback: Path | None = None
    try:
        for region in lib.iterdir():
            if not region.is_dir():
                continue
            for maker in region.iterdir():
                if not maker.is_dir():
                    continue
                uncat = maker.name == "未分类"
                for prefix in prefixes:
                    for cn in code_names:
                        found = _hit(maker / prefix / cn)
                        if found is None:
                            continue
                        if uncat:
                            if fallback is None:
                                fallback = found
                        else:
                            preferred = found
                            _remember_entry_dir(c, found)
                            return found
                    # 前缀目录大小写不一致时扫一层
                    try:
                        for child in maker.iterdir():
                            if not child.is_dir():
                                continue
                            if child.name.upper() != prefix.upper():
                                continue
                            for cn in code_names:
                                found = _hit(child / cn)
                                if found is None:
                                    continue
                                if uncat:
                                    if fallback is None:
                                        fallback = found
                                else:
                                    preferred = found
                                    _remember_entry_dir(c, found)
                                    return found
                            break
                    except OSError:
                        pass
                for cn in code_names:
                    found = _hit(maker / cn)
                    if found is None:
                        continue
                    if uncat:
                        if fallback is None:
                            fallback = found
                    else:
                        preferred = found
                        _remember_entry_dir(c, found)
                        return found
    except OSError:
        return None
    hit = preferred or fallback
    if hit is not None:
        _remember_entry_dir(c, hit)
    return hit


def lookup_export_detail(code: str) -> dict[str, Any] | None:
    """按番号取详细数据：刮削中优先内存 → scrape.json → 索引 meta.json → 缓存。"""
    c = _std_code(code)
    if not c:
        return None
    # 正在刮这一号时：读盘会拿到上一轮落盘，冲掉实时字段；优先 currentDetail
    with _meta_lock:
        cur = _state.get("currentDetail")
        if isinstance(cur, dict) and _std_code(str(cur.get("code") or "")) == c:
            phase = str(cur.get("phase") or "").strip().lower()
            if phase not in _DETAIL_TERMINAL_PHASES and phase != "write":
                out = dict(cur)
                out["events"] = lookup_export_events(c)
                return out
    # 优先读刮削结果；无则回退索引物化（未刮过）
    entry = _find_library_entry_dir(c)
    if entry is not None:
        scraped = _load_scrape_meta(entry)
        meta = scraped if scraped else _load_index_meta(entry)
        if meta:
            detail = _detail_from_entry_dir(
                entry, code=c, phase="done", meta_override=meta
            )
            detail["events"] = lookup_export_events(c)
            _cache_detail(c, detail)
            return detail
    with _meta_lock:
        cur = _state.get("currentDetail")
        if isinstance(cur, dict) and _std_code(str(cur.get("code") or "")) == c:
            out = dict(cur)
            out["events"] = lookup_export_events(c)
            return out
    with _detail_cache_lock:
        cached = _detail_by_code.get(c)
        if cached:
            out = dict(cached)
            out["events"] = lookup_export_events(c)
            return out
    return {
        "code": c,
        "phase": "missing",
        "title": "",
        "titleZh": "",
        "actors": [],
        "genres": [],
        "studio": "",
        "publisher": "",
        "series": "",
        "path": "",
        "poster": "",
        "posterLocal": "",
        "message": "未找到落盘详情（可能失败/已跳过且无本地库）",
        "sourceRuns": [],
        "fieldSources": {},
        "fieldTimings": {},
        "events": lookup_export_events(c),
    }


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_index_meta(entry_dir: Path) -> dict[str, Any]:
    """本地索引物化 meta.json（maker-fs 种子）。"""
    return _load_json_dict(entry_dir / INDEX_META_FILE)


def _load_scrape_meta(entry_dir: Path) -> dict[str, Any]:
    """刮削结果 scrape.json；旧版曾把刮削写进 meta.json，作只读兼容。"""
    scrape = _load_json_dict(entry_dir / SCRAPE_META_FILE)
    if scrape:
        return scrape
    legacy = _load_json_dict(entry_dir / INDEX_META_FILE)
    # 仅当旧 meta 已是网络刮削痕迹时，当作 scrape 读（不改盘）
    if legacy.get("scrapedAt") or legacy.get("exportFields") or legacy.get(
        "sourceRuns"
    ):
        src = str(legacy.get("source") or "").strip().lower()
        if src and src not in {"maker-fs", "index", "forum", "seed", "local"}:
            return legacy
        fs = legacy.get("fieldSources")
        if isinstance(fs, dict) and any(
            str(v or "").strip().lower()
            not in {"", "forum", "maker-fs", "index", "seed", "local"}
            for v in fs.values()
        ):
            return legacy
    return {}


def _load_entry_meta(entry_dir: Path) -> dict[str, Any]:
    """兼容旧名：默认读索引物化。"""
    return _load_index_meta(entry_dir)


def _is_quality_title_zh(text: Any, code: str = "") -> bool:
    """真中文、非壳题可本地复用；不合格则仍走网络 titleZh。"""
    return is_quality_chinese_title(str(text or ""), code)


def _text_is_chinese(text: Any) -> bool:
    return is_likely_chinese(str(text or "").strip())


def _list_is_chinese(items: Any) -> bool:
    if not isinstance(items, list) or not items:
        return False
    cleaned = [str(x).strip() for x in items if str(x).strip()]
    if not cleaned:
        return False
    # 任一项中文，或整串拼起来像中文
    if any(_text_is_chinese(x) for x in cleaned):
        return True
    return _text_is_chinese(" ".join(cleaned))


def _local_quality_fields(
    meta: dict[str, Any] | None,
    *,
    entry_dir: Path | None = None,
    poster_name: str = "poster.jpg",
    want: list[str] | None = None,
) -> dict[str, Any]:
    """从「索引物化 meta.json」提取本地候选字段（仅此来源算本地）。

    网络优先合并时：空网络可填任意非空本地；非中文网络仅在本地为中文时替换。
    want=None：不限制；want=[]：明确不读任何字段。
    不含封面：cover/poster 始终从网络获取。
    勿把 scrape.json（网络结果）传进来当本地。
    """
    raw = meta if isinstance(meta, dict) else {}
    # 误把刮削结果当索引：有落盘刮削痕迹则拒绝
    if raw.get("scrapedAt") or raw.get("exportFields") or raw.get("sourceRuns"):
        return {}
    src = str(raw.get("source") or "").strip().lower()
    if src and src not in {"", "maker-fs", "index", "forum", "seed", "local"}:
        return {}

    if want is None:
        want_set: set[str] | None = None
    else:
        # 允许空列表=不读；勿走 normalize_export_fields（空会默认全开）
        want_set = set(scrape_profiles.normalize_local_fields(want))
        if not want_set:
            return {}
    out: dict[str, Any] = {}

    if want_set is None or "titleZh" in want_set:
        zh = str(raw.get("titleZh") or raw.get("title_zh") or "").strip()
        # 合并候选：非空即可（空网络时原样填；英/日网络时再判中文）
        if zh:
            out["titleZh"] = zh

    if want_set is None or "actors" in want_set:
        actors = raw.get("actors") if isinstance(raw.get("actors"), list) else []
        if not actors:
            actors = raw.get("actress") if isinstance(raw.get("actress"), list) else []
        cleaned = [str(a).strip() for a in actors if str(a).strip()]
        if cleaned:
            out["actors"] = cleaned

    if want_set is None or "outline" in want_set:
        plot = str(raw.get("plot") or raw.get("outline") or "").strip()
        if plot:
            out["outline"] = plot

    if want_set is None or "tags" in want_set:
        tags = raw.get("genres") if isinstance(raw.get("genres"), list) else []
        if not tags:
            tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
        cleaned_t = [str(t).strip() for t in tags if str(t).strip()]
        if cleaned_t:
            out["tags"] = cleaned_t

    if want_set is None or "studio" in want_set:
        studio = str(raw.get("studio") or "").strip()
        if not studio:
            makers = raw.get("makers") if isinstance(raw.get("makers"), list) else []
            if makers:
                studio = str(makers[0] or "").strip()
        # 索引物化常把厂牌名写进 studio，不等于真实制片方，勿当高质量复用
        maker = str(raw.get("maker") or "").strip()
        if studio and maker and studio == maker:
            studio = ""
        if studio and studio not in {"未知", "未分组", "未分类"}:
            out["studio"] = studio

    if want_set is None or "series" in want_set:
        series = str(raw.get("series") or "").strip()
        if series:
            out["series"] = series

    # 封面 / poster 不参与本地复用：一律走网络抓取
    _ = (entry_dir, poster_name)

    return out


def _fill_meta_from_index(
    meta: dict[str, Any] | None,
    entry_dir: Path | None,
    *,
    local_fields: list[str] | None = None,
    display: bool = False,
) -> dict[str, Any]:
    """用索引 meta.json 按本地复用规则补空字段。

    display=True：详情展示时补全部可复用字段（不依赖任务勾选）。
    display=False：仅任务勾选的 localFields（空列表=不补）。
    """
    base = dict(meta) if isinstance(meta, dict) else {}
    if entry_dir is None or not entry_dir.is_dir():
        return base
    if display:
        want: list[str] | None = list(scrape_profiles.LOCAL_REUSE_FIELDS)
    else:
        want = scrape_profiles.normalize_local_fields(local_fields)
        if not want:
            return base
    index = _load_index_meta(entry_dir)
    if not index:
        return base
    local_q = _local_quality_fields(index, entry_dir=entry_dir, want=want)
    if not local_q:
        return base
    return _apply_local_quality_to_meta(base, local_q)


# 索引物化字段在 fieldSources 中的标记（与 javbus/airav 等网络源区分）
INDEX_FIELD_SOURCE = "index"


# 任务勾选字段 → scrape.json 内容键（未勾选则不从本地脏数据/网络顺带写入）
_EXPORT_CONTENT_KEYS: dict[str, tuple[str, ...]] = {
    "titleZh": ("titleZh", "title_zh", "title", "originalTitle"),
    "outline": ("outline", "plot"),
    "studio": ("studio", "publisher", "makers"),
    "actors": ("actors", "actress"),
    "tags": ("tags", "genres"),
    "series": ("series",),
    "cover": (
        "poster",
        "coverUrl",
        "coverUrls",
        "posterLocal",
        "coverLocal",
        "fanart",
    ),
}

_STRUCTURAL_META_KEYS = frozenset(
    {
        "code",
        "prefix",
        "maker",
        "region",
        "regionLabel",
        "scrapeKind",
        "directoryRel",
        "exportFields",
        "scrapedAt",
        "source",
        "message",
        "ok",
        "fieldSources",
        "fieldTimings",
        "sourceRuns",
        "sourcesTried",
        "productId",
        "cid",
        "premiered",
        "runtime",
        "director",
        "userRating",
        "mosaic",
    }
)


def _drop_content_keys(meta: dict[str, Any], field_ids: set[str]) -> None:
    """就地删除指定导出字段对应的内容键，并清理 fieldSources/fieldTimings。"""
    fs = meta.get("fieldSources")
    ft = meta.get("fieldTimings")
    for fid in field_ids:
        for k in _EXPORT_CONTENT_KEYS.get(fid) or ():
            meta.pop(k, None)
            if isinstance(fs, dict):
                fs.pop(k, None)
                if fid == "titleZh":
                    fs.pop("title", None)
                    fs.pop("titleZh", None)
                if fid == "outline":
                    fs.pop("plot", None)
                    fs.pop("outline", None)
                if fid == "tags":
                    fs.pop("tags", None)
                    fs.pop("genres", None)
                if fid == "studio":
                    fs.pop("studio", None)
                    fs.pop("publisher", None)
                    fs.pop("makers", None)
                if fid == "cover":
                    fs.pop("cover", None)
                    fs.pop("poster", None)
            if isinstance(ft, dict):
                ft.pop(k, None)
                if fid == "titleZh":
                    ft.pop("title", None)
                    ft.pop("titleZh", None)
                if fid == "outline":
                    ft.pop("plot", None)
                    ft.pop("outline", None)
                if fid == "tags":
                    ft.pop("tags", None)
                    ft.pop("genres", None)
                if fid == "studio":
                    ft.pop("studio", None)
                    ft.pop("publisher", None)
                    ft.pop("makers", None)
                if fid == "cover":
                    ft.pop("cover", None)
                    ft.pop("poster", None)


def _mask_meta_to_export_fields(
    meta: dict[str, Any],
    want: list[str],
    *,
    prev: dict[str, Any] | None = None,
    keep_prev_for_unselected: bool = True,
) -> dict[str, Any]:
    """只保留任务勾选字段的内容；未勾选的不写入本次脏数据。

    keep_prev_for_unselected：未勾选字段若上次 scrape.json 已有值则保留（避免增量任务抹掉）。
    """
    want_set = set(_normalize_fields(want))
    out = dict(meta) if isinstance(meta, dict) else {}
    prev_d = prev if isinstance(prev, dict) else {}
    unselected = set(_EXPORT_CONTENT_KEYS) - want_set
    _drop_content_keys(out, unselected)
    if keep_prev_for_unselected:
        for fid in unselected:
            for k in _EXPORT_CONTENT_KEYS.get(fid) or ():
                v = prev_d.get(k)
                if v in (None, "", [], {}):
                    continue
                out[k] = v
        # 同步来源标记
        prev_fs = prev_d.get("fieldSources")
        if isinstance(prev_fs, dict):
            fs = out.get("fieldSources")
            if not isinstance(fs, dict):
                fs = {}
                out["fieldSources"] = fs
            for fid in unselected:
                for k in _EXPORT_CONTENT_KEYS.get(fid) or ():
                    if k in prev_fs and k not in fs:
                        fs[k] = prev_fs[k]
                if fid == "studio" and prev_fs.get("studio"):
                    fs.setdefault("studio", prev_fs["studio"])
                if fid == "cover" and prev_fs.get("cover"):
                    fs.setdefault("cover", prev_fs["cover"])
    return out


def _prune_field_priority_for_local(
    fp: dict[str, list[str]] | None,
    local_ok: set[str],
) -> dict[str, list[str]]:
    """已废弃本地裁源：网络优先，本地仅事后合并。保留函数签名以免旧调用崩。"""
    _ = local_ok
    return scrape_profiles.normalize_field_priority(fp)


def _net_field_empty(value: Any, *, is_list: bool = False) -> bool:
    if is_list:
        if not isinstance(value, list):
            return True
        return not any(str(x).strip() for x in value)
    return not str(value or "").strip()


def _should_prefer_local(
    net_val: Any,
    local_val: Any,
    *,
    is_list: bool = False,
) -> bool:
    """网络优先合并：

    - 网络中文 → 保留网络
    - 网络空 → 有本地就用本地（不论语种）
    - 网络英/日等非中文 → 仅本地为中文时替换
    """
    if is_list:
        if not isinstance(local_val, list) or not any(
            str(x).strip() for x in local_val
        ):
            return False
        if _net_field_empty(net_val, is_list=True):
            return True
        if _list_is_chinese(net_val):
            return False
        return _list_is_chinese(local_val)

    loc = str(local_val or "").strip()
    if not loc:
        return False
    if _net_field_empty(net_val, is_list=False):
        return True
    if _text_is_chinese(net_val):
        return False
    return _text_is_chinese(loc)


def _apply_local_quality_to_meta(
    meta: dict[str, Any],
    local_q: dict[str, Any],
) -> dict[str, Any]:
    """网络优先，再按规则用索引物化补/换；替换时 fieldSources=index。"""
    if not local_q:
        return meta
    out = dict(meta)
    fs = (
        dict(out.get("fieldSources") or {})
        if isinstance(out.get("fieldSources"), dict)
        else {}
    )
    src = INDEX_FIELD_SOURCE

    if "titleZh" in local_q:
        net_zh = str(out.get("titleZh") or out.get("title_zh") or "").strip()
        loc_zh = str(local_q.get("titleZh") or "").strip()
        if _should_prefer_local(net_zh, loc_zh):
            out["titleZh"] = loc_zh
            out["title"] = loc_zh
            fs["titleZh"] = src
            fs["title"] = src

    if "actors" in local_q and isinstance(local_q.get("actors"), list):
        net_actors = out.get("actors") if isinstance(out.get("actors"), list) else []
        if not net_actors:
            net_actors = (
                out.get("actress") if isinstance(out.get("actress"), list) else []
            )
        loc_actors = [str(a).strip() for a in local_q["actors"] if str(a).strip()]
        if _should_prefer_local(net_actors, loc_actors, is_list=True):
            out["actors"] = list(loc_actors)
            fs["actors"] = src

    if "outline" in local_q:
        net_plot = str(out.get("plot") or out.get("outline") or "").strip()
        loc_plot = str(local_q.get("outline") or "").strip()
        if _should_prefer_local(net_plot, loc_plot):
            out["plot"] = loc_plot
            out["outline"] = loc_plot
            fs["outline"] = src
            fs["plot"] = src

    if "tags" in local_q and isinstance(local_q.get("tags"), list):
        net_tags = out.get("genres") if isinstance(out.get("genres"), list) else []
        if not net_tags:
            net_tags = out.get("tags") if isinstance(out.get("tags"), list) else []
        loc_tags = [str(t).strip() for t in local_q["tags"] if str(t).strip()]
        if _should_prefer_local(net_tags, loc_tags, is_list=True):
            out["genres"] = list(loc_tags)
            out["tags"] = list(loc_tags)
            fs["tags"] = src
            fs["genres"] = src

    if "studio" in local_q:
        net_studio = str(out.get("studio") or "").strip()
        loc_studio = str(local_q.get("studio") or "").strip()
        if _should_prefer_local(net_studio, loc_studio):
            out["studio"] = loc_studio
            fs["studio"] = src

    if "series" in local_q:
        net_series = str(out.get("series") or "").strip()
        loc_series = str(local_q.get("series") or "").strip()
        if _should_prefer_local(net_series, loc_series):
            out["series"] = loc_series
            fs["series"] = src

    # cover/poster 不钉本地，保留网络结果
    out["fieldSources"] = fs
    return out


def _build_work_template_from_local(
    existing_meta: dict[str, Any],
    *,
    code: str,
    kind: str,
    entry_dir: Path | None,
    poster_name: str,
    want: list[str],
    local_fields: list[str] | None = None,
    scrape_meta: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], set[str], list[str]]:
    """① 读索引物化候选 → ② 网络刮削 → ③ 按中文规则合并。

    scrape.json 是上次网络刮削结果，不算本地，不参与复用。
    封面永不进 local_ok，勾选封面时必走网络。
    """
    index = dict(existing_meta) if isinstance(existing_meta, dict) else {}
    index["code"] = _std_code(code) or str(index.get("code") or code)
    if kind:
        index["scrapeKind"] = kind

    # 仅索引物化；scrape_meta 保留兼容，故意不读内容字段
    _ = scrape_meta
    want_norm = _normalize_fields(want)
    want_set = set(want_norm)
    # 只读任务勾选的「本地可复用」∩「刮削字段」
    reuse = [
        f
        for f in scrape_profiles.normalize_local_fields(local_fields)
        if f in want_set
    ]
    local_q = _local_quality_fields(
        index,
        entry_dir=entry_dir,
        poster_name=poster_name,
        want=reuse,
    )

    # 模板仅目录结构；内容等网络后再合并本地（预览可带本地候选）
    template: dict[str, Any] = {
        "code": index.get("code"),
        "scrapeKind": index.get("scrapeKind") or kind,
    }
    for k in ("prefix", "maker", "region", "regionLabel"):
        v = index.get(k)
        if v not in (None, "", [], {}):
            template[k] = v
    # 预览：先带上本地候选（最终仍以网络优先合并为准）
    template = _apply_local_quality_to_meta(template, local_q)

    local_ok = {
        k
        for k in (
            "titleZh",
            "actors",
            "outline",
            "tags",
            "studio",
            "series",
        )
        if k in local_q
    }
    # 网络优先：勾选字段一律视为待网络；本地只作事后合并候选
    missing = list(want_norm)
    # 未勾选内容键不进模板
    template = _mask_meta_to_export_fields(
        template, want_norm, prev=None, keep_prev_for_unselected=False
    )
    return template, local_q, local_ok, missing


def _target_cover_url(target: dict[str, Any]) -> str:
    u = str(target.get("coverUrl") or "").strip()
    if u.startswith("http"):
        return u
    urls = target.get("coverUrls")
    if isinstance(urls, list):
        for x in urls:
            s = str(x or "").strip()
            if s.startswith("http"):
                return s
    return ""


# 色花堂帖题噪声清洗见 scrape_forum_title


def _forum_seed_for_code(
    code: str,
    *,
    prefix: str | None = None,
    region: str | None = None,
    target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """色花堂种子：优先 maker-fs 本地索引（【影片名称】），否则扫库兜底。"""
    empty: dict[str, Any] = {"title": "", "actors": [], "postsScanned": 0}
    needle = str(code or "").strip().upper()
    if not needle:
        return empty

    if isinstance(target, dict):
        t_title = str(target.get("forumTitle") or "").strip()
        t_actors = target.get("forumActors")
        if t_title or (
            isinstance(t_actors, list) and any(str(a).strip() for a in t_actors)
        ):
            return {
                "title": t_title,
                "actors": [
                    str(a).strip()
                    for a in (t_actors or [])
                    if str(a).strip()
                ],
                "postsScanned": 0,
                "source": "maker-fs",
            }

    local = maker_fs.forum_seed_for_code_local(
        code, prefix=prefix, region=region
    )
    if local and (local.get("title") or local.get("actors")):
        return local

    from .forum_seed import pick_forum_seed_from_posts

    try:
        from . import pg
        from .resource_format import PUBLIC_RESOURCE_FILTER
        from .search_av import build_av_code_ilike_patterns
        from .search_constants import escape_ilike

        patterns = build_av_code_ilike_patterns(needle)
        if not patterns:
            patterns = [f"%{escape_ilike(needle)}%"]
        title_likes = " OR ".join(
            ["rs.title ILIKE %s ESCAPE '\\'"] * len(patterns)
        )
        desc_likes = " OR ".join(
            ["rs.description ILIKE %s ESCAPE '\\'"] * len(patterns)
        )
        params = list(patterns) + list(patterns)
        # 优先【影片名称】/中文帖题，再按时间；扫够行以免漏中文译名
        sql = f"""
SELECT rs.title, rs.description, rs.created_at
FROM resource_sources rs
JOIN ed2k_resources r ON r.hash = rs.hash
WHERE TRUE
{PUBLIC_RESOURCE_FILTER}
  AND (({title_likes}) OR ({desc_likes}))
ORDER BY
  CASE
    WHEN (rs.description ILIKE '%%影片名称%%' OR rs.description ILIKE '%%影片名稱%%')
      AND rs.description ~ '[一-龥]'
      AND rs.description !~ '[ぁ-んァ-ン]' THEN 0
    WHEN rs.title ~ '[一-龥]' AND rs.title !~ '[ぁ-んァ-ン]' THEN 1
    WHEN rs.description ILIKE '%%影片名称%%'
      OR rs.description ILIKE '%%影片名稱%%' THEN 2
    ELSE 3
  END,
  rs.created_at DESC NULLS LAST
LIMIT 96
"""
        rows = pg.query(sql, params)
    except Exception:
        return empty

    posts = []
    for row in rows or []:
        desc = str((row or {}).get("description") or "")
        title = str((row or {}).get("title") or "").strip()
        if desc.strip() or title:
            posts.append({"description": desc, "title": title})
    seed = pick_forum_seed_from_posts(needle, posts)
    seed["source"] = "db"
    return seed


def _forum_title_for_code(code: str, **kwargs: Any) -> str:
    """从资源库【影片名称】取中文题。"""
    return str(_forum_seed_for_code(code, **kwargs).get("title") or "")


def _detail_payload(
    *,
    code: str,
    kind: str,
    region: str,
    region_label: str,
    path: str,
    phase: str,
    meta: dict[str, Any] | None = None,
    source_runs: list[Any] | None = None,
    field_sources: dict[str, Any] | None = None,
    poster_local: str = "",
    fallback_cover: str = "",
    export_fields: list[str] | None = None,
) -> dict[str, Any]:
    m = meta if isinstance(meta, dict) else {}
    want = _normalize_fields(
        export_fields
        if export_fields is not None
        else (_state.get("exportFields") if isinstance(_state, dict) else None)
    )

    actors = m.get("actors") if isinstance(m.get("actors"), list) else []
    if not actors and isinstance(m.get("actress"), list):
        actors = m.get("actress") or []
    genres = m.get("genres") if isinstance(m.get("genres"), list) else []
    if not genres and isinstance(m.get("tags"), list):
        genres = m.get("tags") or []
    poster = str(
        m.get("poster")
        or m.get("coverUrl")
        or fallback_cover
        or ""
    ).strip()
    plot = str(m.get("plot") or m.get("outline") or "").strip()
    publisher = str(m.get("publisher") or "").strip()
    # 只用明确的 studio；禁止 makers[0] 冒充（未勾选制片方时也会带上）
    studio = str(m.get("studio") or "").strip()
    series = str(m.get("series") or "").strip()
    fs = dict(field_sources or {})
    ft: dict[str, Any] = (
        dict(m.get("fieldTimings"))
        if isinstance(m.get("fieldTimings"), dict)
        else {}
    )
    # 前端简介字段读 plot；刮削侧来源记在 outline
    if plot and not fs.get("plot") and fs.get("outline"):
        fs["plot"] = fs["outline"]
    if "outline" in ft and "plot" not in ft:
        ft["plot"] = ft["outline"]
    if genres and not fs.get("genres") and fs.get("tags"):
        fs["genres"] = fs["tags"]
    if "tags" in ft and "genres" not in ft:
        ft["genres"] = ft["tags"]
    title = str(m.get("title") or "").strip()
    title_zh = str(m.get("titleZh") or m.get("title_zh") or "").strip()
    # 刮削服务在无标题时会回落成番号本身，详情里不当作有效标题
    if title.upper() == code.upper():
        title = ""
    if title_zh.upper() == code.upper():
        title_zh = ""
    # 仅本地/索引题做日文拦截；网络源 titleZh 原样展示
    if title_zh:
        src_zh = str(fs.get("titleZh") or "").strip().lower()
        if src_zh in {"", "index", "forum", "maker-fs", "seed", "local"}:
            han = len([c for c in title_zh if "\u4e00" <= c <= "\u9fff"])
            kana = len([c for c in title_zh if "\u3040" <= c <= "\u30ff"])
            if han < 2 or han < kana:
                title_zh = ""
                fs.pop("titleZh", None)
                ft.pop("titleZh", None)

    # 详情展示不按任务勾选裁剪：有数据就返回；未勾选字段仅在 _write_entry 不落盘。

    return {
        "code": code,
        "kind": kind,
        "region": region,
        "regionLabel": region_label,
        "path": path,
        "phase": phase,
        "title": title_zh or title,
        "titleZh": title_zh,
        "originalTitle": str(m.get("originalTitle") or "").strip(),
        "plot": plot,
        "actors": [str(a) for a in actors if str(a).strip()],
        "genres": [str(g) for g in genres if str(g).strip()],
        "publisher": publisher,
        "studio": studio,
        "premiered": str(m.get("premiered") or ""),
        "runtime": m.get("runtime"),
        "director": str(m.get("director") or ""),
        "series": series,
        "userRating": m.get("userRating"),
        "productId": str(m.get("productId") or m.get("cid") or ""),
        "poster": poster,
        "posterLocal": poster_local or "",
        "coverLocal": str(m.get("coverLocal") or ""),
        "mosaic": str(m.get("mosaic") or region_label or ""),
        "message": str(m.get("message") or ""),
        "sourceRuns": list(source_runs or []),
        "fieldSources": fs,
        "fieldTimings": ft,
        "exportFields": list(want) if want else [],
    }


def _std_code(code: str) -> str:
    """落盘番号：补满至少 3 位（OFES-001 / SONE-001）。"""
    raw = str(code or "").strip().upper().replace("_", "-")
    m = re.fullmatch(r"([A-Z0-9]+)-(\d+)", raw)
    if not m:
        return raw
    prefix, digits = m.group(1), m.group(2)
    n = int(digits)
    width = max(3, len(str(n)), len(digits) if prefix.isdigit() else 0)
    return f"{prefix}-{n:0{width}d}"


_CODE_FILTER_SEP = re.compile(r"[,;，、|｜/\n\r]+")


def _parse_export_code_filters(
    code: str | None = None,
    codes: list[str] | None = None,
    *,
    limit: int = 5000,
) -> list[str]:
    """单号 / 逗号顿号多号 / codes 列表 → 去重保序的标准番号。"""
    out: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        c = _std_code(raw)
        if not c or c in seen:
            return
        seen.add(c)
        out.append(c)

    if codes:
        for raw in codes:
            _add(str(raw or ""))
            if len(out) >= limit:
                return out
    s = str(code or "").strip()
    if s:
        if _CODE_FILTER_SEP.search(s):
            for part in _CODE_FILTER_SEP.split(s):
                _add(part)
                if len(out) >= limit:
                    break
        else:
            _add(s)
    return out


def _safe_segment(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(name or "").strip())
    s = s.strip(" .") or "unknown"
    return s[:120]


def export_status(
    *,
    event_limit: int = 80,
    include_codes: bool = False,
    code_limit: int | None = None,
) -> dict[str, Any]:
    """返回进度快照。events 默认只带尾部；番号列表默认截断以免数万级拖死轮询。"""
    _reconcile_stuck_export_state()
    lim = max(0, min(int(event_limit or 0), _MAX_EVENTS))
    cap = _STATUS_CODE_LIST_CAP
    if code_limit is not None:
        cap = max(0, min(int(code_limit), _MAX_RESULT_CODES))
    if include_codes:
        cap = _MAX_RESULT_CODES
    with _meta_lock:
        events = list(_state.get("events") or [])
        total_events = len(events)
        if lim and total_events > lim:
            events = events[-lim:]
        detail = _state.get("currentDetail")

        def _codes(key: str) -> tuple[list[str], int, bool]:
            full = list(_state.get(key) or [])
            n = len(full)
            if include_codes or n <= cap:
                return full, n, False
            # 轮询只带尾部，完整列表走 /scrape/export/codes
            return full[-cap:], n, True

        done_codes, done_n, done_trunc = _codes("doneCodes")
        empty_codes, empty_n, empty_trunc = _codes("emptyCodes")
        skip_codes, skip_n, skip_trunc = _codes("skippedCodes")
        fail_codes, fail_n, fail_trunc = _codes("failedCodes")
        out = {
            "running": bool(_state.get("running")),
            "paused": bool(_state.get("paused")),
            "startedAt": _state.get("startedAt") or "",
            "finishedAt": _state.get("finishedAt") or "",
            "message": _state.get("message") or "",
            "total": int(_state.get("total") or 0),
            "done": int(_state.get("done") or 0) or done_n,
            "failed": int(_state.get("failed") or 0) or fail_n,
            "skipped": int(_state.get("skipped") or 0) or skip_n,
            "empty": int(_state.get("empty") or 0) or empty_n,
            "active": int(_state.get("active") or 0),
            "doneCodes": done_codes,
            "emptyCodes": empty_codes,
            "skippedCodes": skip_codes,
            "failedCodes": fail_codes,
            "codesTruncated": bool(done_trunc or empty_trunc or skip_trunc or fail_trunc),
            "activeCodes": list(_state.get("activeCodes") or []),
            "activeFastCodes": list(_state.get("activeFastCodes") or []),
            "activeSlowCodes": list(_state.get("activeSlowCodes") or []),
            "pendingFast": int(_state.get("pendingFast") or 0),
            "pendingSlow": int(_state.get("pendingSlow") or 0),
            "fastSlots": int(_state.get("fastSlots") or 0),
            "slowSlots": int(_state.get("slowSlots") or 0),
            "current": _state.get("current") or "",
            "region": _state.get("region") or "",
            "maker": _state.get("maker") or "",
            "prefix": _state.get("prefix") or "",
            "codeFilter": _state.get("codeFilter") or "",
            "taskId": _state.get("taskId") or "",
            "taskName": _state.get("taskName") or "",
            "force": bool(_state.get("force")),
            "mode": (
                "force"
                if str(_state.get("mode") or "").strip().lower() == "force"
                or _state.get("force")
                else "incremental"
            ),
            "queue": _queue_public(_state.get("queue")),
            "events": events,
            "eventCount": total_events,
            "currentDetail": dict(detail) if isinstance(detail, dict) else None,
            "watchHold": bool(_state.get("watchHold")),
            "resumable": bool(_state.get("resumable"))
            or bool(_state.get("pauseSaved")),
            "pauseSaved": bool(_state.get("pauseSaved")),
            "exportFields": list(_state.get("exportFields") or []),
            "localFields": list(_state.get("localFields") or []),
        }
        return out


def list_export_codes(
    *,
    task_id: str | None = None,
    bucket: str = "failed",
    limit: int = 50000,
    offset: int = 0,
) -> dict[str, Any]:
    """按任务 + 桶取完整番号列表（点开成功/空号/失败用）。"""
    tid = str(task_id or "").strip()
    b = str(bucket or "").strip().lower()
    if b in {"done", "success", "ok"}:
        b = "done"
    elif b in {"empty", "empty_code", "emptycode"}:
        b = "empty"
    elif b in {"skip", "skipped"}:
        b = "skipped"
    elif b in {"fail", "failed", "error"}:
        b = "failed"
    else:
        b = "failed"
    if not tid:
        with _meta_lock:
            tid = str(_state.get("taskId") or "").strip()
            mem_key = {
                "done": "doneCodes",
                "empty": "emptyCodes",
                "skipped": "skippedCodes",
                "failed": "failedCodes",
            }[b]
            mem = list(_state.get(mem_key) or [])
        if not tid:
            return {
                "taskId": "",
                "bucket": b,
                "codes": mem[offset : offset + limit],
                "total": len(mem),
            }
    db_codes = scrape_export_log_store.list_result_codes(
        tid, b, limit=limit, offset=offset
    )
    counts = scrape_export_log_store.count_result_codes(tid)
    if db_codes or counts.get(b, 0):
        return {
            "taskId": tid,
            "bucket": b,
            "codes": db_codes,
            "total": int(counts.get(b) or len(db_codes)),
        }
    # 回退内存 / 任务卡
    with _meta_lock:
        mem_key = {
            "done": "doneCodes",
            "empty": "emptyCodes",
            "skipped": "skippedCodes",
            "failed": "failedCodes",
        }[b]
        if str(_state.get("taskId") or "").strip() == tid:
            mem = list(_state.get(mem_key) or [])
            return {
                "taskId": tid,
                "bucket": b,
                "codes": mem[offset : offset + max(1, int(limit))],
                "total": len(mem),
            }
    return {"taskId": tid, "bucket": b, "codes": [], "total": 0}


def claim_export() -> bool:
    _reconcile_stuck_export_state()
    with _meta_lock:
        if _state.get("running"):
            return False
        if not _acquire_export_file_lock(steal_if_idle=True):
            return False
        _control["cancel"] = False
        _control["clearOnStop"] = False
        _control["pause_abort"] = False
        _state.update(
            {
                "running": True,
                "paused": False,
                "startedAt": _now_iso(),
                "finishedAt": "",
                "message": "queued",
                "total": 0,
                "done": 0,
                "failed": 0,
                "skipped": 0,
                "empty": 0,
                "active": 0,
                "doneCodes": [],
                "skippedCodes": [],
                "failedCodes": [],
                "emptyCodes": [],
                "activeCodes": [],
                "activeFastCodes": [],
                "activeSlowCodes": [],
                "pendingFast": 0,
                "pendingSlow": 0,
                "current": "",
                "region": "",
                "maker": "",
                "prefix": "",
                "codeFilter": "",
                "taskId": "",
                "taskName": "",
                "events": [],
                "currentDetail": None,
            }
        )
        _clear_pending_detail_display()
        return True


def abort_claim(message: str = "failed") -> None:
    """claim 后未能进入 run_export 时调用；尝试接下一项。"""
    if _export_worker_alive():
        return
    next_job: dict[str, Any] | None = None
    with _meta_lock:
        if _state.get("message") != "queued" and not _state.get("running"):
            return
        # 尚未真正开刮 / building 短窗 / 无 current
        stuck_early = _state.get("message") in ("queued", "building") or (
            _state.get("running")
            and int(_state.get("total") or 0) == 0
            and not _state.get("current")
        )
        if stuck_early:
            _end_flags["message"] = message
            _end_flags["clearOnStop"] = False
            queue = list(_state.get("queue") or [])
            if queue:
                nxt = queue.pop(0)
                _state["queue"] = queue
                if isinstance(nxt, dict):
                    _prime_state_for_job(nxt)
                    next_job = nxt
                else:
                    _state.update(
                        {
                            "running": False,
                            "paused": False,
                            "finishedAt": _now_iso(),
                            "message": message,
                        }
                    )
                    _release_export_file_lock()
            else:
                _control["cancel"] = False
                _control["clearOnStop"] = False
                _state.update(
                    {
                        "running": False,
                        "paused": False,
                        "finishedAt": _now_iso(),
                        "message": message,
                    }
                )
                _release_export_file_lock()
    if next_job:
        _spawn_export_thread(next_job)
    else:
        _reset_export_mutex_if_stale()


def _reset_idle_state() -> None:
    _control["cancel"] = False
    _control["clearOnStop"] = False
    _control["pause_abort"] = False
    _state.update(
        {
            "running": False,
            "paused": False,
            "watchHold": False,
            "resumable": False,
            "pauseSaved": False,
            "allTargets": [],
            "startedAt": "",
            "finishedAt": "",
            "message": "",
            "total": 0,
            "done": 0,
            "failed": 0,
            "skipped": 0,
            "empty": 0,
            "active": 0,
            "doneCodes": [],
            "skippedCodes": [],
            "failedCodes": [],
            "emptyCodes": [],
            "activeCodes": [],
            "activeFastCodes": [],
            "activeSlowCodes": [],
            "pendingFast": 0,
            "pendingSlow": 0,
            "current": "",
            "region": "",
            "maker": "",
            "prefix": "",
            "codeFilter": "",
            "taskId": "",
            "taskName": "",
            "force": False,
            "mode": "incremental",
            "queue": [],
            "events": [],
            "currentDetail": None,
        }
    )
    _clear_pending_detail_display()
    _release_export_file_lock()
    _clear_resume_checkpoint()
    try:
        if _STATUS_PATH.is_file():
            _STATUS_PATH.unlink()
    except OSError:
        pass


def pause_export() -> dict[str, Any]:
    with _pause_cv:
        if not _state.get("running"):
            raise RuntimeError("当前没有进行中的刮削任务")
        if _control.get("cancel"):
            raise RuntimeError("任务正在取消中")
        _state["paused"] = True
        _state["message"] = "paused"
        _state["watchHold"] = True
        _state["pauseSaved"] = True
        _control["pause_abort"] = True
        n_active = _clear_active_progress_locked()
        tid = str(_state.get("taskId") or "")
        done = int(_state.get("done") or 0)
        empty = int(_state.get("empty") or 0)
        skipped = int(_state.get("skipped") or 0)
        failed = int(_state.get("failed") or 0)
        total = int(_state.get("total") or 0)
        done_codes = list(_state.get("doneCodes") or [])
        empty_codes = list(_state.get("emptyCodes") or [])
        skipped_codes = list(_state.get("skippedCodes") or [])
        failed_codes = list(_state.get("failedCodes") or [])
    http_n, flare_n = _abort_all_inflight()
    bits = [f"已暂停，已中断进行中 {n_active} 路"]
    if http_n:
        bits.append(f"关闭 {http_n} 个刮削请求")
    if flare_n:
        bits.append(f"打断 {flare_n} 个过盾")
    _push_event(phase="job", text=" · ".join(bits), level="warn")
    if tid:
        _set_task_watch_armed(tid, False)
        _persist_task_result(
            tid,
            message="已暂停",
            done=done,
            empty=empty,
            skipped=skipped,
            failed=failed,
            total=total,
            done_codes=done_codes,
            empty_codes=empty_codes,
            skipped_codes=skipped_codes,
            failed_codes=failed_codes,
        )
    _write_resume_checkpoint(reason="paused")
    _persist_state(force=True)
    return export_status()


def resume_export() -> dict[str, Any]:
    with _pause_cv:
        if not _state.get("running"):
            raise RuntimeError("当前没有进行中的刮削任务")
        _control["pause_abort"] = False
        _state["paused"] = False
        _state["watchHold"] = False
        _state["message"] = "scraping"
        _pause_cv.notify_all()
    _push_event(phase="job", text="已继续刮削", level="ok")
    _persist_state(force=True)
    return export_status()


def cancel_export(*, clear: bool = False, keep_queue: bool = False) -> dict[str, Any]:
    """取消当前导出。keep_queue=True 时保留后续排队任务（单卡取消）。"""
    with _meta_lock:
        cancel_tid = str(_state.get("taskId") or "").strip()
        if not keep_queue:
            _state["queue"] = []
        if not _state.get("running"):
            if clear:
                _reset_idle_state()
                return export_status()
            raise RuntimeError("当前没有进行中的刮削任务")
        _control["cancel"] = True
        _control["clearOnStop"] = bool(clear)
        _control["pause_abort"] = False
        _state["paused"] = False
        _state["watchHold"] = True
        _state["message"] = "cancelling"
        _clear_active_progress_locked()
    if cancel_tid:
        _set_task_watch_armed(cancel_tid, False)
    _abort_all_inflight()
    with _pause_cv:
        _pause_cv.notify_all()
    _push_event(
        phase="job",
        text=(
            "正在取消当前任务…"
            if keep_queue
            else ("正在取消…" if not clear else "正在删除任务…")
        ),
        level="warn",
    )
    return export_status()


def dequeue_export_task(task_id: str) -> dict[str, Any]:
    """仅从队列移除指定 taskId，不影响正在跑的任务。"""
    tid = str(task_id or "").strip()
    if not tid:
        raise RuntimeError("缺少 taskId")
    with _meta_lock:
        queue = list(_state.get("queue") or [])
        next_q = [
            x
            for x in queue
            if not (
                isinstance(x, dict) and str(x.get("taskId") or "").strip() == tid
            )
        ]
        if len(next_q) == len(queue):
            raise RuntimeError("队列中没有该任务")
        _state["queue"] = next_q
    _push_event(
        phase="job",
        text=f"已移出队列 · {tid}",
        level="info",
    )
    _persist_state(force=True)
    return export_status()


def stop_export_task(task_id: str, *, remove_card: bool = False) -> dict[str, Any]:
    """按任务隔离停止：

    - 正在跑且 taskId 匹配 → 取消当前，保留队列里其它任务
    - 仅在队列中 → 移出队列
    - 都不匹配 → 幂等成功（已结束/空闲卡删除时常见，勿 400）
    """
    tid = str(task_id or "").strip()
    if not tid:
        raise RuntimeError("缺少 taskId")
    _reconcile_stuck_export_state()
    with _meta_lock:
        cur = str(_state.get("taskId") or "").strip()
        running = bool(_state.get("running"))
        in_queue = any(
            isinstance(x, dict) and str(x.get("taskId") or "").strip() == tid
            for x in list(_state.get("queue") or [])
        )
    if running and cur == tid:
        return cancel_export(clear=bool(remove_card), keep_queue=True)
    if in_queue:
        return dequeue_export_task(tid)
    return export_status()


def clear_export() -> dict[str, Any]:
    """删除进度卡片：运行中则取消并清空队列，空闲则直接清空。"""
    _reconcile_stuck_export_state()
    with _meta_lock:
        _state["queue"] = []
        _state["watchHold"] = False
        if _state.get("running"):
            _control["cancel"] = True
            _control["clearOnStop"] = True
            _state["paused"] = False
            _state["message"] = "cancelling"
            running = True
        else:
            _reset_idle_state()
            running = False
    if running:
        _abort_all_inflight()
        with _pause_cv:
            _pause_cv.notify_all()
        _push_event(phase="job", text="正在删除任务…", level="warn")
    return export_status()


def prepare_process_shutdown() -> None:
    """进程退出 / 热重载：先落盘断点与任务计数，再打断导出。"""
    global _lock, _export_worker
    was_busy = False
    reason = "interrupted"
    try:
        with _meta_lock:
            was_busy = bool(_state.get("running")) or str(
                _state.get("message") or ""
            ) in _STUCK_BUSY_MESSAGES or str(_state.get("message") or "") == "paused"
            if was_busy:
                if _state.get("paused") or str(_state.get("message") or "") == "paused":
                    _state["pauseSaved"] = True
                    reason = "paused"
                else:
                    reason = "interrupted"
                    _state["message"] = "interrupted"
        if was_busy:
            _write_resume_checkpoint(reason=reason)
            _persist_state(force=True)
    except Exception:
        log.exception("shutdown checkpoint failed")
    with _meta_lock:
        _control["cancel"] = True
        _control["clearOnStop"] = False
        _control["pause_abort"] = False
        _state["paused"] = False
        _state["queue"] = []
        msg = str(_state.get("message") or "")
        if _state.get("running") or msg in _STUCK_BUSY_MESSAGES or msg == "paused":
            _state["running"] = False
            if msg != "paused" and not _state.get("pauseSaved"):
                _state["message"] = "interrupted"
            elif _state.get("pauseSaved"):
                _state["message"] = "paused"
            _state["finishedAt"] = _now_iso()
        _state["active"] = 0
        _state["activeCodes"] = []
        _state["activeFastCodes"] = []
        _state["activeSlowCodes"] = []
        _state["pendingFast"] = 0
        _state["pendingSlow"] = 0
    _abort_all_inflight()
    _force_clear_export_file_lock()
    _export_worker = None
    _lock = threading.Lock()


def _wait_if_paused_or_cancel() -> str:
    """返回 continue | cancel。暂停时阻塞等待（resume 会 notify）。"""
    with _pause_cv:
        while True:
            if _control.get("cancel"):
                return "cancel"
            # 兼容：假死逻辑曾误清 paused，但 watchHold/pauseSaved 仍表示用户要停
            still_hold = bool(
                _state.get("paused")
                or _control.get("pause_abort")
                or (
                    _state.get("watchHold")
                    and _state.get("pauseSaved")
                    and not _control.get("cancel")
                )
            )
            if not still_hold:
                return "continue"
            if not _state.get("paused") and _state.get("watchHold"):
                # 被误清 paused 时拉回暂停态，避免自动续跑
                _state["paused"] = True
                _control["pause_abort"] = True
            _state["message"] = "paused"
            _pause_cv.wait(timeout=0.5)


def _resolve_library(raw: str | None) -> Path:
    """相对路径相对项目根；绝对路径原样。"""
    s = str(raw or "").strip()
    if not s:
        return DEFAULT_LIBRARY
    p = Path(s)
    if not p.is_absolute():
        return (ROOT / p).resolve()
    return p


def scrape_settings() -> dict[str, Any]:
    raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
    origin = str(raw.get("origin") or "http://127.0.0.1:9210").strip().rstrip("/")
    lib = str(_resolve_library(raw.get("libraryRoot") or raw.get("library_root")))
    try:
        priority_schema = int(
            raw.get("kindPrioritySchema")
            or raw.get("kind_priority_schema")
            or scrape_profiles.KIND_PRIORITY_SCHEMA
        )
    except (TypeError, ValueError):
        priority_schema = scrape_profiles.KIND_PRIORITY_SCHEMA
    profiles = scrape_profiles.normalize_kind_profiles(
        raw.get("kindProfiles")
        or raw.get("kind_profiles")
        or raw.get("regionProfiles")
        or raw.get("region_profiles"),
        priority_schema=priority_schema,
        global_field_priority=scrape_profiles.normalize_field_priority(
            raw.get("fieldPriority") or raw.get("field_priority")
        ),
    )
    sources = scrape_profiles.normalize_sources_map(raw.get("sources"))
    cover_strategy = str(
        raw.get("coverDownloadStrategy") or raw.get("cover_download_strategy") or ""
    ).strip().lower()
    if cover_strategy not in {"priority", "size"}:
        cover_strategy = "priority"
    poster_crop = scrape_profiles.normalize_poster_crop(
        raw.get("posterCrop") or raw.get("poster_crop")
    )
    naming = scrape_naming.fixed_naming()
    metadata_optimize = scrape_metadata_optimize.normalize_metadata_optimize(
        raw.get("metadataOptimize") or raw.get("metadata_optimize")
    )
    fast_conc, slow_conc = _resolve_channel_concurrency(raw if isinstance(raw, dict) else {})
    return {
        # 始终启用；旧配置若写过 false 也视为开启
        "enabled": True,
        "origin": origin or "http://127.0.0.1:9210",
        "libraryRoot": lib,
        "writeTree": bool(raw.get("writeTree", raw.get("write_tree", True))),
        "writeEmby": bool(raw.get("writeEmby", raw.get("write_emby", True))),
        "kindProfiles": profiles,
        "regionProfiles": profiles,
        "sources": sources,
        "coverDownloadStrategy": cover_strategy,
        "posterCrop": poster_crop,
        "naming": naming,
        "metadataOptimize": metadata_optimize,
        "exportFastConcurrency": fast_conc,
        "exportSlowConcurrency": slow_conc,
        "exportConcurrency": max(fast_conc, slow_conc),
        "enabledSourceIds": scrape_profiles.enabled_source_ids(sources),
    }


def _normalize_fields(raw: Any) -> list[str]:
    return scrape_profiles.normalize_export_fields(raw)


def _format_field_priority_hint(fp: dict[str, list[str]] | None) -> str:
    """日志用：封面/标题/简介/制片/女优源序。"""
    fields = scrape_profiles.normalize_field_priority(fp)
    parts: list[str] = []
    labels = {
        "cover": "封面",
        "titleZh": "标题",
        "outline": "简介",
        "studio": "制片",
        "actors": "女优",
        "tags": "标签",
        "series": "系列",
    }
    for key in scrape_profiles.FIELD_PRIORITY_KEYS:
        srcs = [str(s) for s in (fields.get(key) or []) if str(s).strip()]
        lab = labels.get(key, key)
        parts.append(f"{lab}={'/'.join(srcs) if srcs else '—'}")
    return " · ".join(parts)


def _region_label(region_id: str) -> str:
    meta = maker_fs.REGION_META.get(region_id) or {}
    return _safe_segment(str(meta.get("label") or region_id or "unknown"))


def collect_targets(
    *,
    region: str | None = None,
    regions: list[str] | None = None,
    maker: str | None = None,
    prefix: str | None = None,
    code: str | None = None,
    codes: list[str] | None = None,
    rekey: bool = True,
    include_fill: bool = False,
) -> list[dict[str, Any]]:
    """从 maker-fs 收集待刮削/物化番号。

    rekey=False：直接用索引 covers 键（物化热路径，避免全库重算键拖慢十几秒）。
    include_fill=True：digit_pad 前缀按 fillFrom..fillTo 补空洞（刮削要 999 不要只 831）。
    code / codes：限定番号（可多号，逗号/顿号分隔）；缺失时仍合成目标便于强制重刮。
    """
    want_list = _parse_export_code_filters(code, codes)
    want_codes = set(want_list)
    want_prefix = maker_fs._std_prefix(prefix) if prefix else ""  # noqa: SLF001
    want_maker = (maker or "").strip()
    region_ids: list[str] = []
    if regions:
        for r in regions:
            rid = maker_fs.resolve_fs_region(str(r or "")) or str(r or "").strip()
            if rid and rid not in region_ids:
                region_ids.append(rid)
    elif region:
        rid = maker_fs.resolve_fs_region(region) or region
        if rid:
            region_ids = [rid]
    else:
        region_ids = list(maker_fs.REGION_ORDER)
    out: list[dict[str, Any]] = []
    for rid in region_ids:
        if not rid or rid not in maker_fs.REGION_META:
            continue
        cat = maker_fs.read_region_index(rid)
        if not cat:
            continue
        for pinfo in cat.get("prefixes") or []:
            if not isinstance(pinfo, dict):
                continue
            p = maker_fs._std_prefix(str(pinfo.get("prefix") or ""))  # noqa: SLF001
            if not p:
                continue
            if want_prefix and p != want_prefix:
                continue
            board = str(
                pinfo.get("board_name") or pinfo.get("name") or p or "未分组"
            ).strip()
            if want_maker and board != want_maker:
                continue
            idx, _ = maker_fs._find_prefix_index(p, rid)  # noqa: SLF001
            if not idx:
                continue
            covers = idx.get("covers") if isinstance(idx.get("covers"), dict) else {}
            pad = max(1, min(8, int(idx.get("pad") or 3)))
            from_n = max(1, int(idx.get("from") or 1))
            to_n = max(0, int(idx.get("to") or 0))
            if rekey:
                # 按 pad + from..to 规范；超区间（如 to=234 却有 -720）不进刮削
                covers = maker_fs._rekey_covers_to_pad(  # noqa: SLF001
                    covers, prefix=p, pad=pad, from_n=from_n, to_n=to_n
                )
            seen_codes: set[str] = set()
            for ckey, hit in covers.items():
                # 用索引 covers 键原样（仅大小写），不再二次 _std_code 改写
                c = str(ckey or "").strip().upper().replace("_", "-")
                if not c:
                    continue
                if want_codes and c not in want_codes and _std_code(c) not in want_codes:
                    continue
                cover_url = None
                urls: list[str] = []
                forum_title = ""
                forum_actors = None
                if isinstance(hit, dict):
                    urls = [u for u in (hit.get("coverUrls") or []) if u]
                    cover_url = hit.get("coverUrl") or (urls[0] if urls else None)
                    forum_title = str(hit.get("forumTitle") or "").strip()
                    forum_actors = hit.get("forumActors")
                out.append(
                    {
                        "code": c,
                        "prefix": p,
                        "maker": board,
                        "region": rid,
                        "coverUrl": cover_url,
                        "coverUrls": urls[:4],
                        "forumTitle": forum_title or None,
                        "forumActors": (
                            [str(a).strip() for a in forum_actors if str(a).strip()]
                            if isinstance(forum_actors, list)
                            else None
                        ),
                    }
                )
                seen_codes.add(c)
                seen_codes.add(_std_code(c))
            # 刮削：按发现区间补空洞；指定番号时也补，便于空号/无数据强制重刮
            if include_fill and maker_fs.should_fill_digit_range(rid, p):
                fill_from = int(idx.get("fillFrom") or 0)
                fill_to = int(idx.get("fillTo") or 0)
                if fill_to < fill_from or fill_to <= 0:
                    d_from, d_to = maker_fs._discovered_digit_bounds(covers, p)  # noqa: SLF001
                    fill_from, fill_to = d_from, d_to
                if fill_to >= fill_from > 0:
                    for c in maker_fs._iter_filled_digit_codes(  # noqa: SLF001
                        p, fill_from, fill_to, pad
                    ):
                        cu = str(c or "").strip().upper()
                        if not cu or cu in seen_codes:
                            continue
                        if (
                            want_codes
                            and cu not in want_codes
                            and _std_code(cu) not in want_codes
                        ):
                            continue
                        out.append(
                            {
                                "code": cu,
                                "prefix": p,
                                "maker": board,
                                "region": rid,
                                "coverUrl": None,
                                "coverUrls": [],
                                "forumTitle": None,
                                "forumActors": None,
                                "fromFill": True,
                            }
                        )
                        seen_codes.add(cu)
                        seen_codes.add(_std_code(cu))
    # 去重保序：同区同前缀同番号才算一条（FC2 / FC2-PPV 分开）
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for it in out:
        k = f"{it['region']}|{it['prefix']}|{it['code']}"
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)

    # 指定番号但索引/补全都没有：仍合成目标（强制重刮空号）
    if want_list:
        have = {_std_code(str(t.get("code") or "")) for t in uniq}
        have |= {str(t.get("code") or "").strip().upper() for t in uniq}
        rid0 = region_ids[0] if region_ids else ""
        for c in want_list:
            if c in have:
                continue
            pref = want_prefix
            if not pref:
                m = re.fullmatch(r"([A-Z0-9]+)-\d+", c)
                pref = m.group(1) if m else ""
            if not pref or not rid0:
                continue
            uniq.append(
                {
                    "code": c,
                    "prefix": pref,
                    "maker": want_maker or pref,
                    "region": rid0,
                    "coverUrl": None,
                    "coverUrls": [],
                    "forumTitle": None,
                    "forumActors": None,
                    "fromFilter": True,
                }
            )
            have.add(c)
    return uniq


def _region_label_to_id() -> dict[str, str]:
    out: dict[str, str] = {}
    for rid, meta in maker_fs.REGION_META.items():
        lab = str((meta or {}).get("label") or "").strip()
        if lab:
            out[lab] = rid
    try:
        for kid, lab in (scrape_naming.KIND_LABELS or {}).items():
            s = str(lab or "").strip()
            if s and s not in out and kid in maker_fs.REGION_META:
                out[s] = str(kid)
    except Exception:
        pass
    return out


def _target_from_library_entry_dir(
    entry: Path,
    library: Path,
    *,
    label_map: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """从片库番号目录反推刮削目标（空目录 / 仅有种子也可刮）。"""
    try:
        rel = entry.relative_to(library)
        parts = list(rel.parts)
    except Exception:
        try:
            rel = entry.resolve().relative_to(library.resolve())
            parts = list(rel.parts)
        except Exception:
            return None
    if len(parts) < 2:
        return None
    labels = label_map if label_map is not None else _region_label_to_id()
    region_label = str(parts[0] or "").strip()
    rid = labels.get(region_label) or ""
    if not rid:
        if region_label in maker_fs.REGION_META:
            rid = region_label
        else:
            return None
    code = ""
    prefix = ""
    maker = str(parts[1] or "").strip() or "未分组"
    meta_path = entry / INDEX_META_FILE
    raw: dict[str, Any] | None = None
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            loaded = None
        if isinstance(loaded, dict):
            raw = loaded
            code = str(raw.get("code") or "").strip().upper().replace("_", "-")
            prefix = maker_fs._std_prefix(str(raw.get("prefix") or ""))  # noqa: SLF001
            mk = str(raw.get("maker") or raw.get("studio") or "").strip()
            if mk:
                maker = mk
            rr = str(raw.get("region") or "").strip()
            if rr in maker_fs.REGION_META:
                rid = rr
    if not code:
        code = str(entry.name or "").strip().upper().replace("_", "-")
    if not code:
        return None
    if not prefix:
        if "-" in code:
            prefix = maker_fs._std_prefix(code.split("-", 1)[0])  # noqa: SLF001
        elif len(parts) >= 3:
            prefix = maker_fs._std_prefix(str(parts[-2]))  # noqa: SLF001
    cover_url = None
    cover_urls: list[str] = []
    forum_title = None
    if raw is not None:
        cover_url = raw.get("coverUrl") or raw.get("poster")
        cover_urls = [
            str(u).strip()
            for u in (raw.get("coverUrls") or [])
            if str(u).strip()
        ]
        forum_title = (
            str(raw.get("title") or raw.get("titleZh") or "").strip() or None
        )
    url_file = entry / "封面.url"
    if not cover_url and url_file.is_file():
        try:
            text = url_file.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"^\s*URL\s*=\s*(\S+)", text, re.I | re.M)
            if m:
                cover_url = m.group(1).strip()
        except Exception:
            pass
    if cover_url and cover_url not in cover_urls:
        cover_urls = [str(cover_url), *cover_urls]
    return {
        "code": code,
        "prefix": prefix or "",
        "maker": maker,
        "region": rid,
        "coverUrl": cover_url,
        "coverUrls": cover_urls[:4],
        "forumTitle": forum_title,
        "forumActors": None,
        "fromLibraryDir": True,
    }


def _scoped_library_prefix_dirs(
    library: Path,
    *,
    region_ids: list[str] | None,
    maker: str,
    prefix: str,
) -> list[Path]:
    """任务范围内的 {区域}/{厂牌}/{前缀}/ 目录，避免全库扫。"""
    want_prefix = maker_fs._std_prefix(prefix) if prefix else ""  # noqa: SLF001
    want_maker = (maker or "").strip()
    if not want_prefix and not want_maker:
        return []
    labels: list[str] = []
    if region_ids:
        for rid in region_ids:
            lab = _region_label(rid)
            if lab and lab not in labels:
                labels.append(lab)
    else:
        try:
            for child in library.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    labels.append(child.name)
        except OSError:
            return []
    roots: list[Path] = []
    for lab in labels:
        region_dir = library / lab
        if not region_dir.is_dir():
            continue
        try:
            makers = [p for p in region_dir.iterdir() if p.is_dir()]
        except OSError:
            continue
        for maker_dir in makers:
            if want_maker and maker_dir.name != want_maker:
                continue
            if want_prefix:
                cand = maker_dir / want_prefix
                if cand.is_dir():
                    roots.append(cand)
                    continue
                # 大小写不一致
                try:
                    for child in maker_dir.iterdir():
                        if (
                            child.is_dir()
                            and child.name.upper() == want_prefix.upper()
                        ):
                            roots.append(child)
                            break
                except OSError:
                    pass
            else:
                roots.append(maker_dir)
    return roots


def collect_library_empty_folder_targets(
    *,
    region: str | None = None,
    regions: list[str] | None = None,
    maker: str | None = None,
    prefix: str | None = None,
    code: str | None = None,
) -> list[dict[str, Any]]:
    """扫描任务范围内片库：无 scrape.json 的番号目录纳入刮削。

    必须带前缀或番号；禁止全库扫描（十万级目录会卡死「开始」数十秒）。
    空洞补全由 collect_targets(include_fill=True) 负责。
    """
    from . import library_materialize as lm

    want_code = str(code or "").strip().upper().replace("_", "-")
    want_prefix = maker_fs._std_prefix(prefix) if prefix else ""  # noqa: SLF001
    want_maker = (maker or "").strip()
    if not want_prefix and not want_code and not want_maker:
        return []

    region_ids: list[str] = []
    if regions:
        for r in regions:
            rid = maker_fs.resolve_fs_region(str(r or "")) or str(r or "").strip()
            if rid and rid not in region_ids:
                region_ids.append(rid)
    elif region:
        rid = maker_fs.resolve_fs_region(region) or region
        if rid:
            region_ids = [rid]

    library = _resolve_library_root()
    if not library.is_dir():
        return []

    label_map = _region_label_to_id()
    out: list[dict[str, Any]] = []

    def _maybe_add(entry: Path) -> None:
        scrape_path = entry / SCRAPE_META_FILE
        if scrape_path.is_file():
            return
        t = _target_from_library_entry_dir(entry, library, label_map=label_map)
        if not t:
            return
        rid = str(t.get("region") or "")
        if region_ids and rid not in region_ids:
            return
        c = str(t.get("code") or "")
        if want_code and c != want_code and _std_code(c) != want_code:
            return
        p = maker_fs._std_prefix(str(t.get("prefix") or ""))  # noqa: SLF001
        if want_prefix and p != want_prefix:
            return
        board = str(t.get("maker") or "").strip()
        if want_maker and board != want_maker:
            return
        out.append(t)

    if want_code and not want_prefix:
        # 单番号：走定位，不做目录遍历
        found = _find_library_entry_dir(want_code)
        if found is not None:
            _maybe_add(found)
        return out

    roots = _scoped_library_prefix_dirs(
        library,
        region_ids=region_ids or None,
        maker=want_maker,
        prefix=want_prefix,
    )
    for root in roots:
        try:
            children = [p for p in root.iterdir() if p.is_dir()]
        except OSError:
            continue
        for child in children:
            # root 已是前缀目录 → 子项为番号；或 root 是厂牌 → 子项可能是前缀/番号
            if lm._is_entry_dir(child):  # noqa: SLF001
                _maybe_add(child)
                continue
            if want_prefix:
                continue
            try:
                for code_dir in child.iterdir():
                    if code_dir.is_dir() and lm._is_entry_dir(code_dir):  # noqa: SLF001
                        _maybe_add(code_dir)
            except OSError:
                pass
    return out


def merge_scrape_targets(
    index_targets: list[dict[str, Any]],
    disk_targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """索引目标优先；片库空目录补漏。同 区|前缀|番号 合并，磁盘侧补空字段。"""
    best: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for src in (index_targets, disk_targets):
        for t in src:
            if not isinstance(t, dict):
                continue
            rid = str(t.get("region") or "").strip()
            p = maker_fs._std_prefix(str(t.get("prefix") or ""))  # noqa: SLF001
            c = str(t.get("code") or "").strip().upper().replace("_", "-")
            if not c:
                continue
            key = f"{rid}|{p}|{c}"
            prev = best.get(key)
            if prev is None:
                best[key] = {**t, "prefix": p, "code": c}
                order.append(key)
                continue
            # 补空：封面/标题等
            merged = dict(prev)
            for k in ("coverUrl", "forumTitle", "maker"):
                if not str(merged.get(k) or "").strip() and str(t.get(k) or "").strip():
                    merged[k] = t.get(k)
            prev_urls = [
                str(u).strip() for u in (merged.get("coverUrls") or []) if str(u).strip()
            ]
            for u in t.get("coverUrls") or []:
                s = str(u).strip()
                if s and s not in prev_urls:
                    prev_urls.append(s)
            if prev_urls:
                merged["coverUrls"] = prev_urls[:4]
            if t.get("fromLibraryDir"):
                merged["fromLibraryDir"] = True
            if t.get("fromFill"):
                merged["fromFill"] = True
            best[key] = merged
    return [best[k] for k in order if k in best]


_NO_DETAIL_ERR_MARKERS = (
    "未找到详情页",
    "未找到详情",
    "详情页不存在",
    "not found",
    "no detail",
    "detail not found",
    "404",
)


def _is_no_detail_error(text: str) -> bool:
    s = str(text or "").strip().lower()
    if not s:
        return False
    if s in {"not_found", "notfound"}:
        return True
    return any(m in s for m in _NO_DETAIL_ERR_MARKERS)


def _meta_is_not_found(meta: dict[str, Any] | None) -> bool:
    """落盘 scrape.json 是否为「全网无详情」失败标记（非成功数据）。"""
    if not isinstance(meta, dict):
        return False
    if meta.get("ok") is not False:
        return False
    msg = str(meta.get("message") or "").strip()
    msg_l = msg.lower()
    return (
        msg_l in {"not_found", "notfound"}
        or _is_no_detail_error(msg)
        or "全部源未找到详情页" in msg
    )


def _iter_network_source_runs(runs: Any) -> list[dict[str, Any]]:
    """网络源 run（排除 index/本地 与 cid-retry 附记）。"""
    out: list[dict[str, Any]] = []
    if not isinstance(runs, list):
        return out
    skip_ids = {"index", "seed", "local", "maker-fs", "forum"}
    for run in runs:
        if not isinstance(run, dict):
            continue
        sid = str(run.get("id") or "").strip().lower()
        if not sid or sid in skip_ids:
            continue
        if str(run.get("detail") or "").strip() == "cid-retry":
            continue
        out.append(run)
    return out


def _has_usable_scrape_payload(meta: dict[str, Any], code: str) -> bool:
    """是否有真实可用的刮削内容（番号本身当 title 不算）。"""
    c = _std_code(code) or _std_code(str(meta.get("code") or ""))
    title = str(meta.get("title") or "").strip()
    title_zh = str(meta.get("titleZh") or "").strip()
    if title_zh:
        return True
    if title:
        t_std = _std_code(title)
        if t_std and c and t_std == c:
            pass
        elif title.upper() == (c or "").upper():
            pass
        else:
            return True
    if str(meta.get("poster") or meta.get("coverUrl") or "").strip():
        return True
    if str(meta.get("coverLocal") or meta.get("posterLocal") or "").strip():
        return True
    actors = meta.get("actors")
    if isinstance(actors, list) and any(str(a).strip() for a in actors):
        return True
    if str(meta.get("plot") or meta.get("outline") or "").strip():
        return True
    studio = str(meta.get("studio") or "").strip()
    if studio and studio.upper() != (c or "").upper():
        return True
    tags = meta.get("genres") or meta.get("tags")
    if isinstance(tags, list) and any(str(t).strip() for t in tags):
        return True
    if str(meta.get("series") or "").strip():
        return True
    return False


def _all_network_sources_no_detail(
    runs: Any,
    *,
    expected_sources: list[str] | None = None,
) -> bool:
    """所有网络源均反馈未找到详情页（番号不存在）。

    超时 / 5xx / 连接失败不算「无数据」。
    若传入 expected_sources，须这些源都实际跑过且均无详情，才算全源确认。
    """
    net_runs = _iter_network_source_runs(runs)
    if not net_runs:
        return False
    meta_runs = [
        r
        for r in net_runs
        if str(r.get("mode") or "").strip().lower() in {"", "meta"}
    ]
    use = meta_runs if meta_runs else net_runs
    if not use:
        return False
    if any(bool(r.get("ok")) for r in use):
        return False
    if not all(
        _is_no_detail_error(str(r.get("error") or ""))
        or _is_no_detail_error(str(r.get("message") or ""))
        for r in use
    ):
        return False
    if expected_sources:
        tried = {
            str(r.get("id") or "").strip().lower()
            for r in use
            if str(r.get("id") or "").strip()
        }
        want = {
            str(s).strip().lower() for s in expected_sources if str(s).strip()
        }
        if want and not want <= tried:
            return False
    return True


def _is_confirmed_empty_meta(meta: dict[str, Any] | None) -> bool:
    """落盘是否为「无数据」空号（可增量跳过）。

    快源判定 not_found 后落盘；无 sourceRuns 的旧空号标记也认（无可用字段即可）。
    """
    if not _meta_is_not_found(meta):
        return False
    assert isinstance(meta, dict)
    code = str(meta.get("code") or "")
    if _has_usable_scrape_payload(meta, code):
        return False
    runs = meta.get("sourceRuns")
    net = _iter_network_source_runs(runs)
    if not net:
        return True
    return _all_network_sources_no_detail(runs)


def _classify_network_scrape(
    meta: dict[str, Any],
    *,
    code: str,
    need_net: bool,
    expected_sources: list[str] | None = None,
) -> str:
    """网络刮削结果：ok | not_found | hard_fail。

    not_found（空号）：快源识别不到 / 无任何可用字段。
    hard_fail（失败）：超时等可重试，或有部分字段但不齐。
    """
    if not need_net:
        return "ok"
    msg = str(meta.get("message") or "").strip()
    msg_l = msg.lower()
    if msg in {"paused", "cancelled", "needs_flare"}:
        return msg
    runs = meta.get("sourceRuns")
    has_partial = _has_usable_scrape_payload(meta, code)
    # 快源已判定无详情 → 空号（允许 sourceRuns 稍后补全）
    if (not has_partial) and (
        msg_l in {"not_found", "notfound"}
        or _all_network_sources_no_detail(runs, expected_sources=expected_sources)
    ):
        return "not_found"
    if (not meta.get("ok")) and (
        msg in {"bad response", "scrape_timeout", "scrape_deadline", "no_meta"}
        or msg.startswith(("刮削服务", "无法连接刮削服务"))
    ):
        return "hard_fail"
    if bool(meta.get("ok")) or has_partial:
        return "ok"
    # 无字段且未给出 not_found：失败可重试
    return "hard_fail"


def _call_scrape(
    origin: str,
    code: str,
    prefer_cover: str | None,
    *,
    force: bool,
    kind: str | None = None,
    region: str | None = None,
    meta_sources: list[str] | None = None,
    cover_sources: list[str] | None = None,
    field_priority: dict[str, list[str]] | None = None,
    prefer_title: str | None = None,
    prefer_actors: list[str] | None = None,
    prefer_local: dict[str, Any] | None = None,
    cover_download_strategy: str | None = None,
    poster_crop: dict[str, Any] | None = None,
    channel: str | None = None,
    deadline_ms: int | None = None,
) -> dict[str, Any]:
    url = f"{origin.rstrip('/')}/api/scrape"
    payload: dict[str, Any] = {"code": code, "force": force}
    ch = str(channel or "").strip().lower()
    if ch in {"fast", "slow"}:
        payload["channel"] = ch
    if prefer_cover:
        payload["preferCoverUrl"] = prefer_cover
    if prefer_title:
        payload["preferTitle"] = prefer_title
    if prefer_actors:
        payload["preferActors"] = [
            str(a).strip() for a in prefer_actors if str(a).strip()
        ]
    if isinstance(prefer_local, dict) and prefer_local:
        payload["preferLocal"] = prefer_local
    if kind:
        payload["kind"] = kind
    if region:
        payload["region"] = region
    if meta_sources:
        payload["metaSources"] = meta_sources
    if cover_sources:
        payload["coverSources"] = cover_sources
    if field_priority:
        payload["fieldPriority"] = field_priority
    if cover_download_strategy in {"priority", "size"}:
        payload["coverDownloadStrategy"] = cover_download_strategy
    if isinstance(poster_crop, dict) and poster_crop:
        payload["posterCrop"] = poster_crop
    if deadline_ms is not None:
        try:
            payload["deadlineMs"] = max(10000, min(120000, int(deadline_ms)))
        except Exception:
            pass
    last_err = "bad response"
    # 空号/全源失败时个别站会拖很久；过长读超时 + 重试会让快源槽位全堵死
    read_s = 40.0
    if deadline_ms is not None:
        try:
            read_s = max(12.0, min(90.0, float(deadline_ms) / 1000.0 + 5.0))
        except Exception:
            read_s = 40.0
    http_timeout = httpx.Timeout(10.0, read=read_s)
    for attempt in range(2):
        abort = _work_abort_kind()
        if abort == "cancel":
            return {"code": code, "ok": False, "message": "cancelled"}
        if abort == "paused":
            return {"code": code, "ok": False, "message": "paused"}
        client: httpx.Client | None = None
        try:
            # trust_env=False：禁止走系统代理，否则 127.0.0.1:9210 会被代理成 502
            client = httpx.Client(timeout=http_timeout, trust_env=False)
            _register_http_client(client)
            r = client.post(url, json=payload)
            if r.status_code in (502, 503, 504):
                last_err = f"刮削服务暂不可用 ({r.status_code})"
                time.sleep(1.2 * (attempt + 1))
                continue
            if r.status_code == 499 or (
                r.status_code >= 400
                and "abort" in (r.text or "").lower()
            ):
                abort = _work_abort_kind() or "paused"
                return {
                    "code": code,
                    "ok": False,
                    "message": "cancelled" if abort == "cancel" else "paused",
                }
            if r.status_code >= 400:
                detail = ""
                try:
                    detail = str((r.json() or {}).get("message") or "")
                except Exception:
                    detail = (r.text or "")[:120]
                last_err = detail or f"刮削服务 HTTP {r.status_code}"
                break
            body = r.json()
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, dict):
                return data
            last_err = str(body.get("message") or "bad response")
            break
        except httpx.TimeoutException:
            # 超时不重试：否则 5 槽 × 3 次 × 180s 会卡死整晚
            last_err = "scrape_timeout"
            return {"code": code, "ok": False, "message": "scrape_timeout"}
        except httpx.RequestError as e:
            abort = _work_abort_kind()
            if abort == "paused":
                return {"code": code, "ok": False, "message": "paused"}
            if abort == "cancel":
                return {"code": code, "ok": False, "message": "cancelled"}
            last_err = f"无法连接刮削服务 ({e.__class__.__name__})"
            time.sleep(1.2 * (attempt + 1))
        except Exception as e:
            abort = _work_abort_kind()
            if abort == "paused":
                return {"code": code, "ok": False, "message": "paused"}
            if abort == "cancel":
                return {"code": code, "ok": False, "message": "cancelled"}
            last_err = str(e)[:160]
            break
        finally:
            if client is not None:
                _unregister_http_client(client)
                try:
                    client.close()
                except Exception:
                    pass
    abort = _work_abort_kind()
    if abort == "paused":
        return {"code": code, "ok": False, "message": "paused"}
    if abort == "cancel":
        return {"code": code, "ok": False, "message": "cancelled"}
    return {"code": code, "ok": False, "message": last_err}


def _copy_cover(meta: dict[str, Any], dest: Path) -> bool:
    # 优先已裁好的竖版海报；否则用横版缩略图
    for key in ("posterLocal", "coverLocal"):
        local = meta.get(key)
        if local and Path(str(local)).is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(local), dest)
            return True
    poster = str(meta.get("poster") or "")
    # 跳过明显非封面资源，避免长时间外网阻塞
    lower = poster.lower()
    if not poster.startswith("http"):
        return False
    if any(x in lower for x in ("logo", "favicon", "sprite", ".svg")):
        return False
    try:
        with httpx.Client(timeout=8.0, follow_redirects=True) as client:
            r = client.get(poster)
            if r.status_code < 400 and len(r.content) > 200:
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(dest.suffix + ".tmp")
                tmp.write_bytes(r.content)
                tmp.replace(dest)
                return True
    except Exception as e:
        log.debug("cover download %s: %s", dest, e)
    return False


def _path_has_uncategorized(path: Path) -> bool:
    try:
        return "未分类" in path.parts
    except Exception:
        return "未分类" in str(path)


def _fc2_author_from_meta(
    meta: dict[str, Any], target: dict[str, Any]
) -> str | None:
    """刮削结果里可用的 FC2 作者名；无效则 None。"""
    makers = meta.get("makers") if isinstance(meta.get("makers"), list) else []
    actors = meta.get("actors") if isinstance(meta.get("actors"), list) else []
    candidates = [
        meta.get("studio"),
        makers[0] if makers else None,
        actors[0] if actors else None,
        target.get("maker"),
    ]
    bad = {"", "未知", "未分组", "未分类", "未知作者", "自定义"}
    for c in candidates:
        s = str(c or "").strip()
        if not s or s in bad:
            continue
        try:
            if maker_fs._is_fc2_plate_maker_name(s):
                continue
        except Exception:
            pass
        return s
    return None


def _write_entry(
    target: dict[str, Any],
    meta: dict[str, Any],
    *,
    library: Path,
    write_tree: bool = True,
    write_emby: bool = True,
    force: bool = False,
    fields: list[str] | None = None,
    local_fields: list[str] | None = None,
    naming: dict[str, Any] | None = None,
) -> str:
    """返回 done|skipped|failed。只写入本地库已有 {CODE} 目录（物化产物）。"""
    del write_tree, write_emby, naming  # 落盘仅 scrape.json + 封面；不改索引 meta.json
    code = _std_code(str(target.get("code") or meta.get("code") or ""))
    if not code:
        return "failed"
    want = _normalize_fields(fields)
    want_set = set(want)
    reuse = [
        f
        for f in scrape_profiles.normalize_local_fields(local_fields)
        if f in want_set
    ]
    rid = str(target.get("region") or "")
    label = _region_label(rid)
    naming_cfg = scrape_naming.fixed_naming()
    kind_id = scrape_naming.resolve_kind(
        kind=str(meta.get("scrapeKind") or ""),
        region=rid,
        code=code,
    )

    existing = _find_library_entry_dir(code)
    if existing is None or not existing.is_dir():
        # 补全号 / 未物化：按命名规则建空目录，允许继续刮削落盘
        try:
            existing = scrape_naming.resolve_entry_dir(
                library,
                naming_cfg,
                code=code,
                meta={
                    "code": code,
                    "prefix": target.get("prefix"),
                    "maker": target.get("maker"),
                    "region": rid,
                    "regionLabel": label,
                },
                target=target,
                category=label,
                kind=kind_id,
            )
            existing.mkdir(parents=True, exist_ok=True)
        except Exception:
            log.warning(
                "scrape write skip %s: 本地库无对应文件夹且无法创建",
                code,
                exc_info=True,
            )
            return "failed"
    _remember_entry_dir(code, existing)

    # 索引 meta.json 只读；激活的本地可复用字段事后按中文规则合并
    index_meta = _load_index_meta(existing)
    prev_scrape = _load_scrape_meta(existing)
    local_keep = _local_quality_fields(
        index_meta,
        entry_dir=existing,
        poster_name="poster.jpg",
        want=reuse,
    )

    # 刮削结果独立成文：以本次网络 meta 为底，再按中文规则合并索引
    write_meta = _apply_local_quality_to_meta(dict(meta), local_keep)
    # 目录定位字段可从索引带上；studio 仅 FC2 搬家需要，不当作制片方落盘
    for k in ("prefix", "maker", "region", "regionLabel"):
        if not str(write_meta.get(k) or "").strip() and str(
            index_meta.get(k) or ""
        ).strip():
            write_meta[k] = index_meta.get(k)

    fc2_author = None
    write_target = target
    if kind_id == "fc2":
        fc2_author = _fc2_author_from_meta(write_meta, target)
        if not fc2_author:
            # 未勾选制片时 write_meta 可能无 studio，仍允许从索引取作者只为搬家
            fc2_author = _fc2_author_from_meta(index_meta, target)
        if fc2_author:
            write_meta = {**write_meta, "studio": fc2_author}
            write_target = {**target, "maker": fc2_author}

    entry_dir = existing
    old_elsewhere: Path | None = None

    # FC2：仅从未分类挪到作者目录（仍基于已有条目，不是凭空建号）
    if (
        kind_id == "fc2"
        and fc2_author
        and _path_has_uncategorized(existing)
    ):
        desired_dir = scrape_naming.resolve_entry_dir(
            library,
            naming_cfg,
            code=code,
            meta=write_meta,
            target=write_target,
            category=label,
            kind=kind_id,
        )
        if desired_dir.resolve() != existing.resolve():
            entry_dir = desired_dir
            old_elsewhere = existing

    poster_name = "poster.jpg"

    need_meta = bool(
        want_set
        & {"titleZh", "publisher", "studio", "actors", "outline", "tags", "series"}
    )
    need_cover = "cover" in want_set
    if not need_meta and not need_cover:
        need_meta = True

    if not force and _entry_complete(
        existing,
        poster_name=poster_name,
        need_cover=need_cover,
        export_fields=want,
    ):
        # 已在未分类且本次刮到作者 → 仍要搬家
        if not (
            kind_id == "fc2"
            and fc2_author
            and _path_has_uncategorized(existing)
            and old_elsewhere is not None
        ):
            return "skipped"

    existing_poster = None
    for name in (poster_name, "poster.jpg"):
        legacy = existing / name
        if legacy.is_file():
            existing_poster = legacy.read_bytes()
            break
    if existing_poster is None and entry_dir != existing:
        p2 = entry_dir / poster_name
        if p2.is_file():
            existing_poster = p2.read_bytes()

    poster = write_meta.get("poster") or write_meta.get("coverUrl")
    try:
        directory_rel = str(entry_dir.resolve().relative_to(library.resolve())).replace(
            "\\", "/"
        )
    except Exception:
        ctx = scrape_naming.build_naming_context(
            code=code,
            meta=write_meta,
            target=write_target,
            category=label,
            naming=naming_cfg,
            kind=kind_id,
        )
        directory_rel = scrape_naming.render_directory_rel(
            naming_cfg, ctx, kind=kind_id
        )
    payload = {
        **{k: v for k, v in write_meta.items() if k not in ("fanart", "coverBase64")},
        "code": code,
        "prefix": write_target.get("prefix") or write_meta.get("prefix"),
        "maker": write_target.get("maker") or write_meta.get("maker"),
        "region": write_target.get("region") or rid or write_meta.get("region"),
        "regionLabel": label or write_meta.get("regionLabel"),
        "poster": poster or write_meta.get("poster"),
        "fanart": [],
        "exportFields": want,
        "directoryRel": directory_rel,
        "scrapedAt": write_meta.get("scrapedAt")
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    payload = _apply_local_quality_to_meta(payload, local_keep)
    # 未勾选字段一律不落盘（含旧 scrape 脏值 / 索引厂牌冒充的 studio）
    payload = _mask_meta_to_export_fields(
        payload,
        want,
        prev=None,
        keep_prev_for_unselected=False,
    )
    # 仅本地/索引题做语种拦截；网络源 titleZh 原样落盘
    zh_out = str(payload.get("titleZh") or "").strip()
    fs_chk = payload.get("fieldSources")
    zh_src = (
        str(fs_chk.get("titleZh") or "").strip().lower()
        if isinstance(fs_chk, dict)
        else ""
    )
    if zh_out and zh_src in {"", "index", "forum", "maker-fs", "seed", "local"}:
        if not is_likely_chinese(zh_out):
            payload.pop("titleZh", None)
            fs_out = payload.get("fieldSources")
            if isinstance(fs_out, dict):
                fs_out.pop("titleZh", None)
                if str(fs_out.get("title") or "") == INDEX_FIELD_SOURCE:
                    fs_out.pop("title", None)
            if str(payload.get("title") or "").strip() == zh_out:
                ot = str(payload.get("originalTitle") or "").strip()
                if ot:
                    payload["title"] = ot
    # FC2 搬家临时写过 studio：未勾选制片方时仍剔除
    if kind_id == "fc2" and "studio" not in want_set:
        payload.pop("studio", None)
        fs = payload.get("fieldSources")
        if isinstance(fs, dict):
            fs.pop("studio", None)
            fs.pop("makers", None)

    # 就地写 scrape.json / poster，绝不删改 meta.json（索引物化）
    entry_dir.mkdir(parents=True, exist_ok=True)
    if old_elsewhere is not None and entry_dir.resolve() != existing.resolve():
        # FC2 搬家：先把索引文件一并迁到新目录
        entry_dir.mkdir(parents=True, exist_ok=True)
        for name in (INDEX_META_FILE, "封面.url", poster_name, "poster.jpg"):
            src = existing / name
            if src.is_file():
                dest = entry_dir / name
                if not dest.exists():
                    try:
                        shutil.copy2(src, dest)
                    except Exception:
                        pass
    try:
        scrape_path = entry_dir / SCRAPE_META_FILE
        tmp_scrape = entry_dir / (SCRAPE_META_FILE + ".tmp")
        tmp_scrape.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp_scrape.replace(scrape_path)
        try:
            from . import library_materialize

            library_materialize.upsert_region_facet_entry(
                entry_dir,
                region=str(payload.get("region") or write_meta.get("region") or "")
                or None,
                studio=str(
                    payload.get("studio")
                    or payload.get("maker")
                    or write_meta.get("studio")
                    or write_meta.get("maker")
                    or ""
                )
                or None,
                prefix=str(
                    payload.get("prefix")
                    or write_meta.get("prefix")
                    or write_target.get("prefix")
                    or ""
                )
                or None,
                code=str(payload.get("code") or code or "") or None,
            )
        except Exception:
            log.debug("facet upsert after scrape write failed", exc_info=True)

        wrote_cover = False
        if need_cover:
            wrote_cover = _copy_cover(write_meta, entry_dir / poster_name)
            if not wrote_cover and existing_poster is not None:
                if not (entry_dir / poster_name).is_file():
                    (entry_dir / poster_name).write_bytes(existing_poster)

        _remember_entry_dir(code, entry_dir)
        if old_elsewhere is not None and old_elsewhere.exists():
            try:
                if old_elsewhere.resolve() != entry_dir.resolve():
                    shutil.rmtree(old_elsewhere, ignore_errors=True)
            except Exception:
                shutil.rmtree(old_elsewhere, ignore_errors=True)
        # FC2 作者目录进白名单：同步对齐索引时不删
        if kind_id == "fc2" and fc2_author and not _path_has_uncategorized(entry_dir):
            try:
                from . import library_materialize

                library_materialize.add_fc2_keep_path(library, entry_dir)
            except Exception:
                log.debug("fc2 keep path failed", exc_info=True)
    except Exception:
        raise

    if kind_id == "fc2" and fc2_author:
        try:
            pref = str(
                write_target.get("prefix")
                or payload.get("prefix")
                or "FC2PPV"
            ).strip() or "FC2PPV"
            maker_fs.set_prefix_board_name("fc2", pref, fc2_author)
        except Exception:
            log.debug("fc2 board_name sync failed", exc_info=True)

    ok_files = (entry_dir / SCRAPE_META_FILE).is_file() if need_meta else True
    return "done" if ok_files else "failed"

def run_export(
    *,
    region: str | None = None,
    regions: list[str] | None = None,
    maker: str | None = None,
    prefix: str | None = None,
    code: str | None = None,
    codes: list[str] | None = None,
    force: bool = False,
    mode: str | None = None,
    fields: list[str] | None = None,
    local_fields: list[str] | None = None,
    task_id: str | None = None,
    task_name: str | None = None,
    from_claim: bool = False,
) -> dict[str, Any]:
    if not from_claim:
        with _meta_lock:
            if _state.get("running"):
                raise RuntimeError("刮削导出正在进行中")
    _reconcile_stuck_export_state()
    if not _lock.acquire(blocking=False):
        _reset_export_mutex_if_stale()
        if not _lock.acquire(blocking=False):
            if from_claim:
                abort_claim("刮削导出正在进行中")
            raise RuntimeError("刮削导出正在进行中")

    _end_flags["message"] = ""
    _end_flags["clearOnStop"] = False
    _end_flags["hadError"] = False

    cfg = scrape_settings()
    origin = cfg["origin"]
    try:
        from .conn_settings_routes import ensure_scrape_network_synced

        ensure_scrape_network_synced(retries=3, delay_sec=0.8)
    except Exception:
        logging.getLogger("sns.export").exception("pre-export network sync failed")
    # 任务开始即重读磁盘配置（字段优先级 / 启用源）
    cfg = scrape_settings()
    profiles = cfg.get("kindProfiles") or cfg["regionProfiles"]
    export_fields = _normalize_fields(fields)
    local_export_fields = [
        f
        for f in scrape_profiles.normalize_local_fields(local_fields)
        if f in set(export_fields)
    ]
    force, mode_key = _coerce_force_mode(
        force=force, mode=mode, task_id=task_id
    )
    # 可变盒：暂停中改任务卡后，worker 热读可写回同一引用
    force_ref = [bool(force)]
    mode_ref = [str(mode_key)]

    def _refresh_job_opts_from_task() -> None:
        """从已存任务卡刷新字段/模式（下一番号立即生效）。"""
        row = _find_scrape_task(str(task_id or tid or ""))
        if not row:
            return
        opts = _task_export_opts(row)
        export_fields[:] = list(opts["fields"])
        allow = set(export_fields)
        local_export_fields[:] = [
            f for f in list(opts["localFields"]) if f in allow
        ]
        force_ref[0] = bool(opts["force"])
        mode_ref[0] = str(opts["mode"])
        with _meta_lock:
            _state["exportFields"] = list(export_fields)
            _state["localFields"] = list(local_export_fields)
            _state["force"] = force_ref[0]
            _state["mode"] = mode_ref[0]
            if opts["taskName"]:
                _state["taskName"] = opts["taskName"]
            _state["maker"] = opts["maker"]
            _state["prefix"] = opts["prefix"]
            if opts["code"]:
                _state["codeFilter"] = opts["code"]
            if opts["region"]:
                _state["region"] = opts["region"]

    region_label = ""
    if regions:
        region_label = ",".join(str(r) for r in regions if r)
    elif region:
        region_label = str(region)

    maker_s = (maker or "").strip()
    prefix_s = (prefix or "").strip().upper()
    code_list = _parse_export_code_filters(code, codes)
    code_s = "，".join(code_list) if code_list else ""
    scope_bits = [
        x
        for x in (
            region_label,
            maker_s,
            prefix_s,
            code_s
            if len(code_list) <= 3
            else (f"{len(code_list)} 个番号" if code_list else ""),
        )
        if x
    ]
    with _meta_lock:
        global _result_seen
        started = _state.get("startedAt") or _now_iso()
        tid = str(task_id or _state.get("taskId") or "").strip()
        tname = str(task_name or _state.get("taskName") or "").strip()
        _result_seen = set()
        _state.update(
            {
                "running": True,
                "startedAt": started,
                "finishedAt": "",
                "message": "building",
                "region": region_label,
                "maker": maker_s,
                "prefix": prefix_s,
                "codeFilter": code_s,
                "taskId": tid,
                "taskName": tname,
                "force": bool(force_ref[0]),
                "mode": mode_ref[0],
                "exportFields": export_fields,
                "localFields": local_export_fields,
                "done": 0,
                "failed": 0,
                "skipped": 0,
                "empty": 0,
                "active": 0,
                "doneCodes": [],
                "skippedCodes": [],
                "failedCodes": [],
                "emptyCodes": [],
                "activeCodes": [],
                "activeFastCodes": [],
                "activeSlowCodes": [],
                "pendingFast": 0,
                "pendingSlow": 0,
                "current": "",
                "events": list(_state.get("events") or []),
                "currentDetail": None,
            }
        )
        _clear_pending_detail_display()
    field_hint = ""
    if set(export_fields) != set(DEFAULT_EXPORT_FIELDS):
        field_hint = " · 字段 " + "/".join(export_fields)
    if local_export_fields:
        field_hint += " · 本地复用 " + "/".join(local_export_fields)
    _push_event(
        phase="job",
        text=(
            f"开始刮削任务"
            + (f" · {tname}" if tname else "")
            + f" · 模式 {'强制重刮' if force else '增量'}"
            + (f" · {'/'.join(scope_bits)}" if scope_bits else "")
            + field_hint
        ),
        level="info",
    )
    # 明示本次从设置重读到的源序（避免「以为没用上配置」）
    try:
        boot_kind = "japan_censored"
        if regions:
            boot_kind = scrape_profiles.detect_scrape_kind("", str(regions[0] or ""))
        elif region:
            boot_kind = scrape_profiles.detect_scrape_kind("", str(region or ""))
        boot_prof = scrape_profiles.resolve_kind_profile(
            boot_kind,
            profiles=profiles,
            global_library=cfg["libraryRoot"],
            global_write_tree=bool(cfg["writeTree"]),
            global_write_emby=bool(cfg["writeEmby"]),
        )
        boot_fp = scrape_profiles.filter_field_priority_for_export(
            boot_prof.get("fieldPriority") or {},
            export_fields,
        )
        _push_event(
            phase="job",
            text="已加载数据源配置 · " + _format_field_priority_hint(boot_fp),
            level="info",
        )
    except Exception:
        logging.getLogger("sns.export").exception("log field priority failed")

    try:
        if _wait_if_paused_or_cancel() == "cancel":
            with _meta_lock:
                _end_flags["message"] = "cancelled"
                _end_flags["clearOnStop"] = bool(_control.get("clearOnStop"))
            return export_status()

        _push_event(phase="job", text="收集目标…", level="info")
        targets = collect_targets(
            region=region,
            regions=regions,
            maker=maker,
            prefix=prefix,
            code=code,
            codes=codes,
            include_fill=True,
        )
        fill_n = sum(1 for t in targets if t.get("fromFill"))
        if fill_n:
            _push_event(
                phase="job",
                text=f"索引目标 {len(targets)} · 含补全号 {fill_n}",
                level="info",
            )
        try:
            disk_extra = collect_library_empty_folder_targets(
                region=region,
                regions=regions,
                maker=maker,
                prefix=prefix,
                code=code,
            )
            before_n = len(targets)
            targets = merge_scrape_targets(targets, disk_extra)
            added = len(targets) - before_n
            if disk_extra:
                _push_event(
                    phase="job",
                    text=(
                        f"片库空目录补入 {len(disk_extra)} 条"
                        + (f" · 净增 {added}" if added else " · 均已在索引目标中")
                    ),
                    level="info",
                )
        except Exception:
            log.exception("collect library empty folder targets failed")
        # 强制重刮指定番号：忽略断点里的已完成集合，否则空号/成功不会再进池
        resume = _load_resume_checkpoint()
        resume_tid = str((resume or {}).get("taskId") or "").strip()
        cur_tid = str(task_id or tid or "").strip()
        force_code_rerun = bool(force_ref[0]) and bool(code_list)
        if resume and resume_tid and resume_tid == cur_tid and force_code_rerun:
            _clear_resume_checkpoint()
            resume = None
        if resume and resume_tid and resume_tid == cur_tid:
            finished = set()
            # 失败不进 finished：增量/续跑都会重新入队再刮
            for bucket in ("doneCodes", "emptyCodes", "skippedCodes"):
                for c in list((resume or {}).get(bucket) or []):
                    s = str(c or "").strip()
                    if s:
                        finished.add(s)
            failed_resume = {
                str(c or "").strip()
                for c in list((resume or {}).get("failedCodes") or [])
                if str(c or "").strip()
            }
            pause_resume = bool(
                (resume or {}).get("paused")
                or str((resume or {}).get("reason") or "") == "paused"
                or str((resume or {}).get("message") or "") == "paused"
            )
            remaining_saved = [
                t
                for t in list((resume or {}).get("remainingTargets") or [])
                if isinstance(t, dict) and str(t.get("code") or "").strip()
            ]
            all_saved = [
                t
                for t in list((resume or {}).get("allTargets") or [])
                if isinstance(t, dict)
            ]
            retry_failed = [
                t
                for t in (all_saved or targets)
                if str(t.get("code") or "").strip() in failed_resume
            ]
            if pause_resume and remaining_saved:
                # 未跑完的 + 本轮已失败的重试
                seen_q: set[str] = set()
                merged: list[dict[str, Any]] = []
                for t in [*retry_failed, *remaining_saved]:
                    c = str(t.get("code") or "").strip()
                    if not c or c in seen_q:
                        continue
                    seen_q.add(c)
                    merged.append(t)
                targets = merged
            elif finished or failed_resume:
                targets = [
                    t
                    for t in targets
                    if str(t.get("code") or "").strip() not in finished
                ]
            with _meta_lock:
                _state["done"] = int((resume or {}).get("done") or 0)
                _state["empty"] = int((resume or {}).get("empty") or 0)
                _state["skipped"] = int((resume or {}).get("skipped") or 0)
                # 失败项将重刮，本轮计数从 0 再累计
                _state["failed"] = 0
                _state["doneCodes"] = list((resume or {}).get("doneCodes") or [])[
                    -_MAX_RESULT_CODES:
                ]
                _state["emptyCodes"] = list(
                    (resume or {}).get("emptyCodes") or []
                )[-_MAX_RESULT_CODES:]
                _state["skippedCodes"] = list(
                    (resume or {}).get("skippedCodes") or []
                )[-_MAX_RESULT_CODES:]
                _state["failedCodes"] = []
                total_saved = int((resume or {}).get("total") or 0)
                _state["total"] = total_saved or (
                    len(targets)
                    + int(_state["done"])
                    + int(_state["empty"])
                    + int(_state["skipped"])
                    + int(_state["failed"])
                )
                _state["allTargets"] = all_saved or list(targets)
                _result_seen = set(finished)
            _push_event(
                phase="job",
                text=(
                    f"{'暂停续跑' if pause_resume else '断点续跑'} · 已完成 {int((resume or {}).get('done') or 0)}"
                    + (f" · 失败重试 {len(retry_failed)}" if retry_failed else "")
                    + f" · 剩余 {len(targets)}"
                ),
                level="info",
            )
        else:
            with _meta_lock:
                _state["total"] = len(targets)
                _state["allTargets"] = list(targets)

        # 增量：按本地真实状态预分类（成功/空号/失败），只把未完成送进工作池
        if not bool(force_ref[0]) and targets:
            try:
                lib_root = _resolve_library_root()
                before_pending = len(targets)
                _push_event(
                    phase="job",
                    text=f"增量预分类扫描 {before_pending} …",
                    level="info",
                )
                targets = _bulk_skip_complete_targets(
                    targets,
                    library=lib_root,
                    export_fields=export_fields,
                )
                if len(targets) < before_pending:
                    with _meta_lock:
                        # total 保持 allTargets 全量；processed = done+empty+fail
                        all_n = len(list(_state.get("allTargets") or []))
                        if all_n > 0:
                            _state["total"] = all_n
            except Exception:
                log.exception("bulk classify complete targets failed")

        if _control.get("cancel"):
            _push_event(phase="job", text="任务已取消", level="warn")
            with _meta_lock:
                _end_flags["message"] = "cancelled"
                _end_flags["clearOnStop"] = bool(_control.get("clearOnStop"))
            return export_status()
        if not targets:
            with _meta_lock:
                done_n = int(_state.get("done") or 0)
                empty_n = int(_state.get("empty") or 0)
                skip_n = int(_state.get("skipped") or 0)
                fail_n = int(_state.get("failed") or 0)
            if done_n + empty_n + skip_n + fail_n > 0:
                _push_event(
                    phase="job",
                    text=(
                        f"增量无需新刮 · 成功 {done_n} · 空号 {empty_n}"
                        + (f" · 跳过 {skip_n}" if skip_n else "")
                        + f" · 数据不全 {fail_n}"
                    ),
                    level="ok",
                )
                with _meta_lock:
                    _end_flags["message"] = "ok"
                    _end_flags["clearOnStop"] = bool(_control.get("clearOnStop"))
                _clear_resume_checkpoint()
                return export_status()
            _push_event(
                phase="job",
                text="无待刮削番号（请先构建 maker-fs 索引）",
                level="warn",
            )
            with _meta_lock:
                _end_flags["message"] = "无待刮削番号（请先构建 maker-fs 索引）"
                _end_flags["clearOnStop"] = bool(_control.get("clearOnStop"))
            _clear_resume_checkpoint()
            return export_status()

        _push_event(
            phase="job",
            text=f"待刮削 {len(targets)} 个番号",
            level="info",
        )
        _write_resume_checkpoint(all_targets=list(_state.get("allTargets") or targets), reason="progress")

        cancelled = False
        abandoned_remaining: list[dict[str, Any]] = []
        # 快/慢双通道各用独立并发；慢通道任务可并行，过盾请求在刮削服务单飞排队。
        fast_slots, slow_slots = _resolve_channel_concurrency(cfg)
        pool_cap = fast_slots + slow_slots
        with _meta_lock:
            _state["fastSlots"] = fast_slots
            _state["slowSlots"] = slow_slots
            _state["pendingFast"] = 0
            _state["pendingSlow"] = 0
            _state["activeFastCodes"] = []
            _state["activeSlowCodes"] = []
        _push_event(
            phase="job",
            text=(
                f"双通道并发 快源≤{fast_slots} · 慢源≤{slow_slots}"
                f"（刮削服务分队列；过盾请求排队单飞）"
            ),
            level="info",
        )

        def _run_one(t: dict[str, Any], channel: str = "fast") -> tuple[str, str]:
            c = str(t.get("code") or "")
            abort = _work_abort_kind()
            if abort == "cancel":
                return "cancel", c
            if abort == "paused":
                return "paused", c
            return _run_one_inner(t, channel)

        def _run_one_inner(t: dict[str, Any], channel: str = "fast") -> tuple[str, str]:
            c = str(t.get("code") or "")
            abort = _work_abort_kind()
            if abort == "cancel":
                return "cancel", c
            if abort == "paused":
                return "paused", c
            rid = str(t.get("region") or "")
            ch = "slow" if str(channel or "").strip().lower() == "slow" else "fast"
            with _meta_lock:
                # 暂停清理后可能已把 active 清零；仍登记本路，便于继续前展示
                if _work_abort_kind() == "paused":
                    return "paused", c
                _state["active"] = int(_state.get("active") or 0) + 1
                _append_result_code("activeCodes", c)
                _append_result_code(
                    "activeSlowCodes" if ch == "slow" else "activeFastCodes", c
                )
                _state["current"] = c
                if not _state.get("paused"):
                    _state["message"] = "scraping"
            try:
                # 每个番号：热读任务卡（暂停中改字段/强制，下一片立即生效）+ 重读源优先级
                _refresh_job_opts_from_task()
                live = scrape_settings()
                live_profiles = live.get("kindProfiles") or live["regionProfiles"]
                kind = scrape_profiles.detect_scrape_kind(c, rid)
                prof = scrape_profiles.resolve_kind_profile(
                    kind,
                    profiles=live_profiles,
                    global_library=live["libraryRoot"],
                    global_write_tree=bool(live["writeTree"]),
                    global_write_emby=bool(live["writeEmby"]),
                )
                enabled = set(live.get("enabledSourceIds") or [])
                fp_raw = prof.get("fieldPriority") or {}
                fp_for_task = scrape_profiles.filter_field_priority_for_export(
                    fp_raw, export_fields
                )
                field_priority = {
                    key: scrape_profiles.filter_sources_by_enabled(
                        list(fp_for_task.get(key) or []), enabled
                    )
                    for key in scrape_profiles.FIELD_PRIORITY_KEYS
                }
                meta_src, cover_src = scrape_profiles.derive_sources_from_fields(
                    field_priority
                )
                meta_src = scrape_profiles.filter_sources_by_enabled(
                    meta_src, enabled
                )
                cover_src = scrape_profiles.filter_sources_by_enabled(
                    cover_src, enabled
                )
                _push_event(
                    phase="scrape",
                    code=c,
                    text="源序 " + _format_field_priority_hint(field_priority),
                    level="info",
                )
                library = _resolve_library(
                    prof.get("libraryRoot") or live.get("libraryRoot")
                )
                library.mkdir(parents=True, exist_ok=True)

                label = _region_label(rid)
                naming_cfg = scrape_naming.fixed_naming()
                kind_id = scrape_naming.resolve_kind(kind=kind, region=rid, code=c)
                found_dir = _find_library_entry_dir(c)
                if found_dir is None or not found_dir.is_dir():
                    _reset_title_events()
                    _push_event(
                        phase="parse",
                        code=c,
                        text="本地库无此番号文件夹，请先同步片库",
                        level="error",
                    )
                    return "failed", c

                entry_dir = found_dir
                try:
                    entry_rel = str(entry_dir.resolve().relative_to(library)).replace(
                        "\\", "/"
                    )
                except Exception:
                    entry_rel = str(entry_dir)
                poster_name = "poster.jpg"
                need_cover = "cover" in set(export_fields)
                # 已由 _refresh_job_opts_from_task 热更新；勿对闭包 force 赋值
                item_force = bool(force_ref[0])
                already = (not item_force) and _entry_complete(
                    entry_dir,
                    poster_name=poster_name,
                    need_cover=need_cover,
                    export_fields=export_fields,
                )

                # FC2 未分类：种子未刮、或 meta 已有作者却仍在未分类 → 进流程（搬家/刮削）
                if (
                    already
                    and kind_id == "fc2"
                    and _path_has_uncategorized(found_dir)
                ):
                    try:
                        raw_meta = _load_scrape_meta(found_dir) or _load_index_meta(
                            found_dir
                        )
                    except Exception:
                        raw_meta = {}
                    if _fc2_author_from_meta(raw_meta, t):
                        already = False
                    elif (
                        str(raw_meta.get("source") or "") in {"", "maker-fs"}
                        and not raw_meta.get("scrapedAt")
                    ):
                        already = False

                # 详情与日志都只展示当前片子，覆盖上一片（不预填色花堂封面）
                if item_force:
                    # 强制重刮：清旧日志，后面整段重写
                    _clear_events_for_code(c)
                _reset_title_events()
                _set_current_detail(
                    _detail_payload(
                        code=c,
                        kind=kind,
                        region=rid,
                        region_label=label,
                        path=entry_rel,
                        phase="parse",
                        meta={},
                    )
                )
                # 增量已完成：只刷实时条，不落库重写；强制/新刮才写库
                log_archive = bool(item_force or not already)
                _push_event(
                    phase="parse",
                    code=c,
                    text=f"解析番号 · 识别为 {c} · 方案 {kind}",
                    level="ok",
                    archive=log_archive,
                )
                _push_event(
                    phase="parse",
                    code=c,
                    text=f"目标路径 {entry_rel}",
                    level="info",
                    archive=log_archive,
                )
                if item_force and found_dir is not None and _entry_complete(
                    found_dir,
                    poster_name=poster_name,
                    need_cover=need_cover,
                    export_fields=export_fields,
                ):
                    _push_event(
                        phase="parse",
                        code=c,
                        text="强制重刮 · 忽略已有落盘",
                        level="info",
                    )

                if already:
                    existing = _load_scrape_meta(entry_dir) or _load_index_meta(
                        entry_dir
                    )
                    before_actors = [
                        str(a).strip()
                        for a in (
                            existing.get("actors")
                            if isinstance(existing.get("actors"), list)
                            else []
                        )
                        if str(a).strip()
                    ]
                    # 增量跳过也要按任务本地可复用补空（女优等），并写回 scrape.json
                    filled = _fill_meta_from_index(
                        existing,
                        entry_dir,
                        local_fields=local_export_fields,
                    )
                    after_actors = [
                        str(a).strip()
                        for a in (
                            filled.get("actors")
                            if isinstance(filled.get("actors"), list)
                            else []
                        )
                        if str(a).strip()
                    ]
                    if filled != existing and not _meta_is_not_found(existing):
                        try:
                            _patch_scrape_meta_file(entry_dir, filled)
                            note = "增量跳过 · 已用索引补空本地可复用字段"
                            if after_actors and not before_actors:
                                note += f" · 女优 {', '.join(after_actors)}"
                            _push_event(
                                phase="parse",
                                code=c,
                                text=note,
                                level="ok",
                                archive=False,
                            )
                        except Exception:
                            log.debug(
                                "patch scrape meta from index failed %s",
                                c,
                                exc_info=True,
                            )
                    existing = filled
                    # not_found = 空号；已刮成功立刻记成功
                    is_nf = _is_confirmed_empty_meta(existing)
                    result = "empty" if is_nf else "done"
                    poster_local = ""
                    for cand in (poster_name, "poster.jpg"):
                        if (entry_dir / cand).is_file():
                            poster_local = f"{entry_rel}/{cand}"
                            break
                    _set_current_detail(
                        _detail_payload(
                            code=c,
                            kind=kind,
                            region=rid,
                            region_label=label,
                            path=entry_rel,
                            phase="empty" if is_nf else "done",
                            meta=existing,
                            source_runs=(
                                existing.get("sourceRuns")
                                if isinstance(existing.get("sourceRuns"), list)
                                else None
                            ),
                            field_sources=(
                                existing.get("fieldSources")
                                if isinstance(existing.get("fieldSources"), dict)
                                else None
                            ),
                            poster_local=poster_local,
                            fallback_cover=str(
                                existing.get("poster") or existing.get("coverUrl") or ""
                            ),
                            export_fields=(
                                existing.get("exportFields")
                                if isinstance(existing.get("exportFields"), list)
                                else export_fields
                            ),
                        )
                    )
                    if is_nf:
                        _push_event(
                            phase="scrape",
                            code=c,
                            text="已确认无详情（not_found）· 计入空号",
                            level="warn",
                            archive=False,
                        )
                    else:
                        _push_event(
                            phase="write",
                            code=c,
                            text="已存在 meta/封面，记为成功",
                            level="ok",
                            archive=False,
                        )
                else:
                    # ① 索引 meta.json 与刮削 scrape.json 分文件读取（不合并落盘）
                    index_meta = _load_index_meta(entry_dir)
                    prev_scrape = _load_scrape_meta(entry_dir)
                    _push_event(
                        phase="parse",
                        code=c,
                        text=(
                            "读取本地索引物化 meta.json"
                            + (
                                f" · {len(index_meta)} 键"
                                if index_meta
                                else " · 无索引"
                            )
                            + (
                                f" · 既有网络刮削 scrape.json {len(prev_scrape)} 键（不复用）"
                                if prev_scrape
                                else ""
                            )
                        ),
                        level="info",
                    )
                    template, local_q, local_ok, missing = (
                        _build_work_template_from_local(
                            index_meta,
                            code=c,
                            kind=kind,
                            entry_dir=entry_dir,
                            poster_name=poster_name,
                            want=export_fields,
                            local_fields=local_export_fields,
                            scrape_meta=None,
                        )
                    )
                    _push_event(
                        phase="parse",
                        code=c,
                        text=(
                            "① 网络刮削 → ② 本地索引按中文规则合并"
                            + (
                                f" · 本地候选 {', '.join(sorted(local_ok))}"
                                if local_ok
                                else " · 无本地候选"
                            )
                            + (
                                f" · 网络字段 {', '.join(missing)}"
                                if missing
                                else ""
                            )
                        ),
                        level="ok" if local_ok else "info",
                    )
                    # 先把模板推到详情页，再发起网络
                    _set_current_detail(
                        _detail_payload(
                            code=c,
                            kind=kind,
                            region=rid,
                            region_label=label,
                            path=entry_rel,
                            phase="scrape",
                            meta=template,
                            field_sources=(
                                template.get("fieldSources")
                                if isinstance(template.get("fieldSources"), dict)
                                else None
                            ),
                            export_fields=export_fields,
                        )
                    )
                    # 网络优先：不因本地候选裁掉网络源
                    fp_use = scrape_profiles.normalize_field_priority(
                        field_priority
                    )
                    meta_src_use, cover_src_use = (
                        scrape_profiles.derive_sources_from_fields(fp_use)
                    )
                    # 无封面补全号：不砍超时，让快源跑完以便立即判空号
                    is_fill_empty = (
                        bool(t.get("fromFill")) or bool(t.get("fromLibraryDir"))
                    ) and not str(t.get("coverUrl") or "").strip()
                    if not is_fill_empty and not str(t.get("coverUrl") or "").strip():
                        urls = t.get("coverUrls") or []
                        if not any(str(u).strip() for u in urls):
                            is_fill_empty = True
                    scrape_deadline_ms: int | None = None
                    need_net = bool(meta_src_use or cover_src_use)
                    _push_event(
                        phase="parse",
                        code=c,
                        text=(
                            "准备网络请求"
                            + (" · 补全空洞" if is_fill_empty else "")
                            if need_net
                            else "无网络源 · 仅用本地候选"
                        ),
                        level="info",
                    )
                    sites = meta_src_use or cover_src_use
                    if need_net:
                        _push_event(
                            phase="scrape",
                            code=c,
                            text=(
                                f"开始从以下[{len(sites)}]个站点分波抓取"
                                + (
                                    f": {', '.join(sites[:12])}"
                                    if sites
                                    else ""
                                )
                            ),
                            level="info",
                        )
                    meta_opt = scrape_metadata_optimize.normalize_metadata_optimize(
                        cfg.get("metadataOptimize")
                        if isinstance(cfg.get("metadataOptimize"), dict)
                        else {}
                    )
                    if need_net:
                        meta = _call_scrape(
                            origin,
                            c,
                            None,
                            force=item_force,
                            kind=kind,
                            region=rid,
                            meta_sources=meta_src_use,
                            cover_sources=cover_src_use,
                            field_priority=fp_use,
                            prefer_title=None,
                            prefer_actors=None,
                            prefer_local=None,
                            cover_download_strategy=str(
                                cfg.get("coverDownloadStrategy") or "priority"
                            ),
                            poster_crop=cfg.get("posterCrop")
                            if isinstance(cfg.get("posterCrop"), dict)
                            else None,
                            channel=ch,
                            deadline_ms=scrape_deadline_ms,
                        )
                        scrape_abort = str(meta.get("message") or "")
                        if scrape_abort == "paused":
                            return "paused", c
                        if scrape_abort == "cancelled":
                            return "cancel", c
                        # 快通道：不过盾不够 → 转入慢源补过盾（不计成功/失败）
                        # 空号：快源全员确认无详情 → 立即判空号，不进慢源
                        if scrape_abort == "needs_flare" and ch == "fast":
                            runs_nf = (
                                meta.get("sourceRuns")
                                if isinstance(meta, dict)
                                else None
                            )
                            meta_runs = [
                                r
                                for r in _iter_network_source_runs(runs_nf)
                                if str(r.get("mode") or "") == "meta"
                            ]
                            fast_meta_nf = bool(meta_runs) and all(
                                (not bool(r.get("ok")))
                                and _is_no_detail_error(
                                    str(r.get("error") or r.get("message") or "")
                                )
                                for r in meta_runs
                            )
                            if fast_meta_nf:
                                if isinstance(meta, dict):
                                    meta = {
                                        **meta,
                                        "message": "not_found",
                                        "ok": False,
                                    }
                            else:
                                _push_event(
                                    phase="scrape",
                                    code=c,
                                    text="快源不够 · 转入慢源补过盾",
                                    level="info",
                                )
                                return "defer_slow", c
                    else:
                        meta = {
                            **template,
                            "ok": True,
                            "code": c,
                            "source": str(template.get("source") or "index"),
                            "sourceRuns": [
                                {
                                    "id": "index",
                                    "ok": True,
                                    "ms": 0,
                                    "mode": "meta",
                                    "detail": "index-only",
                                }
                            ],
                            "message": "index",
                        }
                    # 网络结果分类（在合并本地之前）：
                    # 空号 = 快源全员确认无详情（立即判定）；失败 = 字段不齐 / 超时未确认
                    net_raw = dict(meta or {})
                    net_outcome = _classify_network_scrape(
                        net_raw,
                        code=c,
                        need_net=need_net,
                        expected_sources=None,
                    )
                    # 网络结果为底；再按中文规则合并本地索引
                    net = dict(meta or {})
                    net_fs = (
                        net.get("fieldSources")
                        if isinstance(net.get("fieldSources"), dict)
                        else {}
                    )
                    meta = {**net}
                    meta["fieldSources"] = {**net_fs}
                    meta = _apply_local_quality_to_meta(meta, local_q)
                    meta = scrape_metadata_optimize.apply_metadata_optimize(
                        {**meta, "scrapeKind": kind},
                        {**meta_opt, "useForumZhTitle": False},
                        forum_title=None,
                        forum_actors=None,
                    )
                    meta = _apply_local_quality_to_meta(meta, local_q)
                    # 兜底：再读一遍索引，避免 local_q 构建时遗漏女优等
                    meta = _fill_meta_from_index(
                        meta,
                        entry_dir,
                        local_fields=local_export_fields,
                    )
                    # 未勾选字段（如制片）不进本次结果，避免脏数据/顺带字段
                    meta = _mask_meta_to_export_fields(
                        meta,
                        export_fields,
                        prev=None,
                        keep_prev_for_unselected=False,
                    )
                    scrape_msg = str(net_raw.get("message") or meta.get("message") or "")
                    runs = (
                        net_raw.get("sourceRuns")
                        if isinstance(net_raw.get("sourceRuns"), list)
                        else (
                            meta.get("sourceRuns")
                            if isinstance(meta.get("sourceRuns"), list)
                            else []
                        )
                    )
                    field_sources = (
                        meta.get("fieldSources")
                        if isinstance(meta.get("fieldSources"), dict)
                        else {}
                    )
                    if net_outcome == "hard_fail":
                        has_partial = _has_usable_scrape_payload(meta, c)
                        # 无封面空洞超时且无任何字段 → 按空号（无数据），非字段不齐失败
                        if (
                            (not has_partial)
                            and is_fill_empty
                            and scrape_msg
                            in {
                                "scrape_timeout",
                                "scrape_deadline",
                                "no_meta",
                                "not_found",
                                "notfound",
                            }
                        ):
                            _push_event(
                                phase="scrape",
                                code=c,
                                text="记为空号 · 无数据（快源未识别到详情）",
                                level="warn",
                            )
                            _set_current_detail(
                                _detail_payload(
                                    code=c,
                                    kind=kind,
                                    region=rid,
                                    region_label=label,
                                    path=entry_rel,
                                    phase="empty",
                                    meta=meta,
                                    source_runs=runs,
                                    field_sources=field_sources,
                                )
                            )
                            try:
                                _write_not_found_marker(
                                    entry_dir,
                                    code=c,
                                    export_fields=export_fields,
                                    meta={
                                        **(meta if isinstance(meta, dict) else {}),
                                        "ok": False,
                                        "message": "not_found",
                                    },
                                    runs=runs,
                                )
                            except Exception:
                                log.debug(
                                    "write not_found marker failed %s",
                                    c,
                                    exc_info=True,
                                )
                            result = "empty"
                            return "empty", c
                        fail_txt = scrape_msg or "刮削失败"
                        if scrape_msg in {"scrape_timeout", "scrape_deadline"}:
                            fail_txt = "刮削超时（源站过慢或无响应）"
                        elif scrape_msg in {"no_meta", "not_found", "notfound"}:
                            fail_txt = "未确认无数据 · 记为失败（可重试）"
                        if has_partial:
                            fail_txt = "字段数据不齐全 · 记为失败"
                        _push_event(
                            phase="scrape",
                            code=c,
                            text=fail_txt,
                            level="error",
                        )
                        _set_current_detail(
                            _detail_payload(
                                code=c,
                                kind=kind,
                                region=rid,
                                region_label=label,
                                path=entry_rel,
                                phase="failed",
                                meta=meta if has_partial else {},
                                source_runs=runs if has_partial else None,
                                field_sources=field_sources if has_partial else None,
                            )
                        )
                        result = "failed"
                        return "failed", c
                    for run in runs:
                        if not isinstance(run, dict):
                            continue
                        sid = str(run.get("id") or "")
                        ok = bool(run.get("ok"))
                        ms = int(run.get("ms") or 0)
                        err = str(run.get("error") or "").strip()
                        detail = str(run.get("detail") or "").strip()
                        if detail == "cid-retry":
                            cid = str(meta.get("productId") or "").strip()
                            if ok:
                                _push_event(
                                    phase="scrape",
                                    code=c,
                                    source=sid,
                                    ms=ms,
                                    text=(
                                        (
                                            f"其它刮削源返回了 DMM CID"
                                            f" ({cid})，尝试用 CID 再次查询"
                                            if cid
                                            else "尝试用 CID 再次查询"
                                        )
                                        + f" · 成功抓取到数据, 用时 {ms / 1000:.3f}s <{sid}>"
                                    ),
                                    level="ok",
                                )
                            else:
                                _push_event(
                                    phase="scrape",
                                    code=c,
                                    source=sid,
                                    ms=ms,
                                    text=(
                                        "CID 再次查询未抓取到更优数据"
                                        + (f"：{err}" if err else "")
                                    ),
                                    level="warn",
                                )
                            continue
                        if ok:
                            _push_event(
                                phase="scrape",
                                code=c,
                                source=sid,
                                ms=ms,
                                text=f"成功抓取到数据, 用时 {ms / 1000:.3f}s <{sid}>",
                                level="ok",
                            )
                        else:
                            _push_event(
                                phase="scrape",
                                code=c,
                                source=sid,
                                ms=ms,
                                text=(
                                    f"未抓取到数据 <{sid}>"
                                    + (f"：{err}" if err else "")
                                ),
                                level="warn",
                            )
                    # 空号 = 全部数据源都没有数据；失败 = 有部分字段但不齐全
                    if net_outcome == "not_found":
                        has_partial = _has_usable_scrape_payload(meta, c)
                        # 本通道 runs 全员无详情即可；快→慢已保证慢源也会跑
                        confirmed_empty = (
                            not has_partial
                            and _all_network_sources_no_detail(runs)
                        )
                        if has_partial or not confirmed_empty:
                            _push_event(
                                phase="scrape",
                                code=c,
                                text=(
                                    "字段数据不齐全 · 记为失败"
                                    if has_partial
                                    else "未确认全源无数据 · 记为失败（可重试）"
                                ),
                                level="error",
                            )
                            _set_current_detail(
                                _detail_payload(
                                    code=c,
                                    kind=kind,
                                    region=rid,
                                    region_label=label,
                                    path=entry_rel,
                                    phase="failed",
                                    meta=meta,
                                    source_runs=runs,
                                    field_sources=field_sources,
                                )
                            )
                            result = "failed"
                            return "failed", c
                        _push_event(
                            phase="scrape",
                            code=c,
                            text="记为空号 · 快源均无详情",
                            level="warn",
                        )
                        _set_current_detail(
                            _detail_payload(
                                code=c,
                                kind=kind,
                                region=rid,
                                region_label=label,
                                path=entry_rel,
                                phase="empty",
                                meta=meta,
                                source_runs=runs,
                                field_sources=field_sources,
                            )
                        )
                        try:
                            _write_not_found_marker(
                                entry_dir,
                                code=c,
                                export_fields=export_fields,
                                meta=meta,
                                runs=runs,
                            )
                        except Exception:
                            log.debug(
                                "write not_found marker failed %s",
                                c,
                                exc_info=True,
                            )
                        result = "empty"
                        return "empty", c
                    _push_event(
                        phase="scrape",
                        code=c,
                        text="元数据获取成功",
                        level="ok",
                    )

                    _set_current_detail(
                        _detail_payload(
                            code=c,
                            kind=kind,
                            region=rid,
                            region_label=label,
                            path=entry_rel,
                            phase="write",
                            meta=meta,
                            source_runs=runs,
                            field_sources=field_sources,
                            fallback_cover=str(meta.get("poster") or ""),
                        )
                    )

                    _push_event(
                        phase="write",
                        code=c,
                        text=f"创建目录 {entry_rel}",
                        level="info",
                    )
                    if need_cover:
                        _push_event(
                            phase="cover",
                            code=c,
                            text=f"下载封面 {poster_name}",
                            level="info",
                        )
                    _push_event(
                        phase="write",
                        code=c,
                        text="写入 scrape.json",
                        level="info",
                    )
                    result = _write_entry(
                        t,
                        meta,
                        library=library,
                        force=item_force,
                        fields=export_fields,
                        local_fields=local_export_fields,
                        naming=naming_cfg,
                    )
                    # 写入后以库内真实目录为准展示
                    found_after = _find_library_entry_dir(c)
                    if found_after is not None:
                        entry_dir = found_after
                        try:
                            entry_rel = str(
                                found_after.resolve().relative_to(library)
                            ).replace("\\", "/")
                        except Exception:
                            entry_rel = str(found_after)
                    poster_name = "poster.jpg"
                    poster_local = ""
                    for cand in (poster_name, "poster.jpg"):
                        if (entry_dir / cand).is_file():
                            poster_local = f"{entry_rel}/{cand}"
                            break
                    # 有数据但任务勾选强制字段不齐 → 失败（系列白名单不计入）
                    if result == "done":
                        miss = _meta_missing_required_fields(
                            meta if isinstance(meta, dict) else {},
                            entry_dir=entry_dir,
                            poster_name=poster_name,
                            need_cover=need_cover,
                            export_fields=export_fields,
                        )
                        if not miss and not _entry_complete(
                            entry_dir,
                            poster_name=poster_name,
                            need_cover=need_cover,
                            export_fields=export_fields,
                        ):
                            # 兜底：entry_complete 未过但 miss 为空（例如未写入 exportFields）
                            miss = ["titleZh"]
                        if miss:
                            labels = _field_labels_zh()
                            miss_zh = "、".join(
                                labels.get(x, x) for x in miss
                            )
                            result = "failed"
                            _push_event(
                                phase="write",
                                code=c,
                                text=f"字段数据不齐全（缺 {miss_zh}）· 记为失败",
                                level="error",
                            )
                            _set_current_detail(
                                _detail_payload(
                                    code=c,
                                    kind=kind,
                                    region=rid,
                                    region_label=label,
                                    path=entry_rel,
                                    phase="failed",
                                    meta=meta,
                                    source_runs=runs,
                                    field_sources=field_sources,
                                    poster_local=poster_local,
                                    fallback_cover=str(meta.get("poster") or ""),
                                )
                            )
                            return "failed", c
                    _set_current_detail(
                        _detail_payload(
                            code=c,
                            kind=kind,
                            region=rid,
                            region_label=label,
                            path=entry_rel,
                            phase="done" if result == "done" else result,
                            meta=meta,
                            source_runs=runs,
                            field_sources=field_sources,
                            poster_local=poster_local,
                            fallback_cover=str(meta.get("poster") or ""),
                        )
                    )
                    if result == "done":
                        _push_event(
                            phase="write",
                            code=c,
                            text="写入完成",
                            level="ok",
                        )
                    elif result == "skipped":
                        # 兼容旧返回值；对外记成功
                        result = "done"
                        _push_event(
                            phase="write",
                            code=c,
                            text="已存在，记为成功",
                            level="ok",
                        )
                    else:
                        _push_event(
                            phase="write",
                            code=c,
                            text="写入失败",
                            level="error",
                        )
            except Exception as e:
                abort = _work_abort_kind()
                if abort == "paused":
                    result = "paused"
                elif abort == "cancel":
                    result = "cancel"
                else:
                    log.warning("scrape export %s: %s", c, e)
                    result = "failed"
                    _push_event(
                        phase="write",
                        code=c,
                        text=f"失败：{e}",
                        level="error",
                    )
                    with _meta_lock:
                        cur = _state.get("currentDetail")
                        if (
                            isinstance(cur, dict)
                            and _std_code(str(cur.get("code") or ""))
                            == _std_code(c)
                            and not _detail_display_ready(cur)
                        ):
                            failed_detail = dict(cur)
                            failed_detail["phase"] = "failed"
                        else:
                            failed_detail = None
                    if failed_detail is not None:
                        _set_current_detail(failed_detail)
            finally:
                with _meta_lock:
                    _state["active"] = max(0, int(_state.get("active") or 0) - 1)
                    _remove_active_code(c)
            return result, c
        pool = _DaemonThreadPoolExecutor(max_workers=pool_cap)
        try:
            # 双通道互不影响：
            # - 快源：最多 workers 路真正并行
            # - 慢源：最多 workers 路任务在跑，过盾在 FS 侧排队单飞
            fast_q, slow_q = _partition_targets_fast_slow(
                targets,
                export_fields=export_fields,
                local_fields=local_export_fields,
                profiles=profiles,
                cfg=cfg,
            )
            _push_event(
                phase="job",
                text=(
                    f"调度：快源 {len(fast_q)}（≤{fast_slots} 并行，不够再转慢）· "
                    f"慢源 {len(slow_q)}（≤{slow_slots}，纯过盾）"
                ),
                level="info",
            )
            pending_fast = deque(fast_q)
            pending_slow = deque(slow_q)
            inflight: dict[Any, tuple[str, dict[str, Any]]] = {}
            slow_inflight = 0

            def _sync_channel_queue() -> None:
                with _meta_lock:
                    _state["pendingFast"] = len(pending_fast)
                    _state["pendingSlow"] = len(pending_slow)
                    _state["fastSlots"] = fast_slots
                    _state["slowSlots"] = slow_slots
                    _rebuild_active_from_inflight(inflight)

            def _fill() -> None:
                nonlocal slow_inflight
                if (
                    _control.get("cancel")
                    or _state.get("paused")
                    or _control.get("pause_abort")
                ):
                    _sync_channel_queue()
                    return
                while True:
                    fast_n = sum(1 for k, _ in inflight.values() if k == "fast")
                    if pending_fast and fast_n < fast_slots:
                        t = pending_fast.popleft()
                        fut = pool.submit(_run_one, t, "fast")
                        inflight[fut] = ("fast", t)
                        continue
                    if pending_slow and slow_inflight < slow_slots:
                        t = pending_slow.popleft()
                        fut = pool.submit(_run_one, t, "slow")
                        inflight[fut] = ("slow", t)
                        slow_inflight += 1
                        continue
                    break
                _sync_channel_queue()

            def _requeue_paused(kind: str, t: dict[str, Any]) -> None:
                nonlocal slow_inflight
                if kind == "slow":
                    pending_slow.appendleft(t)
                    slow_inflight = max(0, slow_inflight - 1)
                else:
                    pending_fast.appendleft(t)

            _fill()
            while inflight or pending_fast or pending_slow:
                if _control.get("cancel"):
                    cancelled = True
                    with _meta_lock:
                        active_n = int(_state.get("active") or 0)
                    if active_n <= 0 and _last_progress_mono > 0:
                        idle = time.monotonic() - _last_progress_mono
                        if idle > 8.0:
                            log.warning(
                                "scrape export: cancel drain abort idle=%.0fs inflight=%s",
                                idle,
                                len(inflight),
                            )
                            break
                    pending_fast.clear()
                    pending_slow.clear()
                    _sync_channel_queue()
                elif _state.get("paused") or _control.get("pause_abort"):
                    if not inflight:
                        if _wait_if_paused_or_cancel() == "cancel":
                            cancelled = True
                            pending_fast.clear()
                            pending_slow.clear()
                            _sync_channel_queue()
                            break
                        with _meta_lock:
                            _control["pause_abort"] = False
                        _fill()
                        continue
                if not inflight:
                    if _state.get("paused") or _control.get("pause_abort"):
                        continue
                    # 仍有排队却无人在跑：补填；补不上再退出（避免慢源计数漂移时早停）
                    if pending_fast or pending_slow:
                        before_f = len(pending_fast)
                        before_s = len(pending_slow)
                        _fill()
                        if inflight:
                            continue
                        # slow_inflight 可能虚高导致慢队列永远填不进：强制校正后再试一次
                        if pending_slow and slow_inflight > 0:
                            log.warning(
                                "scrape export: empty inflight with pending "
                                "fast=%s slow=%s slow_inflight=%s → reset slow_inflight",
                                before_f,
                                before_s,
                                slow_inflight,
                            )
                            slow_inflight = 0
                            _fill()
                            if inflight:
                                continue
                        if pending_fast or pending_slow:
                            abandoned_remaining = [
                                t
                                for t in (list(pending_fast) + list(pending_slow))
                                if isinstance(t, dict)
                            ]
                            log.warning(
                                "scrape export: abandon remaining queue "
                                "fast=%s slow=%s (cannot schedule)",
                                len(pending_fast),
                                len(pending_slow),
                            )
                            pending_fast.clear()
                            pending_slow.clear()
                            _sync_channel_queue()
                    break
                done_set, _ = futures_wait(
                    set(inflight.keys()),
                    timeout=(
                        0.5
                        if (_state.get("paused") or _control.get("pause_abort"))
                        else 2.0
                    ),
                    return_when=FIRST_COMPLETED,
                )
                if not done_set:
                    if not cancelled and not (
                        _state.get("paused") or _control.get("pause_abort")
                    ):
                        _fill()
                    continue
                for fut in done_set:
                    kind, t = inflight.pop(fut, ("fast", {}))
                    try:
                        pair = fut.result()
                        if isinstance(pair, tuple) and len(pair) == 2:
                            result, code = pair
                        else:
                            result, code = pair, ""
                    except Exception as e:
                        log.warning("scrape export worker: %s", e)
                        result, code = "failed", ""
                    if result == "cancel":
                        cancelled = True
                        if kind == "slow":
                            slow_inflight = max(0, slow_inflight - 1)
                        continue
                    if result == "paused":
                        if isinstance(t, dict) and t:
                            _requeue_paused(kind, t)
                        elif kind == "slow":
                            slow_inflight = max(0, slow_inflight - 1)
                        continue
                    if result == "defer_slow":
                        # 快→慢：不计终端结果，入慢队列；避免二次 defer
                        if kind == "slow":
                            slow_inflight = max(0, slow_inflight - 1)
                        elif isinstance(t, dict) and t:
                            t = {**t, "_deferred_slow": True}
                            pending_slow.append(t)
                        with _meta_lock:
                            _rebuild_active_from_inflight(inflight)
                        _touch_progress()
                        continue
                    if kind == "slow":
                        slow_inflight = max(0, slow_inflight - 1)
                    with _meta_lock:
                        if result not in ("cancel", "paused", "defer_slow"):
                            _record_terminal_result(str(result or "done"), code)
                        _rebuild_active_from_inflight(inflight)
                    _touch_progress()
                if not cancelled and not (
                    _state.get("paused") or _control.get("pause_abort")
                ):
                    _fill()
                    with _meta_lock:
                        _rebuild_active_from_inflight(inflight)
        finally:
            # wait=False：热重载时绝不阻塞进程退出
            pool.shutdown(wait=False, cancel_futures=True)


        if cancelled:
            _push_event(phase="job", text="任务已取消", level="warn")
            end_message = "cancelled"
            # 取消也保留计数到任务卡；清断点避免误续跑
            _clear_resume_checkpoint()
        elif abandoned_remaining:
            n_left = len(abandoned_remaining)
            _push_event(
                phase="job",
                text=f"调度异常中断 · 剩余 {n_left} 未处理，已保存断点",
                level="error",
            )
            end_message = "interrupted"
            _write_resume_checkpoint(
                all_targets=list(_state.get("allTargets") or targets),
                reason="interrupted",
            )
        else:
            _push_event(phase="job", text="任务结束", level="ok")
            end_message = "ok"
            _clear_resume_checkpoint()
        scrape_export_log_store.flush_events()
        with _meta_lock:
            _end_flags["message"] = end_message
            _end_flags["clearOnStop"] = bool(_control.get("clearOnStop"))
        return export_status()
    except Exception as e:
        _push_event(phase="job", text=str(e), level="error")
        with _meta_lock:
            _end_flags["message"] = str(e)
            _end_flags["clearOnStop"] = bool(_control.get("clearOnStop"))
            _end_flags["hadError"] = True
        _persist_state(force=True)
        raise
    finally:
        try:
            _lock.release()
        except RuntimeError:
            pass
        # 若 try/except 未写入结束标记（极少），兜底
        with _meta_lock:
            if not _end_flags.get("message") and _state.get("running"):
                _end_flags["message"] = str(_state.get("message") or "ok")
                _end_flags["clearOnStop"] = bool(_control.get("clearOnStop"))
        next_job = _take_next_job_after_finish()
        _persist_state(force=True)
        if next_job:
            qleft = 0
            with _meta_lock:
                qleft = len(_state.get("queue") or [])
            _push_event(
                phase="job",
                text=(
                    f"开始队列下一项 · {next_job.get('taskName') or next_job.get('taskId') or ''}"
                    + (f" · 剩余 {qleft}" if qleft else "")
                ).strip(),
                level="info",
            )
            _spawn_export_thread(next_job)


_hydrate_state()
