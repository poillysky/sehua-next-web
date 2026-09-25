"""115 云解压：转存后轮询离线任务，完成后立即解压。"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlencode

import httpx

from app.p115.client import (
    _read_json,
    encode_form,
    form_headers,
    headers,
    human_error,
    normalize_cookie,
)
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

log = logging.getLogger("p115-extract")

# 有界执行器：突发 autoExtract 时限制并发轮询线程数，避免无界起线程
_extract_pool = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="p115-extract",
)

POLL_MAX_S = 120.0
PUSH_READY_MAX_S = 30.0
EXTRACT_PROGRESS_MAX_S = 180.0
ARCHIVE_RE = re.compile(r"\.(zip|rar|7z)$", re.I)
# 115 云解压不支持分卷；识别后跳过解压、只搬家
MULTIPART_RE = re.compile(
    r"(?:"
    r"\.part\d+\.rar$"
    r"|\.r\d{2,}$"
    r"|\.(?:zip|7z|rar)\.\d{3}$"
    r"|\.z\d{2}$"
    r")",
    re.I,
)
OFFLINE_TASK_MAX_PAGES = 8


def _is_archive_name(name: str) -> bool:
    return bool(ARCHIVE_RE.search(name or ""))


def _is_multipart_archive(name: str) -> bool:
    """分卷压缩包：115 云解压不支持。"""
    n = (name or "").strip()
    if not n:
        return False
    if MULTIPART_RE.search(n):
        return True
    # foo.part1.rar 已被 MULTIPART；纯 .rar 单卷不算
    return False


def _can_cloud_extract(name: str) -> bool:
    return _is_archive_name(name) and not _is_multipart_archive(name)


# 兼容旧名：relocate 与既有脚本按 `p115_extract._is_task_done` 取用
_is_task_done = is_task_done
_is_task_failed = is_task_failed


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
    offset: int = 0,
) -> list[Any]:
    qs = urlencode(
        {
            "aid": "1",
            "cid": folder_cid or "0",
            "o": "user_ptime",
            "asc": "0",
            "offset": str(max(0, int(offset))),
            "show_dir": "1",
            "limit": str(max(1, min(200, int(limit)))),
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


def _list_folder_files_all(
    client: httpx.Client,
    cookie: str,
    folder_cid: str,
    *,
    page_size: int = 200,
    max_pages: int = 20,
) -> list[Any]:
    """分页拉全目录，避免 inbox 内多项时漏压缩包。"""
    out: list[Any] = []
    offset = 0
    for _ in range(max_pages):
        batch = _list_folder_files_once(
            client, cookie, folder_cid, limit=page_size, offset=offset
        )
        if not batch:
            break
        out.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return out


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
        rows = _list_folder_files_all(client, cookie, parent_cid)
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
    """兼容旧调用：默认拉多页。"""
    return _list_offline_tasks_pages(client, cookie)


def _list_offline_tasks_pages(
    client: httpx.Client,
    cookie: str,
    *,
    max_pages: int = OFFLINE_TASK_MAX_PAGES,
) -> list[Any]:
    from app.p115.offline import extract_tasks_from_payload, fetch_task_lists_once

    out: list[Any] = []
    seen_hash: set[str] = set()
    for page in range(1, max(1, max_pages) + 1):
        data = fetch_task_lists_once(client, cookie, page=page)
        batch = extract_tasks_from_payload(data)
        if not batch:
            break
        for t in batch:
            if not isinstance(t, dict):
                continue
            h = str(t.get("info_hash") or t.get("infoHash") or "").lower()
            key = h or f"row:{id(t)}"
            if key in seen_hash:
                continue
            seen_hash.add(key)
            out.append(t)
        page_count = data.get("page_count") or data.get("pageCount")
        try:
            if page_count is not None and page >= int(page_count):
                break
        except (TypeError, ValueError):
            pass
        if len(batch) < 30:
            # 115 每页通常较多；过短视为末页
            break
    return out


def _pick_codes_from_tasks(
    tasks: list[Any],
    info_hashes: list[str],
) -> list[dict[str, str]]:
    """只挑可云解压的压缩包（排除分卷 / 非压缩包）。"""
    want = {h.lower() for h in info_hashes if h}
    out: list[dict[str, str]] = []
    seen_pick: set[str] = set()
    for t in tasks:
        if not isinstance(t, dict):
            continue
        hash_ = str(t.get("info_hash") or t.get("infoHash") or "").lower()
        name = str(t.get("name") or t.get("file_name") or "")
        pick = str(
            t.get("pick_code") or t.get("pickcode") or t.get("pc") or ""
        ).strip()
        if want and hash_ and hash_ not in want:
            continue
        if want and not hash_:
            continue
        if not is_task_done(t):
            continue
        if not pick or pick in seen_pick:
            continue
        if not _can_cloud_extract(name):
            continue
        seen_pick.add(pick)
        out.append({"pickCode": pick, "name": name, "infoHash": hash_})
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
        if pick and _can_cloud_extract(name):
            raw_t = r.get("t") or r.get("te") or r.get("ptime") or 0
            try:
                ts = float(raw_t)
            except (TypeError, ValueError):
                # 115 有时返回 "2026-09-25 12:28" 这类字符串
                ts = 0.0
            archives.append(
                {
                    "pickCode": pick,
                    "name": name,
                    "time": ts,
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
                {"pickCode": a["pickCode"], "name": a["name"]} for a in matched
            ]
    archives.sort(key=lambda a: a["time"], reverse=True)
    return [{"pickCode": a["pickCode"], "name": a["name"]} for a in archives]


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
    budget = max(POLL_MAX_S, min(600.0, 60.0 + 45.0 * max(1, len(hashes))))

    while time.time() - started < budget:
        tasks: list[Any] = []
        try:
            tasks = _list_offline_tasks_pages(client, cookie)
        except Exception as err:
            last_note = str(err) or "拉取离线任务失败"
            time.sleep(POLL_INTERVAL_S)
            continue

        if hashes:
            matched = match_tasks_by_hashes(tasks, hashes)
            if matched:
                phases = task_phases(matched)
                if phases["all_failed"]:
                    return {"ok": False, "message": "离线任务全部失败，无法解压"}

                # 有任意完成即可开始解压已完成的包（不必死等全员）
                from_tasks = _pick_codes_from_tasks(tasks, hashes)
                if from_tasks and (
                    phases["all_terminal"] or len(from_tasks) >= 1
                ):
                    # 仍有下载中：只返回已完成的 targets，调用方可再轮
                    if phases["all_terminal"] or phases["any_done"]:
                        log.info(
                            "transfer ready via tasks hashes=%s archives=%s terminal=%s",
                            hashes,
                            [t["name"] for t in from_tasks],
                            phases["all_terminal"],
                        )
                        return {
                            "ok": True,
                            "targets": from_tasks,
                            "allTerminal": phases["all_terminal"],
                        }

                if not phases["all_terminal"]:
                    last_note = progress_note(phases["pct"])

        try:
            rows = _list_folder_files_all(client, cookie, folder_cid)
            from_folder = _pick_codes_from_folder(rows, job.get("titleHint"))
            if from_folder:
                if not hashes:
                    log.info(
                        "transfer ready via folder archives=%s",
                        [t["name"] for t in from_folder],
                    )
                    return {
                        "ok": True,
                        "targets": from_folder,
                        "allTerminal": True,
                    }

                matched = match_tasks_by_hashes(tasks, hashes)
                phases = task_phases(matched)
                if phases["any_done"]:
                    log.info(
                        "transfer ready via folder+tasks archives=%s",
                        [t["name"] for t in from_folder],
                    )
                    return {
                        "ok": True,
                        "targets": from_folder,
                        "allTerminal": phases["all_terminal"],
                    }
        except Exception:
            pass

        time.sleep(POLL_INTERVAL_S)

    return {
        "ok": False,
        "message": timeout_message(budget, last_note),
    }


def _unzip_status_from_payload(data: Any) -> int:
    """115 进度字段位置不统一：data.unzip_status 或 data.extract_status.unzip_status。"""
    if not isinstance(data, dict):
        return -1
    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    nested = (
        inner.get("extract_status")
        if isinstance(inner.get("extract_status"), dict)
        else {}
    )
    status = (
        nested.get("unzip_status")
        if nested.get("unzip_status") is not None
        else (
            inner.get("unzip_status")
            if inner.get("unzip_status") is not None
            else data.get("unzip_status")
        )
    )
    try:
        return int(status) if status is not None else -1
    except (TypeError, ValueError):
        return -1


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
        return {
            "ok": True,
            "message": "已推送云解压",
            "unzipStatus": _unzip_status_from_payload(data),
        }
    return {"ok": False, "message": human_error(data, "推送云解压失败")}


def _read_push_progress(
    client: httpx.Client,
    cookie: str,
    pick_code: str,
) -> dict[str, Any]:
    qs = urlencode({"pick_code": pick_code})
    res = client.get(
        f"https://webapi.115.com/files/push_extract?{qs}",
        headers=headers(cookie),
    )
    data = _read_json(res)
    status_i = _unzip_status_from_payload(data)
    return {
        "ok": not (
            data.get("state") is False
            or (data.get("errno") and status_i < 0)
        ),
        "unzipStatus": status_i,
        "raw": data,
    }


def _wait_push_ready(
    client: httpx.Client,
    cookie: str,
    pick_code: str,
    *,
    timeout_s: float = PUSH_READY_MAX_S,
    already_status: Any = None,
) -> dict[str, Any]:
    """等 unzip_status=4（就绪）再读目录 / 提交解压。"""
    try:
        if already_status is not None and int(already_status) in {4, 6}:
            return {"ok": True, "unzipStatus": int(already_status)}
    except (TypeError, ValueError):
        pass

    started = time.time()
    last = -1
    while time.time() - started < timeout_s:
        prog = _read_push_progress(client, cookie, pick_code)
        st = int(prog.get("unzipStatus") or -1)
        last = st
        if st in {4, 6}:
            return {"ok": True, "unzipStatus": st}
        time.sleep(1.5)
    return {
        "ok": False,
        "message": f"等待云解压就绪超时（status={last}）",
        "unzipStatus": last,
    }


def _parse_extract_list_items(lst: Any) -> tuple[list[str], list[str]]:
    files: list[str] = []
    dirs: list[str] = []
    if not isinstance(lst, list):
        return files, dirs
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
    return files, dirs


def _extract_info_all(
    client: httpx.Client,
    cookie: str,
    pick_code: str,
) -> dict[str, Any]:
    """翻页拉全压缩包根目录，避免大包漏文件/文件夹。"""
    files: list[str] = []
    dirs: list[str] = []
    seen_f: set[str] = set()
    seen_d: set[str] = set()
    next_marker = ""
    last_err = ""

    for _ in range(50):
        qs = urlencode(
            {
                "pick_code": pick_code,
                "file_name": "",
                "next_marker": next_marker,
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
            last_err = human_error(data, "读取压缩包目录失败（可能尚未就绪）")
            break

        inner = data.get("data") if isinstance(data.get("data"), dict) else {}
        lst = (
            inner.get("list")
            or data.get("list")
            or inner.get("files")
            or data.get("files")
            or []
        )
        page_files, page_dirs = _parse_extract_list_items(lst)
        for f in page_files:
            if f not in seen_f:
                seen_f.add(f)
                files.append(f)
        for d in page_dirs:
            if d not in seen_d:
                seen_d.add(d)
                dirs.append(d)

        nxt = str(
            inner.get("next_marker")
            or data.get("next_marker")
            or ""
        ).strip()
        if not nxt or nxt == next_marker:
            return {"files": files, "dirs": dirs}
        next_marker = nxt

    if files or dirs:
        return {"files": files, "dirs": dirs}
    return {
        "files": [],
        "dirs": [],
        "message": last_err or "读取压缩包目录失败（可能尚未就绪）",
    }


def _extract_info_once(
    client: httpx.Client,
    cookie: str,
    pick_code: str,
) -> dict[str, Any]:
    """兼容旧名：等价于全量翻页。"""
    return _extract_info_all(client, cookie, pick_code)


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
        # 空列表兜底：请求解压全部（115 约定）
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
        return {
            "ok": True,
            "message": "已提交解压到目录",
            "extractId": str(extract_id) if extract_id is not None else "",
        }
    return {"ok": False, "message": human_error(data, "解压到目录失败")}


def _wait_extract_progress(
    client: httpx.Client,
    cookie: str,
    extract_id: str,
    *,
    timeout_s: float = 45.0,
) -> dict[str, Any]:
    """轮询「解压到目录」进度。字段兼容多层嵌套；已完成/无 id 立即返回。"""
    if not extract_id:
        return {"ok": True, "message": "无 extract_id", "percent": None}

    started = time.time()
    last_pct = 0.0
    while time.time() - started < timeout_s:
        qs = urlencode({"extract_id": extract_id})
        try:
            res = client.get(
                f"https://webapi.115.com/files/add_extract?{qs}",
                headers=headers(cookie),
            )
            data = _read_json(res)
        except Exception as err:
            log.debug("extract progress poll err: %s", err)
            time.sleep(1.5)
            continue

        inner = data.get("data") if isinstance(data.get("data"), dict) else {}
        nested = (
            inner.get("extract_status")
            if isinstance(inner.get("extract_status"), dict)
            else {}
        )
        # percent 可能在 data / extract_status / 顶层
        raw_pct = (
            nested.get("progress")
            if nested.get("progress") is not None
            else (
                nested.get("percent")
                if nested.get("percent") is not None
                else (
                    inner.get("percent")
                    if inner.get("percent") is not None
                    else (
                        inner.get("percentDone")
                        if inner.get("percentDone") is not None
                        else data.get("percent")
                    )
                )
            )
        )
        try:
            pct = float(raw_pct) if raw_pct is not None else 0.0
        except (TypeError, ValueError):
            pct = 0.0
        last_pct = pct

        unzip = _unzip_status_from_payload(data)
        # 100% 或 unzip_status 已成功 → 完成
        if pct >= 100 or unzip in {4, 6}:
            return {"ok": True, "message": "解压完成", "percent": pct or 100.0}
        # 接口直接成功且无进度字段：视为已受理完成（避免空转）
        if (
            (data.get("state") is True or data.get("state") == 1)
            and raw_pct is None
            and unzip < 0
        ):
            return {"ok": True, "message": "解压已受理", "percent": None}

        time.sleep(1.5)

    # 超时不当成整单失败：文件往往已在解；由调用方决定是否搬家
    return {
        "ok": True,
        "message": f"解压进度未刷到 100%（末次 {int(last_pct)}%），继续",
        "percent": last_pct,
        "softTimeout": True,
    }


def extract_one_archive(
    client: httpx.Client,
    job: dict[str, Any],
    target: dict[str, str],
) -> dict[str, Any]:
    """解压单个压缩包到同名夹，并等到进度完成（或可接受的短等）。"""
    cookie = normalize_cookie(str(job.get("cookie") or ""))
    password = str(job.get("password") or "").strip()
    folder_cid = str(job.get("folderCid") or "0")
    name = str(target.get("name") or "")
    pick = str(target.get("pickCode") or "").strip()

    if not pick:
        return {"ok": False, "message": "无 pick_code", "folderCid": ""}
    if _is_multipart_archive(name):
        return {
            "ok": False,
            "message": f"分卷压缩包不支持云解压，已跳过：{name}",
            "skipped": True,
            "folderCid": "",
        }
    if not _can_cloud_extract(name) and name:
        return {
            "ok": False,
            "message": f"非可云解压文件，已跳过：{name}",
            "skipped": True,
            "folderCid": "",
        }

    push = _push_extract(client, cookie, pick, password)
    if not push.get("ok"):
        return {"ok": False, "message": str(push.get("message") or ""), "folderCid": ""}

    ready = _wait_push_ready(
        client,
        cookie,
        pick,
        already_status=push.get("unzipStatus"),
        timeout_s=PUSH_READY_MAX_S,
    )
    if not ready.get("ok"):
        return {
            "ok": False,
            "message": str(ready.get("message") or "云解压未就绪"),
            "folderCid": "",
        }

    info: dict[str, Any] = {"files": [], "dirs": []}
    for _ in range(8):
        info = _extract_info_all(client, cookie, pick)
        if info.get("files") or info.get("dirs") or not info.get("message"):
            break
        time.sleep(2.0)

    files = list(info.get("files") or [])
    dirs = list(info.get("dirs") or [])
    # 列表仍空：走「解压全部」兜底，避免漏
    if not files and not dirs and info.get("message"):
        log.warning(
            "extract_info empty for %s (%s); fallback extract-all",
            name,
            info.get("message"),
        )

    dest_name = _same_name_folder_label(name, job.get("titleHint"))
    dest = _ensure_same_name_folder(client, cookie, folder_cid, dest_name)
    if not dest.get("ok"):
        return {
            "ok": False,
            "message": str(dest.get("message") or ""),
            "folderCid": "",
        }

    add = _add_extract_file(
        client,
        cookie,
        pick,
        str(dest["cid"]),
        files,
        dirs,
    )
    if not add.get("ok"):
        return {
            "ok": False,
            "message": str(add.get("message") or ""),
            "folderCid": str(dest["cid"]),
        }

    prog = _wait_extract_progress(
        client, cookie, str(add.get("extractId") or "")
    )
    if not prog.get("ok"):
        # 已提交；进度超时仍返回 folder，便于 relocate 搬走同名夹
        log.warning(
            "extract progress incomplete %s: %s",
            name,
            prog.get("message"),
        )
        return {
            "ok": True,
            "message": f"已提交解压（进度未完成：{prog.get('message')}）",
            "folderCid": str(dest["cid"]),
            "folderName": dest_name,
            "partial": True,
        }

    return {
        "ok": True,
        "message": f"已解压到「{dest_name}」",
        "folderCid": str(dest["cid"]),
        "folderName": dest_name,
        "files": len(files),
        "dirs": len(dirs),
    }


def _extract_ready_targets(
    client: httpx.Client,
    job: dict[str, Any],
    targets: list[dict[str, str]],
) -> dict[str, Any]:
    extracted = 0
    skipped = 0
    last_err = ""
    folder_cids: list[str] = []

    for t in targets:
        one = extract_one_archive(client, job, t)
        if one.get("skipped"):
            skipped += 1
            last_err = str(one.get("message") or "")
            continue
        if one.get("ok"):
            extracted += 1
            cid = str(one.get("folderCid") or "").strip()
            if cid:
                folder_cids.append(cid)
        else:
            last_err = str(one.get("message") or "")

    if extracted > 0:
        return {
            "ok": True,
            "message": f"已解压 {extracted} 个压缩包"
            + (f"，跳过 {skipped} 个" if skipped else ""),
            "extracted": extracted,
            "skipped": skipped,
            "folderCids": folder_cids,
        }
    return {
        "ok": False,
        "message": last_err or "解压未成功",
        "extracted": 0,
        "skipped": skipped,
        "folderCids": folder_cids,
    }


def run_poll_then_extract(job: dict[str, Any]) -> dict[str, Any]:
    cookie = normalize_cookie(str(job.get("cookie") or ""))
    if not cookie:
        return {"ok": False, "message": "无 Cookie", "extracted": 0}

    hashes = [
        h.lower()
        for h in (job.get("infoHashes") or [])
        if isinstance(h, str) and h
    ]
    extracted_total = 0
    folder_cids: list[str] = []
    last_err = ""
    pending = set(hashes)
    started = time.time()
    budget = max(POLL_MAX_S, min(900.0, 90.0 + 60.0 * max(1, len(hashes))))
    seen_picks: set[str] = set()

    with httpx.Client(
        timeout=30.0, follow_redirects=True, trust_env=False
    ) as client:
        # 无 hash：退回旧的一次就绪逻辑
        if not pending:
            ready = _wait_until_transfer_ready(client, job)
            if not ready.get("ok"):
                return {
                    "ok": False,
                    "message": str(ready.get("message") or "等待失败"),
                    "extracted": 0,
                }
            result = _extract_ready_targets(
                client, job, list(ready.get("targets") or [])
            )
            return result

        while pending and time.time() - started < budget:
            try:
                tasks = _list_offline_tasks_pages(client, cookie)
            except Exception as err:
                last_err = str(err) or "拉取离线任务失败"
                time.sleep(POLL_INTERVAL_S)
                continue

            matched = match_tasks_by_hashes(tasks, list(pending))
            for t in matched:
                if is_task_failed(t):
                    h = str(t.get("info_hash") or t.get("infoHash") or "").lower()
                    pending.discard(h)
                    continue
                if not is_task_done(t):
                    continue
                h = str(t.get("info_hash") or t.get("infoHash") or "").lower()
                name = str(t.get("name") or t.get("file_name") or "")
                pick = str(
                    t.get("pick_code") or t.get("pickcode") or t.get("pc") or ""
                ).strip()
                if h:
                    pending.discard(h)
                if not _can_cloud_extract(name):
                    if _is_multipart_archive(name):
                        log.info("skip multipart cloud-extract: %s", name)
                    continue
                if not pick or pick in seen_picks:
                    continue
                seen_picks.add(pick)
                one = extract_one_archive(
                    client,
                    job,
                    {"pickCode": pick, "name": name, "infoHash": h},
                )
                if one.get("ok"):
                    extracted_total += 1
                    cid = str(one.get("folderCid") or "").strip()
                    if cid:
                        folder_cids.append(cid)
                elif not one.get("skipped"):
                    last_err = str(one.get("message") or "")

            if pending:
                time.sleep(POLL_INTERVAL_S)

        # 兜底：inbox 内尚未覆盖的压缩包
        if extracted_total == 0 or pending:
            rows = _list_folder_files_all(
                client, cookie, str(job.get("folderCid") or "0")
            )
            for t in _pick_codes_from_folder(rows, job.get("titleHint")):
                pick = t["pickCode"]
                if pick in seen_picks:
                    continue
                seen_picks.add(pick)
                one = extract_one_archive(client, job, t)
                if one.get("ok"):
                    extracted_total += 1
                    cid = str(one.get("folderCid") or "").strip()
                    if cid:
                        folder_cids.append(cid)

    if extracted_total > 0:
        return {
            "ok": True,
            "message": f"已解压 {extracted_total} 个压缩包",
            "extracted": extracted_total,
            "folderCids": folder_cids,
            "pending": list(pending),
        }
    return {
        "ok": False,
        "message": last_err
        or (
            timeout_message(budget, "仍有任务未完成")
            if pending
            else "解压未成功"
        ),
        "extracted": 0,
        "folderCids": folder_cids,
        "pending": list(pending),
    }


def schedule_deferred_extract(job: dict[str, Any]) -> dict[str, str]:
    job_id = submit_deferred(
        _extract_pool, log=log, job=job, runner=run_poll_then_extract
    )
    log.info(
        "scheduled poll-then-extract %s hashes=%s folderCid=%s",
        job_id,
        len(job.get("infoHashes") or []),
        job.get("folderCid"),
    )
    return {"jobId": job_id, "mode": "poll"}
