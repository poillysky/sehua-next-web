"""出站 HTTP：统一走刮削设置里的 proxyUrl（封面代理 / 拉图）。"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx

from . import settings_store


def normalize_proxy_url(raw: str | None) -> str:
    """裸 host:port → http://；非法则空串。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = f"http://{s}"
    s = s.rstrip("/")
    parsed = urlparse(s)
    if parsed.scheme not in ("http", "https", "socks4", "socks5") or not parsed.netloc:
        return ""
    return s


def resolve_scrape_proxy_url() -> str:
    """优先 settings.scrape.proxyUrl，其次 SNS_PROXY_URL / 环境变量。"""
    raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
    if not isinstance(raw, dict):
        raw = {}
    hit = normalize_proxy_url(
        str(raw.get("proxyUrl") or raw.get("proxy_url") or "")
    )
    if hit:
        return hit
    return normalize_proxy_url(
        os.environ.get("SNS_PROXY_URL", "").strip()
        or os.environ.get("HTTPS_PROXY", "").strip()
        or os.environ.get("HTTP_PROXY", "").strip()
    )


def httpx_client(**kwargs: Any) -> httpx.Client:
    """创建出站客户端；有代理时强制走项目代理，不读系统环境以免绕开设置。"""
    proxy = resolve_scrape_proxy_url()
    opts: dict[str, Any] = {"trust_env": False, "follow_redirects": True}
    opts.update(kwargs)
    if proxy:
        opts["proxy"] = proxy
    return httpx.Client(**opts)
