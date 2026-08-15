"""厂商区 maker-fs 只读挂载 + 构建触发。"""

from __future__ import annotations

import mimetypes
import threading
from email.utils import formatdate
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query
from fastapi.responses import FileResponse

from . import maker_fs

router = APIRouter(tags=["maker-fs"])


def _wrap(data: Any, message: str = "ok", status: int = 200) -> dict[str, Any]:
    return {"data": data, "message": message, "status": status}


def _file_cache_headers(path: Path) -> dict[str, str]:
    st = path.stat()
    return {
        "Cache-Control": "public, max-age=0, must-revalidate",
        "ETag": f'"{int(st.st_mtime_ns)}-{int(st.st_size)}"',
        "Last-Modified": formatdate(st.st_mtime, usegmt=True),
    }


@router.get("/maker-fs/manifest")
def get_manifest() -> dict[str, Any]:
    return _wrap(maker_fs.read_manifest())


@router.get("/maker-fs/status")
def get_status() -> dict[str, Any]:
    from . import maker_fs_auto

    st = maker_fs.build_status()
    st["autoDaily"] = maker_fs_auto.get_config()
    return _wrap(st)


@router.get("/maker-fs/auto-daily")
def get_auto_daily() -> dict[str, Any]:
    from . import maker_fs_auto

    return _wrap(maker_fs_auto.get_config())


@router.put("/maker-fs/auto-daily")
def put_auto_daily(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    from . import maker_fs_auto

    enabled = bool((body or {}).get("enabled"))
    cfg = maker_fs_auto.set_enabled(enabled)
    # 刚打开且今天未跑：后台补一次
    if enabled and maker_fs_auto.needs_daily_run():
        threading.Thread(
            target=lambda: maker_fs_auto.run_daily_sync(reason="enable"),
            name="maker-fs-auto-enable",
            daemon=True,
        ).start()
        cfg = {**cfg, "starting": True}
    return _wrap(cfg, "已开启每日自动增量" if enabled else "已关闭每日自动增量")


@router.get("/maker-fs/tree")
def get_tree() -> dict[str, Any]:
    tree = maker_fs.read_tree()
    if not tree:
        raise HTTPException(status_code=404, detail="本地树尚未生成，请先构建")
    return _wrap(tree)


@router.get("/maker-fs/regions")
def list_regions() -> dict[str, Any]:
    overview = maker_fs.read_regions_overview()
    if not overview:
        regions = [
            {
                "id": rid,
                "label": meta["label"],
                "dbRegion": meta["db_region"],
                "navPath": meta["navPath"],
                "prefixCount": 0,
                "makerCount": 0,
                "codeCount": 0,
                "dir": f"r/{rid}",
            }
            for rid, meta in maker_fs.REGION_META.items()
        ]
        return _wrap(
            {
                "version": 1,
                "updatedAt": "",
                "regionCount": len(regions),
                "regions": regions,
                "ready": False,
            }
        )
    return _wrap({**overview, "ready": True})


@router.get("/maker-fs/regions/{region_id}")
def get_region(region_id: str) -> dict[str, Any]:
    idx = maker_fs.read_region_index(region_id)
    if not idx:
        raise HTTPException(status_code=404, detail="该区本地索引不存在，请先构建")
    return _wrap(idx)


@router.post("/maker-fs/regions/{region_id}/prefixes")
def add_region_prefix(
    region_id: str,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    try:
        cat = maker_fs.add_region_prefix(
            region_id,
            str(body.get("prefix") or ""),
            board_name=str(body.get("board_name") or ""),
            name=str(body.get("name") or ""),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return _wrap(cat, "已添加主番号")


@router.delete("/maker-fs/regions/{region_id}/prefixes/{prefix}")
def remove_region_prefix(region_id: str, prefix: str) -> dict[str, Any]:
    try:
        cat = maker_fs.remove_region_prefix(region_id, prefix)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return _wrap(cat, "已删除主番号")


@router.post("/maker-fs/regions/{region_id}/prefixes/reset")
def reset_region_prefixes(region_id: str) -> dict[str, Any]:
    try:
        cat = maker_fs.reset_region_prefix_overrides(region_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return _wrap(cat, "已恢复导航默认")


@router.get("/maker-fs/prefixes/{prefix}")
def get_prefix_index(
    prefix: str,
    region: str = Query(""),
) -> dict[str, Any]:
    idx = maker_fs.read_prefix_index(prefix, (region or "").strip() or None)
    if not idx:
        raise HTTPException(status_code=404, detail="此前缀本地索引不存在")
    summary = {k: v for k, v in idx.items() if k != "covers"}
    summary["coverCount"] = idx.get("coverCount") or len(idx.get("covers") or {})
    return _wrap(summary)


@router.get("/maker-fs/prefixes/{prefix}/range")
def get_prefix_range_local(
    prefix: str,
    region: str = Query(""),
) -> dict[str, Any]:
    from . import prefix_ranges

    # 优先全局规范位数；本地 index 的 from/to 作补充
    data = prefix_ranges.get_range(prefix)
    local = maker_fs.range_for_prefix_local(
        prefix, (region or "").strip() or None
    )
    if not data and not local:
        raise HTTPException(status_code=404, detail="本地无此前缀范围")
    if data and local:
        merged = {**data, **{k: local[k] for k in ("from", "to", "total", "region", "updatedAt") if k in local}}
        merged["pad"] = int(data.get("pad") or local.get("pad") or 3)
        merged["sample"] = data.get("sample") or f"{prefix}-{1:0{merged['pad']}d}"
        return _wrap(merged)
    return _wrap(data or local)


@router.put("/maker-fs/prefixes/{prefix}/range")
def put_prefix_range_local(
    prefix: str,
    pad: int = Query(..., ge=1, le=8),
    lock: int = Query(1, ge=0, le=1),
    region: str = Query(""),
) -> dict[str, Any]:
    from . import prefix_ranges

    data = prefix_ranges.set_pad(prefix, pad, lock=bool(lock))
    if not data:
        raise HTTPException(status_code=404, detail="未知前缀")
    _ = region  # 位数为全局规范，区仅用于回读展示
    local = maker_fs.range_for_prefix_local(
        prefix, (region or "").strip() or None
    )
    if local:
        data = {
            **data,
            "from": local.get("from"),
            "to": local.get("to"),
            "total": local.get("total"),
            "region": local.get("region"),
        }
    return _wrap(data)


@router.get("/maker-fs/prefixes/{prefix}/codes")
def list_prefix_codes(
    prefix: str,
    region: str = Query(""),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    q: str = Query(""),
) -> dict[str, Any]:
    data = maker_fs.list_prefix_codes(
        prefix,
        (region or "").strip() or None,
        offset=offset,
        limit=limit,
        q=(q or "").strip() or None,
    )
    if data is None:
        raise HTTPException(status_code=404, detail="本地无此前缀索引")
    return _wrap(data)


@router.get("/maker-fs/prefixes/{prefix}/covers")
def get_prefix_covers_local(
    prefix: str,
    codes: str = Query(..., min_length=1),
    region: str = Query(""),
) -> dict[str, Any]:
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    data = maker_fs.covers_for_codes_local(
        prefix,
        code_list,
        region=(region or "").strip() or None,
    )
    if data is None:
        raise HTTPException(status_code=404, detail="本地无此前缀索引")
    return _wrap(data)


@router.get("/maker-fs/file/{file_path:path}")
def get_local_file(file_path: str) -> FileResponse:
    """安全读取 maker-fs 根下的相对文件（封面等）。"""
    root = maker_fs.ensure_root().resolve()
    target = (root / file_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="非法路径") from e
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    media, _ = mimetypes.guess_type(str(target))
    return FileResponse(
        target,
        media_type=media or "application/octet-stream",
        headers=_file_cache_headers(target),
    )


def _run_build(
    limit: int | None,
    max_covers: int,
    catalogs_only: bool,
    workers: int,
    skip_fresh_hours: float,
    region: str | None,
    only_prefix: str | None = None,
) -> None:
    try:
        maker_fs.build_maker_fs(
            limit_prefixes=limit,
            max_covers_per_prefix=max_covers,
            catalogs_only=catalogs_only,
            workers=workers,
            skip_fresh_hours=skip_fresh_hours,
            region=region,
            only_prefix=only_prefix,
            from_claim=True,
        )
    except Exception as e:
        maker_fs.abort_claim(str(e) or "failed")


@router.post("/maker-fs/build")
def start_build(
    background: BackgroundTasks,
    limit: int = Query(0, ge=0, le=5000, description="0=全部前缀"),
    maxCovers: int = Query(
        20000,
        ge=50,
        le=50000,
        description="单前缀最多写入番号数；须 ≥ 扫库行上限以免截断",
    ),
    sync: int = Query(0, description="1=同步执行（调试）"),
    catalogsOnly: int = Query(
        0, description="1=仅写七区番号细表，不导出封面"
    ),
    workers: int = Query(
        maker_fs.DEFAULT_EXPORT_WORKERS,
        ge=1,
        le=6,
        description="并行扫库线程数",
    ),
    skipFreshHours: float = Query(
        maker_fs.DEFAULT_SKIP_FRESH_HOURS,
        ge=0,
        le=720,
        description="跳过 N 小时内已导出的前缀；0=强制全量",
    ),
    force: int = Query(0, description="1=强制全量（忽略 skipFreshHours）"),
    region: str = Query(
        "",
        description="仅扫描指定分区 id，如 japan_censored；空=全部",
    ),
    prefix: str = Query(
        "",
        description="仅扫描单个前缀（须同时传 region）；强制重扫该前缀",
    ),
) -> dict[str, Any]:
    lim = limit if limit > 0 else None
    cats_only = catalogsOnly == 1
    skip_h = 0.0 if force == 1 else float(skipFreshHours)
    region_key = (region or "").strip() or None
    prefix_key = (prefix or "").strip() or None
    if prefix_key and not region_key:
        raise HTTPException(
            status_code=400, detail="单前缀扫描必须指定 region"
        )
    if prefix_key:
        # 单前缀一律强制重扫
        skip_h = 0.0
        lim = None
        cats_only = False
    if sync == 1:
        try:
            result = maker_fs.build_maker_fs(
                limit_prefixes=lim,
                max_covers_per_prefix=maxCovers,
                catalogs_only=cats_only,
                workers=1 if prefix_key else workers,
                skip_fresh_hours=skip_h,
                region=region_key,
                only_prefix=prefix_key,
            )
            return _wrap(result, "构建完成")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
    if not maker_fs.claim_build(region=region_key):
        raise HTTPException(status_code=409, detail="构建任务正在进行中")
    background.add_task(
        _run_build,
        lim,
        maxCovers,
        cats_only,
        1 if prefix_key else workers,
        skip_h,
        region_key,
        prefix_key,
    )
    return _wrap(maker_fs.build_status(), "已开始后台构建")


@router.post("/maker-fs/build/cancel")
def cancel_build() -> dict[str, Any]:
    if not maker_fs.request_cancel_build():
        raise HTTPException(status_code=409, detail="当前没有进行中的构建")
    return _wrap(maker_fs.build_status(), "已请求取消")
