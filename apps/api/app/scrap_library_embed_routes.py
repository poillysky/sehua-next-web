# -*- coding: utf-8 -*-
"""刮削库向量灌库 API（写入元库 SNS_META_DSN / :5439）。"""

from __future__ import annotations

import hashlib
import mimetypes
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .auth_routes import get_optional_user, require_user
from .cover_focus_routes import (
    _disk_get,
    _disk_put,
    _mem_get,
    _mem_put,
    _resize_cover,
)
from . import scrap_library_embed as svc

router = APIRouter(prefix="/scrap-library", tags=["scrap-library-embed"])

_CACHE_HEADERS = {
    # 本地文件 + ETag；public 便于浏览器磁盘缓存，二次打开更快
    "Cache-Control": "public, max-age=604800, immutable",
}


class SettingsBody(BaseModel):
    root: str = ""


class StartBody(BaseModel):
    root: str = ""
    force: bool = False


class SearchBody(BaseModel):
    query: str = ""
    limit: int = Field(default=8, ge=1, le=50)
    region: str = ""


@router.get("/embed")
def get_settings(_user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return {"ok": True, "data": svc.get_settings()}


@router.put("/embed")
def put_settings(
    body: SettingsBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        data = svc.put_settings(root=body.root)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


@router.get("/embed/stats")
def get_stats(_user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    try:
        return {"ok": True, "data": svc.stats()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e


@router.get("/embed/status")
def get_status(_user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return {"ok": True, "data": svc.get_job_status()}


@router.post("/embed/start")
def start_ingest(
    body: StartBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        data = svc.start_ingest_job(root=body.root, force=bool(body.force))
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


@router.get("/embed/regions")
def get_regions(_user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    try:
        return {"ok": True, "data": {"regions": svc.list_regions()}}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e


@router.get("/embed/prefixes")
def get_prefixes(
    region: str = Query(""),
    studio: str = Query(""),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            "data": {
                "prefixes": svc.list_prefixes(region=region, studio=studio),
            },
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e


@router.get("/embed/items")
def get_items(
    region: str = Query(""),
    prefix: str = Query(""),
    q: str = Query(""),
    genre: str = Query(""),
    tag: str = Query(""),
    studio: str = Query(""),
    actress: str = Query(""),
    sort: str = Query("name"),
    order: str = Query("asc"),
    offset: int = Query(0, ge=0),
    limit: int = Query(36, ge=1, le=100),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            "data": svc.list_items(
                region=region,
                prefix=prefix,
                q=q,
                genre=genre,
                tag=tag,
                studio=studio,
                actress=actress,
                sort=sort,
                order=order,
                offset=offset,
                limit=limit,
            ),
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e


@router.get("/embed/facets")
def get_facets(
    region: str = Query(""),
    kind: str = Query("genre"),
    studio: str = Query(""),
    prefix: str = Query(""),
    sort: str = Query("count"),
    order: str = Query("desc"),
    offset: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1, le=100),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            "data": svc.list_facets(
                region=region,
                kind=kind,
                studio=studio,
                prefix=prefix,
                sort=sort,
                order=order,
                offset=offset,
                limit=limit,
            ),
        }
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e


@router.get("/embed/recommend")
def get_recommend(
    region: str = Query(""),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        return {"ok": True, "data": svc.list_recommend(region=region)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e


@router.post("/embed/search")
def search(
    body: SearchBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        hits = svc.search(body.query, limit=int(body.limit), region=body.region)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": {"hits": hits}}


def _local_file_etag(abs_path, w: int | None, *, rp: bool = False) -> str:
    st = abs_path.stat()
    # rp=1：横图裁右侧竖幅（有码 thumb）
    raw = f"{abs_path}|{st.st_mtime_ns}|{st.st_size}|w={w or 0}|rp={1 if rp else 0}".encode(
        "utf-8"
    )
    return f'"{hashlib.sha1(raw).hexdigest()}"'


@router.get("/file")
def get_local_file(
    request: Request,
    path: str = Query(..., min_length=1),
    w: int | None = Query(None, ge=32, le=1280),
    rp: int | None = Query(
        None,
        ge=0,
        le=1,
        description="1=横图裁右侧竖幅（列表默认）；0=保持横图（预览/fanart）",
    ),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> Response:
    """按 data 相对路径返回本地封面；?w= 缩略并走 cover-cache。"""
    try:
        abs_path = svc.resolve_local_file(path)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e

    width = int(w) if w else 0
    # 列表缩略：仅显式 rp=1，或文件名像 thumb/fanart 时才右裁；
    # poster.jpg 等竖图不要因 ?w= 默认右裁。
    do_rp = bool(rp) if rp is not None else False
    if rp is None and width > 0:
        low = str(path or "").replace("\\", "/").lower()
        name = low.rsplit("/", 1)[-1]
        do_rp = (
            ("thumb" in name)
            or ("fanart" in name)
            or name.startswith("landscape")
        )
    etag = _local_file_etag(abs_path, width or None, rp=do_rp)
    if_none = (request.headers.get("if-none-match") or "").strip()
    if if_none and if_none == etag:
        return Response(status_code=304, headers={**_CACHE_HEADERS, "ETag": etag})

    mime, _ = mimetypes.guess_type(str(abs_path))
    media = mime or "application/octet-stream"
    headers = {**_CACHE_HEADERS, "ETag": etag}

    if width <= 0:
        return FileResponse(
            abs_path,
            media_type=media,
            filename=abs_path.name,
            headers=headers,
        )

    st = abs_path.stat()
    rp_flag = 1 if do_rp else 0
    cache_key = hashlib.sha1(
        f"scrap-file-v2|{path}|{st.st_mtime_ns}|{st.st_size}|w={width}|rp={rp_flag}".encode(
            "utf-8"
        )
    ).hexdigest()
    hit = _mem_get(cache_key) or _disk_get(cache_key)
    if hit is not None:
        data, ctype = hit
        _mem_put(cache_key, data, ctype)
        return Response(content=data, media_type=ctype, headers=headers)

    try:
        raw = abs_path.read_bytes()
    except OSError as e:
        raise HTTPException(404, str(e)) from e

    resized = _resize_cover(raw, width, right_portrait=do_rp)
    if resized is not None:
        data, ctype = resized
    else:
        data, ctype = raw, media
    _mem_put(cache_key, data, ctype)
    _disk_put(cache_key, data, ctype)
    return Response(content=data, media_type=ctype, headers=headers)
