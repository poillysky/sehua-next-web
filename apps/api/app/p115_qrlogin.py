"""115 扫码登录 → Cookie（UID/CID/SEID/KID）。"""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urlencode

import httpx

from .p115_client import UA, encode_form, human_error, normalize_cookie

# 绑定 alipaymini，降低挤掉网页/手机端登录的概率（与 AList 建议一致）
DEFAULT_APP = "alipaymini"
ALLOWED_APPS = frozenset(
    {
        "web",
        "android",
        "ios",
        "linux",
        "mac",
        "windows",
        "tv",
        "alipaymini",
        "wechatmini",
        "qandroid",
    }
)

_STATUS_LABEL = {
    0: "等待扫码",
    1: "已扫码，请在手机上确认",
    2: "已确认",
    -1: "二维码已过期",
    -2: "已取消扫码",
}


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=15.0,
        follow_redirects=True,
        trust_env=False,
        headers={
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )


def start_qrlogin(app: str = DEFAULT_APP) -> dict[str, Any]:
    """Fetch QR token + PNG data URL for display."""
    device = (app or DEFAULT_APP).strip().lower()
    if device not in ALLOWED_APPS:
        device = DEFAULT_APP

    try:
        with _client() as client:
            token_res = client.get("https://qrcodeapi.115.com/api/1.0/web/1.0/token/")
            token_json = token_res.json()
            if not isinstance(token_json, dict) or not token_json.get("data"):
                return {
                    "ok": False,
                    "message": human_error(token_json, "获取二维码失败"),
                }
            data = token_json["data"]
            if not isinstance(data, dict):
                return {"ok": False, "message": "二维码响应异常"}

            uid = str(data.get("uid") or "").strip()
            time_ = data.get("time")
            sign = str(data.get("sign") or "").strip()
            if not uid or time_ is None or not sign:
                return {"ok": False, "message": "二维码参数不完整"}

            img_res = client.get(
                f"https://qrcodeapi.115.com/api/1.0/mac/1.0/qrcode?uid={uid}"
            )
            qr_image = ""
            ctype = (img_res.headers.get("content-type") or "").lower()
            if img_res.status_code == 200 and "image" in ctype:
                b64 = base64.b64encode(img_res.content).decode("ascii")
                qr_image = f"data:image/png;base64,{b64}"
            elif data.get("qrcode"):
                # 无图时前端可另渲染；仍返回原始内容
                qr_image = ""

            return {
                "ok": True,
                "uid": uid,
                "time": time_,
                "sign": sign,
                "qrcode": str(data.get("qrcode") or "").strip() or None,
                "qrImage": qr_image or None,
                "app": device,
                "message": "请使用 115 App 扫码",
            }
    except Exception as e:
        return {"ok": False, "message": str(e) or "获取二维码失败"}


def poll_qrlogin_status(
    uid: str,
    time_: Any,
    sign: str,
) -> dict[str, Any]:
    """Poll scan status. status: 0 wait / 1 scanned / 2 done / -1 expired / -2 canceled."""
    uid = str(uid or "").strip()
    sign = str(sign or "").strip()
    if not uid or time_ is None or not sign:
        return {"ok": False, "message": "缺少扫码参数"}

    try:
        qs = urlencode({"uid": uid, "time": str(time_), "sign": sign})
        with _client() as client:
            res = client.get(f"https://qrcodeapi.115.com/get/status/?{qs}")
            data = res.json()
    except Exception as e:
        return {"ok": False, "message": str(e) or "查询扫码状态失败"}

    if not isinstance(data, dict):
        return {"ok": False, "message": "扫码状态响应异常"}

    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    try:
        status = int(inner.get("status")) if inner.get("status") is not None else None
    except (TypeError, ValueError):
        status = None

    if status is None and data.get("state") is False:
        return {
            "ok": False,
            "message": human_error(data, "查询扫码状态失败"),
        }

    label = _STATUS_LABEL.get(status if status is not None else 0, f"状态 {status}")
    return {
        "ok": True,
        "status": status,
        "statusLabel": label,
        "done": status == 2,
        "expired": status in (-1, -2),
        "message": label,
    }


def complete_qrlogin(uid: str, app: str = DEFAULT_APP) -> dict[str, Any]:
    """Exchange confirmed QR for cookie string."""
    uid = str(uid or "").strip()
    device = (app or DEFAULT_APP).strip().lower()
    if device not in ALLOWED_APPS:
        device = DEFAULT_APP
    if not uid:
        return {"ok": False, "message": "缺少二维码 uid"}

    try:
        with _client() as client:
            res = client.post(
                f"https://passportapi.115.com/app/1.0/{device}/1.0/login/qrcode/",
                content=encode_form([("app", device), ("account", uid)]),
                headers={
                    "User-Agent": UA,
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Accept": "application/json, text/plain, */*",
                },
            )
            data = res.json()
    except Exception as e:
        return {"ok": False, "message": str(e) or "扫码登录失败"}

    if not isinstance(data, dict):
        return {"ok": False, "message": "登录响应异常"}

    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    cookie_map = inner.get("cookie") if isinstance(inner.get("cookie"), dict) else None
    if not cookie_map:
        return {
            "ok": False,
            "message": human_error(data, "扫码登录未返回 Cookie"),
        }

    # Prefer stable order for readability
    parts: list[str] = []
    for key in ("UID", "CID", "SEID", "KID"):
        if key in cookie_map and cookie_map[key] is not None:
            parts.append(f"{key}={cookie_map[key]}")
    for key, val in cookie_map.items():
        up = str(key).upper()
        if up in ("UID", "CID", "SEID", "KID"):
            continue
        parts.append(f"{key}={val}")

    cookie = normalize_cookie("; ".join(parts))
    if not cookie:
        return {"ok": False, "message": "Cookie 为空"}

    return {
        "ok": True,
        "cookie": cookie,
        "app": device,
        "userId": inner.get("user_id") or cookie_map.get("UID"),
        "message": "扫码登录成功",
    }
