"""PanSou 网盘搜索客户端（外挂 Docker 实例）。"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from . import settings_store

log = logging.getLogger("app.pansou")

PANSOU_KEY = "pansou"
DEFAULT_BASE_URL = "http://192.168.2.38:8188"
DEFAULT_TIMEOUT_S = 60.0

CLOUD_TYPE_LABELS: dict[str, str] = {
    "baidu": "百度",
    "aliyun": "阿里",
    "quark": "夸克",
    "uc": "UC",
    "xunlei": "迅雷",
    "tianyi": "天翼",
    "mobile": "移动",
    "115": "115",
    "123": "123",
    "pikpak": "PikPak",
    "guangya": "光鸭",
    "magnet": "磁力",
    "ed2k": "ED2K",
}


class PansouError(Exception):
    pass


def _normalize_base(url: str) -> str:
    s = str(url or "").strip().rstrip("/")
    if not s:
        return ""
    if "://" not in s:
        s = f"http://{s}"
    return s.rstrip("/")


def get_config() -> dict[str, Any]:
    raw = settings_store.get_setting(PANSOU_KEY) or {}
    if not isinstance(raw, dict):
        raw = {}
    env = os.environ.get("PANSOU_BASE_URL") or os.environ.get("SNS_PANSOU_BASE_URL")
    base = _normalize_base(env) if env else _normalize_base(str(raw.get("baseUrl") or ""))
    if not base:
        base = DEFAULT_BASE_URL
    enabled = raw.get("enabled")
    if enabled is None:
        enabled = True
    timeout = float(raw.get("timeoutSec") or DEFAULT_TIMEOUT_S)
    return {
        "enabled": bool(enabled),
        "baseUrl": base,
        "timeoutSec": max(8.0, min(timeout, 180.0)),
        "note": str(raw.get("note") or ""),
    }


def is_configured() -> bool:
    cfg = get_config()
    return bool(cfg["enabled"] and cfg["baseUrl"])


def cloud_label(type_key: str) -> str:
    k = str(type_key or "").strip().lower()
    return CLOUD_TYPE_LABELS.get(k) or (type_key or "其他")


def _normalize_cloud_type(type_key: str, url: str = "") -> str:
    t = str(type_key or "").strip().lower()
    u = str(url or "").strip().lower()
    if t in ("115", "pan115", "share115"):
        return "115"
    if t in ("magnet", "ed2k"):
        return t
    if u.startswith("magnet:"):
        return "magnet"
    if u.startswith("ed2k:"):
        return "ed2k"
    if any(h in u for h in ("115.com", "115cdn.com", "anxia.com", "115.com.cn")):
        return "115"
    return t


def _keep_cloud_type(type_key: str, allowed: set[str]) -> bool:
    return str(type_key or "").strip().lower() in allowed


def _flatten_results(
    raw: dict[str, Any],
    *,
    allowed_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    """把 results / merged_by_type 归一成卡片列表。"""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed = allowed_types

    results = raw.get("results")
    if isinstance(results, list):
        for row in results:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            links_in = row.get("links") if isinstance(row.get("links"), list) else []
            links: list[dict[str, str]] = []
            for lk in links_in:
                if not isinstance(lk, dict):
                    continue
                url = str(lk.get("url") or "").strip()
                if not url:
                    continue
                t = _normalize_cloud_type(str(lk.get("type") or ""), url)
                if allowed is not None and not _keep_cloud_type(t, allowed):
                    continue
                links.append(
                    {
                        "type": t or "other",
                        "url": url,
                        "password": str(lk.get("password") or "").strip(),
                        "workTitle": str(lk.get("work_title") or "").strip(),
                        "label": cloud_label(t),
                    }
                )
            if not links:
                continue
            uid = str(row.get("unique_id") or "").strip() or f"{title}|{links[0]['url']}"
            if uid in seen:
                continue
            seen.add(uid)
            items.append(
                {
                    "id": uid,
                    "title": title or (links[0]["workTitle"] if links else "未命名资源"),
                    "content": str(row.get("content") or "").strip(),
                    "channel": str(row.get("channel") or "").strip(),
                    "datetime": str(row.get("datetime") or "").strip(),
                    "tags": [str(t).strip() for t in (row.get("tags") or []) if str(t).strip()]
                    if isinstance(row.get("tags"), list)
                    else [],
                    "links": links,
                }
            )

    merged = raw.get("merged_by_type")
    if isinstance(merged, dict) and not items:
        for type_key, rows in merged.items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                if not url or url in seen:
                    continue
                t = _normalize_cloud_type(str(type_key or ""), url)
                if allowed is not None and not _keep_cloud_type(t, allowed):
                    continue
                seen.add(url)
                note = str(row.get("note") or "").strip()
                items.append(
                    {
                        "id": url,
                        "title": note or url,
                        "content": "",
                        "channel": str(row.get("source") or "").strip(),
                        "datetime": str(row.get("datetime") or "").strip(),
                        "tags": [],
                        "links": [
                            {
                                "type": t or "other",
                                "url": url,
                                "password": str(row.get("password") or "").strip(),
                                "workTitle": note,
                                "label": cloud_label(t),
                            }
                        ],
                    }
                )

    return items


def search(
    keyword: str,
    *,
    refresh: bool = False,
    src: str = "all",
    cloud_types: list[str] | None = None,
) -> dict[str, Any]:
    cfg = get_config()
    if not cfg["enabled"]:
        raise PansouError("PanSou 未启用")
    base = cfg["baseUrl"]
    if not base:
        raise PansouError("未配置 PanSou 地址")

    kw = str(keyword or "").strip()
    if not kw:
        raise PansouError("关键词为空")

    types = [
        str(x).strip().lower()
        for x in (cloud_types or [])
        if str(x).strip()
    ]
    allowed = set(types) if types else None

    # 该实例对 merge/merged_by_type 常返回空，results/all 可用
    payload: dict[str, Any] = {
        "kw": kw,
        "res": "results",
        "src": src if src in ("all", "tg", "plugin") else "all",
        "refresh": bool(refresh),
    }
    if types:
        payload["cloud_types"] = types

    url = f"{base}/api/search"
    try:
        with httpx.Client(timeout=cfg["timeoutSec"], trust_env=False, follow_redirects=True) as client:
            resp = client.post(url, json=payload)
    except httpx.TimeoutException as e:
        raise PansouError("PanSou 搜索超时") from e
    except httpx.HTTPError as e:
        raise PansouError(f"无法连接 PanSou: {e}") from e

    if resp.status_code >= 400:
        raise PansouError(f"PanSou HTTP {resp.status_code}")

    try:
        body = resp.json()
    except Exception as e:
        raise PansouError("PanSou 返回非 JSON") from e

    code = body.get("code")
    if code not in (None, 0, "0", 200, "200"):
        raise PansouError(str(body.get("message") or "PanSou 搜索失败"))

    data = body.get("data") if isinstance(body.get("data"), dict) else body
    if not isinstance(data, dict):
        data = {}

    items = _flatten_results(data, allowed_types=allowed)
    host = urlparse(base).netloc or base
    return {
        "keyword": kw,
        "source": "pansou",
        "baseUrl": base,
        "host": host,
        "cloudTypes": types,
        "total": len(items),
        "items": items,
    }


def health() -> dict[str, Any]:
    cfg = get_config()
    base = cfg["baseUrl"]
    if not cfg["enabled"] or not base:
        return {"ok": False, "configured": False, "baseUrl": base, "message": "未配置"}
    try:
        with httpx.Client(timeout=8.0, trust_env=False, follow_redirects=True) as client:
            resp = client.get(f"{base}/api/health")
        if resp.status_code >= 400:
            return {
                "ok": False,
                "configured": True,
                "baseUrl": base,
                "message": f"HTTP {resp.status_code}",
            }
        body = resp.json() if resp.content else {}
        status = str(body.get("status") or "").lower()
        ok = status in ("ok", "healthy", "up") or bool(body.get("plugins") or body.get("channels"))
        return {
            "ok": ok,
            "configured": True,
            "baseUrl": base,
            "plugins": body.get("plugins") or [],
            "channels": body.get("channels") or [],
            "raw": body,
            "message": "ok" if ok else "unexpected health payload",
        }
    except Exception as e:
        return {
            "ok": False,
            "configured": True,
            "baseUrl": base,
            "message": str(e),
        }
