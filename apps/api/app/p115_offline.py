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
    human_error,
    require_cookie_parts,
)

BATCH_LIMIT = 15
REQUEST_GAP_S = 0.4

_LINK_RE = re.compile(r"^(magnet:|ed2k://|https?://|ftp://)", re.I)


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
