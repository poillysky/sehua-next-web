"""磁力搜索（Bitmagnet 本地库）HTTP 路由。"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query

from . import bitmagnet_client
from .outbound_http import httpx_client

log = logging.getLogger(__name__)
router = APIRouter(tags=["magnet"])

_HASH_RE = re.compile(r"^[a-fA-F0-9]{40}$")


def _wrap(data: Any, message: str = "ok", status: int = 200) -> dict[str, Any]:
    return {"data": data, "message": message, "status": status}


@router.get("/magnet/search")
def magnet_search(
    keyword: str = Query(..., min_length=1, max_length=200),
    page: int = Query(1, ge=1, le=500),
    sortType: str = Query("default", max_length=20),
    filterTime: str = Query("all", max_length=20),
    filterSize: str = Query("all", max_length=20),
) -> dict[str, Any]:
    """搜 Bitmagnet 库；结果含 magnet URI 与文件列表。"""
    try:
        data = bitmagnet_client.search(
            keyword,
            page=page,
            sort_type=sortType,
            filter_time=filterTime,
            filter_size=filterSize,
        )
        return _wrap(data, "success")
    except bitmagnet_client.BitmagnetError as e:
        msg = str(e)
        code = 400 if ("未配置" in msg or "启用并填写" in msg) else 502
        raise HTTPException(status_code=code, detail=msg) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bitmagnet 搜索失败: {e}") from e


@router.get("/magnet/detail")
def magnet_detail(
    hash: str = Query(..., min_length=8, max_length=64),
) -> dict[str, Any]:
    try:
        data = bitmagnet_client.get(hash)
        return _wrap(data, "success")
    except bitmagnet_client.BitmagnetError as e:
        msg = str(e)
        code = 404 if "未找到" in msg else (400 if "无效" in msg or "未配置" in msg else 502)
        raise HTTPException(status_code=code, detail=msg) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bitmagnet 详情失败: {e}") from e


@router.get("/magnet/resolve")
def magnet_resolve(
    path: str = Query(..., min_length=8, max_length=200),
    keyword: str = Query("", max_length=120),
) -> dict[str, Any]:
    """兼容旧前端：Bitmagnet 列表已带磁力，resolve 不再需要。"""
    del keyword
    h = (path or "").strip().lower().removeprefix("/detail/")
    if len(h) < 8:
        raise HTTPException(status_code=400, detail="无效 infoHash")
    magnet = bitmagnet_client.magnet_uri(info_hash_hex=h, name=h, size=0)
    return _wrap(
        {
            "path": h,
            "magnet": magnet,
            "magnets": [magnet],
            "detailUrl": "",
            "cached": True,
        },
        "bitmagnet 无需 resolve，已由 infoHash 生成",
    )


@router.get("/magnet/preview")
def magnet_preview(
    hash: str = Query(..., min_length=8, max_length=64),
) -> dict[str, Any]:
    """对齐 Bitmagnet-Next-Web：经 WhatsLink 拉内容截图预览。

    无截图 / 超时 / 失败时一律返回空列表（不 502），详情页静默隐藏区块。
    """
    h = (hash or "").strip().lower()
    if not _HASH_RE.match(h):
        raise HTTPException(status_code=400, detail="无效 infoHash")

    empty = {
        "hash": h,
        "name": "",
        "file_type": "unknown",
        "screenshots": [],
        "error": "",
    }

    magnet = f"magnet:?xt=urn:btih:{h}"
    url = f"https://whatslink.info/api/v1/link?url={quote(magnet, safe='')}"

    raw: Any = None
    # 先直连（多数环境更快）；失败再走刮削代理
    try:
        import httpx

        with httpx.Client(timeout=8.0, trust_env=False, follow_redirects=True) as client:
            resp = client.get(url)
        if resp.status_code < 400:
            raw = resp.json()
    except Exception as e:
        log.info("whatslink direct failed: %s", e)

    if raw is None:
        try:
            with httpx_client(timeout=8.0) as client:
                resp = client.get(url)
            if resp.status_code >= 400:
                empty["error"] = f"status {resp.status_code}"
                return _wrap(empty, "empty")
            raw = resp.json()
        except Exception as e:
            log.warning("whatslink proxy failed: %s", e)
            empty["error"] = str(e)
            return _wrap(empty, "empty")

    if not isinstance(raw, dict) or raw.get("error"):
        empty["error"] = str((raw or {}).get("error") or "invalid")
        return _wrap(empty, "empty")

    shots_raw = raw.get("screenshots") or []
    screenshots: list[dict[str, Any]] = []
    if isinstance(shots_raw, list):
        for item in shots_raw:
            if not isinstance(item, dict):
                continue
            shot = str(item.get("screenshot") or "").strip()
            if not shot:
                continue
            screenshots.append({"time": item.get("time"), "screenshot": shot})

    return _wrap(
        {
            "hash": h,
            "name": str(raw.get("name") or ""),
            "file_type": str(raw.get("file_type") or "unknown"),
            "size": raw.get("size"),
            "count": raw.get("count"),
            "screenshots": screenshots,
            "error": "",
        },
        "success" if screenshots else "empty",
    )


@router.get("/magnet/meta")
def magnet_meta() -> dict[str, Any]:
    return _wrap(bitmagnet_client.meta(), "success")
