# -*- coding: utf-8 -*-
"""刮削库向量灌库 API（写入元库 SNS_META_DSN / :5439）。"""

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
    # 封面会被 overwrite 重刮；勿用 immutable/长 max-age（Cursor 内置浏览器尤甚）。
    # ETag 含 mtime：未变走 304，变了立刻换新图。
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


@router.get("/embed/status")
def get_status(_user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return {"ok": True, "data": svc.get_job_status()}


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
