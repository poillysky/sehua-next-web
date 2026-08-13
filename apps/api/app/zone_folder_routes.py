"""综合区自定义文件夹 HTTP 路由。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import zone_folders

router = APIRouter(tags=["zone-folders"])


def _wrap(data: Any, message: str = "ok", status: int = 200) -> dict[str, Any]:
    return {"data": data, "message": message, "status": status}


class CreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    parentId: str | None = None
    kind: Literal["folder", "search"] | None = None
    searchKeyword: str | None = Field(default=None, max_length=200)


@router.get("/zone-folders")
def list_zone_folders() -> dict[str, Any]:
    return _wrap(zone_folders.read_zone_folders(), "ok")


@router.post("/zone-folders")
def create_zone_folder(body: CreateBody) -> dict[str, Any]:
    try:
        data = zone_folders.create_zone_folder(
            name=body.name,
            parent_id=body.parentId,
            kind=body.kind,
            search_keyword=body.searchKeyword,
        )
        return _wrap(data, "已创建")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/zone-folders/{folder_id}")
def delete_zone_folder(folder_id: str) -> dict[str, Any]:
    try:
        store = zone_folders.delete_zone_folder(folder_id)
        return _wrap({"store": store}, "已删除")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
