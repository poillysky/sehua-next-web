"""115 离线云下载：lixian 优先，clouddownload 回退。"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

from .p115_client import (
    SOFT_OK_ERRCODES,
    encode_form,
    errcode_of,
    extract_uid,
    fetch_offline_sign,
    form_headers,
    headers,
    human_error,
    require_cookie_parts,
)

BATCH_LIMIT = 15
REQUEST_GAP_S = 0.4

_LINK_RE = re.compile(r"^(magnet:|ed2k://|https?://|ftp://)", re.I)

# 对齐 p115client / 开放平台 clear_task flag
CLEAR_MODE_FLAGS: dict[str, int] = {
    "done": 0,
    "all": 1,
    "failed": 2,
}

_STATUS_LABEL: dict[int, str] = {
    -1: "失败",
    0: "排队",
    1: "下载中",
    2: "完成",
}


def _read_json(res: httpx.Response) -> Any:
    try:
        return res.json()
    except Exception:
        text = (res.text or "")[:240]
        return {"state": False, "error": text or f"HTTP {res.status_code}"}


def collect_info_hashes(raw: Any) -> list[str]:
    out: set[str] = set()

    def dig(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, str) and re.fullmatch(r"[a-f0-9]{32,40}", node, re.I):
            out.add(node.lower())
            return
        if isinstance(node, list):
            for item in node:
                dig(item)
            return
        if not isinstance(node, dict):
            return
        h = node.get("info_hash") or node.get("infoHash") or node.get("hash")
        if isinstance(h, str) and len(h) >= 32:
            out.add(h.lower())
        if node.get("result") is not None:
            dig(node["result"])
        if node.get("data") is not None:
            dig(node["data"])

    dig(raw)
    return list(out)


def _is_add_ok(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    code = errcode_of(data)
    # 10008 任务已存在：对用户等同成功（避免重复点「转存」报错）
    if code in SOFT_OK_ERRCODES and code != 0:
        return True
    if data.get("state") is True or data.get("state") == 1:
        return True
    if code == 0:
        return True
    if data.get("info_hash") or (
        isinstance(data.get("data"), dict) and data["data"].get("info_hash")
    ):
        return True
    result = data.get("result")
    if isinstance(result, list):
        for row in result:
            if not isinstance(row, dict):
                continue
            row_code = errcode_of(row)
            if row_code in SOFT_OK_ERRCODES and row_code != 0:
                return True
            if (
                row.get("state") is True
                or row_code == 0
                or row.get("info_hash")
                or (not row.get("error_msg") and not row.get("error"))
            ):
                return True
    return False


def _add_via_lixian(
    client: httpx.Client,
    cookie: str,
    urls: list[str],
    folder_cid: str,
    sign: dict[str, Any],
) -> dict[str, Any]:
    uid = extract_uid(cookie)
    body: list[tuple[str, str]] = [
        ("uid", uid),
        ("sign", str(sign.get("sign") or "")),
        ("time", str(sign.get("time") or "")),
        ("wp_path_id", str(folder_cid or "0")),
    ]
    multi = len(urls) > 1
    endpoint = (
        "https://115.com/web/lixian/?ct=lixian&ac=add_task_urls"
        if multi
        else "https://115.com/web/lixian/?ct=lixian&ac=add_task_url"
    )
    if multi:
        for i, u in enumerate(urls):
            body.append((f"url[{i}]", str(u)))
    else:
        body.append(("url", str(urls[0])))

    res = client.post(
        endpoint,
        content=encode_form(body),
        headers=form_headers(cookie, "https://115.com/web/lixian/"),
    )
    data = _read_json(res)

    if _is_add_ok(data):
        per_url: list[dict[str, str]] = []
        result = data.get("result") if isinstance(data, dict) else None
        if isinstance(result, list):
            for i, row in enumerate(result):
                if not isinstance(row, dict):
                    continue
                u = str(row.get("url") or (urls[i] if i < len(urls) else "") or "")
                row_code = errcode_of(row)
                # 已存在不算失败
                if row_code in SOFT_OK_ERRCODES and row_code != 0:
                    continue
                if row.get("error_msg") or (
                    row.get("state") is False and not row.get("info_hash")
                ):
                    per_url.append(
                        {"url": u, "message": human_error(row, "添加失败")}
                    )
        if per_url and len(per_url) >= len(urls):
            return {
                "ok": False,
                "message": per_url[0]["message"],
                "raw": data,
                "perUrl": per_url,
            }
        code = errcode_of(data)
        if code == 10008:
            ok_msg = "云下载任务已存在"
        elif multi:
            ok_msg = f"已提交 {len(urls)} 条到云下载"
        else:
            ok_msg = "已加入云下载"
        return {
            "ok": True,
            "message": ok_msg,
            "raw": data,
            "perUrl": per_url,
        }

    return {
        "ok": False,
        "message": human_error(data, "lixian 添加失败"),
        "raw": data,
    }


def _add_via_clouddownload(
    client: httpx.Client,
    cookie: str,
    urls: list[str],
    folder_cid: str,
) -> dict[str, Any]:
    multi = len(urls) > 1
    body: list[tuple[str, str]] = [
        ("ac", "add_task_urls" if multi else "add_task_url"),
        ("wp_path_id", str(folder_cid or "0")),
    ]
    if multi:
        for i, u in enumerate(urls):
            body.append((f"url[{i}]", str(u)))
    else:
        body.append(("url", str(urls[0])))

    res = client.post(
        "https://clouddownload.115.com/web/",
        content=encode_form(body),
        headers=form_headers(cookie, "https://115.com/"),
    )
    data = _read_json(res)

    if _is_add_ok(data):
        return {
            "ok": True,
            "message": f"已提交 {len(urls)} 条到云下载" if multi else "已加入云下载",
            "raw": data,
        }
    return {
        "ok": False,
        "message": human_error(data, "clouddownload 添加失败"),
        "raw": data,
    }


def _add_url_chunk(
    client: httpx.Client,
    cookie: str,
    urls: list[str],
    folder_cid: str,
    sign: dict[str, Any] | None,
) -> dict[str, Any]:
    if sign:
        primary = _add_via_lixian(client, cookie, urls, folder_cid, sign)
        if primary.get("ok"):
            return primary
        msg = str(primary.get("message") or "")
        if re.search(r"签名|Cookie|过期|验证码|911|配额|空间不足", msg, re.I):
            return primary
    return _add_via_clouddownload(client, cookie, urls, folder_cid)


def add_offline_tasks(
    cookie: str,
    urls: list[str],
    folder_cid: str = "0",
) -> dict[str, Any]:
    bad = require_cookie_parts(cookie)
    if bad:
        return {"ok": False, "message": bad, "added": 0, "failed": []}

    cleaned: list[str] = []
    seen: set[str] = set()
    for u in urls:
        s = (u or "").strip()
        if not s or not _LINK_RE.match(s):
            continue
        low = s.lower()
        if "115cdn.com/s/" in low or "115.com/s/" in low:
            continue
        if s in seen:
            continue
        seen.add(s)
        cleaned.append(s)

    if not cleaned:
        return {
            "ok": False,
            "message": "没有可转存的磁力/ED2K/HTTP 链接",
            "added": 0,
            "failed": [],
        }

    cid = (folder_cid or "0").strip() or "0"
    sign_res = fetch_offline_sign(cookie)
    sign = sign_res if sign_res.get("ok") else None
    if not sign:
        sign_msg = str(sign_res.get("message") or "")
        # Cookie / 验证码类：回退 clouddownload 也过不了，直接给出可操作提示
        if re.search(r"Cookie|过期|签名|验证码|911|登录|凭证", sign_msg, re.I):
            return {
                "ok": False,
                "message": sign_msg
                or "获取离线签名失败（Cookie 可能过期，请到设置重新粘贴）",
                "added": 0,
                "failed": [],
                "infoHashes": [],
            }

    failed: list[dict[str, str]] = []
    info_hashes: set[str] = set()
    added = 0

    with httpx.Client(
        timeout=30.0, follow_redirects=True, trust_env=False
    ) as client:
        for i in range(0, len(cleaned), BATCH_LIMIT):
            chunk = cleaned[i : i + BATCH_LIMIT]
            try:
                attempt = _add_url_chunk(client, cookie, chunk, cid, sign)
                if attempt.get("ok"):
                    for h in collect_info_hashes(attempt.get("raw")):
                        info_hashes.add(h)
                    chunk_failed = attempt.get("perUrl") or []
                    added += len(chunk) - len(chunk_failed)
                    failed.extend(chunk_failed)
                elif len(chunk) == 1:
                    failed.append(
                        {
                            "url": chunk[0],
                            "message": str(attempt.get("message") or "添加失败"),
                        }
                    )
                else:
                    for url in chunk:
                        try:
                            one = _add_url_chunk(client, cookie, [url], cid, sign)
                            if one.get("ok"):
                                added += 1
                                for h in collect_info_hashes(one.get("raw")):
                                    info_hashes.add(h)
                            else:
                                failed.append(
                                    {
                                        "url": url,
                                        "message": str(
                                            one.get("message") or "添加失败"
                                        ),
                                    }
                                )
                        except Exception as err:
                            failed.append(
                                {"url": url, "message": str(err) or "请求失败"}
                            )
                        time.sleep(REQUEST_GAP_S)
            except Exception as err:
                for url in chunk:
                    failed.append(
                        {"url": url, "message": str(err) or "请求失败"}
                    )

            if i + BATCH_LIMIT < len(cleaned):
                time.sleep(REQUEST_GAP_S)

    hashes = list(info_hashes)

    if added > 0 and not failed:
        soft = any(
            "已存在" in str(f.get("message") or "") for f in (failed or [])
        )
        return {
            "ok": True,
            "message": (
                f"已转存 {added} 条到 115 云下载"
                if not soft
                else f"已提交 {added} 条（部分任务已存在）"
            ),
            "added": added,
            "failed": failed,
            "infoHashes": hashes,
        }
    if added > 0:
        example = f"（例：{failed[0]['message']}）" if failed else ""
        return {
            "ok": True,
            "message": f"转存完成：成功 {added} · 失败 {len(failed)}{example}",
            "added": added,
            "failed": failed,
            "infoHashes": hashes,
        }

    msg = (
        (failed[0]["message"] if failed else None)
        or (sign_res.get("message") if not sign_res.get("ok") else None)
        or "转存失败"
    )
    return {
        "ok": False,
        "message": str(msg),
        "added": 0,
        "failed": failed,
        "infoHashes": hashes,
    }


def _as_int(value: Any) -> int | None:
    if value is None or value is False:
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None or value is False:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def extract_tasks_from_payload(data: Any) -> list[Any]:
    """Parse tasks array from task_lists / space-like payloads."""
    if not isinstance(data, dict):
        return []
    tasks = data.get("tasks") or (
        data.get("data", {}).get("tasks")
        if isinstance(data.get("data"), dict)
        else None
    ) or data.get("list") or []
    return tasks if isinstance(tasks, list) else []


def fetch_task_lists_once(
    client: httpx.Client,
    cookie: str,
    page: int = 1,
) -> dict[str, Any]:
    """GET web lixian task_lists (same endpoint as extract / quota)."""
    page_n = max(1, int(page or 1))
    res = client.get(
        f"https://115.com/web/lixian/?ct=lixian&ac=task_lists&page={page_n}",
        headers=headers(cookie, "https://115.com/web/lixian/"),
    )
    data = _read_json(res)
    return data if isinstance(data, dict) else {"state": False, "error": "响应异常"}


def normalize_offline_task(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    status = _as_int(raw.get("status"))
    if status is None:
        status = -99
    percent = _as_float(raw.get("percentDone") or raw.get("percent_done"))
    if percent is None:
        percent = 0.0
    err = ""
    for k in ("error_msg", "error", "message", "msg", "errMsg"):
        v = raw.get(k)
        if v:
            err = str(v).strip()
            break
    # 部分失败任务把原因放在 move / del_path 等字段旁的文案里
    if not err and status is not None and status < 0:
        for k in ("move", "del_path", "file_id"):
            v = raw.get(k)
            if isinstance(v, str) and v.strip() and not v.strip().isdigit():
                err = v.strip()
                break
    label = _STATUS_LABEL.get(status) if status is not None else None
    if not label:
        if status is not None and status < 0:
            label = "失败"
        else:
            label = f"状态 {status}"
    info_hash = str(raw.get("info_hash") or raw.get("infoHash") or "").strip()
    return {
        "name": str(raw.get("name") or raw.get("file_name") or "").strip() or "未命名任务",
        "status": status,
        "statusLabel": label,
        "percent": max(0.0, min(100.0, percent)),
        "error": err,
        "infoHash": info_hash,
        "size": _as_int(raw.get("size")),
        "addTime": _as_int(raw.get("add_time") or raw.get("addTime")),
        "updateTime": _as_int(raw.get("last_update") or raw.get("update_time")),
        "fileId": str(raw.get("file_id") or raw.get("fileId") or "").strip() or None,
    }


def list_offline_tasks(cookie: str, page: int = 1) -> dict[str, Any]:
    """List cloud-download (offline) tasks + quota snapshot."""
    bad = require_cookie_parts(cookie)
    if bad:
        return {"ok": False, "message": bad, "tasks": []}

    try:
        with httpx.Client(
            timeout=15.0, follow_redirects=True, trust_env=False
        ) as client:
            data = fetch_task_lists_once(client, cookie, page)
    except Exception as e:
        return {
            "ok": False,
            "message": str(e) or "获取离线任务失败",
            "tasks": [],
        }

    if data.get("state") is False or (
        data.get("errno") and not extract_tasks_from_payload(data)
    ):
        return {
            "ok": False,
            "message": human_error(data, "获取离线任务失败（Cookie 可能过期）"),
            "tasks": [],
        }

    tasks: list[dict[str, Any]] = []
    for row in extract_tasks_from_payload(data):
        item = normalize_offline_task(row)
        if item:
            tasks.append(item)

    return {
        "ok": True,
        "message": "ok",
        "tasks": tasks,
        "page": _as_int(data.get("page")) or max(1, int(page or 1)),
        "pageCount": _as_int(data.get("page_count") or data.get("pageCount")),
        "count": _as_int(data.get("count")),
        "quota": _as_int(data.get("quota")),
        "quotaTotal": _as_int(data.get("total") or data.get("quota_total")),
    }


def _is_clear_ok(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("state") is True or data.get("state") == 1:
        return True
    code = errcode_of(data)
    if code == 0 and data.get("state") is not False:
        return True
    return False


def _clear_via_lixian(
    client: httpx.Client,
    cookie: str,
    flag: int,
) -> dict[str, Any]:
    res = client.post(
        "https://115.com/web/lixian/?ct=lixian&ac=task_clear",
        content=encode_form([("flag", flag)]),
        headers=form_headers(cookie, "https://115.com/web/lixian/"),
    )
    data = _read_json(res)
    if _is_clear_ok(data):
        return {"ok": True, "message": "已清理", "raw": data}
    return {
        "ok": False,
        "message": human_error(data, "lixian 清理失败"),
        "raw": data,
    }


def _clear_via_clouddownload(
    client: httpx.Client,
    cookie: str,
    flag: int,
) -> dict[str, Any]:
    res = client.post(
        "https://clouddownload.115.com/?ac=task_clear",
        content=encode_form([("flag", flag)]),
        headers=form_headers(cookie, "https://115.com/web/lixian/"),
    )
    data = _read_json(res)
    if _is_clear_ok(data):
        return {"ok": True, "message": "已清理", "raw": data}
    return {
        "ok": False,
        "message": human_error(data, "clouddownload 清理失败"),
        "raw": data,
    }


def clear_offline_tasks(cookie: str, mode: str = "done") -> dict[str, Any]:
    """Clear offline tasks. mode: done | failed | all (no source-file delete)."""
    bad = require_cookie_parts(cookie)
    if bad:
        return {"ok": False, "message": bad}

    key = (mode or "done").strip().lower()
    if key not in CLEAR_MODE_FLAGS:
        return {
            "ok": False,
            "message": "清理类型无效（支持 done / failed / all）",
        }
    flag = CLEAR_MODE_FLAGS[key]
    label = {"done": "已完成", "failed": "已失败", "all": "全部"}.get(key, key)

    try:
        with httpx.Client(
            timeout=20.0, follow_redirects=True, trust_env=False
        ) as client:
            primary = _clear_via_lixian(client, cookie, flag)
            if primary.get("ok"):
                primary["message"] = f"已清理{label}任务"
                primary["mode"] = key
                primary["flag"] = flag
                return primary
            msg = str(primary.get("message") or "")
            if re.search(r"Cookie|过期|验证码|911|登录|凭证", msg, re.I):
                primary["mode"] = key
                primary["flag"] = flag
                return primary
            fallback = _clear_via_clouddownload(client, cookie, flag)
            if fallback.get("ok"):
                fallback["message"] = f"已清理{label}任务"
            fallback["mode"] = key
            fallback["flag"] = flag
            return fallback
    except Exception as e:
        return {
            "ok": False,
            "message": str(e) or "清理离线任务失败",
            "mode": key,
            "flag": flag,
        }
