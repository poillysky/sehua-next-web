"""CloudSaver 网盘搜索 HTTP 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import app.search.cloudsaver_client as cloudsaver_client
import app.core.settings_store as settings_store

router = APIRouter(tags=["cloudsaver"])


def _wrap(data: Any, message: str = "ok", status: int = 200) -> dict[str, Any]:
    return {"data": data, "message": message, "status": status}


class CloudSaverConfigBody(BaseModel):
    enabled: bool = True
    baseUrl: str = Field(default=cloudsaver_client.DEFAULT_BASE_URL, max_length=300)
    username: str = Field(default="", max_length=80)
    password: str = Field(default="", max_length=200)
    timeoutSec: float = Field(default=60, ge=8, le=180)
    note: str = Field(default="", max_length=200)


@router.get("/cloudsaver/health")
def cloudsaver_health() -> dict[str, Any]:
    return _wrap(cloudsaver_client.health())


@router.get("/cloudsaver/search")
def cloudsaver_search(
    keyword: str = Query(..., min_length=1, max_length=200),
) -> dict[str, Any]:
    try:
        data = cloudsaver_client.search(keyword)
        return _wrap(data, "success")
    except cloudsaver_client.CloudSaverError as e:
        msg = str(e)
        code = (
            400
            if ("未启用" in msg or "未配置" in msg or "为空" in msg or "账号" in msg)
            else 502
        )
        raise HTTPException(status_code=code, detail=msg) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CloudSaver 搜索失败: {e}") from e


@router.get("/settings/cloudsaver")
def get_cloudsaver_settings() -> dict[str, Any]:
    return _wrap(cloudsaver_client.get_config(include_secrets=False))


@router.put("/settings/cloudsaver")
def put_cloudsaver_settings(body: CloudSaverConfigBody) -> dict[str, Any]:
    base = cloudsaver_client._normalize_base(body.baseUrl)
    if not base:
        raise HTTPException(status_code=400, detail="baseUrl 不能为空")
    prev = settings_store.get_setting(cloudsaver_client.CLOUDSAVER_KEY) or {}
    if not isinstance(prev, dict):
        prev = {}
    password = body.password.strip()
    if not password:
        password = str(prev.get("password") or "")
    settings_store.put_setting(
        cloudsaver_client.CLOUDSAVER_KEY,
        {
            "enabled": body.enabled,
            "baseUrl": base,
            "username": body.username.strip(),
            "password": password,
            "timeoutSec": body.timeoutSec,
            "note": body.note.strip(),
            "token": "",  # 改配置后强制重新登录
        },
    )
    return _wrap(cloudsaver_client.get_config(include_secrets=False), "saved")
