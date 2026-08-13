"""磁力中转（柠檬）HTTP 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from . import lemon_client

router = APIRouter(tags=["magnet"])


def _wrap(data: Any, message: str = "ok", status: int = 200) -> dict[str, Any]:
    return {"data": data, "message": message, "status": status}


@router.get("/magnet/search")
def magnet_search(
    keyword: str = Query(..., min_length=1, max_length=80),
    page: int = Query(1, ge=1, le=100),
) -> dict[str, Any]:
    """代搜磁力柠檬列表（不含磁力；复制时再调 /magnet/resolve）。"""
    try:
        data = lemon_client.search(keyword, page=page)
        return _wrap(data, "success")
    except lemon_client.LemonError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"柠檬搜索失败: {e}") from e


@router.get("/magnet/resolve")
def magnet_resolve(
    path: str = Query(..., min_length=8, max_length=200),
    keyword: str = Query(..., min_length=1, max_length=80),
) -> dict[str, Any]:
    """进入柠檬详情页解析 magnet:? 链接。"""
    try:
        data = lemon_client.resolve_magnet(path, keyword)
        return _wrap(data, "success")
    except lemon_client.LemonError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析磁力失败: {e}") from e


@router.get("/magnet/meta")
def magnet_meta() -> dict[str, Any]:
    base = lemon_client.resolve_base_url()
    return _wrap(
        {
            "source": "lemon",
            "baseUrl": base,
            "openUrl": base,
        },
        "success",
    )
