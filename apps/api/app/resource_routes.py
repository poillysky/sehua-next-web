"""Resource browse / search / detail HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from . import prefix_ranges, prefix_service, resource_service
from .boards_nav import load_board_nav
from .pg import ResourceDbUnavailable

router = APIRouter(tags=["resources"])


def _wrap(data: Any, message: str = "ok", status: int = 200) -> dict[str, Any]:
    return {"data": data, "message": message, "status": status}


@router.get("/boards")
def boards() -> dict[str, Any]:
    try:
        return _wrap(load_board_nav(), "success")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/prefix-covers")
def prefix_covers(
    prefix: str = Query(..., min_length=1, max_length=40),
    codes: str = Query(
        ...,
        min_length=1,
        description="逗号分隔番号，如 SONE-1030,SONE-1029",
    ),
    bust: str = Query("0"),
    region: str = Query(""),
) -> dict[str, Any]:
    """预设番号格：按页回填库内封面（可按日本/国产/欧美裁板）。"""
    try:
        code_list = [c.strip() for c in codes.split(",") if c.strip()]
        do_bust = bust in {"1", "true", "True"}
        data = prefix_service.covers_for_codes(
            prefix,
            code_list,
            bust=do_bust,
            region=(region or "").strip() or None,
        )
        return _wrap(data, "success")
    except ResourceDbUnavailable as e:
        raise HTTPException(status_code=503, detail=e.message) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/prefix-range")
def prefix_range(
    prefix: str = Query(..., min_length=1, max_length=40),
    refresh: str = Query("0"),
) -> dict[str, Any]:
    """预设番号上限（库内 max + 余量；每日 00:00 增量刷新）。"""
    try:
        if refresh in {"1", "true", "True"}:
            prefix_ranges.refresh_from_db(incremental=True)
        data = prefix_ranges.get_range(prefix)
        if not data:
            return _wrap(
                {
                    "prefix": prefix.strip().upper(),
                    "from": 0,
                    "to": 0,
                    "pad": 3,
                    "total": 0,
                    "skip": True,
                },
                "success",
            )
        return _wrap(data, "success")
    except ResourceDbUnavailable as e:
        # 无库时仍可返回已缓存上限
        data = prefix_ranges.get_range(prefix)
        if data:
            return _wrap(data, "success")
        raise HTTPException(status_code=503, detail=e.message) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/prefix-range")
def put_prefix_range(
    prefix: str = Query(..., min_length=1, max_length=40),
    pad: int = Query(..., ge=1, le=8),
    lock: int = Query(1, ge=0, le=1),
) -> dict[str, Any]:
    """编辑前缀规范位数（抽码截断用）；默认锁定不被日刷覆盖。"""
    try:
        data = prefix_ranges.set_pad(prefix, pad, lock=bool(lock))
        if not data:
            raise HTTPException(status_code=404, detail="未知前缀")
        return _wrap(data, "success")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/prefix")
def prefix_resources(
    prefix: str = Query(..., min_length=1, max_length=40),
    p: int = Query(1, ge=1),
    ps: int = Query(60, ge=1, le=120),
    bust: str = Query("0"),
    region: str = Query(""),
) -> dict[str, Any]:
    try:
        do_bust = bust in {"1", "true", "True"}
        region_key = (region or "").strip() or None
        if do_bust:
            prefix_service.clear_prefix_cache(prefix, region=region_key)
        offset = (p - 1) * ps
        data = prefix_service.list_prefix_resources(
            prefix,
            limit=ps,
            offset=offset,
            bust=do_bust,
            region=region_key,
        )
        return _wrap(
            {
                **data,
                "page": p,
                "page_size": ps,
                "prefix": prefix.strip(),
            },
            "success",
        )
    except ResourceDbUnavailable as e:
        raise HTTPException(status_code=503, detail=e.message) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/browse")
def browse(
    p: int = Query(1, ge=1),
    ps: int = Query(10, ge=1, le=50),
    link_kind: str | None = Query(None),
    board_fid: str | None = Query(None),
    board: str | None = Query(None),
    board_parent: str | None = Query(None),
    keyword: str | None = Query(None, max_length=100),
    withTotalCount: str = Query("0"),
) -> dict[str, Any]:
    try:
        data = resource_service.browse_resources(
            p=p,
            ps=ps,
            link_kind=link_kind,
            board_fid=board_fid,
            board=board,
            board_parent=board_parent,
            keyword=keyword,
            with_total_count=withTotalCount in {"1", "true", "True"},
        )
        return _wrap(data, "success")
    except ResourceDbUnavailable as e:
        raise HTTPException(status_code=503, detail=e.message) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/search")
def search(
    keyword: str = Query(..., min_length=2, max_length=100),
    p: int = Query(1, ge=1),
    ps: int = Query(10, ge=1, le=80),
    sortType: str = Query("default"),
    filterTime: str = Query("all"),
    filterSize: str = Query("all"),
    matchMode: str = Query("smart"),
    withTotalCount: str = Query("1"),
    countOnly: str = Query("0"),
    jp: str = Query("0"),
    cn: str = Query("0"),
    ck: str = Query("0"),
    yc: str = Query("0"),
    xu: str = Query(""),
    # 四国白名单：japan_censored|japan_uncensored|china|western（yc=1 等价有码）
    region: str = Query(""),
    # 是否纳入可选补强板；默认 1
    optb: str = Query("1"),
) -> dict[str, Any]:
    try:
        count_only = countOnly == "1"
        japan = jp == "1"
        japan_censored = yc == "1"
        # xu: 空=默认（有码且未开破解则排除无码）；1/0 显式覆盖
        exclude_uncensored: bool | None
        if xu == "1":
            exclude_uncensored = True
        elif xu == "0":
            exclude_uncensored = False
        else:
            exclude_uncensored = None
        data = resource_service.search_resources(
            keyword=keyword,
            p=p,
            ps=ps,
            sort_type=sortType,
            filter_time=filterTime,
            filter_size=filterSize,
            match_mode=matchMode,
            with_total_count=True if count_only else withTotalCount != "0",
            count_only=count_only,
            prefer_chinese=japan and cn == "1",
            prefer_crack=japan and ck == "1",
            japan_censored=japan_censored,
            exclude_uncensored=exclude_uncensored,
            region=(region or "").strip() or None,
            include_optional_boards=optb != "0",
        )
        return _wrap(data, "success")
    except ResourceDbUnavailable as e:
        raise HTTPException(status_code=503, detail=e.message) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/resources/{hash}")
def resource_detail(hash: str) -> dict[str, Any]:
    try:
        item = resource_service.resource_by_hash(hash)
        if not item:
            raise HTTPException(status_code=404, detail="资源不存在")
        return _wrap(item, "success")
    except ResourceDbUnavailable as e:
        raise HTTPException(status_code=503, detail=e.message) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
