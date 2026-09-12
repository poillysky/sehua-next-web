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


@router.post("/embed/reset-skeletons")
def reset_to_skeletons(_user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """清空向量库并按七区目录重建仅番号骨架（本地 NFO 不删）。"""
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


class EnrichBody(BaseModel):
    region: str = ""
    # 空 = 使用策略里已开启的七区
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


class EnrichStrategyCoverBody(BaseModel):
    quality: str = "high"
    cropRatio: str = "full"
    regionCrop: dict[str, str] = Field(default_factory=dict)


class EnrichStrategyBody(BaseModel):
    mode: str = "parallel_all"
    adaptiveWorkers: int = Field(default=0, ge=0, le=64)
    flareWorkers: int = Field(default=0, ge=0, le=64)
    includeFlare: bool = True
    perSourceTimeoutSec: int = Field(default=45, ge=5, le=180)
    regionGroups: dict[str, list[str]] = Field(default_factory=dict)
    regionsEnabled: dict[str, bool] = Field(default_factory=dict)
    fillMode: str = "incremental"
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
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


@router.get("/embed/enrich/status")
def get_enrich_status(
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    import app.scrap_library.enrich as enrich_svc

    return {"ok": True, "data": enrich_svc.get_enrich_status()}


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


@router.post("/embed/enrich/cancel")
def cancel_enrich(
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """兼容旧接口：等同暂停（保留进度）。"""
    import app.scrap_library.enrich as enrich_svc

    return {"ok": True, "data": enrich_svc.request_enrich_pause()}


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


@router.get("/embed/status")
def get_status(_user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return {"ok": True, "data": svc.get_job_status()}


class ActressOptimizeBody(BaseModel):
    reembed: bool = True
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
    """批量优化女优元数据：中文标准名映射 + 排除导演/男优（不改 NFO）。"""
    try:
        lim = int(body.limit or 0)
        data = svc.start_actress_optimize_job(
            reembed=bool(body.reembed),
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


@router.post("/embed/actress-avatar/start")
def start_actress_avatar(
    body: ActressAvatarBody,
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """向量库女优 → GFriends 头像刮削落盘（media/scrap-library/_actress）。"""
    import app.scrap_library.actress_avatar as av

    try:
        lim = int(body.limit or 0)
        data = av.start_actress_avatar_job(
            force=bool(body.force),
            limit=lim if lim > 0 else None,
            region=str(body.region or ""),
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
        data = svc.start_ingest_job(root=body.root, force=bool(body.force))
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
    """重建浏览快照：默认七区厂牌/标签/女优 + 推荐 + 影片首页预热。"""
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
