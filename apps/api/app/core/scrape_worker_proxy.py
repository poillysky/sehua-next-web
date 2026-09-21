"""UI → scrape-worker 内网代理。

NAS 上 APP_ROLE=ui 且配置 SCRAPE_WORKER_URL 时，把扫描/刮削/向量化等
重接口转到独立 worker 容器，避免与页面同进程抢 GIL/连接池/磁盘。

本机未设 SCRAPE_WORKER_URL 时不代理（开发行为不变）。
"""

from __future__ import annotations

import logging
import os
from typing import Iterable

import httpx
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger(__name__)

# (method, path) — path 为 FastAPI 挂载后的完整路径
_HEAVY_EXACT: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/scrap-library/embed/enrich"),
        ("POST", "/scrap-library/embed/enrich/one"),
        ("GET", "/scrap-library/embed/enrich/status"),
        ("GET", "/scrap-library/embed/enrich/status/stream"),
        ("GET", "/scrap-library/embed/enrich/logs"),
        ("POST", "/scrap-library/embed/enrich/logs/clear"),
        ("POST", "/scrap-library/embed/enrich/queue-scan"),
        ("POST", "/scrap-library/embed/enrich/cancel"),
        ("POST", "/scrap-library/embed/enrich/pause"),
        ("POST", "/scrap-library/embed/enrich/stop"),
        ("POST", "/scrap-library/embed/enrich/retry-fails"),
        ("POST", "/scrap-library/embed/enrich/retry-softs"),
        ("POST", "/scrap-library/embed/start"),
        ("GET", "/scrap-library/embed/status"),
        ("POST", "/scrap-library/embed/reset-skeletons"),
        ("POST", "/scrap-library/embed/posters/recompress"),
        ("GET", "/scrap-library/embed/posters/recompress/status"),
        ("POST", "/scrap-library/embed/actress-optimize/start"),
        ("GET", "/scrap-library/embed/actress-optimize/status"),
        ("POST", "/scrap-library/embed/nfo-optimize/start"),
        ("GET", "/scrap-library/embed/nfo-optimize/status"),
        ("POST", "/scrap-library/embed/actress-avatar/start"),
        ("GET", "/scrap-library/embed/actress-avatar/status"),
        ("POST", "/scrap-library/embed/facets/refresh"),
    }
)

_HOP_BY_HOP = frozenset(
    {
        b"connection",
        b"keep-alive",
        b"proxy-authenticate",
        b"proxy-authorization",
        b"te",
        b"trailers",
        b"transfer-encoding",
        b"upgrade",
        b"host",
        b"content-length",
    }
)


def app_role() -> str:
    return str(os.environ.get("APP_ROLE") or "").strip().lower()


def scrape_worker_url() -> str:
    return str(os.environ.get("SCRAPE_WORKER_URL") or "").strip().rstrip("/")


def is_ui_proxy_enabled() -> bool:
    """仅 UI 角色且配置了 worker 地址时启用代理。"""
    if app_role() != "ui":
        return False
    return bool(scrape_worker_url())


def is_heavy_path(method: str, path: str) -> bool:
    m = (method or "GET").upper()
    p = path or ""
    return (m, p) in _HEAVY_EXACT


def should_proxy(method: str, path: str) -> bool:
    return is_ui_proxy_enabled() and is_heavy_path(method, path)


def _filter_request_headers(headers: Iterable[tuple[bytes, bytes]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers:
        lk = key.lower()
        if lk in _HOP_BY_HOP:
            continue
        out[key.decode("latin-1")] = value.decode("latin-1")
    return out


def _filter_response_headers(headers: Iterable[tuple[str, str]]) -> list[tuple[bytes, bytes]]:
    out: list[tuple[bytes, bytes]] = []
    for key, value in headers:
        lk = key.lower().encode("latin-1")
        if lk in _HOP_BY_HOP:
            continue
        out.append((key.encode("latin-1"), value.encode("latin-1")))
    return out


class ScrapeWorkerProxyMiddleware:
    """把重活 ASGI 请求流式转到 scrape-worker。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method") or "GET").upper()
        path = str(scope.get("path") or "")
        if not should_proxy(method, path):
            await self.app(scope, receive, send)
            return

        base = scrape_worker_url()
        raw_qs = scope.get("query_string") or b""
        qs = raw_qs.decode("latin-1") if isinstance(raw_qs, (bytes, bytearray)) else str(raw_qs)
        url = f"{base}{path}"
        if qs:
            url = f"{url}?{qs}"

        body = b""
        while True:
            message = await receive()
            if message["type"] != "http.request":
                continue
            body += message.get("body") or b""
            if not message.get("more_body"):
                break

        headers = _filter_request_headers(scope.get("headers") or [])
        timeout = httpx.Timeout(connect=10.0, read=None, write=120.0, pool=10.0)

        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
                async with client.stream(
                    method,
                    url,
                    content=body if body else None,
                    headers=headers,
                ) as resp:
                    await send(
                        {
                            "type": "http.response.start",
                            "status": int(resp.status_code),
                            "headers": _filter_response_headers(resp.headers.items()),
                        }
                    )
                    async for chunk in resp.aiter_raw():
                        if chunk:
                            await send(
                                {
                                    "type": "http.response.body",
                                    "body": chunk,
                                    "more_body": True,
                                }
                            )
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b"",
                            "more_body": False,
                        }
                    )
        except httpx.HTTPError as e:
            log.warning("scrape-worker proxy failed %s %s: %s", method, path, e)
            import json

            payload = json.dumps(
                {
                    "detail": f"刮削服务不可用（{type(e).__name__}），请检查 scrape-worker",
                },
                ensure_ascii=False,
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/json; charset=utf-8"),
                        (b"content-length", str(len(payload)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": payload, "more_body": False})
