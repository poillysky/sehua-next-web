"""七区前缀/番号目录 API（维护用，不读资源仓库）。"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import app.prefix.catalog_avwikidb as avwikidb
import app.prefix.catalog_harvest as harvest
import app.prefix.catalog_local_index as local_index
import app.prefix.catalog_store as store
import app.prefix.catalog_strm_sync as strm_sync
from app.core.region_meta import REGION_ORDER

router = APIRouter(prefix="/prefix-catalog", tags=["prefix-catalog"])

_job_lock = threading.Lock()
_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "log": [],
    "result": None,
    "error": None,
}
_local_index_lock = threading.Lock()
_local_index_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "progress": None,
    "log": [],
    "result": None,
    "error": None,
}
_strm_sync_lock = threading.Lock()
_strm_sync_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "progress": None,
    "log": [],
    "result": None,
    "error": None,
}
_strm_hydrated = False
_strm_hydrate_lock = threading.Lock()


def _persist_strm_job(**extra: Any) -> None:
    try:
        from app.core import job_persist

        with _strm_sync_lock:
            payload = {
                "status": (
                    "running"
                    if _strm_sync_job.get("running")
                    else str(
                        extra.get("status")
                        or _strm_sync_job.get("phase")
                        or "idle"
                    )
                ),
                "phase": str(_strm_sync_job.get("phase") or ""),
                "progress": dict(_strm_sync_job.get("progress") or {}) or None,
                "log": list(_strm_sync_job.get("log") or [])[-40:],
                "result": _strm_sync_job.get("result"),
                "error": _strm_sync_job.get("error"),
                "running": bool(_strm_sync_job.get("running")),
            }
        for k, v in extra.items():
            payload[k] = v
        if payload.get("running"):
            payload["status"] = "running"
        job_persist.save_job(job_persist.STRM_SYNC_JOB_KEY, payload)
    except Exception:  # noqa: BLE001
        pass


def _hydrate_strm_job(*, force: bool = False) -> dict[str, Any]:
    global _strm_hydrated
    with _strm_hydrate_lock:
        if _strm_hydrated and not force:
            return {}
        _strm_hydrated = True
    try:
        from app.core import job_persist

        raw = job_persist.load_job(job_persist.STRM_SYNC_JOB_KEY)
        if not raw:
            return {}
        with _strm_sync_lock:
            if _strm_sync_job.get("running"):
                return raw
            if not _strm_sync_job.get("phase") and raw.get("phase"):
                _strm_sync_job["phase"] = str(raw.get("phase") or "")
            if not _strm_sync_job.get("progress") and raw.get("progress"):
                _strm_sync_job["progress"] = dict(raw.get("progress") or {})
            if not _strm_sync_job.get("log") and raw.get("log"):
                _strm_sync_job["log"] = list(raw.get("log") or [])[-40:]
            if (
                _strm_sync_job.get("result") is None
                and raw.get("result") is not None
            ):
                _strm_sync_job["result"] = raw.get("result")
            if not _strm_sync_job.get("error") and raw.get("error"):
                _strm_sync_job["error"] = raw.get("error")
            if str(raw.get("status") or "") == "running":
                _strm_sync_job["phase"] = "interrupted"
                prog = dict(_strm_sync_job.get("progress") or {})
                prog["label"] = "进程中断 · 可继续（已写文件会跳过）"
                _strm_sync_job["progress"] = prog
                raw = dict(raw)
                raw["status"] = "interrupted"
                raw["running"] = False
                job_persist.save_job(job_persist.STRM_SYNC_JOB_KEY, raw)
        return raw
    except Exception:  # noqa: BLE001
        return {}


def _job_log(msg: str) -> None:
    _job["phase"] = msg
    logs = _job.get("log") or []
    logs.append(msg)
    _job["log"] = logs[-200:]


def _local_index_log(payload: Any) -> None:
    if isinstance(payload, dict):
        phase = str(payload.get("phase") or "").strip()
        progress = {
            "stage": str(payload.get("stage") or ""),
            "done": payload.get("done"),
            "total": payload.get("total"),
            "percent": payload.get("percent"),
            "label": phase,
        }
        _local_index_job["progress"] = progress
        if phase:
            _local_index_job["phase"] = phase
            logs = _local_index_job.get("log") or []
            # 同阶段高频计数只保留最新一条，避免刷屏
            if logs and _same_progress_family(logs[-1], phase):
                logs[-1] = phase
            else:
                logs.append(phase)
            _local_index_job["log"] = logs[-80:]
        return

    phase = str(payload or "").strip()
    _local_index_job["phase"] = phase
    if phase:
        logs = _local_index_job.get("log") or []
        logs.append(phase)
        _local_index_job["log"] = logs[-80:]


def _strm_sync_log(payload: Any) -> None:
    if isinstance(payload, dict):
        phase = str(payload.get("phase") or "").strip()
        _strm_sync_job["progress"] = {
            "stage": str(payload.get("stage") or ""),
            "done": payload.get("done"),
            "total": payload.get("total"),
            "percent": payload.get("percent"),
            "label": phase,
        }
        if phase:
            _strm_sync_job["phase"] = phase
            logs = _strm_sync_job.get("log") or []
            if logs and str(logs[-1]).startswith("写入 ") and phase.startswith("写入 "):
                logs[-1] = phase
            else:
                logs.append(phase)
            _strm_sync_job["log"] = logs[-80:]
        done = payload.get("done")
        total = payload.get("total")
        if (
            isinstance(done, int)
            and isinstance(total, int)
            and (done == total or done % 2000 == 0)
        ):
            _persist_strm_job(status="running")
        return
    phase = str(payload or "").strip()
    _strm_sync_job["phase"] = phase
    if phase:
        logs = _strm_sync_job.get("log") or []
        logs.append(phase)
        _strm_sync_job["log"] = logs[-80:]


def _same_progress_family(prev: str, cur: str) -> bool:
    """色花堂/Bitmagnet 计数行视为同一族，原地覆盖。"""
    for prefix in ("色花堂 ", "Bitmagnet torrents.", "Bitmagnet content."):
        if prev.startswith(prefix) and cur.startswith(prefix):
            # Bitmagnet 需同 table.col
            if prefix.startswith("Bitmagnet"):
                prev_key = prev.split(" ", 1)[1].rsplit(" ", 1)[0]
                cur_key = cur.split(" ", 1)[1].rsplit(" ", 1)[0]
                return prev_key == cur_key
            return True
    return False


class RebuildBody(BaseModel):
    clear: bool = True


class HarvestBody(BaseModel):
    region: str = "japan_censored"
    prefixes: list[str] = Field(default_factory=list)
    limit: int = 0
    hi_cap: int = 800
    full_scan_limit: int = 80
    pages: int = 2
    mode: str = "quick"  # quick | dense | latest | avwikidb
    expand: bool = True
    min_movie_count: int = 5


class PrefixUpsertBody(BaseModel):
    prefix: str
    maker: str = ""
    maker_ja: str = ""
    label_ja: str = ""
    sources: list[str] = Field(default_factory=list)
    pad: int = 3
    format: str = "{prefix}-{num}"
    dmm_digit: str = ""
    serials: list[int] = Field(default_factory=list)
    status: str = "active"
    notes: str = ""


@router.get("")
def get_catalog_summary() -> dict[str, Any]:
    return {"ok": True, "data": store.public_summary()}


@router.get("/regions")
def get_regions() -> dict[str, Any]:
    doc = store.load_catalog()
    rows = []
    for rid in REGION_ORDER:
        reg = doc["regions"][rid]
        prefs = reg.get("prefixes") or {}
        rows.append(
            {
                "id": rid,
                "label": reg.get("label"),
                "prefix_count": len(prefs),
                "code_count": sum(store.effective_code_count(p) for p in prefs.values()),
            }
        )
    return {"ok": True, "data": rows}


@router.get("/regions/{region_id}/prefixes")
def get_region_prefixes(
    region_id: str,
    q: str = Query(""),
) -> dict[str, Any]:
    if region_id not in REGION_ORDER:
        raise HTTPException(404, f"unknown region: {region_id}")
    return {"ok": True, "data": store.list_prefixes(region_id, q=q)}


@router.get("/regions/{region_id}/makers")
def get_region_makers(
    region_id: str,
    q: str = Query(""),
) -> dict[str, Any]:
    if region_id not in REGION_ORDER:
        raise HTTPException(404, f"unknown region: {region_id}")
    return {"ok": True, "data": store.list_makers(region_id, q=q)}


@router.get("/regions/{region_id}/prefixes/{prefix}")
def get_prefix_detail(
    region_id: str,
    prefix: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    if region_id not in REGION_ORDER:
        raise HTTPException(404, f"unknown region: {region_id}")
    ent = store.get_prefix(region_id, prefix)
    if not ent:
        raise HTTPException(404, f"prefix not found: {prefix}")
    codes = store.codes_of(ent, offset=offset, limit=limit)
    # 不把完整 serials/codes 数组回给前端，避免大 payload 卡顿
    slim = {k: v for k, v in ent.items() if k not in ("serials", "codes")}
    return {
        "ok": True,
        "data": {
            **slim,
            "codes": codes,
            "codes_offset": offset,
            "codes_limit": limit,
        },
    }


@router.put("/regions/{region_id}/prefixes/{prefix}")
def put_prefix(region_id: str, prefix: str, body: PrefixUpsertBody) -> dict[str, Any]:
    if region_id not in REGION_ORDER:
        raise HTTPException(404, f"unknown region: {region_id}")
    payload = body.model_dump()
    payload["prefix"] = prefix
    ent = store.upsert_prefix(region_id, payload)
    return {"ok": True, "data": ent}


@router.delete("/regions/{region_id}/prefixes/{prefix}")
def remove_prefix(region_id: str, prefix: str) -> dict[str, Any]:
    if region_id not in REGION_ORDER:
        raise HTTPException(404, f"unknown region: {region_id}")
    ok = store.delete_prefix(region_id, prefix)
    if not ok:
        raise HTTPException(404, f"prefix not found: {prefix}")
    return {"ok": True}


@router.post("/rebuild")
def post_rebuild(body: RebuildBody) -> dict[str, Any]:
    summary = harvest.rebuild_from_seed(clear=body.clear)
    return {"ok": True, "data": summary}


@router.get("/harvest/status")
def harvest_status() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "running": bool(_job["running"]),
            "phase": _job.get("phase") or "",
            "log": list(_job.get("log") or [])[-50:],
            "result": _job.get("result"),
            "error": _job.get("error"),
        },
    }


@router.post("/harvest")
def post_harvest(body: HarvestBody) -> dict[str, Any]:
    mode = (body.mode or "quick").strip().lower() or "quick"
    allowed = {
        "japan_censored": {"quick", "dense", "latest", "avwikidb"},
        "japan_gravure": {"latest", "avwikidb"},
        "japan_amateur": {"latest", "avwikidb"},
        "japan_uncensored": {"avwikidb"},
        "china": {"latest"},
        "western": {"latest"},
    }
    if body.region not in allowed or mode not in allowed[body.region]:
        raise HTTPException(
            400,
            "支持：japan_censored(quick|dense|latest|avwikidb)；"
            "japan_gravure/japan_amateur(latest|avwikidb)；"
            "japan_uncensored(avwikidb)；"
            "china/western(latest)",
        )
    with _job_lock:
        if _job["running"]:
            raise HTTPException(409, "harvest already running")
        _job.update(
            {
                "running": True,
                "phase": "starting",
                "log": [],
                "result": None,
                "error": None,
            }
        )

    def run() -> None:
        try:
            if mode == "avwikidb":
                result = avwikidb.sync_maker_prefix_map(
                    region=body.region,
                    prefixes=body.prefixes or None,
                    limit=body.limit,
                    expand=bool(body.expand),
                    min_movie_count=max(1, int(body.min_movie_count or 5)),
                    on_progress=_job_log,
                )
            elif mode == "latest":
                result = harvest.harvest_latest_via_search(
                    body.region,
                    prefixes=body.prefixes or None,
                    limit=body.limit,
                    pages=max(1, int(body.pages or 2)),
                    on_progress=_job_log,
                )
            else:
                result = harvest.harvest_japan_censored(
                    prefixes=body.prefixes or None,
                    limit=body.limit,
                    hi_cap=body.hi_cap,
                    full_scan_limit=body.full_scan_limit,
                    mode=mode,
                    on_progress=_job_log,
                )
            _job["result"] = result
            _job["phase"] = "done"
        except Exception as e:  # noqa: BLE001
            _job["error"] = str(e)
            _job["phase"] = "error"
        finally:
            _job["running"] = False

    threading.Thread(target=run, name="prefix-catalog-harvest", daemon=True).start()
    return {"ok": True, "data": {"started": True, "region": body.region, "mode": mode}}


@router.get("/local-index/status")
def local_index_status() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "running": bool(_local_index_job["running"]),
            "phase": _local_index_job.get("phase") or "",
            "progress": _local_index_job.get("progress"),
            "log": list(_local_index_job.get("log") or [])[-20:],
            "result": _local_index_job.get("result"),
            "error": _local_index_job.get("error"),
        },
    }


@router.post("/local-index")
def post_local_index() -> dict[str, Any]:
    """手动触发 Sehua + Bitmagnet 双库扫描，更新七区番号。"""
    with _local_index_lock:
        if _local_index_job["running"]:
            raise HTTPException(409, "双库扫描已在运行")
        _local_index_job.update(
            {
                "running": True,
                "phase": "starting",
                "progress": {
                    "stage": "prepare",
                    "done": 0,
                    "total": None,
                    "percent": 0,
                    "label": "starting",
                },
                "log": [],
                "result": None,
                "error": None,
            }
        )

    def run() -> None:
        try:
            result = local_index.run_local_db_index(on_progress=_local_index_log)
            # 扫描结束后：按目录 1:1 同步番号骨架（少补多删，不覆盖已刮削）
            skeleton: dict[str, Any] = {"ok": False, "skipped": True}
            try:
                import app.scrap_library.embed as embed_svc

                def _skel_prog(payload: dict[str, Any]) -> None:
                    _local_index_log(
                        {
                            "stage": "skeleton",
                            "phase": str(payload.get("label") or "同步番号骨架…"),
                            "done": payload.get("done"),
                            "total": payload.get("total"),
                            "percent": payload.get("percent"),
                            "label": str(payload.get("label") or ""),
                        }
                    )

                _local_index_log(
                    {
                        "stage": "skeleton",
                        "phase": "同步番号骨架…",
                        "percent": 96,
                        "label": "同步番号骨架…",
                    }
                )
                skeleton = embed_svc.upsert_catalog_skeletons(on_progress=_skel_prog)
            except Exception as sk_e:  # noqa: BLE001
                skeleton = {"ok": False, "error": str(sk_e)}
                _local_index_log(
                    {
                        "stage": "skeleton",
                        "phase": f"骨架同步失败 · {sk_e}",
                        "percent": 99,
                        "label": f"骨架同步失败 · {sk_e}",
                    }
                )
            _local_index_job["result"] = {
                "updated": result.get("updated"),
                "cleared_miss": result.get("cleared_miss"),
                "summary": result.get("summary"),
                "by_region": result.get("by_region"),
                "skeleton": skeleton,
            }
            sk_ins = int(skeleton.get("inserted") or 0)
            sk_skip = int(skeleton.get("skipped_existing") or 0)
            sk_codes = int(skeleton.get("purged_codes") or 0)
            _local_index_job["phase"] = "done"
            _local_index_job["progress"] = {
                "stage": "done",
                "done": result.get("updated"),
                "total": None,
                "percent": 100,
                "label": (
                    f"done · 骨架 +{sk_ins} / 已有 {sk_skip}"
                    f" · 清目录外向量 {sk_codes}"
                ),
            }
        except Exception as e:  # noqa: BLE001
            _local_index_job["error"] = str(e)
            _local_index_job["phase"] = "error"
        finally:
            _local_index_job["running"] = False

    threading.Thread(target=run, name="prefix-catalog-local-index", daemon=True).start()
    return {"ok": True, "data": {"started": True}}


class StrmSyncSettingsBody(BaseModel):
    root: str = ""


class StrmSyncStartBody(BaseModel):
    root: str = ""


class StrmMkdirBody(BaseModel):
    parent: str = ""
    name: str = ""


@router.get("/strm-sync")
def get_strm_sync() -> dict[str, Any]:
    return {"ok": True, "data": strm_sync.get_strm_sync_settings()}


@router.put("/strm-sync")
def put_strm_sync(body: StrmSyncSettingsBody) -> dict[str, Any]:
    try:
        data = strm_sync.put_strm_sync_settings(root=body.root)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "data": data}


@router.get("/strm-sync/browse")
def browse_strm_dirs(path: str = Query("")) -> dict[str, Any]:
    try:
        return {"ok": True, "data": strm_sync.browse_data_dirs(path)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except OSError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/strm-sync/mkdir")
def mkdir_strm_dir(body: StrmMkdirBody) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            "data": strm_sync.mkdir_data_dir(parent=body.parent, name=body.name),
        }
    except FileExistsError:
        raise HTTPException(409, "文件夹已存在") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except OSError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/strm-sync/status")
def strm_sync_status() -> dict[str, Any]:
    _hydrate_strm_job()
    return {
        "ok": True,
        "data": {
            "running": bool(_strm_sync_job["running"]),
            "phase": _strm_sync_job.get("phase") or "",
            "progress": _strm_sync_job.get("progress"),
            "log": list(_strm_sync_job.get("log") or [])[-20:],
            "result": _strm_sync_job.get("result"),
            "error": _strm_sync_job.get("error"),
        },
    }


@router.post("/strm-sync")
def post_strm_sync(body: StrmSyncStartBody | None = None) -> dict[str, Any]:
    """同步七区番号为本地 STRM 树：区/前缀/番号/番号.strm。"""
    root = str((body.root if body else "") or "").strip()
    if root:
        try:
            strm_sync.put_strm_sync_settings(root=root)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    else:
        cfg = strm_sync.get_strm_sync_settings()
        if not str(cfg.get("root") or "").strip():
            strm_sync.put_strm_sync_settings(root=strm_sync.DEFAULT_REL_ROOT)

    prev = _hydrate_strm_job()
    resumed = str(prev.get("status") or "") in {
        "interrupted",
        "running",
        "paused",
    }

    with _strm_sync_lock:
        if _strm_sync_job["running"]:
            raise HTTPException(409, "STRM 同步已在运行")
        _strm_sync_job.update(
            {
                "running": True,
                "phase": "继续" if resumed else "starting",
                "progress": {
                    "stage": "prepare",
                    "done": 0,
                    "total": None,
                    "percent": 0,
                    "label": "继续（已有文件跳过）" if resumed else "starting",
                },
                "log": (
                    list(_strm_sync_job.get("log") or [])[-20:] if resumed else []
                ),
                "result": None,
                "error": None,
            }
        )
    _persist_strm_job(status="running", params={"root": root})

    def run() -> None:
        try:
            result = strm_sync.run_strm_sync(on_progress=_strm_sync_log)
            _strm_sync_job["result"] = result
            _strm_sync_job["phase"] = "done"
            _strm_sync_job["progress"] = {
                "stage": "done",
                "done": result.get("written"),
                "total": result.get("total"),
                "percent": 100,
                "label": "done",
            }
            _persist_strm_job(status="done")
        except Exception as e:  # noqa: BLE001
            _strm_sync_job["error"] = str(e)
            _strm_sync_job["phase"] = "error"
            _persist_strm_job(status="error")
        finally:
            _strm_sync_job["running"] = False
            _persist_strm_job()

    threading.Thread(target=run, name="prefix-catalog-strm-sync", daemon=True).start()
    return {"ok": True, "data": {"started": True, "resumed": resumed}}
