"""115 云解压：转存后轮询离线任务，完成后立即解压。"""

from __future__ import annotations

import logging
import re
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from .p115_client import encode_form, form_headers, headers, human_error, normalize_cookie

log = logging.getLogger("p115-extract")

POLL_INTERVAL_S = 3.0
POLL_MAX_S = 30.0
ARCHIVE_RE = re.compile(r"\.(zip|rar|7z)$", re.I)


def _read_json(res: httpx.Response) -> Any:
    try:
        return res.json()
    except Exception:
        text = (res.text or "")[:240]
        return {"state": False, "error": text or f"HTTP {res.status_code}"}


def _is_archive_name(name: str) -> bool:
    return bool(ARCHIVE_RE.search(name or ""))


def _is_task_done(t: Any) -> bool:
    if not isinstance(t, dict):
        return False
    try:
        status = int(t.get("status", -99))
    except (TypeError, ValueError):
        status = -99
    if status == 2 or t.get("status") == "2":
        return True
    for key in ("percentDone", "percent_done"):
        try:
            if float(t.get(key) or 0) >= 100:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _is_task_failed(t: Any) -> bool:
    if not isinstance(t, dict):
        return False
    try:
        status = int(t.get("status") or 0)
    except (TypeError, ValueError):
        status = 0
    return status < 0


def _same_name_folder_label(archive_name: str, title_hint: str | None = None) -> str:
    base = (archive_name or "").strip()
    if base:
        base = re.sub(r"\.(zip|rar|7z)$", "", base, flags=re.I)
    if not base:
        base = (title_hint or "").strip() or "解压内容"
    base = re.sub(r'[<>"]', "_", base)
    base = re.sub(r"[/\\:*?|]", "_", base)
    base = re.sub(r"\s+", " ", base).strip()[:200]
    return base or "解压内容"


def _list_folder_files_once(
    client: httpx.Client,
    cookie: str,
    folder_cid: str,
    limit: int = 100,
) -> list[Any]:
    qs = urlencode(
        {
            "aid": "1",
            "cid": folder_cid or "0",
            "o": "user_ptime",
            "asc": "0",
            "offset": "0",
            "show_dir": "1",
            "limit": str(limit),
            "type": "0",
            "format": "json",
        }
    )
    res = client.get(
        f"https://webapi.115.com/files?{qs}",
        headers=headers(cookie),
    )
    data = _read_json(res)
    return data.get("data") if isinstance(data.get("data"), list) else []


def _ensure_same_name_folder(
    client: httpx.Client,
    cookie: str,
    parent_cid: str,
    folder_name: str,
) -> dict[str, Any]:
    body = [("pid", parent_cid or "0"), ("cname", folder_name)]
    res = client.post(
        "https://webapi.115.com/files/add",
        content=encode_form(body),
        headers=form_headers(cookie),
    )
    data = _read_json(res)
    cid = str(
        data.get("cid")
        or data.get("file_id")
        or (
            data.get("data", {}).get("cid")
            if isinstance(data.get("data"), dict)
            else ""
        )
        or (
            data.get("data", {}).get("file_id")
            if isinstance(data.get("data"), dict)
            else ""
        )
        or ""
    )
    if (data.get("state") is True or data.get("state") == 1 or data.get("errno") == 0) and cid:
        return {"ok": True, "cid": cid, "name": folder_name}

    try:
        rows = _list_folder_files_once(client, cookie, parent_cid)
        for r in rows:
            if not isinstance(r, dict):
                continue
            if (
                r.get("cid") is not None
                and not r.get("fid")
                and str(r.get("n") or r.get("name") or "").strip() == folder_name
            ):
                return {"ok": True, "cid": str(r["cid"]), "name": folder_name}
    except Exception:
        pass

    return {"ok": False, "message": human_error(data, "创建同名文件夹失败")}


def _list_offline_tasks_once(client: httpx.Client, cookie: str) -> list[Any]:
    qs = urlencode({"ct": "lixian", "ac": "task_lists", "page": "1"})
    res = client.get(
        f"https://115.com/web/lixian/?{qs}",
        headers=headers(cookie, "https://115.com/web/lixian/"),
    )
    data = _read_json(res)
    tasks = data.get("tasks") or (
        data.get("data", {}).get("tasks")
        if isinstance(data.get("data"), dict)
        else None
    ) or data.get("list") or []
    return tasks if isinstance(tasks, list) else []


def _pick_codes_from_tasks(
    tasks: list[Any],
    info_hashes: list[str],
) -> list[dict[str, str]]:
    want = {h.lower() for h in info_hashes}
    out: list[dict[str, str]] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        hash_ = str(t.get("info_hash") or t.get("infoHash") or "").lower()
        name = str(t.get("name") or t.get("file_name") or "")
        pick = str(t.get("pick_code") or t.get("pickcode") or t.get("pc") or "").strip()
        if want and hash_ and hash_ not in want:
            continue
        if not _is_task_done(t):
            continue
        if pick and (_is_archive_name(name) or hash_ in want):
            out.append({"pickCode": pick, "name": name})
    return out


def _pick_codes_from_folder(
    rows: list[Any],
    title_hint: str | None = None,
) -> list[dict[str, str]]:
    hint = re.sub(r"\s+", "", title_hint or "")[:16].lower()
    archives: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("fid") or r.get("ns"):
            continue
        pick = str(r.get("pc") or r.get("pick_code") or "").strip()
        name = str(r.get("n") or r.get("name") or "")
        if pick and _is_archive_name(name):
            archives.append(
                {
                    "pickCode": pick,
                    "name": name,
                    "time": float(r.get("t") or r.get("te") or r.get("ptime") or 0),
                }
            )
    if not archives:
        return []
    if hint:
        matched = [
            a
            for a in archives
            if hint[:10] in re.sub(r"\s+", "", a["name"].lower())
        ]
        if matched:
            return [
                {"pickCode": a["pickCode"], "name": a["name"]} for a in matched[:3]
            ]
    archives.sort(key=lambda a: a["time"], reverse=True)
    return [{"pickCode": a["pickCode"], "name": a["name"]} for a in archives[:3]]


def _wait_until_transfer_ready(
    client: httpx.Client,
    job: dict[str, Any],
) -> dict[str, Any]:
    cookie = normalize_cookie(str(job.get("cookie") or ""))
    folder_cid = str(job.get("folderCid") or "0")
    hashes = [
        h.lower()
        for h in (job.get("infoHashes") or [])
        if isinstance(h, str) and h
    ]
    started = time.time()
    last_note = "等待离线转存完成"

    while time.time() - started < POLL_MAX_S:
        tasks: list[Any] = []
        try:
            tasks = _list_offline_tasks_once(client, cookie)
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
                failed = [t for t in matched if _is_task_failed(t)]
                if len(failed) == len(matched):
                    return {"ok": False, "message": "离线任务全部失败，无法解压"}

                all_terminal = all(
                    _is_task_done(t) or _is_task_failed(t) for t in matched
                )
                any_done = any(_is_task_done(t) for t in matched)

                if any_done and all_terminal:
                    from_tasks = _pick_codes_from_tasks(tasks, hashes)
                    if from_tasks:
                        log.info(
                            "transfer ready via tasks hashes=%s archives=%s",
                            hashes,
                            [t["name"] for t in from_tasks],
                        )
                        return {"ok": True, "targets": from_tasks}

                if not all_terminal:
                    downloading = next(
                        (
                            t
                            for t in matched
                            if not _is_task_done(t) and not _is_task_failed(t)
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

        try:
            rows = _list_folder_files_once(client, cookie, folder_cid)
            from_folder = _pick_codes_from_folder(rows, job.get("titleHint"))
            if from_folder:
                if not hashes:
                    log.info(
                        "transfer ready via folder archives=%s",
                        [t["name"] for t in from_folder],
                    )
                    return {"ok": True, "targets": from_folder}

                matched = [
                    t
                    for t in tasks
                    if isinstance(t, dict)
                    and str(t.get("info_hash") or t.get("infoHash") or "").lower()
                    in hashes
                ]
                all_done_or_missing = (not matched) or all(
                    _is_task_done(t) or _is_task_failed(t) for t in matched
                )
                if all_done_or_missing and any(_is_task_done(t) for t in matched):
                    log.info(
                        "transfer ready via folder+tasks archives=%s",
                        [t["name"] for t in from_folder],
                    )
                    return {"ok": True, "targets": from_folder}
        except Exception:
            pass

        time.sleep(POLL_INTERVAL_S)

    return {
        "ok": False,
        "message": f"等待转存超时（{int(POLL_MAX_S)} 秒）：{last_note}",
    }


def _push_extract(
    client: httpx.Client,
    cookie: str,
    pick_code: str,
    password: str,
) -> dict[str, Any]:
    body = [("pick_code", pick_code), ("secret", password or "")]
    res = client.post(
        "https://webapi.115.com/files/push_extract",
        content=encode_form(body),
        headers=form_headers(cookie),
    )
    data = _read_json(res)
    if data.get("state") is True or data.get("state") == 1 or data.get("errno") == 0:
        return {"ok": True, "message": "已推送云解压"}
    return {"ok": False, "message": human_error(data, "推送云解压失败")}


def _extract_info_once(
    client: httpx.Client,
    cookie: str,
    pick_code: str,
) -> dict[str, Any]:
    qs = urlencode(
        {
            "pick_code": pick_code,
            "file_name": "",
            "next_marker": "",
            "page_count": "999",
            "paths": "文件",
        }
    )
    res = client.get(
        f"https://webapi.115.com/files/extract_info?{qs}",
        headers=headers(cookie),
    )
    data = _read_json(res)
    if data.get("state") is False or data.get("errno"):
        return {
            "files": [],
            "dirs": [],
            "message": human_error(data, "读取压缩包目录失败（可能尚未就绪）"),
        }

    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    lst = (
        inner.get("list")
        or data.get("list")
        or inner.get("files")
        or data.get("files")
        or []
    )
    files: list[str] = []
    dirs: list[str] = []
    if isinstance(lst, list):
        for item in lst:
            if not isinstance(item, dict):
                continue
            name = str(
                item.get("file_name") or item.get("n") or item.get("name") or ""
            ).strip()
            if not name:
                continue
            is_dir = (
                item.get("file_category") == 0
                or item.get("file_category") == "0"
                or bool(item.get("ns"))
                or name.endswith("/")
            )
            if is_dir:
                dirs.append(name.rstrip("/"))
            else:
                files.append(name)
    return {"files": files, "dirs": dirs}


def _add_extract_file(
    client: httpx.Client,
    cookie: str,
    pick_code: str,
    to_pid: str,
    files: list[str],
    dirs: list[str],
) -> dict[str, Any]:
    body: list[tuple[str, str]] = [
        ("pick_code", pick_code),
        ("paths", "文件"),
        ("to_pid", to_pid or "0"),
    ]
    if not files and not dirs:
        body.append(("extract_file[]", ""))
    else:
        for f in files:
            body.append(("extract_file[]", f))
        for d in dirs:
            body.append(("extract_dir[]", d))

    res = client.post(
        "https://webapi.115.com/files/add_extract_file",
        content=encode_form(body),
        headers=form_headers(cookie),
    )
    data = _read_json(res)
    extract_id = data.get("extract_id") or (
        data.get("data", {}).get("extract_id")
        if isinstance(data.get("data"), dict)
        else None
    )
    if (
        data.get("state") is True
        or data.get("state") == 1
        or data.get("errno") == 0
        or extract_id
    ):
        return {"ok": True, "message": "已提交解压到目录"}
    return {"ok": False, "message": human_error(data, "解压到目录失败")}


def _extract_ready_targets(
    client: httpx.Client,
    job: dict[str, Any],
    targets: list[dict[str, str]],
) -> dict[str, Any]:
    cookie = normalize_cookie(str(job.get("cookie") or ""))
    password = str(job.get("password") or "").strip()
    folder_cid = str(job.get("folderCid") or "0")
    extracted = 0
    last_err = ""

    for t in targets:
        push = _push_extract(client, cookie, t["pickCode"], password)
        if not push.get("ok"):
            last_err = str(push.get("message") or "")
            continue

        info = _extract_info_once(client, cookie, t["pickCode"])
        for _ in range(6):
            if info.get("files") or info.get("dirs") or not info.get("message"):
                break
            time.sleep(2.0)
            info = _extract_info_once(client, cookie, t["pickCode"])

        if info.get("message") and not info.get("files") and not info.get("dirs"):
            last_err = str(info["message"])
            continue

        dest_name = _same_name_folder_label(t.get("name") or "", job.get("titleHint"))
        dest = _ensure_same_name_folder(client, cookie, folder_cid, dest_name)
        if not dest.get("ok"):
            last_err = str(dest.get("message") or "")
            continue

        add = _add_extract_file(
            client,
            cookie,
            t["pickCode"],
            str(dest["cid"]),
            list(info.get("files") or []),
            list(info.get("dirs") or []),
        )
        if add.get("ok"):
            extracted += 1
        else:
            last_err = str(add.get("message") or "")

    if extracted > 0:
        return {
            "ok": True,
            "message": f"已提交解压 {extracted} 个压缩包到同名文件夹",
            "extracted": extracted,
        }
    return {"ok": False, "message": last_err or "解压未成功", "extracted": 0}


def run_poll_then_extract(job: dict[str, Any]) -> dict[str, Any]:
    cookie = normalize_cookie(str(job.get("cookie") or ""))
    if not cookie:
        return {"ok": False, "message": "无 Cookie", "extracted": 0}

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        ready = _wait_until_transfer_ready(client, job)
        if not ready.get("ok"):
            return {
                "ok": False,
                "message": str(ready.get("message") or "等待失败"),
                "extracted": 0,
            }
        return _extract_ready_targets(client, job, list(ready.get("targets") or []))


def schedule_deferred_extract(job: dict[str, Any]) -> dict[str, str]:
    job_id = f"{int(time.time() * 1000)}_{secrets.token_hex(3)}"

    def runner() -> None:
        try:
            result = run_poll_then_extract(job)
            log.info(
                "%s %s %s",
                job_id,
                "ok" if result.get("ok") else "fail",
                result.get("message"),
            )
        except Exception:
            log.exception("%s fail", job_id)

    threading.Thread(target=runner, daemon=True, name=f"p115-extract-{job_id}").start()
    log.info(
        "scheduled poll-then-extract %s hashes=%s folderCid=%s",
        job_id,
        len(job.get("infoHashes") or []),
        job.get("folderCid"),
    )
    return {"jobId": job_id, "mode": "poll"}
