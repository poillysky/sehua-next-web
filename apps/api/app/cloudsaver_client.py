"""CloudSaver 网盘搜索客户端（外挂 Docker 实例）。"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from . import settings_store
from .pansou_client import cloud_label

log = logging.getLogger("app.cloudsaver")

CLOUDSAVER_KEY = "cloudsaver"
DEFAULT_BASE_URL = "http://192.168.2.38:8008"
DEFAULT_TIMEOUT_S = 60.0

_TAG_RE = re.compile(r"<[^>]+>")
_AMP_RE = re.compile(r"&amp;", re.I)


class CloudSaverError(Exception):
    pass


def _normalize_base(url: str) -> str:
    s = str(url or "").strip().rstrip("/")
    if not s:
        return ""
    if "://" not in s:
        s = f"http://{s}"
    return s.rstrip("/")


def get_config(*, include_secrets: bool = False) -> dict[str, Any]:
    raw = settings_store.get_setting(CLOUDSAVER_KEY) or {}
    if not isinstance(raw, dict):
        raw = {}
    env_base = os.environ.get("CLOUDSAVER_BASE_URL") or os.environ.get(
        "SNS_CLOUDSAVER_BASE_URL"
    )
    env_user = os.environ.get("CLOUDSAVER_USERNAME")
    env_pass = os.environ.get("CLOUDSAVER_PASSWORD")
    base = (
        _normalize_base(env_base)
        if env_base
        else _normalize_base(str(raw.get("baseUrl") or ""))
    )
    if not base:
        base = DEFAULT_BASE_URL
    username = (
        str(env_user).strip()
        if env_user is not None
        else str(raw.get("username") or "").strip()
    )
    password = (
        str(env_pass)
        if env_pass is not None
        else str(raw.get("password") or "")
    )
    enabled = raw.get("enabled")
    if enabled is None:
        enabled = True
    timeout = float(raw.get("timeoutSec") or DEFAULT_TIMEOUT_S)
    out: dict[str, Any] = {
        "enabled": bool(enabled),
        "baseUrl": base,
        "username": username,
        "timeoutSec": max(8.0, min(timeout, 180.0)),
        "hasPassword": bool(password),
        "note": str(raw.get("note") or ""),
    }
    if include_secrets:
        out["password"] = password
        out["token"] = str(raw.get("token") or "").strip()
    return out


def _save_token(token: str) -> None:
    raw = settings_store.get_setting(CLOUDSAVER_KEY) or {}
    if not isinstance(raw, dict):
        raw = {}
    raw["token"] = str(token or "").strip()
    settings_store.put_setting(CLOUDSAVER_KEY, raw)


def _strip_html(s: str) -> str:
    t = _TAG_RE.sub("", str(s or ""))
    return _AMP_RE.sub("&", t).strip()


def _normalize_cloud_type(type_key: str, url: str = "") -> str:
    t = str(type_key or "").strip().lower()
    u = str(url or "").strip().lower()
    aliases = {
        "quark": "quark",
        "baidu": "baidu",
        "aliyun": "aliyun",
        "ali": "aliyun",
        "alipan": "aliyun",
        "uc": "uc",
        "xunlei": "xunlei",
        "tianyi": "tianyi",
        "cloud189": "tianyi",
        "115": "115",
        "pan115": "115",
        "share115": "115",
        "123": "123",
        "pikpak": "pikpak",
        "magnet": "magnet",
        "ed2k": "ed2k",
    }
    if t in aliases:
        return aliases[t]
    if u.startswith("magnet:"):
        return "magnet"
    if u.startswith("ed2k:"):
        return "ed2k"
    if "pan.quark.cn" in u:
        return "quark"
    if "pan.baidu.com" in u:
        return "baidu"
    if "alipan.com" in u or "aliyundrive.com" in u:
        return "aliyun"
    if "drive.uc.cn" in u:
        return "uc"
    if "115.com" in u or "anxia.com" in u:
        return "115"
    if "cloud.189.cn" in u:
        return "tianyi"
    return t or "other"


def login(*, force: bool = False) -> str:
    cfg = get_config(include_secrets=True)
    if not cfg["enabled"]:
        raise CloudSaverError("CloudSaver 未启用")
    if not cfg["baseUrl"]:
        raise CloudSaverError("未配置 CloudSaver 地址")
    if not cfg["username"] or not cfg["password"]:
        raise CloudSaverError("未配置 CloudSaver 账号密码")

    token = "" if force else str(cfg.get("token") or "").strip()
    if token and not force:
        return token

    url = f"{cfg['baseUrl']}/api/user/login"
    try:
        with httpx.Client(timeout=min(cfg["timeoutSec"], 20.0), trust_env=False) as client:
            resp = client.post(
                url,
                json={"username": cfg["username"], "password": cfg["password"]},
            )
    except httpx.TimeoutException as e:
        raise CloudSaverError("CloudSaver 登录超时") from e
    except httpx.HTTPError as e:
        raise CloudSaverError(f"无法连接 CloudSaver: {e}") from e

    if resp.status_code >= 400:
        raise CloudSaverError(f"CloudSaver 登录 HTTP {resp.status_code}")
    try:
        body = resp.json()
    except Exception as e:
        raise CloudSaverError("CloudSaver 登录返回非 JSON") from e
    if not body.get("success"):
        raise CloudSaverError(str(body.get("message") or "CloudSaver 登录失败"))
    token = str((body.get("data") or {}).get("token") or "").strip()
    if not token:
        raise CloudSaverError("CloudSaver 未返回 token")
    try:
        _save_token(token)
    except Exception:
        log.debug("persist cloudsaver token failed", exc_info=True)
    return token


def _request_search(
    keyword: str,
    token: str,
    timeout: float,
    base: str,
) -> tuple[dict[str, Any], int]:
    url = f"{base}/api/search"
    with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=True) as client:
        resp = client.get(
            url,
            params={"keyword": keyword, "lastMessageId": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {"success": False, "message": "CloudSaver 返回非 JSON"}
    return body, int(resp.status_code)


def _auth_failed(body: dict[str, Any], status_code: int = 200) -> bool:
    if status_code in (401, 403):
        return True
    msg = str(body.get("message") or "")
    code = body.get("code")
    low = msg.lower()
    return (
        code in (401, 40100, "401", "40100")
        or "无效的 token" in msg
        or "未提供 token" in msg
        or "未登录" in msg
        or ("token" in low and ("无效" in msg or "过期" in msg or "未提供" in msg))
    )


def _flatten(raw_data: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    channels = raw_data if isinstance(raw_data, list) else []
    for ch in channels:
        if not isinstance(ch, dict):
            continue
        rows = ch.get("list") if isinstance(ch.get("list"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = _strip_html(str(row.get("title") or ""))
            links: list[dict[str, str]] = []
            for lk in row.get("cloudLinks") or []:
                if not isinstance(lk, dict):
                    continue
                url = _AMP_RE.sub("&", str(lk.get("link") or lk.get("url") or "").strip())
                if not url:
                    continue
                t = _normalize_cloud_type(
                    str(lk.get("cloudType") or lk.get("type") or ""),
                    url,
                )
                links.append(
                    {
                        "type": t or "other",
                        "url": url,
                        "password": str(lk.get("password") or lk.get("code") or "").strip(),
                        "workTitle": "",
                        "label": cloud_label(t),
                    }
                )
            magnet = _AMP_RE.sub("&", str(row.get("magnetLink") or "").strip())
            if magnet.startswith("magnet:"):
                links.append(
                    {
                        "type": "magnet",
                        "url": magnet,
                        "password": "",
                        "workTitle": "",
                        "label": cloud_label("magnet"),
                    }
                )
            # 无可用链接的条目跳过，避免弹窗噪声
            if not links:
                continue
            uid = str(row.get("messageId") or "").strip() or f"{title}|{links[0]['url']}"
            if uid in seen:
                continue
            seen.add(uid)
            channel = str(row.get("channel") or row.get("channelId") or ch.get("name") or "").strip()
            tags = []
            if isinstance(row.get("tags"), list):
                tags = [_strip_html(str(t)) for t in row["tags"] if str(t).strip()]
            items.append(
                {
                    "id": uid,
                    "title": title or "未命名资源",
                    "content": _strip_html(str(row.get("content") or "")),
                    "channel": channel,
                    "datetime": str(row.get("pubDate") or "").strip(),
                    "tags": tags[:8],
                    "links": links,
                }
            )
    return items


def search(keyword: str) -> dict[str, Any]:
    cfg = get_config(include_secrets=True)
    if not cfg["enabled"]:
        raise CloudSaverError("CloudSaver 未启用")
    base = cfg["baseUrl"]
    if not base:
        raise CloudSaverError("未配置 CloudSaver 地址")
    kw = str(keyword or "").strip()
    if not kw:
        raise CloudSaverError("关键词为空")

    token = login(force=False)
    try:
        body, status = _request_search(kw, token, cfg["timeoutSec"], base)
    except httpx.TimeoutException as e:
        raise CloudSaverError("CloudSaver 搜索超时") from e
    except httpx.HTTPError as e:
        raise CloudSaverError(f"无法连接 CloudSaver: {e}") from e

    if (not body.get("success") or status >= 400) and _auth_failed(body, status):
        token = login(force=True)
        try:
            body, status = _request_search(kw, token, cfg["timeoutSec"], base)
        except httpx.TimeoutException as e:
            raise CloudSaverError("CloudSaver 搜索超时") from e
        except httpx.HTTPError as e:
            raise CloudSaverError(f"无法连接 CloudSaver: {e}") from e

    if status >= 400 and not body.get("success"):
        raise CloudSaverError(
            str(body.get("message") or f"CloudSaver HTTP {status}")
        )
    if not body.get("success"):
        raise CloudSaverError(str(body.get("message") or "CloudSaver 搜索失败"))

    items = _flatten(body.get("data"))
    host = urlparse(base).netloc or base
    return {
        "keyword": kw,
        "source": "cloudsaver",
        "baseUrl": base,
        "host": host,
        "total": len(items),
        "items": items,
    }


def health() -> dict[str, Any]:
    cfg = get_config(include_secrets=True)
    base = cfg["baseUrl"]
    if not cfg["enabled"] or not base:
        return {"ok": False, "configured": False, "baseUrl": base, "message": "未配置"}
    if not cfg["username"] or not cfg["password"]:
        return {
            "ok": False,
            "configured": False,
            "baseUrl": base,
            "message": "未配置账号密码",
        }
    try:
        login(force=False)
        return {
            "ok": True,
            "configured": True,
            "baseUrl": base,
            "username": cfg["username"],
            "message": "ok",
        }
    except Exception as e:
        return {
            "ok": False,
            "configured": True,
            "baseUrl": base,
            "username": cfg["username"],
            "message": str(e),
        }
