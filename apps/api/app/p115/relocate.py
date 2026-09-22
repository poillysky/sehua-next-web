# -*- coding: utf-8 -*-
"""转存先入「最近接收」，完成后移到程序指定目录。"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

import app.p115.client as p115_client
import app.p115.extract as p115_extract
from app.p115.client import normalize_cookie
from app.p115.polling import (
    POLL_INTERVAL_S,
    is_task_done,
    is_task_failed,
    match_tasks_by_hashes,
    progress_note,
    submit_deferred,
    task_phases,
    timeout_message,
)

log = logging.getLogger("p115-relocate")

_relocate_pool = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="p115-relocate",
)

# 离线完成可能较慢，比纯解压轮询更久
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
        if not is_task_done(t):
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
                matched = match_tasks_by_hashes(tasks, hashes)
                if matched:
                    phases = task_phases(matched)
                    if phases["all_failed"]:
                        return {"ok": False, "message": "离线任务全部失败", "fileIds": []}
                    if phases["any_done"] and phases["all_terminal"]:
                        ids = _file_ids_from_tasks(matched, hashes)
                        if ids:
                            return {"ok": True, "fileIds": ids, "message": "转存完成"}
                        last_note = "任务完成但未拿到 file_id，继续等待…"
                    else:
                        last_note = progress_note(phases["pct"])

            time.sleep(POLL_INTERVAL_S)

    return {
        "ok": False,
        "message": timeout_message(POLL_MAX_S, last_note),
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
    if dest_cid in {"", "0"} or dest_cid == inbox_cid:
        return {
            "ok": True,
            "message": "目标未设置或就是接收目录，留在「最近接收」，不搬到根目录",
            "moved": 0,
        }

    ready = _wait_offline_file_ids(job)
    if not ready.get("ok"):
        return {
            "ok": False,
            "message": str(ready.get("message") or "等待失败"),
            "moved": 0,
        }

    file_ids = list(ready.get("fileIds") or [])

    # 云解压仍在「最近接收」内进行，解压出的同名夹一并搬走
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
                f"已从「最近接收」移到指定目录（{moved.get('moved') or 0}）"
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
    """分享接收后：把「最近接收」里新增项移到指定目录。"""
    cookie_n = normalize_cookie(cookie)
    dest = (dest_cid or "0").strip() or "0"
    inbox = (inbox_cid or "0").strip() or "0"
    if dest in {"", "0"} or dest == inbox:
        return {
            "ok": True,
            "message": "目标未设置或就是接收目录，留在「最近接收」",
            "moved": 0,
        }
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
            "message": "分享已接收，但未在「最近接收」识别到新文件",
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
    job_id = submit_deferred(
        _relocate_pool, log=log, job=job, runner=run_poll_then_relocate
    )
    log.info(
        "scheduled poll-then-relocate %s hashes=%s inbox=%s dest=%s",
        job_id,
        len(job.get("infoHashes") or []),
        job.get("inboxCid"),
        job.get("destCid"),
    )
    return {"jobId": job_id, "mode": "poll-relocate"}
