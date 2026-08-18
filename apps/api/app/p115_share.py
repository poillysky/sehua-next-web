"""115 分享链接转存（share/snap + share/receive）。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlencode

import httpx

from .p115_client import (
    encode_form,
    extract_uid,
    form_headers,
    headers,
    human_error,
    normalize_cookie,
)

SHARE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(115cdn\.com|115\.com)/s/([A-Za-z0-9]+)(?:\?([^\s#]*))?",
    re.I,
)


def _read_json(res: httpx.Response) -> Any:
    try:
        return res.json()
    except Exception:
        text = (res.text or "")[:240]
        return {"state": False, "error": text or f"HTTP {res.status_code}"}


def is_115_share_link(link: str | None) -> bool:
    lower = (link or "").strip().lower()
    return "115cdn.com/s/" in lower or "115.com/s/" in lower


def _query_param(query: str, key: str) -> str:
    if not query:
        return ""
    q = query[1:] if query.startswith("?") else query
    try:
        params = parse_qs(q, keep_blank_values=True)
        for k in (key, key.upper(), key.lower()):
            vals = params.get(k)
            if vals and vals[0]:
                return str(vals[0]).strip()
    except Exception:
        return ""
    return ""


def parse_115_share_url(
    link: str,
    fallback_password: str = "",
) -> dict[str, str] | None:
    raw = (link or "").strip()
    if not raw:
        return None
    m = SHARE_URL_RE.search(raw)
    if not m:
        return None
    host = (m.group(1) or "115cdn.com").lower()
    share_code = (m.group(2) or "").strip()
    if not share_code:
        return None
    receive_code = (
        _query_param(m.group(3) or "", "password")
        or _query_param(m.group(3) or "", "pwd")
        or _query_param(m.group(3) or "", "passwd")
        or (fallback_password or "").strip()
    )
    url = (
        f"https://{host}/s/{share_code}?password={receive_code}"
        if receive_code
        else f"https://{host}/s/{share_code}"
    )
    return {
        "shareCode": share_code,
        "receiveCode": receive_code,
        "host": host,
        "url": url,
    }


def _share_referer(share: dict[str, str]) -> str:
    return (
        f"https://{share['host']}/s/{share['shareCode']}"
        f"?password={share.get('receiveCode') or ''}&"
    )


def _fetch_share_snap(
    client: httpx.Client,
    cookie: str,
    share: dict[str, str],
    cid: str = "0",
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    qs = urlencode(
        {
            "share_code": share["shareCode"],
            "receive_code": share.get("receiveCode") or "",
            "cid": cid,
            "limit": str(limit),
            "offset": str(offset),
            "format": "json",
        }
    )
    try:
        res = client.get(
            f"https://webapi.115.com/share/snap?{qs}",
            headers=headers(cookie, _share_referer(share)),
        )
        data = _read_json(res)
        if not data.get("state"):
            return {
                "ok": False,
                "message": human_error(data, "读取分享内容失败"),
                "list": [],
                "count": 0,
            }
        inner = data.get("data") if isinstance(data.get("data"), dict) else {}
        lst = inner.get("list") if isinstance(inner.get("list"), list) else []
        count = int(inner.get("count") if inner.get("count") is not None else len(lst)) or len(
            lst
        )
        return {"ok": True, "message": "ok", "list": lst, "count": count}
    except Exception as err:
        return {
            "ok": False,
            "message": str(err) or "读取分享内容失败",
            "list": [],
            "count": 0,
        }


def _list_all_share_root_items(
    client: httpx.Client,
    cookie: str,
    share: dict[str, str],
) -> dict[str, Any]:
    file_ids: list[str] = []
    offset = 0
    limit = 100
    total = float("inf")

    while offset < total and offset < 2000:
        page = _fetch_share_snap(client, cookie, share, "0", offset, limit)
        if not page.get("ok"):
            return {"ok": False, "message": page.get("message"), "fileIds": []}
        total = page.get("count") or len(page.get("list") or [])
        for item in page.get("list") or []:
            if not isinstance(item, dict):
                continue
            fid = item.get("fid")
            if fid is None:
                fid = item.get("file_id")
            if fid is None:
                fid = item.get("cid")
            id_str = str(fid or "").strip()
            if id_str and id_str != "0":
                file_ids.append(id_str)
        lst = page.get("list") or []
        if not lst:
            break
        offset += len(lst)
        if len(lst) < limit:
            break

    unique = list(dict.fromkeys(file_ids))
    if not unique:
        return {
            "ok": False,
            "message": "分享内容为空或无法读取文件列表",
            "fileIds": [],
        }
    return {"ok": True, "message": "ok", "fileIds": unique}


def _post_share_receive(
    client: httpx.Client,
    cookie: str,
    share: dict[str, str],
    file_ids: list[str],
    folder_cid: str,
) -> dict[str, Any]:
    uid = extract_uid(cookie)
    if not uid:
        return {"ok": False, "message": "Cookie 缺少 UID"}

    body: list[tuple[str, str]] = [
        ("user_id", uid),
        ("share_code", share["shareCode"]),
        ("receive_code", share.get("receiveCode") or ""),
        ("file_id", ",".join(str(x) for x in file_ids)),
    ]
    if folder_cid and str(folder_cid) != "0":
        body.append(("cid", str(folder_cid)))

    try:
        res = client.post(
            "https://webapi.115.com/share/receive",
            content=encode_form(body),
            headers=form_headers(cookie, _share_referer(share)),
        )
        data = _read_json(res)
        if data.get("state"):
            return {"ok": True, "message": "分享已转存到网盘"}
        err = human_error(data, "分享转存失败")
        if re.search(r"无需重复接收|已经接收|已接收", err):
            return {"ok": True, "message": "分享已在网盘中（无需重复接收）"}
        return {"ok": False, "message": err}
    except Exception as err:
        return {"ok": False, "message": str(err) or "分享转存请求失败"}


def receive_115_shares(
    cookie_raw: str,
    urls: list[str],
    folder_cid: str = "0",
    fallback_password: str = "",
) -> dict[str, Any]:
    cookie = normalize_cookie(cookie_raw)
    if not cookie:
        return {"ok": False, "message": "Cookie 为空", "received": 0, "failed": []}

    failed: list[dict[str, str]] = []
    received = 0
    seen: set[str] = set()

    with httpx.Client(
        timeout=30.0, follow_redirects=True, trust_env=False
    ) as client:
        for raw in urls:
            share = parse_115_share_url(raw, fallback_password)
            if not share:
                failed.append({"url": raw, "message": "不是有效的 115 分享链接"})
                continue
            key = f"{share['host']}/{share['shareCode']}".lower()
            if key in seen:
                continue
            seen.add(key)

            listed = _list_all_share_root_items(client, cookie, share)
            if not listed.get("ok"):
                failed.append(
                    {
                        "url": share["url"],
                        "message": str(listed.get("message") or "读取失败"),
                    }
                )
                continue

            result = _post_share_receive(
                client,
                cookie,
                share,
                listed["fileIds"],
                folder_cid or "0",
            )
            if result.get("ok"):
                received += 1
            else:
                failed.append(
                    {
                        "url": share["url"],
                        "message": str(result.get("message") or "转存失败"),
                    }
                )

    if received > 0 and not failed:
        return {
            "ok": True,
            "message": f"已转存 {received} 个 115 分享到网盘",
            "received": received,
            "failed": failed,
        }
    if received > 0:
        return {
            "ok": True,
            "message": f"转存完成：成功 {received} · 失败 {len(failed)}",
            "received": received,
            "failed": failed,
        }
    return {
        "ok": False,
        "message": (failed[0]["message"] if failed else "分享转存失败"),
        "received": 0,
        "failed": failed,
    }
