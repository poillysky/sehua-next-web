"""115 webapi helpers — validate cookie / list folders (aligned with sehua-search)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

import httpx

ERRCODE_HINT: dict[int, str] = {
    911: "需要验证码，请先在 115 网页「云下载」通过验证后再试",
    10008: "云下载任务已存在（可到 115 云下载查看）",
    10004: "链接无效或不支持（请检查磁力/ED2K 是否完整）",
    10007: "115 空间不足，请清理后再转存",
    10009: "离线任务配额已满，请到 115 清理云下载任务后再试",
    990001: "Cookie 无效或已过期，请到设置重新粘贴",
    -1: "Cookie 无效或已过期，请到设置重新粘贴",
}

# 对用户视为成功（已在队列 / 已存在）
SOFT_OK_ERRCODES = {0, 10008}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def normalize_cookie(cookie: str) -> str:
    c = (cookie or "").strip()
    c = re.sub(r"\r?\n", "; ", c)
    c = re.sub(r";{2,}", "; ", c)
    return c.strip("; ").strip()


def cookie_part(cookie: str, key: str) -> str:
    m = re.search(rf"(?:^|;\s*){key}=([^;]+)", normalize_cookie(cookie), re.I)
    return (m.group(1) if m else "").strip()


def extract_uid(cookie: str) -> str:
    raw = cookie_part(cookie, "UID")
    m = re.match(r"^(\d+)", raw)
    return m.group(1) if m else raw


def require_cookie_parts(cookie: str) -> str | None:
    c = normalize_cookie(cookie)
    for key in ("UID", "CID", "SEID"):
        if not re.search(rf"(?:^|;\s*){key}=", c, re.I):
            return f"Cookie 缺少 {key}（需含 UID / CID / SEID，建议含 KID）"
    return None


def headers(cookie: str, referer: str = "https://115.com/") -> dict[str, str]:
    return {
        "Cookie": normalize_cookie(cookie),
        "User-Agent": UA,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": "https://115.com",
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
    }


def form_headers(cookie: str, referer: str = "https://115.com/") -> dict[str, str]:
    return {
        **headers(cookie, referer),
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }


def encode_form(pairs: list[tuple[str, Any]]) -> bytes:
    """Align with sehua URLSearchParams.toString().

    httpx>=0.28 breaks on ``data=[(k, v), ...]`` (TypeError: sequence item 1…);
    always send pre-encoded body bytes instead.
    """
    cleaned: list[tuple[str, str]] = []
    for key, value in pairs:
        cleaned.append((str(key), "" if value is None else str(value)))
    return urlencode(cleaned, doseq=True).encode("utf-8")


def errcode_of(data: Any) -> int | None:
    if not isinstance(data, dict):
        return None
    for k in ("errcode", "errno", "error_code"):
        if data.get(k) is None:
            continue
        try:
            return int(data[k])
        except (TypeError, ValueError):
            continue
    return None


def human_error(data: Any, fallback: str = "操作失败") -> str:
    code = errcode_of(data)
    if code is not None and code in ERRCODE_HINT:
        return ERRCODE_HINT[code]
    msg = ""
    if isinstance(data, dict):
        for k in ("error_msg", "error", "message", "msg", "errMsg"):
            v = data.get(k)
            if v:
                msg = str(v).strip()
                break
        # 批量结果里取第一条可读错误
        result = data.get("result")
        if not msg and isinstance(result, list):
            for row in result:
                if not isinstance(row, dict):
                    continue
                row_code = errcode_of(row)
                if row_code is not None and row_code in ERRCODE_HINT:
                    return ERRCODE_HINT[row_code]
                for k in ("error_msg", "error", "message", "msg"):
                    v = row.get(k)
                    if v:
                        msg = str(v).strip()
                        break
                if msg:
                    break
    if re.search(r"验证码|captcha|911", msg, re.I):
        return ERRCODE_HINT[911]
    if re.search(r"登录|cookie|过期|未登录|凭证", msg, re.I):
        return ERRCODE_HINT[-1]
    return msg or fallback


def _as_int(value: Any) -> int | None:
    if value is None or value is False:
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def fetch_offline_sign(cookie: str) -> dict[str, Any]:
    try:
        with httpx.Client(
            timeout=12.0, follow_redirects=True, trust_env=False
        ) as client:
            res = client.get(
                "https://115.com/?ct=offline&ac=space",
                headers=headers(cookie, "https://115.com/web/lixian/"),
            )
            data = res.json()
    except Exception as e:
        return {"ok": False, "message": str(e) or "获取离线签名失败"}

    if data.get("state") is False or (not data.get("sign") and data.get("errno")):
        return {
            "ok": False,
            "message": human_error(data, "获取离线签名失败（Cookie 可能过期）"),
        }
    sign = str(data.get("sign") or "").strip()
    time = str(data.get("time") if data.get("time") is not None else "").strip()
    if not sign or not time:
        return {
            "ok": False,
            "message": human_error(data, "离线签名为空，请重新登录 115 复制 Cookie"),
        }

    # 新版 space：data 可能是剩余空间字节，limit 为单任务上限；额度另见 task_lists
    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    quota = _as_int(inner.get("count") if inner else None)
    quota_total = _as_int(inner.get("size") if inner else None)
    if quota is None:
        quota = _as_int(data.get("quota"))
    if quota_total is None:
        quota_total = _as_int(data.get("quota_total") or data.get("total"))

    remain_bytes = None
    if isinstance(data.get("data"), (int, float)):
        remain_bytes = float(data["data"])
    limit_bytes = _as_int(data.get("limit"))

    return {
        "ok": True,
        "sign": sign,
        "time": time,
        "quota": quota,
        "quotaTotal": quota_total,
        "spaceRemain": remain_bytes,
        "spaceRemainText": str(data.get("size") or "").strip() or None,
        "offlineLimit": limit_bytes,
    }


def fetch_offline_quota(cookie: str) -> dict[str, Any]:
    """云转存额度：来自离线任务列表 quota/total（剩余 / 总额）。"""
    try:
        with httpx.Client(
            timeout=12.0, follow_redirects=True, trust_env=False
        ) as client:
            res = client.get(
                "https://115.com/web/lixian/?ct=lixian&ac=task_lists&page=1",
                headers=headers(cookie, "https://115.com/web/lixian/"),
            )
            data = res.json()
    except Exception as e:
        return {"ok": False, "message": str(e) or "获取云转存额度失败"}

    if not isinstance(data, dict):
        return {"ok": False, "message": "云转存额度响应异常"}

    if data.get("state") is False or data.get("errno"):
        return {
            "ok": False,
            "message": human_error(data, "获取云转存额度失败（Cookie 可能过期）"),
        }

    quota = _as_int(data.get("quota"))
    total = _as_int(data.get("total") or data.get("quota_total"))
    if quota is None and total is None:
        return {"ok": False, "message": "未返回云转存额度字段"}

    return {
        "ok": True,
        "quota": quota,
        "quotaTotal": total,
        "taskCount": _as_int(data.get("count")),
    }


def fetch_space_info(cookie: str) -> dict[str, Any]:
    """网盘容量：已用 / 总量 / 剩余。"""
    try:
        with httpx.Client(
            timeout=12.0, follow_redirects=True, trust_env=False
        ) as client:
            res = client.get(
                "https://webapi.115.com/files/index_info",
                headers=headers(cookie),
            )
            data = res.json()
    except Exception as e:
        return {"ok": False, "message": str(e) or "获取网盘空间失败"}

    if not isinstance(data, dict) or data.get("state") is False:
        return {
            "ok": False,
            "message": human_error(data if isinstance(data, dict) else {}, "获取网盘空间失败"),
        }
    body = data.get("data") if isinstance(data.get("data"), dict) else {}
    space = body.get("space_info") if isinstance(body.get("space_info"), dict) else {}

    def _pick(node: Any) -> tuple[float | None, str | None]:
        if not isinstance(node, dict):
            return None, None
        size = node.get("size")
        text = str(node.get("size_format") or "").strip() or None
        try:
            num = float(size) if size is not None else None
        except (TypeError, ValueError):
            num = None
        return num, text

    total_n, total_t = _pick(space.get("all_total"))
    used_n, used_t = _pick(space.get("all_use"))
    remain_n, remain_t = _pick(space.get("all_remain"))
    if total_n is None and used_n is None and remain_n is None:
        return {"ok": False, "message": "未返回网盘空间字段"}
    return {
        "ok": True,
        "spaceTotal": total_n,
        "spaceTotalText": total_t,
        "spaceUsed": used_n,
        "spaceUsedText": used_t,
        "spaceRemain": remain_n,
        "spaceRemainText": remain_t,
    }


def validate_p115(cookie: str, folder_cid: str = "0") -> dict[str, Any]:
    bad = require_cookie_parts(cookie)
    if bad:
        return {"ok": False, "message": bad}

    cid = (folder_cid or "0").strip() or "0"
    qs = urlencode(
        {
            "aid": "1",
            "cid": cid,
            "o": "user_ptime",
            "asc": "1",
            "offset": "0",
            "show_dir": "1",
            "limit": "1",
            "type": "0",
            "format": "json",
        }
    )
    try:
        with httpx.Client(
            timeout=12.0, follow_redirects=True, trust_env=False
        ) as client:
            res = client.get(
                f"https://webapi.115.com/files?{qs}",
                headers=headers(cookie),
            )
            data = res.json()
    except Exception as e:
        return {"ok": False, "message": str(e) or "请求 115 失败"}

    if data.get("state") is False or data.get("errno"):
        return {"ok": False, "message": human_error(data, "Cookie 无效或已过期")}

    path_arr = data.get("path") if isinstance(data.get("path"), list) else []
    last = path_arr[-1] if path_arr else {}
    if cid == "0":
        folder_name = "根目录"
    else:
        folder_name = str(
            (last or {}).get("name")
            or (last or {}).get("n")
            or data.get("name")
            or f"CID {cid}"
        )

    sign_res = fetch_offline_sign(cookie)
    quota_res = fetch_offline_quota(cookie)
    space_res = fetch_space_info(cookie)
    uid = extract_uid(cookie)

    quota = quota_res.get("quota") if quota_res.get("ok") else sign_res.get("quota")
    quota_total = (
        quota_res.get("quotaTotal") if quota_res.get("ok") else sign_res.get("quotaTotal")
    )

    if not sign_res.get("ok"):
        out = {
            "ok": True,
            "message": f"目录可读，但离线签名失败：{sign_res.get('message')}",
            "userId": uid,
            "folderCid": cid,
            "folderName": folder_name,
            "quota": quota,
            "quotaTotal": quota_total,
        }
    else:
        out = {
            "ok": True,
            "message": "连通正常（目录 + 离线签名）",
            "userId": uid,
            "folderCid": cid,
            "folderName": folder_name,
            "quota": quota,
            "quotaTotal": quota_total,
            "offlineLimit": sign_res.get("offlineLimit"),
        }

    if space_res.get("ok"):
        out.update(
            {
                "spaceTotal": space_res.get("spaceTotal"),
                "spaceTotalText": space_res.get("spaceTotalText"),
                "spaceUsed": space_res.get("spaceUsed"),
                "spaceUsedText": space_res.get("spaceUsedText"),
                "spaceRemain": space_res.get("spaceRemain"),
                "spaceRemainText": space_res.get("spaceRemainText"),
            }
        )
    return out


def list_folders(cookie: str, parent_cid: str = "0") -> dict[str, Any]:
    bad = require_cookie_parts(cookie)
    if bad:
        return {
            "ok": False,
            "message": bad,
            "parentCid": "0",
            "path": [],
            "folders": [],
        }

    cid = (parent_cid or "0").strip() or "0"
    qs = urlencode(
        {
            "aid": "1",
            "cid": cid,
            "o": "user_ptime",
            "asc": "1",
            "offset": "0",
            "show_dir": "1",
            "limit": "100",
            "type": "0",
            "format": "json",
            "star": "0",
            "natsort": "0",
            "fc_mix": "0",
        }
    )
    try:
        with httpx.Client(
            timeout=15.0, follow_redirects=True, trust_env=False
        ) as client:
            res = client.get(
                f"https://webapi.115.com/files?{qs}",
                headers=headers(cookie),
            )
            data = res.json()
    except Exception as e:
        return {
            "ok": False,
            "message": str(e) or "获取目录失败",
            "parentCid": cid,
            "path": [],
            "folders": [],
        }

    if data.get("state") is False or data.get("errno"):
        return {
            "ok": False,
            "message": human_error(data, "获取目录失败"),
            "parentCid": cid,
            "path": [],
            "folders": [],
        }

    rows = data.get("data") if isinstance(data.get("data"), list) else []
    folders: list[dict[str, str]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        item_cid = item.get("cid")
        if item_cid is None or str(item_cid) == "":
            continue
        if item.get("fid") or item.get("sha"):
            continue
        folders.append(
            {
                "cid": str(item_cid),
                "name": str(item.get("n") or item.get("name") or item_cid),
            }
        )

    path_raw = data.get("path") if isinstance(data.get("path"), list) else []
    path = [
        {
            "cid": str(p.get("cid") if p.get("cid") is not None else p.get("file_id") or "0"),
            "name": str(p.get("name") or p.get("n") or "根目录"),
        }
        for p in path_raw
        if isinstance(p, dict)
    ]
    if not path:
        path = [{"cid": "0", "name": "根目录"}]

    return {
        "ok": True,
        "message": "ok",
        "parentCid": cid,
        "path": path,
        "folders": folders,
    }
