"""PanSou 网盘搜索 HTTP 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import pansou_client, settings_store

router = APIRouter(tags=["pansou"])


def _wrap(data: Any, message: str = "ok", status: int = 200) -> dict[str, Any]:
    return {"data": data, "message": message, "status": status}


class PansouConfigBody(BaseModel):
    enabled: bool = True
    baseUrl: str = Field(default=pansou_client.DEFAULT_BASE_URL, max_length=300)
    timeoutSec: float = Field(default=60, ge=8, le=180)
    note: str = Field(default="", max_length=200)


@router.get("/pansou/health")
def pansou_health() -> dict[str, Any]:
    return _wrap(pansou_client.health())


@router.get("/pansou/search")
def pansou_search(
    keyword: str = Query(..., min_length=1, max_length=200),
    refresh: bool = Query(False),
    src: str = Query("all", max_length=16),
) -> dict[str, Any]:
    try:
        data = pansou_client.search(keyword, refresh=refresh, src=src)
        return _wrap(data, "success")
    except pansou_client.PansouError as e:
        msg = str(e)
        code = 400 if ("未启用" in msg or "未配置" in msg or "为空" in msg) else 502
        raise HTTPException(status_code=code, detail=msg) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PanSou 搜索失败: {e}") from e


@router.get("/settings/pansou")
def get_pansou_settings() -> dict[str, Any]:
    return _wrap(pansou_client.get_config())


@router.put("/settings/pansou")
def put_pansou_settings(body: PansouConfigBody) -> dict[str, Any]:
    base = pansou_client._normalize_base(body.baseUrl)
    if not base:
        raise HTTPException(status_code=400, detail="baseUrl 不能为空")
    settings_store.put_setting(
        pansou_client.PANSOU_KEY,
        {
            "enabled": body.enabled,
            "baseUrl": base,
            "timeoutSec": body.timeoutSec,
            "note": body.note.strip(),
        },
    )
    return _wrap(pansou_client.get_config(), "saved")
