"""刮削导出 API。"""

from __future__ import annotations

from email.utils import formatdate
from pathlib import Path
from typing import Any
import threading

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from .auth_routes import get_optional_user, require_user
from . import library_materialize, scrape_export
from .cover_focus_routes import _fetch_bytes, _safe_image_url

router = APIRouter(tags=["scrape-export"])

_EXPORT_MEDIA_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _file_cache_headers(path: Path) -> dict[str, str]:
    st = path.stat()
    long_cache = library_materialize.LIBRARY_COVERS_DIR in path.parts
    return {
        "Cache-Control": (
            "public, max-age=604800, immutable"
            if long_cache
            else "public, max-age=0, must-revalidate"
        ),
        "ETag": f'"{int(st.st_mtime_ns)}-{int(st.st_size)}"',
        "Last-Modified": formatdate(st.st_mtime, usegmt=True),
    }


def _wrap(data: Any, message: str = "ok", status: int = 200) -> dict[str, Any]:
    return {"data": data, "message": message, "status": status}


# 刮削端任务路由已移除（改用 MDC 代理）
# 保留 detail/events、file/img、library/* 供本地库与番号页元数据使用


@router.get("/scrape/export/detail")
def export_detail(
    code: str = Query(..., min_length=1, max_length=64),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    data = scrape_export.lookup_export_detail(code)
    if not data:
        raise HTTPException(status_code=404, detail="未找到番号")
    return _wrap(data)


@router.get("/scrape/export/events")
def export_events(
    code: str = Query(..., min_length=1, max_length=64),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    c = str(code or "").strip()
    events = scrape_export.lookup_export_events(c)
    return _wrap({"code": c, "events": events})


@router.get("/scrape/export/file")
def export_library_file(
    rel: str = Query(..., min_length=1, max_length=480),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> FileResponse:
    """读取 library 内相对路径图片（进度页封面预览）。"""
    raw = str(rel or "").replace("\\", "/").strip().lstrip("/")
    if (
        not raw
        or raw.startswith("/")
        or ".." in Path(raw).parts
        or Path(raw).suffix.lower() not in _EXPORT_MEDIA_EXT
    ):
        raise HTTPException(status_code=400, detail="非法路径")
    from . import library_materialize as lm

    target = lm.resolve_library_media_path(raw)
    if target is not None:
        return FileResponse(target, headers=_file_cache_headers(target))
    raise HTTPException(status_code=404, detail="文件不存在")


@router.get("/scrape/export/img")
def export_remote_img(
    u: str = Query(default="", max_length=2000),
    url: str = Query(default="", max_length=2000),
    code: str = Query(default="", max_length=64),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> Response:
    """代理远程封面（进度预览）。与 /cover-proxy 共用 Referer / 超时策略。"""
    _ = code
    raw = (u or url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="缺少图片地址")
    safe = _safe_image_url(raw)
    try:
        data, ctype = _fetch_bytes(safe)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return Response(
        content=data,
        media_type=ctype,
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---- library materialize + browse ----


@router.get("/scrape/library/status")
def get_library_materialize_status(
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    return _wrap(library_materialize.materialize_status())


@router.post("/scrape/library/materialize")
def start_library_materialize(
    region: str = Query("", description="分区 id，空=全部"),
    sync: int = Query(0, description="1=同步执行"),
    force: int = Query(0, description="1=强制抢占僵死任务"),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    region_key = (region or "").strip() or None
    if sync == 1:
        try:
            result = library_materialize.materialize_library(region=region_key)
            return _wrap(result, "同步完成")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    if not library_materialize.claim_materialize(
        region=region_key, force=force == 1
    ):
        st = library_materialize.materialize_status()
        detail = "本地片库同步正在进行中"
        cur = str(st.get("currentCode") or "").strip()
        done = st.get("done")
        total = st.get("total")
        msg = str(st.get("message") or "").strip()
        if total:
            detail = f"{detail}（{done or 0}/{total}"
            if cur:
                detail = f"{detail} · {cur}"
            detail = f"{detail}）"
        elif msg:
            detail = f"{detail}（{msg}）"
        raise HTTPException(status_code=409, detail=detail)

    def _job() -> None:
        try:
            library_materialize.materialize_library(region=region_key)
        except RuntimeError as e:
            # 另一任务已持锁：勿清 running，避免把正在跑的任务标成失败
            if "正在进行中" in str(e):
                return
            library_materialize.fail_materialize(str(e) or "failed")
        except Exception as e:
            library_materialize.fail_materialize(str(e) or "failed")

    # 独立线程：避免长时间占用 anyio 线程池导致 status 等接口饿死
    threading.Thread(
        target=_job, name="library-materialize", daemon=True
    ).start()
    return _wrap(library_materialize.materialize_status(), "已开始同步本地片库")


@router.get("/scrape/library/regions")
def library_regions(
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    return _wrap(library_materialize.browse_regions())


@router.get("/scrape/library/regions/{region_id}")
def library_region(
    region_id: str,
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    data = library_materialize.browse_region(region_id)
    if not data:
        raise HTTPException(status_code=404, detail="未知分区")
    return _wrap(data)


@router.get("/scrape/library/regions/{region_id}/facets")
def library_region_facets(
    region_id: str,
    rebuild: bool = Query(False),
    sync: bool = Query(False),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    data = library_materialize.browse_region_facets(
        region_id,
        rebuild=rebuild,
        sync=sync,
    )
    if not data:
        raise HTTPException(status_code=404, detail="未知分区")
    return _wrap(data)


@router.get("/scrape/library/facet-codes")
def library_facet_codes(
    region: str = Query(..., min_length=1),
    kind: str = Query(..., min_length=1),
    value: str = Query(..., min_length=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    data = library_materialize.browse_facet_codes(
        region=region,
        kind=kind,
        value=value,
        offset=offset,
        limit=limit,
    )
    if data is None:
        raise HTTPException(status_code=404, detail="未知分区或分类")
    return _wrap(data)


@router.get("/scrape/library/tile-covers")
def library_tile_covers(
    region: str = Query(..., min_length=1),
    studio: str = Query(..., min_length=1),
    prefix: str = Query(""),
    prefixes: str = Query(""),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    """前缀卡：最新 1 张；厂牌卡：最新前缀的最新番号 1 张。"""
    return _wrap(
        library_materialize.browse_tile_covers(
            region=region,
            studio=studio,
            prefix=prefix or "",
            prefixes=prefixes or "",
        )
    )


@router.post("/scrape/library/tile-covers/batch")
def library_tile_covers_batch(
    payload: dict[str, Any] = Body(...),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    """片商/前缀格子一次取齐封面库路径。"""
    region = str((payload or {}).get("region") or "")
    queries = (payload or {}).get("queries")
    if not isinstance(queries, list):
        queries = []
    return _wrap(
        library_materialize.browse_tile_covers_batch(
            region=region,
            queries=queries,
        )
    )


@router.get("/scrape/library/codes")
def library_codes(
    region: str = Query(..., min_length=1),
    studio: str = Query(..., min_length=1),
    prefix: str = Query(..., min_length=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    q: str = Query(""),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    data = library_materialize.browse_codes(
        region=region,
        studio=studio,
        prefix=prefix,
        offset=offset,
        limit=limit,
        q=q or None,
    )
    if data is None:
        raise HTTPException(status_code=404, detail="未知分区")
    return _wrap(data)
