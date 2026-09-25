# -*- coding: utf-8 -*-
"""转存先入「最近接收」，完成后移到程序指定目录。"""

from __future__ import annotations

import logging
import re
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

# 多链路时按数量放大；上限 15 分钟
POLL_MAX_S = 180.0
POLL_MAX_CAP_S = 900.0


def _poll_budget(n_hashes: int) -> float:
    return max(POLL_MAX_S, min(POLL_MAX_CAP_S, 90.0 + 60.0 * max(1, n_hashes)))


def _protected_cids(*cids: str) -> set[str]:
    """Never move these: inbox itself, dest, root."""
    out = {"0", ""}
    for c in cids:
        s = str(c or "").strip()
        if s:
            out.add(s)
    return out


def _file_ids_from_tasks(
    tasks: list[Any],
    info_hashes: list[str],
    *,
    reject: set[str] | None = None,
) -> list[str]:
    """Collect completed task file_ids. Skip save-path pollution (file_id == inbox)."""
    want = {h.lower() for h in info_hashes if h}
    blocked = reject or set()
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
        if not fid or fid in seen:
            continue
        if fid in blocked:
            log.warning(
                "offline task file_id=%s equals save/dest path — ignore (hash=%s name=%s)",
                fid,
                hash_ or "?",
                str(t.get("name") or t.get("file_name") or "")[:80],
            )
            continue
        seen.add(fid)
        out.append(fid)
    return out


def _task_file_id(task: dict[str, Any], reject: set[str]) -> str:
    fid = str(task.get("file_id") or task.get("fileId") or "").strip()
    if not fid or fid in reject:
        return ""
    return fid


def _list_inbox_entries(cookie: str, folder_cid: str) -> list[dict[str, Any]]:
    """分页列出 inbox 全部子项。"""
    bad = p115_client.require_cookie_parts(cookie)
    if bad:
        return []
    cid = (folder_cid or "0").strip() or "0"
    out: list[dict[str, Any]] = []
    offset = 0
    page = 200
    for _ in range(25):
        listed = p115_client.list_dir_entries(
            cookie, cid, limit=page, offset=offset
        )
        if not listed.get("ok"):
            break
        batch = listed.get("entries") or []
        out.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return out


def _snapshot_ids(cookie: str, folder_cid: str) -> set[str]:
    return {
        str(e.get("id") or "")
        for e in _list_inbox_entries(cookie, folder_cid)
        if e.get("id")
    }


def _diff_new_ids(cookie: str, folder_cid: str, before: set[str]) -> list[str]:
    out: list[str] = []
    for e in _list_inbox_entries(cookie, folder_cid):
        eid = str(e.get("id") or "").strip()
        if eid and eid not in before:
            out.append(eid)
    return out


def _resolve_ids_from_inbox(
    cookie: str,
    inbox_cid: str,
    *,
    title_hint: str = "",
    name_hint: str = "",
) -> list[str]:
    """When task.file_id is polluted, pick real children under 最近接收（不截断）。"""
    entries = _list_inbox_entries(cookie, inbox_cid)
    if not entries:
        return []

    name_key = re.sub(r"\s+", "", name_hint or "").lower()
    if name_key:
        matched = [
            str(e["id"])
            for e in entries
            if name_key[:24]
            in re.sub(r"\s+", "", str(e.get("name") or "").lower())
        ]
        if matched:
            return matched

    hint = re.sub(r"\s+", "", title_hint or "").lower()
    if hint:
        matched = [
            str(e["id"])
            for e in entries
            if hint[:10] in re.sub(r"\s+", "", str(e.get("name") or "").lower())
        ]
        if matched:
            return matched

    archives = [
        str(e["id"])
        for e in entries
        if p115_extract._is_archive_name(str(e.get("name") or ""))
    ]
    if archives:
        return archives

    return [str(e["id"]) for e in entries if e.get("id")]


def _movable_ids_in_inbox(
    cookie: str,
    candidate_ids: list[str],
    *,
    inbox_cid: str,
    dest_cid: str,
    title_hint: str = "",
    name_hint: str = "",
    allow_inbox_resolve: bool = False,
) -> list[str]:
    """Only move children of inbox. Never move 最近接收 / dest / root."""
    blocked = _protected_cids(inbox_cid, dest_cid)
    children = _snapshot_ids(cookie, inbox_cid)
    out: list[str] = []
    seen: set[str] = set()
    dropped_protected = False

    for raw in candidate_ids:
        fid = str(raw or "").strip()
        if not fid or fid in seen:
            continue
        if fid in blocked:
            dropped_protected = True
            log.warning(
                "refuse to move protected cid=%s (inbox=%s dest=%s)",
                fid,
                inbox_cid,
                dest_cid,
            )
            continue
        if children and fid not in children:
            log.warning(
                "refuse to move cid=%s — not under inbox %s",
                fid,
                inbox_cid,
            )
            continue
        seen.add(fid)
        out.append(fid)

    if not out and (allow_inbox_resolve or dropped_protected):
        for fid in _resolve_ids_from_inbox(
            cookie,
            inbox_cid,
            title_hint=title_hint,
            name_hint=name_hint,
        ):
            if fid in blocked or fid in seen:
                continue
            if children and fid not in children:
                continue
            seen.add(fid)
            out.append(fid)
        if out:
            log.info(
                "resolved %s move id(s) from inbox after rejecting polluted file_id",
                len(out),
            )
    return out


def _wait_offline_file_ids(job: dict[str, Any]) -> dict[str, Any]:
    """无渐进路径时的兜底：等全部终态再返回。"""
    cookie = normalize_cookie(str(job.get("cookie") or ""))
    hashes = [
        h.lower()
        for h in (job.get("infoHashes") or [])
        if isinstance(h, str) and h
    ]
    reject = _protected_cids(
        str(job.get("inboxCid") or ""),
        str(job.get("destCid") or ""),
    )
    budget = _poll_budget(len(hashes))
    started = time.time()
    last_note = "等待离线转存完成"
    saw_terminal = False
    with httpx.Client(
        timeout=30.0, follow_redirects=True, trust_env=False
    ) as client:
        while time.time() - started < budget:
            try:
                tasks = p115_extract._list_offline_tasks_pages(client, cookie)
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
                        saw_terminal = True
                        ids = _file_ids_from_tasks(matched, hashes, reject=reject)
                        if ids:
                            return {"ok": True, "fileIds": ids, "message": "转存完成"}
                        last_note = "任务完成但 file_id 无效（疑似落点目录），改从「最近接收」解析"
                        return {
                            "ok": True,
                            "fileIds": [],
                            "message": last_note,
                            "resolveInbox": True,
                        }
                    else:
                        last_note = progress_note(phases["pct"])

            time.sleep(POLL_INTERVAL_S)

    if saw_terminal:
        return {
            "ok": True,
            "fileIds": [],
            "message": last_note,
            "resolveInbox": True,
        }
    return {
        "ok": False,
        "message": timeout_message(budget, last_note),
        "fileIds": [],
    }


def _resolve_pick_from_inbox(
    client: httpx.Client,
    cookie: str,
    inbox_cid: str,
    *,
    name: str = "",
    title_hint: str = "",
) -> dict[str, str] | None:
    """离线任务常不带 pick_code：从「最近接收」里按文件名找回。"""
    try:
        rows = p115_extract._list_folder_files_all(client, cookie, inbox_cid)
    except Exception:
        log.exception("list inbox for pick_code failed")
        return None

    name_n = (name or "").strip()
    if name_n:
        for r in rows:
            if not isinstance(r, dict) or not r.get("fid"):
                continue
            rn = str(r.get("n") or r.get("name") or "").strip()
            pick = str(r.get("pc") or r.get("pick_code") or "").strip()
            if pick and rn == name_n:
                return {"pickCode": pick, "name": rn}

    hint = name_n or title_hint
    for t in p115_extract._pick_codes_from_folder(rows, hint):
        return t
    return None


def _process_one_done_task(
    client: httpx.Client,
    *,
    cookie: str,
    inbox_cid: str,
    dest_cid: str,
    title_hint: str,
    want_extract: bool,
    password: str,
    task: dict[str, Any],
    already_moved: set[str],
) -> dict[str, Any]:
    """单个离线任务完成：可选解压 → 安全搬家。"""
    reject = _protected_cids(inbox_cid, dest_cid)
    name = str(task.get("name") or task.get("file_name") or "")
    hash_ = str(task.get("info_hash") or task.get("infoHash") or "").lower()
    pick = str(
        task.get("pick_code") or task.get("pickcode") or task.get("pc") or ""
    ).strip()

    move_ids: list[str] = []
    extracted = 0
    notes: list[str] = []

    fid = _task_file_id(task, reject)
    if not fid:
        for rid in _resolve_ids_from_inbox(
            cookie, inbox_cid, title_hint=title_hint, name_hint=name
        ):
            if rid not in already_moved:
                move_ids.append(rid)
    else:
        move_ids.append(fid)

    # 压缩包：wantExtract 或文件名本身可云解压 → 必须先解压成功再搬；
    # 解压失败则留在「最近接收」，避免「只搬走压缩包、不解压」。
    should_extract = bool(want_extract) or p115_extract._can_cloud_extract(name)
    extract_ok = not should_extract  # 非压缩包视为无需解压

    if should_extract and p115_extract._is_multipart_archive(name):
        notes.append(f"分卷不支持云解压，仅转存：{name}")
        extract_ok = True  # 分卷只能原样搬
    elif should_extract and p115_extract._can_cloud_extract(name):
        if not pick:
            try:
                found = _resolve_pick_from_inbox(
                    client,
                    cookie,
                    inbox_cid,
                    name=name,
                    title_hint=title_hint,
                )
            except Exception:
                log.exception("resolve pick_code from inbox failed")
                found = None
            if found:
                pick = found["pickCode"]
                if not name:
                    name = found.get("name") or name
                log.info(
                    "resolved pick_code from inbox for %s",
                    name[:80],
                )
        if not pick:
            notes.append(f"未找到 pick_code，无法云解压：{name or hash_}")
            extract_ok = False
        else:
            before = _snapshot_ids(cookie, inbox_cid)
            one = p115_extract.extract_one_archive(
                client,
                {
                    "cookie": cookie,
                    "folderCid": inbox_cid,
                    "password": password,
                    "titleHint": title_hint,
                },
                {"pickCode": pick, "name": name, "infoHash": hash_},
            )
            if one.get("ok"):
                extracted = 1
                extract_ok = True
                notes.append(str(one.get("message") or "已解压"))
                folder_cid = str(one.get("folderCid") or "").strip()
                if folder_cid and folder_cid not in move_ids:
                    move_ids.append(folder_cid)
                for nid in _diff_new_ids(cookie, inbox_cid, before):
                    if nid not in move_ids:
                        move_ids.append(nid)
            elif one.get("skipped"):
                notes.append(str(one.get("message") or "跳过解压"))
                extract_ok = True
            else:
                notes.append(str(one.get("message") or "解压失败"))
                extract_ok = False

    if should_extract and not extract_ok:
        # 不解压成功就不搬压缩包，留给下次或人工处理
        return {
            "ok": False,
            "moved": 0,
            "extracted": extracted,
            "message": "；".join(notes) or "云解压未成功，压缩包仍留在「最近接收」",
            "ids": [],
        }

    safe = _movable_ids_in_inbox(
        cookie,
        move_ids,
        inbox_cid=inbox_cid,
        dest_cid=dest_cid,
        title_hint=title_hint,
        name_hint=name,
        allow_inbox_resolve=not bool(fid),
    )
    safe = [x for x in safe if x not in already_moved]
    moved_n = 0
    if safe:
        moved = p115_client.move_files(cookie, safe, dest_cid)
        if moved.get("ok"):
            moved_n = int(moved.get("moved") or len(safe))
            already_moved.update(safe)
        else:
            notes.append(str(moved.get("message") or "移动失败"))
            return {
                "ok": False,
                "moved": 0,
                "extracted": extracted,
                "message": "；".join(notes) or "移动失败",
                "ids": [],
            }

    return {
        "ok": True,
        "moved": moved_n,
        "extracted": extracted,
        "message": "；".join(notes) if notes else "ok",
        "ids": safe,
    }


def run_poll_then_relocate(job: dict[str, Any]) -> dict[str, Any]:
    """离线：逐个完成即（可选）解压并搬到 destCid —— 多 ed2k 不全员死等。"""
    cookie = normalize_cookie(str(job.get("cookie") or ""))
    inbox_cid = str(job.get("inboxCid") or "").strip() or "0"
    dest_cid = str(job.get("destCid") or "").strip() or "0"
    title_hint = str(job.get("titleHint") or "")
    want_extract = bool(job.get("wantExtract"))
    password = str(job.get("password") or "")
    hashes = [
        h.lower()
        for h in (job.get("infoHashes") or [])
        if isinstance(h, str) and h
    ]

    if not cookie:
        return {"ok": False, "message": "无 Cookie", "moved": 0}
    if dest_cid in {"", "0"} or dest_cid == inbox_cid:
        return {
            "ok": True,
            "message": "目标未设置或就是接收目录，留在「最近接收」，不搬到根目录",
            "moved": 0,
        }

    # 无 hash：兜底旧路径（等齐 → 解压 → 搬）
    if not hashes:
        return _run_relocate_legacy_no_hash(job)

    pending = set(hashes)
    already_moved: set[str] = set()
    moved_total = 0
    extracted_total = 0
    fail_notes: list[str] = []
    budget = _poll_budget(len(pending))
    started = time.time()

    with httpx.Client(
        timeout=30.0, follow_redirects=True, trust_env=False
    ) as client:
        while pending and time.time() - started < budget:
            try:
                tasks = p115_extract._list_offline_tasks_pages(client, cookie)
            except Exception as err:
                fail_notes.append(str(err) or "拉取离线任务失败")
                time.sleep(POLL_INTERVAL_S)
                continue

            matched = match_tasks_by_hashes(tasks, list(pending))
            progressed = False

            for t in matched:
                h = str(t.get("info_hash") or t.get("infoHash") or "").lower()
                if not h or h not in pending:
                    continue
                if is_task_failed(t):
                    pending.discard(h)
                    fail_notes.append(
                        f"{t.get('name') or h}: {t.get('error') or '离线失败'}"
                    )
                    progressed = True
                    continue
                if not is_task_done(t):
                    continue

                one = _process_one_done_task(
                    client,
                    cookie=cookie,
                    inbox_cid=inbox_cid,
                    dest_cid=dest_cid,
                    title_hint=title_hint,
                    want_extract=want_extract,
                    password=password,
                    task=t,
                    already_moved=already_moved,
                )
                pending.discard(h)
                progressed = True
                moved_total += int(one.get("moved") or 0)
                extracted_total += int(one.get("extracted") or 0)
                if not one.get("ok"):
                    fail_notes.append(str(one.get("message") or "处理失败"))

            if pending and not progressed:
                time.sleep(POLL_INTERVAL_S)
            elif pending:
                time.sleep(0.4)

        # 超时：对仍在 inbox 的已完成压缩包再扫一次兜底解压/搬家
        if pending and want_extract:
            try:
                rows = p115_extract._list_folder_files_all(
                    client, cookie, inbox_cid
                )
                for t in p115_extract._pick_codes_from_folder(rows, title_hint):
                    before = _snapshot_ids(cookie, inbox_cid)
                    one = p115_extract.extract_one_archive(
                        client,
                        {
                            "cookie": cookie,
                            "folderCid": inbox_cid,
                            "password": password,
                            "titleHint": title_hint,
                        },
                        t,
                    )
                    if one.get("ok"):
                        extracted_total += 1
                        ids = []
                        cid = str(one.get("folderCid") or "").strip()
                        if cid:
                            ids.append(cid)
                        ids.extend(_diff_new_ids(cookie, inbox_cid, before))
                        safe = _movable_ids_in_inbox(
                            cookie,
                            ids,
                            inbox_cid=inbox_cid,
                            dest_cid=dest_cid,
                            title_hint=title_hint,
                            allow_inbox_resolve=False,
                        )
                        safe = [x for x in safe if x not in already_moved]
                        if safe:
                            moved = p115_client.move_files(
                                cookie, safe, dest_cid
                            )
                            if moved.get("ok"):
                                moved_total += int(
                                    moved.get("moved") or len(safe)
                                )
                                already_moved.update(safe)
            except Exception:
                log.exception("inbox fallback extract failed")

    ok = moved_total > 0 or extracted_total > 0 or not pending
    parts = [
        f"已搬家 {moved_total} 项",
    ]
    if extracted_total:
        parts.append(f"已解压 {extracted_total} 个")
    if pending:
        parts.append(f"未完成 {len(pending)} 个任务")
        ok = moved_total > 0 or extracted_total > 0
    if fail_notes:
        parts.append(fail_notes[0])

    return {
        "ok": ok,
        "message": " · ".join(parts),
        "moved": moved_total,
        "extracted": extracted_total,
        "pendingHashes": list(pending),
        "destCid": dest_cid,
        "inboxCid": inbox_cid,
    }


def _run_relocate_legacy_no_hash(job: dict[str, Any]) -> dict[str, Any]:
    """无 infoHashes 时：等齐（或 resolveInbox）→ 解压 → 搬。"""
    cookie = normalize_cookie(str(job.get("cookie") or ""))
    inbox_cid = str(job.get("inboxCid") or "").strip() or "0"
    dest_cid = str(job.get("destCid") or "").strip() or "0"
    title_hint = str(job.get("titleHint") or "")

    ready = _wait_offline_file_ids(job)
    if not ready.get("ok"):
        return {
            "ok": False,
            "message": str(ready.get("message") or "等待失败"),
            "moved": 0,
        }

    file_ids = list(ready.get("fileIds") or [])
    resolve_inbox = bool(ready.get("resolveInbox"))

    if job.get("wantExtract"):
        try:
            extract_job = {
                "cookie": cookie,
                "folderCid": inbox_cid,
                "password": job.get("password") or "",
                "infoHashes": job.get("infoHashes") or [],
                "titleHint": title_hint,
            }
            with httpx.Client(
                timeout=30.0, follow_redirects=True, trust_env=False
            ) as client:
                targets = p115_extract._pick_codes_from_tasks(
                    p115_extract._list_offline_tasks_pages(client, cookie),
                    [],
                )
                if not targets:
                    rows = p115_extract._list_folder_files_all(
                        client, cookie, inbox_cid
                    )
                    targets = p115_extract._pick_codes_from_folder(
                        rows, title_hint
                    )
                if targets:
                    before_extract = _snapshot_ids(cookie, inbox_cid)
                    result = p115_extract._extract_ready_targets(
                        client, extract_job, targets
                    )
                    for cid in result.get("folderCids") or []:
                        if cid not in file_ids:
                            file_ids.append(str(cid))
                    for nid in _diff_new_ids(cookie, inbox_cid, before_extract):
                        if nid not in file_ids:
                            file_ids.append(nid)
        except Exception:
            log.exception("extract before relocate failed")

    if resolve_inbox or not file_ids:
        for fid in _resolve_ids_from_inbox(
            cookie, inbox_cid, title_hint=title_hint
        ):
            if fid not in file_ids:
                file_ids.append(fid)

    file_ids = _movable_ids_in_inbox(
        cookie,
        file_ids,
        inbox_cid=inbox_cid,
        dest_cid=dest_cid,
        title_hint=title_hint,
        allow_inbox_resolve=resolve_inbox,
    )

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
    time.sleep(0.8)
    new_ids = _diff_new_ids(cookie_n, inbox, before_ids)
    if not new_ids:
        time.sleep(1.2)
        new_ids = _diff_new_ids(cookie_n, inbox, before_ids)
    if not new_ids:
        return {
            "ok": False,
            "message": "分享已接收，但未在「最近接收」识别到新文件",
            "moved": 0,
        }
    blocked = _protected_cids(inbox, dest)
    safe_ids = [fid for fid in new_ids if fid not in blocked]
    if not safe_ids:
        return {
            "ok": False,
            "message": "分享已接收，但可移动项无效（已拦截落点目录）",
            "moved": 0,
        }
    moved = p115_client.move_files(cookie_n, safe_ids, dest)
    return {
        "ok": bool(moved.get("ok")),
        "message": str(moved.get("message") or ""),
        "moved": int(moved.get("moved") or 0),
        "fileIds": safe_ids,
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
