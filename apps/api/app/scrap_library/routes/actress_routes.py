# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import mimetypes
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.auth.routes import get_optional_user, require_user
from app.scrap_library.cover_focus_routes import (
    _disk_get,
    _disk_put,
    _mem_get,
    _mem_put,
    _resize_cover,
)
import app.scrap_library.embed as svc

router = APIRouter(prefix="/scrap-library", tags=["scrap-library-embed"])

_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=0, must-revalidate",
}

class ActressOptimizeBody(BaseModel):
    reembed: bool = True
    # True=全量（未变也重嵌）；False=增量（跳过已对齐）
    force: bool = False
    limit: int = Field(default=0, ge=0, le=200_000)


@router.get("/embed/actress-optimize/status")
def get_actress_optimize_status(
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {"ok": True, "data": svc.get_actress_optimize_status()}


@router.post("/embed/actress-optimize/start")
def start_actress_optimize(
    body: ActressOptimizeBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """同步女优名到向量库：映射标准名写回 source_text + 重嵌。"""
    try:
        lim = int(body.limit or 0)
        data = svc.start_actress_optimize_job(
            reembed=bool(body.reembed),
            force=bool(body.force),
            limit=lim if lim > 0 else None,
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


class NfoOptimizeBody(BaseModel):
    # True=全量（映射有则强制覆盖标题/女优）；False=增量（prefer 策略，仅有变才写）
    force: bool = False
    limit: int = Field(default=0, ge=0, le=500_000)


@router.get("/embed/nfo-optimize/status")
def get_nfo_optimize_status(
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    from app.scrap_library import nfo_optimize as nfo_opt

    return {"ok": True, "data": nfo_opt.get_job_status()}


@router.post("/embed/nfo-optimize/start")
def start_nfo_optimize(
    body: NfoOptimizeBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """本地映射优化磁盘 NFO：标题/女优/标签/片商写回。"""
    from app.scrap_library import nfo_optimize as nfo_opt

    try:
        lim = int(body.limit or 0)
        data = nfo_opt.start_nfo_optimize_job(
            force=bool(body.force),
            limit=lim if lim > 0 else None,
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


class ActressAvatarBody(BaseModel):
    force: bool = False
    limit: int = Field(default=0, ge=0, le=200_000)
    region: str = ""
    # 先映射写回向量库，再刮头像（默认开）
    polishMeta: bool = True


@router.get("/embed/actress-avatar/status")
def get_actress_avatar_status(
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    import app.scrap_library.actress_avatar as av

    return {"ok": True, "data": av.get_job_status()}


@router.get("/embed/actress-avatar/urls")
def get_actress_avatar_urls(
    names: list[str] = Query(default=[]),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """按女优名解析本地头像 API 路径（有则返回）。"""
    import app.scrap_library.actress_avatar as av

    out: dict[str, str] = {}
    for raw in names or []:
        name = str(raw or "").strip()
        if not name or name in out:
            continue
        api = av.resolve_avatar_api(name)
        if api:
            out[name] = api
    return {"ok": True, "data": out}


@router.get("/embed/actress-profile")
def get_actress_profile(
    name: str = Query(""),
    region: str = Query(""),
    refresh: bool = Query(False),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """女优详情：标准名、别名、作品数、本地头像、生日/三围等详细资料。"""
    import app.scrap_library.actress_avatar as av

    n = str(name or "").strip()
    if not n:
        raise HTTPException(400, "name required")
    try:
        data = av.get_actress_profile(
            n, region=str(region or "").strip(), refresh=bool(refresh)
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


@router.post("/embed/actress-avatar/start")
def start_actress_avatar(
    body: ActressAvatarBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """女优刮削：从向量库取女优名 → 头像/资料落本地（默认不写回向量）。"""
    import app.scrap_library.actress_avatar as av

    try:
        lim = int(body.limit or 0)
        data = av.start_actress_avatar_job(
            force=bool(body.force),
            limit=lim if lim > 0 else None,
            region=str(body.region or "").strip(),
            polish_meta=bool(body.polishMeta),
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


