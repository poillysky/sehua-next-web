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

class EnrichBody(BaseModel):
    region: str = ""
    # 空 = 使用策略里已开启的六区
    regions: list[str] = Field(default_factory=list)
    # 空 = 服务端默认完整补齐（封面+女优/片商/剧情/标题）
    kinds: list[str] = Field(default_factory=list)
    # 0 = 全量缺口；预览可由前端传小样本
    limit: int = Field(default=0, ge=0, le=20_000)
    dryRun: bool = False
    # incremental = 仅补缺；overwrite = 全量覆盖已有
    mode: str = "incremental"


class EnrichOneBody(BaseModel):
    itemId: str = ""
    dryRun: bool = False
    # 详情「刷新元数据」默认全量覆盖（重刮 + 覆盖 NFO/向量）
    overwrite: bool = True
    # False：只写本地 NFO/封面（设置页分区刮削/重刮）；True：详情页顺带同步向量+女优
    syncVector: bool = True


class EnrichStrategyCoverBody(BaseModel):
    quality: str = "compact"
    cropRatio: str = "full"
    regionCrop: dict[str, str] = Field(default_factory=dict)
    minShortEdge: int = Field(default=400, ge=120, le=1200)
    coverLogicVersion: int = 9


class EnrichStrategyLocalMapsBody(BaseModel):
    """标题/女优/标签映射模式为字符串；换行精简为布尔。"""

    title: str | None = None
    actors: str | None = None
    tags: str | None = None
    compactOutlineNewlines: bool | None = None


class EnrichStrategyBody(BaseModel):
    mode: str = "parallel_all"
    itemWorkers: int = Field(default=5, ge=1, le=16)
    adaptiveWorkers: int = Field(default=0, ge=0, le=64)
    flareWorkers: int = Field(default=0, ge=0, le=64)
    includeFlare: bool = True
    perSourceTimeoutSec: int = Field(default=45, ge=5, le=180)
    regionGroups: dict[str, list[str]] = Field(default_factory=dict)
    regionSources: dict[str, list[str]] = Field(default_factory=dict)
    regionsEnabled: dict[str, bool] = Field(default_factory=dict)
    fillMode: str = "incremental"
    actressAvatarMode: str = "incremental"
    llmTranslateOnJunk: bool = True
    fieldLanguage: dict[str, str] = Field(default_factory=dict)
    stripTitleActorSuffix: bool = False
    stripTitleCodePrefix: bool = False
    fc2SellerAsActor: bool = True
    coverEnhance: str = "off"
    outlineShow: str = "zh"
    forceFields: list[str] = Field(default_factory=list)
    fieldPriority: dict[str, list[str]] = Field(default_factory=dict)
    fieldPriorityHideEmpty: bool = False
    localMaps: EnrichStrategyLocalMapsBody = Field(
        default_factory=EnrichStrategyLocalMapsBody
    )
    cover: EnrichStrategyCoverBody | None = None


@router.get("/embed/enrich/strategy")
def get_enrich_strategy(
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    import app.scrap_library.enrich_strategy as strat

    return {"ok": True, "data": strat.strategy_public()}


@router.put("/embed/enrich/strategy")
def put_enrich_strategy(
    body: EnrichStrategyBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    import app.scrap_library.enrich_strategy as strat

    payload = body.model_dump()
    if payload.get("cover") is None:
        payload.pop("cover", None)
    # localMaps 嵌套模型：去掉未传的 None，避免覆盖已有配置
    maps = payload.get("localMaps")
    if isinstance(maps, dict):
        payload["localMaps"] = {k: v for k, v in maps.items() if v is not None}
    saved = strat.put_strategy(payload)
    return {"ok": True, "data": strat.strategy_public(saved)}


@router.post("/embed/enrich")
def start_enrich(
    body: EnrichBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    import app.scrap_library.enrich as enrich_svc

    try:
        data = enrich_svc.start_enrich_job(
            region=body.region,
            regions=list(body.regions or []),
            kinds=list(body.kinds or []),
            limit=int(body.limit),
            dry_run=bool(body.dryRun),
            mode=str(body.mode or "incremental"),
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


@router.post("/embed/enrich/one")
def enrich_one(
    body: EnrichOneBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """详情页：按批量补全逻辑同步补这一条，返回更新后的条目。"""
    import app.scrap_library.enrich as enrich_svc

    try:
        data = enrich_svc.enrich_one_by_item_id(
            item_id=body.itemId,
            dry_run=bool(body.dryRun),
            overwrite=bool(body.overwrite),
            sync_vector=bool(body.syncVector),
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


@router.get("/embed/enrich/status")
def get_enrich_status(
    lite: bool = False,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    import app.scrap_library.enrich as enrich_svc

    return {"ok": True, "data": enrich_svc.get_enrich_status(lite=bool(lite))}


@router.get("/embed/enrich/status/stream")
async def enrich_status_stream(
    request: Request,
    lite: bool = False,
    _user: dict[str, Any] = Depends(require_user),
):
    """SSE：刮削状态变更时推送（替代 450ms 轮询）。

    lite=1：总览角标用，不含 queue 抽样（避免设置页卡死）。
    """
    import asyncio
    import json

    import app.scrap_library.enrich as enrich_svc
    from fastapi.responses import StreamingResponse

    want_lite = bool(lite)

    async def gen():
        sub = enrich_svc.subscribe_enrich_updates()
        last = ""
        # 构建一帧状态偏重；通知风暴必须限流。
        # 详情帧含 monitor.elapsedMs，若不抬高间隔会几乎每拍都变、前端一直重绘卡顿。
        min_gap_sec = 1.0 if want_lite else 0.75
        try:
            while True:
                if await request.is_disconnected():
                    break
                t_build0 = asyncio.get_running_loop().time()
                snap = await asyncio.to_thread(
                    lambda: enrich_svc.get_enrich_status(lite=want_lite)
                )
                payload = json.dumps(
                    {"event": "status", "data": snap},
                    ensure_ascii=False,
                    default=str,
                )
                if payload != last:
                    last = payload
                    yield f"data: {payload}\n\n".encode("utf-8")
                spent = asyncio.get_running_loop().time() - t_build0
                if spent < min_gap_sec:
                    await asyncio.sleep(min_gap_sec - spent)
                woken = await asyncio.to_thread(sub.wait, 12.0)
                sub.clear()
                if not woken:
                    yield b": ping\n\n"
        finally:
            enrich_svc.unsubscribe_enrich_updates(sub)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class RecompressBody(BaseModel):
    region: str = ""
    quality: str = ""
    # 0 = 全量；预览可传小样本
    limit: int = Field(default=0, ge=0, le=20_000)
    dryRun: bool = False


@router.post("/embed/posters/recompress")
def start_poster_recompress(
    body: RecompressBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """按当前策略画质重压已落盘 poster.jpg（不改构图）。"""
    from app.scrap_library import poster_recompress as svc

    try:
        data = svc.start_job(
            region=str(body.region or ""),
            quality=str(body.quality or ""),
            limit=int(body.limit or 0),
            dry_run=bool(body.dryRun),
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


@router.get("/embed/posters/recompress/status")
def get_poster_recompress_status(
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    from app.scrap_library import poster_recompress as svc

    return {"ok": True, "data": svc.get_status()}


@router.get("/embed/enrich/logs")
def get_enrich_logs(
    region: str = Query("", alias="region"),
    limit: int = Query(200, ge=1, le=500),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """分区刮削日志（元库持久化，重启可查）。"""
    import app.scrap_library.enrich as enrich_svc

    rid = str(region or "").strip()
    lines = enrich_svc.load_enrich_logs(region=rid, limit=limit)
    return {"ok": True, "data": {"region": rid or None, "log": lines}}


class EnrichLogsClearBody(BaseModel):
    region: str = ""


@router.post("/embed/enrich/logs/clear")
def clear_enrich_logs_route(
    body: EnrichLogsClearBody | None = None,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """清空分区刮削日志表（文本日志 + 队列记录）并清除该区旧检查点。"""
    import app.scrap_library.enrich as enrich_svc

    rid = str((body.region if body else "") or "").strip()
    return {"ok": True, "data": enrich_svc.clear_enrich_logs(region=rid)}


@router.get("/embed/enrich/queue-log")
def get_enrich_queue_log(
    region: str = Query("", alias="region"),
    status: str = Query("", alias="status"),
    code: str = Query("", alias="code"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=1_000_000),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """刮削队列日志表：各状态任务记录（仅清空日志会删除）。支持 code 查番号。"""
    import app.scrap_library.enrich as enrich_svc

    rid = str(region or "").strip()
    st = str(status or "").strip()
    code_q = str(code or "").strip()
    return {
        "ok": True,
        "data": enrich_svc.load_queue_log(
            region=rid,
            status=st,
            limit=limit,
            offset=offset,
            code=code_q,
        ),
    }


@router.get("/embed/enrich/local-covers")
def get_enrich_local_covers(
    region: str = Query("", alias="region"),
    code: str = Query("", alias="code"),
    itemId: str = Query("", alias="itemId"),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """检查用：番号目录里已落盘的 poster/thumb/fanart。"""
    import app.scrap_library.enrich as enrich_svc

    return {
        "ok": True,
        "data": enrich_svc.list_local_covers(
            region=str(region or "").strip(),
            code=str(code or "").strip(),
            item_id=str(itemId or "").strip(),
        ),
    }


class EnrichQueueScanBody(BaseModel):
    region: str = ""
    limit: int = Field(default=0, ge=0, le=50_000)


@router.post("/embed/enrich/queue-scan")
def scan_enrich_queue(
    body: EnrichQueueScanBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """打开分区日志：扫描缺口写入 pending，刷新成功/失败计数（不启动任务）。"""
    import app.scrap_library.enrich as enrich_svc

    rid = str(body.region or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="region required")
    return {
        "ok": True,
        "data": enrich_svc.scan_enrich_queue(region=rid, limit=int(body.limit or 0)),
    }


@router.post("/embed/enrich/cancel")
def cancel_enrich(
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """取消刮削：语义等同暂停（保留进度/checkpoint）。"""
    import app.scrap_library.enrich as enrich_svc

    return {"ok": True, "data": enrich_svc.request_enrich_cancel()}


@router.post("/embed/enrich/pause")
def pause_enrich(
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    import app.scrap_library.enrich as enrich_svc

    return {"ok": True, "data": enrich_svc.request_enrich_pause()}


class EnrichStopBody(BaseModel):
    region: str = ""


@router.post("/embed/enrich/stop")
def stop_enrich(
    body: EnrichStopBody | None = None,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """停止并清除队列；下次开始从头跑。"""
    import app.scrap_library.enrich as enrich_svc

    rid = str((body.region if body else "") or "").strip()
    return {"ok": True, "data": enrich_svc.request_enrich_stop(region=rid)}


class EnrichRetryFailsBody(BaseModel):
    region: str = ""


@router.post("/embed/enrich/retry-fails")
def retry_enrich_fails(
    body: EnrichRetryFailsBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """失败批量重试：转入未处理队列，运行中则插到最前优先处理。"""
    import app.scrap_library.enrich as enrich_svc

    rid = str(body.region or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="region required")
    return {"ok": True, "data": enrich_svc.retry_enrich_fails(region=rid)}


class EnrichRetrySoftsBody(BaseModel):
    region: str = ""


@router.post("/embed/enrich/retry-softs")
def retry_enrich_softs(
    body: EnrichRetrySoftsBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """软成功批量重试：转入未处理队列，运行中则插到最前优先处理。"""
    import app.scrap_library.enrich as enrich_svc

    rid = str(body.region or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="region required")
    return {"ok": True, "data": enrich_svc.retry_enrich_softs(region=rid)}

