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

class SettingsBody(BaseModel):
    root: str = ""


class StartBody(BaseModel):
    root: str = ""
    force: bool = False
    # full=元数据+向量（兼容）；meta=仅同步数据库；embed=仅向量化
    mode: str = "full"


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


@router.post("/embed/reset-skeletons")
def reset_to_skeletons(_user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """清空向量库并按六区目录重建仅番号骨架（本地 NFO 不删）。"""
    try:
        data = svc.reset_embed_to_catalog_skeletons()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e
    return {"ok": bool(data.get("ok")), "data": data}


@router.get("/embed/quality")
def get_quality(
    region: str = Query("japan_censored"),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        return {"ok": True, "data": svc.quality_stats(region=region)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e


@router.get("/embed/quality/items")
def get_quality_items(
    kind: str = Query("no_local"),
    region: str = Query("japan_censored"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        items = svc.quality_items(
            region=region, kind=kind, limit=limit, offset=offset
        )
        return {"ok": True, "data": {"items": items, "kind": kind, "region": region}}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e


@router.get("/embed/quality/gate")
def get_quality_gate(
    itemId: str = Query(""),
    code: str = Query(""),
    relPath: str = Query(""),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """G34：单条合格门禁（只读）。按 itemId / code / relPath 定位本地 NFO+poster。"""
    from pathlib import Path

    from app.scrap_library.quality_gate import evaluate_quality_gate

    folder: Path | None = None
    try:
        settings = svc.get_settings()
        root = svc.resolve_root(settings.get("root"))
        iid = str(itemId or "").strip()
        rel = str(relPath or "").strip().replace("\\", "/")
        code_u = str(code or "").strip().upper()
        if iid or (code_u and not rel):
            try:
                from app.core.db import connect

                table = getattr(svc, "TABLE", "scrap_library_embed")
                with connect() as conn:
                    with conn.cursor() as cur:
                        if iid:
                            cur.execute(
                                f"""
                                SELECT rel_path, code
                                FROM {table}
                                WHERE item_id = %s
                                LIMIT 1
                                """,
                                (iid,),
                            )
                        else:
                            cur.execute(
                                f"""
                                SELECT rel_path, code
                                FROM {table}
                                WHERE UPPER(code) = %s
                                LIMIT 1
                                """,
                                (code_u,),
                            )
                        r = cur.fetchone()
                        if r:
                            if isinstance(r, dict):
                                rel = str(r.get("rel_path") or rel)
                                code_u = str(r.get("code") or code_u).upper()
                            else:
                                rel = str(r[0] or rel)
                                code_u = str(r[1] or code_u).upper()
            except Exception:  # noqa: BLE001
                pass
        if rel:
            folder = (root / rel).resolve()
            try:
                folder.relative_to(root.resolve())
            except ValueError as e:
                raise HTTPException(400, "bad path") from e
            if not folder.is_dir():
                folder = None
        data = evaluate_quality_gate(folder=folder, code=code_u)
        return {"ok": True, "data": data}
    except HTTPException:
        raise
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
        data = svc.start_ingest_job(
            root=body.root,
            force=bool(body.force),
            mode=str(body.mode or "full"),
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


@router.post("/embed/ensure-poster")
def ensure_poster(
    itemId: str = Query("", alias="itemId"),
    coverUrl: str = Query("", alias="coverUrl"),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """缺本地海报时把 NFO cover 外链下载到番号目录 poster.jpg。"""
    iid = str(itemId or "").strip()
    cover = str(coverUrl or "").strip()
    if not iid and not cover:
        raise HTTPException(400, "itemId or coverUrl required")
    try:
        if iid:
            data = svc.ensure_local_poster(item_id=iid, cover_url=cover)
        else:
            data = svc.ensure_local_poster_by_cover(cover_url=cover)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


class PlotSaveBody(BaseModel):
    itemId: str = Field(default="", alias="itemId")
    plot: str = ""

    model_config = {"populate_by_name": True}


@router.post("/embed/plot")
def save_plot(
    body: PlotSaveBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """保存中文剧情到 NFO 并重嵌入（详情页一键翻译落库）。"""
    import app.scrap_library.enrich as enrich_svc

    iid = str(body.itemId or "").strip()
    plot = str(body.plot or "").strip()
    if not iid:
        raise HTTPException(400, "itemId 必填")
    if len(plot) < 2:
        raise HTTPException(400, "剧情太短")
    try:
        data = enrich_svc.save_item_plot(item_id=iid, plot=plot)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


class SubtitleFetchBody(BaseModel):
    itemId: str = ""
    code: str = ""
    force: bool = False
    # 搜到后立即上传 115 字幕目录
    upload115: bool = Field(default=False, alias="upload115")
    region: str = ""

    model_config = {"populate_by_name": True}


@router.get("/embed/subtitles")
def get_subtitles(
    itemId: str = Query("", alias="itemId"),
    code: str = Query(""),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    import app.scrap_library.subtitles as scrap_subtitles

    try:
        data = scrap_subtitles.local_subs_for_code_or_item(
            item_id=itemId, code=code
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


@router.post("/embed/subtitles/fetch")
def fetch_subtitles(
    body: SubtitleFetchBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """搜中文字幕 → 本地保存；可选立即上传 115 字幕目录。"""
    import app.scrap_library.subtitles as scrap_subtitles

    if not str(body.itemId or "").strip() and not str(body.code or "").strip():
        raise HTTPException(400, "itemId 或 code 必填")
    try:
        data = scrap_subtitles.fetch_and_save_for_item(
            item_id=body.itemId,
            code=body.code,
            force=bool(body.force),
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e

    # 本地已有或新下成功：按需立刻上 115
    if (
        bool(body.upload115)
        and data.get("ok")
        and list(data.get("files") or [])
    ):
        try:
            import app.core.settings_store as settings_store
            from app.core.conn_settings_routes import (
                _attach_local_subs_to_115,
                _resolve_p115_folder,
            )

            prev = settings_store.get_setting(settings_store.P115_KEY) or {}
            cookie = str(prev.get("cookie") or "").strip()
            if not cookie:
                data["upload115"] = {
                    "ok": False,
                    "count": 0,
                    "message": "尚未配置 115 Cookie",
                }
            else:
                makers_root_cid, _ = _resolve_p115_folder(prev, source="makers")
                up = _attach_local_subs_to_115(
                    cookie,
                    makers_root_cid,
                    attach_subs_code=str(data.get("code") or body.code or ""),
                    scrap_item_id=str(
                        data.get("itemId") or body.itemId or ""
                    ),
                    makers_root_cid=makers_root_cid,
                    region=str(body.region or "").strip() or None,
                    settings_raw=prev,
                ) or {"ok": False, "count": 0, "message": "未上传"}
                data["upload115"] = up
                if up.get("ok") and up.get("count"):
                    data["message"] = (
                        f"{data.get('message') or '字幕已就绪'} · {up.get('message')}"
                    )
                elif up.get("message"):
                    data["message"] = (
                        f"{data.get('message') or '字幕已保存本地'} · "
                        f"115：{up.get('message')}"
                    )
        except Exception as e:  # noqa: BLE001
            data["upload115"] = {
                "ok": False,
                "count": 0,
                "message": f"上传 115 异常：{e}",
            }
            data["message"] = (
                f"{data.get('message') or '字幕已保存本地'} · 上传 115 异常：{e}"
            )

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
    q: str = Query(""),
    limit: int | None = Query(None, ge=1, le=100),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            "data": {
                "prefixes": svc.list_prefixes(
                    region=region, studio=studio, q=q, limit=limit
                ),
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
    signal: str = Query(""),
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
                signal=signal,
                sort=sort,
                order=order,
                offset=offset,
                limit=limit,
                display_only=True,
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
    q: str = Query(""),
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
                q=q,
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


class FacetsRefreshBody(BaseModel):
    region: str = ""
    kinds: list[str] | None = None
    allRegions: bool = True


@router.get("/embed/facets/snapshot")
def get_facets_snapshot_meta(
    region: str = Query(""),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {"ok": True, "data": svc.facets_snapshot_meta(region=region)}


@router.post("/embed/facets/refresh")
def refresh_facets_snapshot(
    body: FacetsRefreshBody | None = None,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """重建浏览快照：默认六区厂牌/标签/女优 + 推荐 + 影片首页预热。"""
    payload = body or FacetsRefreshBody()
    try:
        data = svc.refresh_facets_snapshot(
            region=str(payload.region or ""),
            kinds=payload.kinds,
            all_regions=bool(payload.allRegions),
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


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
