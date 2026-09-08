# -*- coding: utf-8 -*-
"""转存先入「最近接受」，完成后移到程序指定目录。"""

from __future__ import annotations

import logging
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from . import p115_client
from . import p115_extract
from .p115_client import normalize_cookie

log = logging.getLogger("p115-relocate")

_relocate_pool = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="p115-relocate",
)

# 离线完成可能较慢，比纯解压轮询更久
POLL_INTERVAL_S = 3.0
POLL_MAX_S = 90.0


def _file_ids_from_tasks(
    tasks: list[Any],
    info_hashes: list[str],
) -> list[str]:
    want = {h.lower() for h in info_hashes if h}
    out: list[str] = []
    seen: set[str] = set()
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if not p115_extract._is_task_done(t):
            continue
        hash_ = str(t.get("info_hash") or t.get("infoHash") or "").lower()
        if want and hash_ and hash_ not in want:
            continue
        if want and not hash_:
            continue
        fid = str(t.get("file_id") or t.get("fileId") or "").strip()
        if fid and fid not in seen:
            seen.add(fid)
            out.append(fid)
    return out


def _wait_offline_file_ids(job: dict[str, Any]) -> dict[str, Any]:
    cookie = normalize_cookie(str(job.get("cookie") or ""))
    hashes = [
        h.lower()
        for h in (job.get("infoHashes") or [])
        if isinstance(h, str) and h
    ]
    started = time.time()
    last_note = "等待离线转存完成"
    with httpx.Client(
        timeout=30.0, follow_redirects=True, trust_env=False
    ) as client:
        while time.time() - started < POLL_MAX_S:
            try:
                tasks = p115_extract._list_offline_tasks_once(client, cookie)
            except Exception as err:
                last_note = str(err) or "拉取离线任务失败"
                time.sleep(POLL_INTERVAL_S)
                continue

            if hashes:
                matched = [
                    t
                    for t in tasks
                    if isinstance(t, dict)
                    and str(t.get("info_hash") or t.get("infoHash") or "").lower()
                    in hashes
                ]
                if matched:
                    if all(p115_extract._is_task_failed(t) for t in matched):
                        return {"ok": False, "message": "离线任务全部失败", "fileIds": []}
                    all_terminal = all(
                        p115_extract._is_task_done(t)
                        or p115_extract._is_task_failed(t)
                        for t in matched
                    )
                    any_done = any(p115_extract._is_task_done(t) for t in matched)
                    if any_done and all_terminal:
                        ids = _file_ids_from_tasks(matched, hashes)
                        if ids:
                            return {"ok": True, "fileIds": ids, "message": "转存完成"}
                        last_note = "任务完成但未拿到 file_id，继续等待…"
                    else:
                        downloading = next(
                            (
                                t
                                for t in matched
                                if not p115_extract._is_task_done(t)
                                and not p115_extract._is_task_failed(t)
                            ),
                            None,
                        )
                        pct = 0.0
                        if isinstance(downloading, dict):
                            try:
                                pct = float(
                                    downloading.get("percentDone")
                                    or downloading.get("percent_done")
                                    or 0
                                )
                            except (TypeError, ValueError):
                                pct = 0.0
                        last_note = f"转存中 {int(pct)}%" if pct else "转存中 …"

            time.sleep(POLL_INTERVAL_S)

    return {
        "ok": False,
        "message": f"等待转存超时（{int(POLL_MAX_S)} 秒）：{last_note}",
        "fileIds": [],
    }


def _snapshot_ids(cookie: str, folder_cid: str) -> set[str]:
    listed = p115_client.list_dir_entries(cookie, folder_cid, limit=120)
    if not listed.get("ok"):
        return set()
    return {
        str(e.get("id") or "")
        for e in (listed.get("entries") or [])
        if e.get("id")
    }


def _diff_new_ids(cookie: str, folder_cid: str, before: set[str]) -> list[str]:
    listed = p115_client.list_dir_entries(cookie, folder_cid, limit=120)
    if not listed.get("ok"):
        return []
    out: list[str] = []
    for e in listed.get("entries") or []:
        eid = str(e.get("id") or "").strip()
        if eid and eid not in before:
            out.append(eid)
    return out


def run_poll_then_relocate(job: dict[str, Any]) -> dict[str, Any]:
    """离线：轮询完成 →（可选云解压）→ 移到 destCid。"""
    cookie = normalize_cookie(str(job.get("cookie") or ""))
    inbox_cid = str(job.get("inboxCid") or "").strip() or "0"
    dest_cid = str(job.get("destCid") or "").strip() or "0"
    if not cookie:
        return {"ok": False, "message": "无 Cookie", "moved": 0}
    if dest_cid == inbox_cid:
        return {"ok": True, "message": "目标即接受目录，无需移动", "moved": 0}

    ready = _wait_offline_file_ids(job)
    if not ready.get("ok"):
        return {
            "ok": False,
            "message": str(ready.get("message") or "等待失败"),
            "moved": 0,
        }

    file_ids = list(ready.get("fileIds") or [])

    # 云解压仍在「最近接受」内进行，解压出的同名夹一并搬走
    if job.get("wantExtract"):
        try:
            extract_job = {
                "cookie": cookie,
                "folderCid": inbox_cid,
                "password": job.get("password") or "",
                "infoHashes": job.get("infoHashes") or [],
                "titleHint": job.get("titleHint") or "",
            }
            # 已完成，直接解压（不再二次长轮询）
            with httpx.Client(
                timeout=30.0, follow_redirects=True, trust_env=False
            ) as client:
                targets = p115_extract._pick_codes_from_tasks(
                    p115_extract._list_offline_tasks_once(client, cookie),
                    [
                        h.lower()
                        for h in (job.get("infoHashes") or [])
                        if isinstance(h, str)
                    ],
                )
                if not targets:
                    rows = p115_extract._list_folder_files_once(
                        client, cookie, inbox_cid
                    )
                    targets = p115_extract._pick_codes_from_folder(
                        rows, job.get("titleHint")
                    )
                if targets:
                    before_extract = _snapshot_ids(cookie, inbox_cid)
                    p115_extract._extract_ready_targets(client, extract_job, targets)
                    time.sleep(1.2)
                    for nid in _diff_new_ids(cookie, inbox_cid, before_extract):
                        if nid not in file_ids:
                            file_ids.append(nid)
        except Exception:
            log.exception("extract before relocate failed")

    if not file_ids:
        return {"ok": False, "message": "未找到可移动的文件", "moved": 0}

    moved = p115_client.move_files(cookie, file_ids, dest_cid)
    return {
        "ok": bool(moved.get("ok")),
        "message": str(
            moved.get("message")
            or (
                f"已从「最近接受」移到指定目录（{moved.get('moved') or 0}）"
                if moved.get("ok")
                else "移动失败"
            )
        ),
        "moved": int(moved.get("moved") or 0),
        "fileIds": file_ids,
        "destCid": dest_cid,
        "inboxCid": inbox_cid,
    }


def relocate_share_new_items(
    cookie: str,
    *,
    inbox_cid: str,
    dest_cid: str,
    before_ids: set[str],
) -> dict[str, Any]:
    """分享接收后：把「最近接受」里新增项移到指定目录。"""
    cookie_n = normalize_cookie(cookie)
    dest = (dest_cid or "0").strip() or "0"
    inbox = (inbox_cid or "0").strip() or "0"
    if dest == inbox:
        return {"ok": True, "message": "目标即接受目录，无需移动", "moved": 0}
    # 稍等目录刷新
    time.sleep(0.8)
    new_ids = _diff_new_ids(cookie_n, inbox, before_ids)
    if not new_ids:
        # 再试一次
        time.sleep(1.2)
        new_ids = _diff_new_ids(cookie_n, inbox, before_ids)
    if not new_ids:
        return {
            "ok": False,
            "message": "分享已接收，但未在「最近接受」识别到新文件",
            "moved": 0,
        }
    moved = p115_client.move_files(cookie_n, new_ids, dest)
    return {
        "ok": bool(moved.get("ok")),
        "message": str(moved.get("message") or ""),
        "moved": int(moved.get("moved") or 0),
        "fileIds": new_ids,
    }


def schedule_deferred_relocate(job: dict[str, Any]) -> dict[str, str]:
    job_id = f"{int(time.time() * 1000)}_{secrets.token_hex(3)}"

    def runner() -> None:
        try:
            result = run_poll_then_relocate(job)
            log.info(
                "%s %s %s",
                job_id,
                "ok" if result.get("ok") else "fail",
                result.get("message"),
            )
        except Exception:
            log.exception("%s fail", job_id)

    _relocate_pool.submit(runner)
    log.info(
        "scheduled poll-then-relocate %s hashes=%s inbox=%s dest=%s",
        job_id,
        len(job.get("infoHashes") or []),
        job.get("inboxCid"),
        job.get("destCid"),
    )
    return {"jobId": job_id, "mode": "poll-relocate"}
