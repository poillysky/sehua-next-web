"""片商刮削库收藏 HTTP 路由（按登录账号持久化）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.routes import require_user
import app.search.favorites_store as favorites_store

router = APIRouter(prefix="/scrap-favorites", tags=["scrap-favorites"])


class AddFavoriteBody(BaseModel):
    itemId: str = Field(min_length=1, max_length=512)
    region: str = Field(default="", max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_favorites(
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    items = favorites_store.list_favorites(int(user["id"]))
    return {"ok": True, "data": {"items": items, "total": len(items)}}


@router.get("/check")
def check_favorite(
    itemId: str = Query(..., min_length=1, max_length=512),
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    item_id = str(itemId or "").strip()
    if not item_id:
        raise HTTPException(400, "缺少条目 ID")
    ok = favorites_store.is_favorite(int(user["id"]), item_id)
    return {"ok": True, "data": {"itemId": item_id, "favorited": ok}}


@router.put("")
def add_favorite(
    body: AddFavoriteBody,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """itemId 常含路径分隔符（如 日本有码/AARM/AARM-001），勿放 URL path。"""
    try:
        favorites_store.add_favorite(
            int(user["id"]),
            body.itemId,
            body.payload,
            hub_region=body.region,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": {"itemId": body.itemId, "favorited": True}}


@router.delete("")
def remove_favorite(
    itemId: str = Query(..., min_length=1, max_length=512),
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    item_id = str(itemId or "").strip()
    if not item_id:
        raise HTTPException(400, "缺少条目 ID")
    favorites_store.remove_favorite(int(user["id"]), item_id)
    return {"ok": True, "data": {"itemId": item_id, "favorited": False}}
