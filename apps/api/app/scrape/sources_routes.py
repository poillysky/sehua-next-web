"""全站数据源 API（MDCS provider catalog 移植）。"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import app.scrape.sources_settings as sources

router = APIRouter(prefix="/settings/scrape-sources", tags=["scrape-sources"])

_job_lock = threading.Lock()
_job: dict[str, Any] = {
    "running": False,
    "done": 0,
    "total": 0,
    "current": "",
    "results": [],
}


class ProviderPutBody(BaseModel):
    enabled: bool | None = None
    baseUrl: str | None = None
    cookie: str | None = None
    apiKey: str | None = None
    activeBase: str | None = None


class ProbeBody(BaseModel):
    source: str = ""
    persist: bool = True
    all: bool = False
    onlyEnabled: bool = True


@router.get("")
def get_scrape_sources() -> dict[str, Any]:
    return {"ok": True, "data": sources.public_catalog()}


@router.put("/{source_id}")
def put_scrape_source(source_id: str, body: ProviderPutBody) -> dict[str, Any]:
    try:
        data = sources.save_provider(
            source_id, body.model_dump(exclude_none=True)
        )
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"ok": True, "data": data}


@router.get("/probe/status")
def probe_status() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "running": bool(_job["running"]),
            "done": int(_job.get("done") or 0),
            "total": int(_job.get("total") or 0),
            "current": str(_job.get("current") or ""),
            "results": list(_job.get("results") or [])[-40:],
        },
    }


@router.post("/probe")
def post_probe(body: ProbeBody) -> dict[str, Any]:
    if body.all:
        with _job_lock:
            if _job["running"]:
                raise HTTPException(409, "probe already running")
            cat = sources.public_catalog()
            ids = [
                str(s["id"])
                for s in cat.get("sources") or []
                if (not body.onlyEnabled) or s.get("enabled")
            ]
            _job.update(
                {
                    "running": True,
                    "done": 0,
                    "total": len(ids),
                    "current": "",
                    "results": [],
                }
            )

        def run() -> None:
            try:
                for i, sid in enumerate(ids, 1):
                    _job["current"] = sid
                    _job["done"] = i - 1
                    try:
                        r = sources.probe_provider(sid, persist=body.persist)
                    except Exception as e:  # noqa: BLE001
                        r = {"ok": False, "source": sid, "message": str(e)[:160]}
                    _job["results"] = (list(_job.get("results") or []) + [r])[-80:]
                    _job["done"] = i
            finally:
                _job["running"] = False
                _job["current"] = ""

        threading.Thread(target=run, name="scrape-sources-probe", daemon=True).start()
        return {"ok": True, "data": {"started": True, "total": len(ids)}}

    sid = (body.source or "").strip()
    if not sid:
        raise HTTPException(400, "source required")
    result = sources.probe_provider(sid, persist=body.persist)
    return {"ok": True, "data": result, "message": result.get("message") or ""}
