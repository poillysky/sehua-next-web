"""刮削导出 API。"""

from __future__ import annotations

from email.utils import formatdate
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
import threading

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .auth_routes import get_optional_user, require_user
from . import library_materialize, scrape_export
from .outbound_http import httpx_client

router = APIRouter(tags=["scrape-export"])

_EXPORT_MEDIA_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _file_cache_headers(path: Path) -> dict[str, str]:
    st = path.stat()
    return {
        "Cache-Control": "public, max-age=0, must-revalidate",
        "ETag": f'"{int(st.st_mtime_ns)}-{int(st.st_size)}"',
        "Last-Modified": formatdate(st.st_mtime, usegmt=True),
    }


def _wrap(data: Any, message: str = "ok", status: int = 200) -> dict[str, Any]:
    return {"data": data, "message": message, "status": status}


class ExportBody(BaseModel):
    task_id: str = Field(default="", alias="taskId")
    name: str = ""
    region: str = ""
    regions: list[str] | None = None
    maker: str = ""
    prefix: str = ""
    code: str = ""
    force: bool = False
    mode: Literal["incremental", "force"] | str | None = None
    fields: list[str] | None = None
    local_fields: list[str] | None = Field(default=None, alias="localFields")

    model_config = {"populate_by_name": True}


@router.get("/scrape/export/status")
def get_export_status(
    events: int = Query(default=80, ge=0, le=400),
    codes: int = Query(
        default=0,
        ge=0,
        le=1,
        description="1=返回完整番号列表（可能很大）；0=截断，适合轮询",
    ),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    return _wrap(
        scrape_export.export_status(
            event_limit=events,
            include_codes=bool(codes),
        )
    )


@router.get("/scrape/export/codes")
def get_export_codes(
    task_id: str = Query(default="", alias="taskId"),
    bucket: str = Query(default="failed"),
    limit: int = Query(default=50000, ge=1, le=100000),
    offset: int = Query(default=0, ge=0),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    """任务卡点开成功/跳过/失败时取完整番号列表（SQLite）。"""
    return _wrap(
        scrape_export.list_export_codes(
            task_id=task_id or None,
            bucket=bucket,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/scrape/export/detail")
def get_export_detail(
    code: str = Query(..., min_length=1, max_length=64),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    """按番号查看刮削详细数据（任务卡统计点击用）。"""
    detail = scrape_export.lookup_export_detail(code)
    if not detail:
        raise HTTPException(status_code=404, detail="未找到该番号详情")
    return _wrap(detail)


@router.get("/scrape/export/events")
def get_export_events(
    code: str = Query(..., min_length=1, max_length=64),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    """按番号查看刮削过程日志（成功队列点进「刮削日志」用）。"""
    events = scrape_export.lookup_export_events(code)
    c = str(code or "").strip().upper().replace("_", "-")
    if events and isinstance(events[0], dict) and events[0].get("code"):
        c = str(events[0].get("code") or c)
    return _wrap({"code": c, "events": events})


@router.post("/scrape/export")
def start_export(
    body: ExportBody = Body(default_factory=ExportBody),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    regions = [str(r).strip() for r in (body.regions or []) if str(r).strip()]
    try:
        st = scrape_export.submit_export_job(
            task_id=(body.task_id or "").strip() or None,
            task_name=(body.name or "").strip() or None,
            region=(body.region or "").strip() or None,
            regions=regions or None,
            maker=(body.maker or "").strip() or None,
            prefix=(body.prefix or "").strip() or None,
            code=(body.code or "").strip() or None,
            force=bool(body.force),
            mode=(str(body.mode).strip() if body.mode else None) or None,
            fields=list(body.fields) if body.fields is not None else None,
            local_fields=(
                list(body.local_fields) if body.local_fields is not None else None
            ),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    q = st.get("queue") or []
    running = bool(st.get("running"))
    tid = str(st.get("taskId") or "")
    req_tid = (body.task_id or "").strip()
    if running and req_tid and tid != req_tid:
        msg = "已加入队列"
    elif running and q:
        msg = "已开始导出（后续任务排队中）"
    elif running:
        msg = "已开始导出"
    else:
        msg = "已加入队列"
    return _wrap(st, msg)


@router.get("/scrape/export/preview")
def preview_export(
    region: str = "",
    regions: list[str] | None = Query(default=None),
    maker: str = "",
    prefix: str = "",
    code: str = "",
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    region_list = [str(r).strip() for r in (regions or []) if str(r).strip()]
    items = scrape_export.collect_targets(
        region=region or None,
        regions=region_list or None,
        maker=maker or None,
        prefix=prefix or None,
        code=code or None,
    )
    return _wrap(
        {
            "count": len(items),
            "sample": items[:8],
            "libraryRoot": scrape_export.scrape_settings()["libraryRoot"],
        }
    )


@router.post("/scrape/export/pause")
def pause_export(
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        return _wrap(scrape_export.pause_export(), "已暂停")
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/scrape/export/resume")
def resume_export(
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        return _wrap(scrape_export.resume_export(), "已继续")
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/scrape/export/reset-checkpoint")
def reset_checkpoint(
    task_id: str = Query(..., alias="taskId"),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """重置任务卡时清除该任务断点，避免再次开始只续跑残留番号。"""
    try:
        return _wrap(scrape_export.clear_task_resume(task_id), "已清除断点")
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/scrape/export/purge-task")
def purge_task_logs(
    task_id: str = Query(..., alias="taskId"),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """删除任务卡时清理该任务的 SQLite 过程日志与结果番号。"""
    try:
        return _wrap(scrape_export.purge_task_logs(task_id), "已清理任务日志")
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/scrape/export")
def clear_export(
    task_id: str = Query(default="", alias="taskId"),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """无 taskId：清空全局进度/停当前并清队列。
    有 taskId：只停该任务（取消当前或移出队列），不影响其它排队任务。
    """
    tid = str(task_id or "").strip()
    if tid:
        try:
            return _wrap(scrape_export.stop_export_task(tid), "已停止该任务")
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    return _wrap(scrape_export.clear_export(), "已删除")


@router.post("/scrape/export/cancel")
def cancel_export_task(
    task_id: str = Query(default="", alias="taskId"),
    keep_queue: bool = Query(default=True, alias="keepQueue"),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """取消当前刮削；默认保留队列。传 taskId 时按任务隔离停止。"""
    tid = str(task_id or "").strip()
    try:
        if tid:
            return _wrap(scrape_export.stop_export_task(tid), "已停止该任务")
        return _wrap(
            scrape_export.cancel_export(keep_queue=bool(keep_queue)),
            "已取消",
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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
    lib = Path(scrape_export.scrape_settings()["libraryRoot"])
    # libraryRoot 可能是相对路径
    if not lib.is_absolute():
        from .db import ROOT

        lib = (ROOT / lib).resolve()
    else:
        lib = lib.resolve()
    target = (lib / raw).resolve()
    try:
        target.relative_to(lib)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="越界路径") from e
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(target, headers=_file_cache_headers(target))


@router.get("/scrape/export/img")
def export_remote_img(
    u: str = Query(default="", max_length=2000),
    url: str = Query(default="", max_length=2000),
    code: str = Query(default="", max_length=64),
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> Response:
    """代理远程封面（进度预览）。前端传 u= / 可选 code。"""
    raw = (u or url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="缺少图片地址")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="非法 URL")
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": f"{parsed.scheme}://{parsed.netloc}/",
        }
        with httpx_client(timeout=20.0) as client:
            res = client.get(raw, headers=headers)
            if res.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"拉取失败 {res.status_code}")
            ctype = res.headers.get("content-type") or "image/jpeg"
            return Response(content=res.content, media_type=ctype.split(";")[0].strip())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


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
