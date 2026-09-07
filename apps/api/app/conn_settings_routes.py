"""115 / TMDB / forum / library display settings (Postgres meta)."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .auth_routes import get_optional_user, require_user
from . import p115_client, p115_extract, settings_store
from . import p115_offline as p115_offline_svc
from . import p115_qrlogin as p115_qrlogin_svc
from . import p115_share as p115_share_svc
from .db import ROOT

_ARCHIVE_EXT_RE = re.compile(r"\.(zip|rar|7z)(?:\.[a-z0-9]+)?$", re.I)

router = APIRouter(prefix="/settings", tags=["settings"])

DEFAULT_LIBRARY_REL = "data/library"
_LIBRARY_SKIP_DIRS = frozenset()




def _normalize_library_rel(raw: str | None) -> str:
    """容器内相对路径（POSIX）；绝对路径若落在项目 data/ 下则收成相对。"""
    s = str(raw or "").strip().replace("\\", "/")
    if not s:
        return DEFAULT_LIBRARY_REL
    try:
        p = Path(s)
        if p.is_absolute():
            root = ROOT.resolve()
            try:
                rel = p.resolve().relative_to(root)
                s = rel.as_posix()
            except ValueError:
                # 不在项目内：忽略，回默认
                return DEFAULT_LIBRARY_REL
        s = s.lstrip("/")
        if s.startswith("./"):
            s = s[2:]
        if not s.startswith("data/"):
            # 仅允许 data/ 下
            if s == "data":
                return DEFAULT_LIBRARY_REL
            return DEFAULT_LIBRARY_REL
        # 禁止逃逸
        if ".." in Path(s).parts:
            return DEFAULT_LIBRARY_REL
        return s
    except Exception:
        return DEFAULT_LIBRARY_REL


def _library_abs(rel: str) -> str:
    return str((ROOT / rel).resolve())


def _safe_data_rel(raw: str | None, *, default: str = "data") -> str:
    """浏览用：限制在项目 data/ 下的相对路径。"""
    s = str(raw or "").strip().replace("\\", "/").strip("/")
    if not s:
        return default
    try:
        p = Path(s)
        if p.is_absolute():
            try:
                s = p.resolve().relative_to(ROOT.resolve()).as_posix()
            except ValueError:
                return default
        if s.startswith("./"):
            s = s[2:]
        if s != "data" and not s.startswith("data/"):
            return default
        if ".." in Path(s).parts:
            return default
        return s
    except Exception:
        return default



def _normalize_proxy_url(raw: str | None) -> str:
    """裸 host:port → http://；非法则空串。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = f"http://{s}"
    s = s.rstrip("/")
    parsed = urlparse(s)
    if parsed.scheme not in ("http", "https", "socks4", "socks5") or not parsed.netloc:
        return ""
    return s


class Envelope(BaseModel):
    data: Any = None
    message: str = "ok"
    status: int = 200


_COVER_DOWNLOAD_STRATEGIES = frozenset({"priority", "size"})

_FORUM_REGIONS = frozenset({"japan", "china", "western", "mixed", "other"})


class ForumSehuatangConfig(BaseModel):
    """色花堂子板地区覆盖：key = fid:typeid（整板 typeid 为空）。
    地区：japan|china|western|mixed|other"""

    region_by_key: dict[str, str] = Field(default_factory=dict, alias="regionByKey")

    model_config = {"populate_by_name": True}


def _forum_sehuatang_public(raw: Any) -> dict[str, Any]:
    region_by_key: dict[str, str] = {}
    if isinstance(raw, dict):
        src = raw.get("regionByKey") or raw.get("region_by_key") or {}
        if isinstance(src, dict):
            for k, v in src.items():
                key = str(k or "").strip()
                region = str(v or "").strip().lower()
                if key and region in _FORUM_REGIONS:
                    region_by_key[key] = region
    return {"regionByKey": region_by_key}


class P115TargetFolder(BaseModel):
    folder_cid: str = Field(default="0", alias="folderCid")
    folder_name: str = Field(default="", alias="folderName")

    model_config = {"populate_by_name": True}


class P115Config(BaseModel):
    enabled: bool = False
    cookie: str = ""
    folder_cid: str = Field(default="0", alias="folderCid")
    folder_name: str = Field(default="", alias="folderName")
    label: str = ""
    targets: dict[str, P115TargetFolder] | None = None
    do_validate: bool = Field(default=True, alias="validate")

    model_config = {"populate_by_name": True}


class P115FoldersBody(BaseModel):
    cid: str = "0"
    cookie: str | None = None


class P115ValidateBody(BaseModel):
    cookie: str | None = None
    folder_cid: str = Field(default="0", alias="folderCid")

    model_config = {"populate_by_name": True}


class P115OfflineBody(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=50)
    folder_cid: str | None = Field(default=None, alias="folderCid")
    source: str | None = None
    password: str | None = None
    title_hint: str | None = Field(default=None, alias="titleHint")
    auto_extract: bool | None = Field(default=None, alias="autoExtract")

    model_config = {"populate_by_name": True}


class P115ShareBody(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=20)
    folder_cid: str | None = Field(default=None, alias="folderCid")
    source: str | None = None
    password: str | None = None

    model_config = {"populate_by_name": True}


class P115TasksClearBody(BaseModel):
    """mode: done | failed | all — maps to 115 task_clear flag 0/2/1."""

    mode: str = "done"


class P115QrStartBody(BaseModel):
    app: str = "alipaymini"


class P115QrStatusBody(BaseModel):
    uid: str
    time: str | int
    sign: str


class P115QrCompleteBody(BaseModel):
    uid: str
    app: str = "alipaymini"
    """若 true，登录成功后直接写入已存目录配置。"""
    save: bool = True


P115_SOURCES = ("warehouse", "movie", "tv", "makers")


def _normalize_target_folder(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {"folderCid": "0", "folderName": ""}
    cid = str(raw.get("folder_cid") or raw.get("folderCid") or "0").strip() or "0"
    name = str(raw.get("folder_name") or raw.get("folderName") or "").strip()
    return {"folderCid": cid, "folderName": name}


def _target_usable(item: Any) -> bool:
    return isinstance(item, dict) and (
        item.get("folder_cid") is not None
        or item.get("folderCid") is not None
        or item.get("folder_name") is not None
        or item.get("folderName") is not None
    )


def _p115_targets(raw: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    """Per-entry save dirs: warehouse / movie / tv / makers.

    Legacy ``folder_*`` → warehouse. Legacy ``targets.media`` → movie & tv.
    """
    legacy_cid = str((raw or {}).get("folder_cid") or (raw or {}).get("folderCid") or "0").strip() or "0"
    legacy_name = str((raw or {}).get("folder_name") or (raw or {}).get("folderName") or "").strip()
    warehouse_fallback = {"folderCid": legacy_cid, "folderName": legacy_name}
    src = (raw or {}).get("targets") if isinstance(raw, dict) else None
    legacy_media = (
        _normalize_target_folder(src.get("media"))
        if isinstance(src, dict) and _target_usable(src.get("media"))
        else None
    )
    out: dict[str, dict[str, str]] = {}
    for key in P115_SOURCES:
        item = src.get(key) if isinstance(src, dict) else None
        if _target_usable(item):
            out[key] = _normalize_target_folder(item)
        elif key == "warehouse":
            out[key] = warehouse_fallback
        elif key in ("movie", "tv") and legacy_media is not None:
            out[key] = dict(legacy_media)
        else:
            out[key] = dict(warehouse_fallback)
    return out


def _resolve_p115_folder(
    raw: dict[str, Any] | None,
    *,
    source: str | None = None,
    folder_cid: str | None = None,
) -> tuple[str, str]:
    """Return (cid, name). Explicit folder_cid wins; else targets[source]."""
    targets = _p115_targets(raw)
    if folder_cid is not None and str(folder_cid).strip() != "":
        cid = str(folder_cid).strip() or "0"
        for t in targets.values():
            if t["folderCid"] == cid and t["folderName"]:
                return cid, t["folderName"]
        return cid, ""
    key = (source or "warehouse").strip().lower()
    # legacy alias
    if key == "media":
        key = "movie"
    if key not in P115_SOURCES:
        key = "warehouse"
    t = targets[key]
    return t["folderCid"], t["folderName"]


def _targets_for_store(
    body_targets: dict[str, P115TargetFolder] | None,
    prev: dict[str, Any] | None,
    *,
    fallback_cid: str,
    fallback_name: str,
) -> dict[str, dict[str, str]]:
    merged = _p115_targets(prev)
    # Ensure warehouse reflects legacy fields when body omits targets
    if not body_targets:
        merged["warehouse"] = {
            "folderCid": fallback_cid,
            "folderName": fallback_name,
        }
        return {
            k: {"folder_cid": v["folderCid"], "folder_name": v["folderName"]}
            for k, v in merged.items()
        }
    for key in P115_SOURCES:
        item = body_targets.get(key)
        if item is None:
            continue
        merged[key] = {
            "folderCid": (item.folder_cid or "0").strip() or "0",
            "folderName": (item.folder_name or "").strip(),
        }
    return {
        k: {"folder_cid": v["folderCid"], "folder_name": v["folderName"]}
        for k, v in merged.items()
    }


def _is_offline_url(link: str) -> bool:
    lower = (link or "").strip().lower()
    if not lower or lower.startswith("unavailable://"):
        return False
    if lower.startswith("ed2k://") or lower.startswith("magnet:"):
        return True
    if "115cdn.com/s/" in lower or "115.com/s/" in lower:
        return False
    return bool(re.match(r"^(https?://|ftp://)", lower))


def _looks_archive_link(link: str) -> bool:
    lower = (link or "").strip().lower()
    # ed2k://|file|name.zip|size|hash|/ — 取文件名段再测扩展名
    if lower.startswith("ed2k://"):
        parts = (link or "").split("|")
        if len(parts) >= 3:
            return bool(_ARCHIVE_EXT_RE.search(parts[2].strip()))
    return bool(_ARCHIVE_EXT_RE.search(lower))


def _cookie_hint(cookie: str) -> str:
    for part in (cookie or "").split(";"):
        p = part.strip()
        if p.upper().startswith("UID="):
            return p.split("=", 1)[-1][:16]
    return ""






def _p115_public(raw: dict[str, Any] | None, *, include_cookie: bool = False) -> dict[str, Any]:
    # raw uses snake_case from meta store
    cookie = str((raw or {}).get("cookie") or "").strip()
    configured = bool(cookie and "UID=" in cookie.upper())
    targets = _p115_targets(raw)
    warehouse = targets["warehouse"]
    data = {
        "enabled": bool((raw or {}).get("enabled")),
        "folderCid": warehouse["folderCid"],
        "folderName": warehouse["folderName"],
        "label": str((raw or {}).get("label") or ""),
        "targets": targets,
        "hasCookie": bool(cookie),
        "cookieHint": _cookie_hint(cookie) if configured else "",
        "configured": configured,
    }
    if include_cookie:
        data["cookie"] = cookie
    return data


def _tmdb_public(raw: dict[str, Any] | None, *, include_key: bool = False) -> dict[str, Any]:
    import os

    env_key = os.environ.get("TMDB_API_KEY", "").strip()
    stored = str((raw or {}).get("apiKey") or (raw or {}).get("api_key") or "").strip()
    effective = env_key or stored
    hint = ""
    if effective:
        hint = f"{effective[:4]}…{effective[-4:]}" if len(effective) > 10 else "****"
    data: dict[str, Any] = {
        "configured": bool(effective),
        "fromEnv": bool(env_key),
        "apiKeyHint": hint,
    }
    if include_key and stored and not env_key:
        data["apiKey"] = stored
    return data


@router.get("/forum/sehuatang", response_model=Envelope)
def get_forum_sehuatang(
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> Envelope:
    data = _forum_sehuatang_public(
        settings_store.get_setting(settings_store.FORUM_SEHUATANG_KEY)
    )
    return Envelope(data=data, message="ok")


@router.put("/forum/sehuatang", response_model=Envelope)
def put_forum_sehuatang(
    body: ForumSehuatangConfig,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    cleaned: dict[str, str] = {}
    for k, v in (body.region_by_key or {}).items():
        key = str(k or "").strip()
        region = str(v or "").strip().lower()
        if key and region in _FORUM_REGIONS:
            cleaned[key] = region
    saved = settings_store.put_setting(
        settings_store.FORUM_SEHUATANG_KEY,
        {"regionByKey": cleaned},
    )
    try:
        from .forum_region_tags import invalidate_forum_region_cache

        invalidate_forum_region_cache()
    except Exception:
        pass
    data = _forum_sehuatang_public(saved["value"])
    data["updated_at"] = saved["updated_at"]
    return Envelope(data=data, message="saved")


class TmdbConfig(BaseModel):
    api_key: str = Field(default="", alias="apiKey")

    model_config = {"populate_by_name": True}


@router.get("/tmdb", response_model=Envelope)
def get_tmdb(_user: dict[str, Any] | None = Depends(get_optional_user)) -> Envelope:
    data = _tmdb_public(settings_store.get_setting(settings_store.TMDB_KEY))
    return Envelope(
        data=data,
        message="configured" if data["configured"] else "not_configured",
    )


@router.put("/tmdb", response_model=Envelope)
def put_tmdb(
    body: TmdbConfig,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    prev = settings_store.get_setting(settings_store.TMDB_KEY) or {}
    prev_key = str(prev.get("apiKey") or prev.get("api_key") or "").strip()
    next_key = body.api_key.strip()
    # 已有 key 时，空提交不允许覆盖清空；只有明确输入新 key 才替换
    key = next_key or prev_key
    saved = settings_store.put_setting(
        settings_store.TMDB_KEY,
        {"apiKey": key},
    )
    data = _tmdb_public(saved["value"])
    data["updated_at"] = saved["updated_at"]
    return Envelope(data=data, message="saved")


@router.post("/tmdb/test", response_model=Envelope)
async def test_tmdb(
    body: TmdbConfig,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    import os

    key = body.api_key.strip() or os.environ.get("TMDB_API_KEY", "").strip()
    if not key:
        stored = settings_store.get_setting(settings_store.TMDB_KEY) or {}
        key = str(stored.get("apiKey") or stored.get("api_key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="请先填写 TMDB API Key")
    from .outbound_http import resolve_scrape_proxy_url

    client_kw: dict[str, Any] = {
        "timeout": httpx.Timeout(12.0, connect=4.0),
        "trust_env": False,
        "follow_redirects": True,
    }
    proxy = resolve_scrape_proxy_url()
    if proxy:
        client_kw["proxy"] = proxy
    try:
        async with httpx.AsyncClient(**client_kw) as client:
            r = await client.get(
                "https://api.themoviedb.org/3/search/multi",
                params={
                    "api_key": key,
                    "query": "超人",
                    "language": "zh-CN",
                    "include_adult": "false",
                },
            )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"无法连接 TMDB: {e}") from e
    if r.status_code == 401:
        raise HTTPException(status_code=400, detail="API Key 无效")
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"TMDB 返回 {r.status_code}")
    total = int((r.json() or {}).get("total_results") or 0)
    return Envelope(
        data={"ok": True, "totalResults": total},
        message=f"测试成功，命中约 {total} 条",
    )


@router.get("/p115", response_model=Envelope)
def get_p115(_user: dict[str, Any] | None = Depends(get_optional_user)) -> Envelope:
    raw = settings_store.get_setting(settings_store.P115_KEY)
    data = _p115_public(raw)
    return Envelope(
        data=data,
        message="configured" if data["configured"] else "not_configured",
    )


@router.get("/p115/status", response_model=Envelope)
def get_p115_status(_user: dict[str, Any] | None = Depends(get_optional_user)) -> Envelope:
    """115 实时状态：额度 / 空间 / 单任务上限。用于设置页异步补状态，避免首屏阻塞。"""
    raw = settings_store.get_setting(settings_store.P115_KEY)
    data = _p115_public(raw)
    if not data.get("configured"):
        return Envelope(data=data, message="not_configured")

    cookie = str((raw or {}).get("cookie") or "").strip()
    if not cookie:
        return Envelope(data=data, message="not_configured")

    quota_res = p115_client.fetch_offline_quota(cookie)
    if quota_res.get("ok"):
        data["quota"] = quota_res.get("quota")
        data["quotaTotal"] = quota_res.get("quotaTotal")
    else:
        data["quota"] = None
        data["quotaTotal"] = None
        data["quotaError"] = str(quota_res.get("message") or "额度读取失败")

    space_res = p115_client.fetch_space_info(cookie)
    if space_res.get("ok"):
        data["spaceTotal"] = space_res.get("spaceTotal")
        data["spaceTotalText"] = space_res.get("spaceTotalText")
        data["spaceUsed"] = space_res.get("spaceUsed")
        data["spaceUsedText"] = space_res.get("spaceUsedText")
        data["spaceRemain"] = space_res.get("spaceRemain")
        data["spaceRemainText"] = space_res.get("spaceRemainText")

    sign_res = p115_client.fetch_offline_sign(cookie)
    if sign_res.get("ok") and sign_res.get("offlineLimit") is not None:
        data["offlineLimit"] = sign_res.get("offlineLimit")

    return Envelope(data=data, message="ok")


@router.get("/p115/tasks", response_model=Envelope)
def get_p115_tasks(
    page: int = 1,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    """离线云下载任务列表（转存工作台）。"""
    prev = settings_store.get_setting(settings_store.P115_KEY) or {}
    cookie = str(prev.get("cookie") or "").strip()
    if not cookie:
        raise HTTPException(status_code=400, detail="尚未配置 115，请先填写 Cookie")
    result = p115_offline_svc.list_offline_tasks(cookie, page=max(1, int(page or 1)))
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=str(result.get("message") or "获取任务失败"),
        )
    return Envelope(
        data={
            "tasks": result.get("tasks") or [],
            "page": result.get("page"),
            "pageCount": result.get("pageCount"),
            "count": result.get("count"),
            "quota": result.get("quota"),
            "quotaTotal": result.get("quotaTotal"),
        },
        message=str(result.get("message") or "ok"),
    )


@router.post("/p115/tasks/clear", response_model=Envelope)
def post_p115_tasks_clear(
    body: P115TasksClearBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    """清理离线任务：done / failed / all（不删盘内源文件）。"""
    prev = settings_store.get_setting(settings_store.P115_KEY) or {}
    cookie = str(prev.get("cookie") or "").strip()
    if not cookie:
        raise HTTPException(status_code=400, detail="尚未配置 115，请先填写 Cookie")
    mode = (body.mode or "done").strip().lower()
    result = p115_offline_svc.clear_offline_tasks(cookie, mode)
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=str(result.get("message") or "清理失败"),
        )
    # 清理后顺带回传最新列表与额度，减少前端往返
    listed = p115_offline_svc.list_offline_tasks(cookie, page=1)
    data: dict[str, Any] = {
        "ok": True,
        "mode": result.get("mode") or mode,
        "message": result.get("message"),
    }
    if listed.get("ok"):
        data.update(
            {
                "tasks": listed.get("tasks") or [],
                "count": listed.get("count"),
                "quota": listed.get("quota"),
                "quotaTotal": listed.get("quotaTotal"),
            }
        )
    return Envelope(data=data, message=str(result.get("message") or "已清理"))


@router.post("/p115/qrcode/start", response_model=Envelope)
def post_p115_qrcode_start(
    body: P115QrStartBody | None = None,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    app = (body.app if body else None) or "alipaymini"
    result = p115_qrlogin_svc.start_qrlogin(app)
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=str(result.get("message") or "获取二维码失败"),
        )
    return Envelope(
        data={
            "uid": result.get("uid"),
            "time": result.get("time"),
            "sign": result.get("sign"),
            "qrImage": result.get("qrImage"),
            "qrcode": result.get("qrcode"),
            "app": result.get("app"),
        },
        message=str(result.get("message") or "ok"),
    )


@router.post("/p115/qrcode/status", response_model=Envelope)
def post_p115_qrcode_status(
    body: P115QrStatusBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    result = p115_qrlogin_svc.poll_qrlogin_status(body.uid, body.time, body.sign)
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=str(result.get("message") or "查询扫码状态失败"),
        )
    return Envelope(
        data={
            "status": result.get("status"),
            "statusLabel": result.get("statusLabel"),
            "done": bool(result.get("done")),
            "expired": bool(result.get("expired")),
        },
        message=str(result.get("message") or "ok"),
    )


@router.post("/p115/qrcode/complete", response_model=Envelope)
def post_p115_qrcode_complete(
    body: P115QrCompleteBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    result = p115_qrlogin_svc.complete_qrlogin(body.uid, body.app)
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=str(result.get("message") or "扫码登录失败"),
        )
    cookie = str(result.get("cookie") or "").strip()
    data: dict[str, Any] = {
        "cookie": cookie,
        "app": result.get("app"),
        "saved": False,
    }
    if body.save and cookie:
        prev = settings_store.get_setting(settings_store.P115_KEY) or {}
        targets = _targets_for_store(
            None,
            prev,
            fallback_cid=str(prev.get("folder_cid") or "0"),
            fallback_name=str(prev.get("folder_name") or ""),
        )
        warehouse = targets.get("warehouse") or {
            "folder_cid": "0",
            "folder_name": "",
        }
        value = {
            "enabled": True,
            "cookie": cookie,
            "folder_cid": str(warehouse.get("folder_cid") or "0"),
            "folder_name": str(warehouse.get("folder_name") or ""),
            "label": str(prev.get("label") or ""),
            "targets": targets,
        }
        saved = settings_store.put_setting(settings_store.P115_KEY, value)
        public = _p115_public(saved["value"])
        public["updated_at"] = saved["updated_at"]
        public["saved"] = True
        return Envelope(data=public, message="扫码登录成功，已保存 Cookie")

    return Envelope(data=data, message=str(result.get("message") or "扫码登录成功"))


@router.put("/p115", response_model=Envelope)
def put_p115(
    body: P115Config,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    prev = settings_store.get_setting(settings_store.P115_KEY) or {}
    cookie = (body.cookie or "").strip()
    if not cookie:
        cookie = str(prev.get("cookie") or "").strip()

    stored_targets = _targets_for_store(
        body.targets,
        prev,
        fallback_cid=(body.folder_cid or "0").strip() or "0",
        fallback_name=(body.folder_name or "").strip(),
    )
    warehouse = stored_targets.get("warehouse") or {
        "folder_cid": "0",
        "folder_name": "",
    }
    folder_cid = str(warehouse.get("folder_cid") or "0").strip() or "0"
    folder_name = str(warehouse.get("folder_name") or "").strip()
    label = (body.label or "").strip()

    if not cookie:
        raise HTTPException(status_code=400, detail="请先填写 Cookie")

    quota = None
    quota_total = None
    message = "已保存"
    extra: dict[str, Any] = {}
    if body.do_validate:
        check = p115_client.validate_p115(cookie, folder_cid)
        if not check.get("ok"):
            raise HTTPException(
                status_code=400,
                detail=str(check.get("message") or "验证失败"),
            )
        if not folder_name:
            folder_name = str(check.get("folderName") or "")
            stored_targets["warehouse"] = {
                "folder_cid": folder_cid,
                "folder_name": folder_name,
            }
        quota = check.get("quota")
        quota_total = check.get("quotaTotal")
        message = str(check.get("message") or "已保存")
        for key in (
            "spaceTotal",
            "spaceTotalText",
            "spaceUsed",
            "spaceUsedText",
            "spaceRemain",
            "spaceRemainText",
            "offlineLimit",
        ):
            if key in check:
                extra[key] = check.get(key)

    value = {
        "enabled": True if cookie else bool(body.enabled),
        "cookie": cookie,
        "folder_cid": folder_cid,
        "folder_name": folder_name,
        "label": label,
        "targets": stored_targets,
    }
    saved = settings_store.put_setting(settings_store.P115_KEY, value)
    data = _p115_public(saved["value"])
    data["updated_at"] = saved["updated_at"]
    data["quota"] = quota
    data["quotaTotal"] = quota_total
    data.update(extra)
    return Envelope(data=data, message=message)


@router.post("/p115/folders", response_model=Envelope)
def p115_folders(
    body: P115FoldersBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    prev = settings_store.get_setting(settings_store.P115_KEY) or {}
    cookie = (body.cookie or "").strip() or str(prev.get("cookie") or "").strip()
    if not cookie:
        raise HTTPException(status_code=400, detail="请先配置 115 Cookie")
    result = p115_client.list_folders(cookie, body.cid or "0")
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=str(result.get("message") or "获取目录失败"),
        )
    return Envelope(data=result, message=str(result.get("message") or "ok"))


@router.post("/p115/validate", response_model=Envelope)
def p115_validate(
    body: P115ValidateBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    prev = settings_store.get_setting(settings_store.P115_KEY) or {}
    cookie = (body.cookie or "").strip() or str(prev.get("cookie") or "").strip()
    folder_cid = (body.folder_cid or str(prev.get("folder_cid") or "0")).strip() or "0"
    if not cookie:
        raise HTTPException(status_code=400, detail="请先填写 115 Cookie")
    result = p115_client.validate_p115(cookie, folder_cid)
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=str(result.get("message") or "测试失败"),
        )
    return Envelope(data=result, message=str(result.get("message") or "ok"))


def _p115_public_result(result: dict[str, Any]) -> dict[str, Any]:
    """Strip non-JSON-safe fields (e.g. raw bytes from 115) before responding."""
    out = dict(result or {})
    out.pop("raw", None)
    # Ensure failed rows are plain {url, message}
    failed = out.get("failed")
    if isinstance(failed, list):
        clean: list[dict[str, str]] = []
        for row in failed:
            if not isinstance(row, dict):
                continue
            clean.append(
                {
                    "url": str(row.get("url") or ""),
                    "message": str(row.get("message") or "失败"),
                }
            )
        out["failed"] = clean
    hashes = out.get("infoHashes")
    if isinstance(hashes, list):
        out["infoHashes"] = [str(h) for h in hashes if h]
    per_url = out.get("perUrl")
    if isinstance(per_url, list):
        out["perUrl"] = [
            {
                "url": str(row.get("url") or ""),
                "message": str(row.get("message") or ""),
            }
            for row in per_url
            if isinstance(row, dict)
        ]
    return out


def _p115_json_response(
    *,
    result: dict[str, Any],
    message: str,
    status: int,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    data = _p115_public_result(result)
    if extra:
        data.update(extra)
    payload = Envelope(data=data, message=message or "", status=status)
    try:
        content = payload.model_dump()
        # Hard fallback: never 500 on serialization
        json.dumps(content, ensure_ascii=False, default=str)
    except Exception:
        content = {
            "data": {
                "ok": bool(result.get("ok")),
                "added": int(result.get("added") or 0),
                "failed": [],
                "infoHashes": [],
            },
            "message": message or ("转存成功" if result.get("ok") else "转存失败"),
            "status": status,
        }
    return JSONResponse(status_code=status, content=content)


@router.post("/p115/offline")
def post_p115_offline(
    body: P115OfflineBody,
    _user: dict[str, Any] = Depends(require_user),
) -> JSONResponse:
    """对齐 sehua `/api/115/offline`：lixian → clouddownload，成功后可调度云解压。"""
    try:
        prev = settings_store.get_setting(settings_store.P115_KEY) or {}
        cookie = str(prev.get("cookie") or "").strip()
        if not cookie:
            raise HTTPException(
                status_code=400,
                detail="尚未配置 115，请先打开「设置」填写 Cookie",
            )

        urls = [
            u.strip()
            for u in body.urls
            if (u or "").strip()
            and _is_offline_url(u)
            and not p115_share_svc.is_115_share_link(u)
        ]
        if not urls:
            raise HTTPException(status_code=400, detail="没有可转存的磁力/ED2K 链接")

        folder_cid, _folder_name = _resolve_p115_folder(
            prev,
            source=body.source,
            folder_cid=body.folder_cid,
        )
        result = p115_offline_svc.add_offline_tasks(cookie, urls, folder_cid)
        password = (body.password or "").strip()
        looks_archive = any(_looks_archive_link(u) for u in urls)
        want_extract = (
            bool(result.get("ok"))
            and int(result.get("added") or 0) > 0
            and body.auto_extract is not False
            and (bool(password) or looks_archive or body.auto_extract is True)
        )

        extract_scheduled = False
        if want_extract:
            p115_extract.schedule_deferred_extract(
                {
                    "cookie": cookie,
                    "folderCid": folder_cid,
                    "password": password,
                    "infoHashes": result.get("infoHashes") or [],
                    "titleHint": body.title_hint or "",
                }
            )
            extract_scheduled = True

        message = str(result.get("message") or "")
        if extract_scheduled:
            message = f"{message} · 后台轮询转存（最长约 30 秒），完成后立即云解压"

        status = 200 if result.get("ok") else 400
        return _p115_json_response(
            result=result,
            message=message,
            status=status,
            extra={
                "extractScheduled": extract_scheduled,
                "extractMode": "poll" if extract_scheduled else None,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        return _p115_json_response(
            result={"ok": False, "added": 0, "failed": [], "infoHashes": []},
            message=f"转存异常：{type(e).__name__}: {e}",
            status=400,
        )


@router.post("/p115/share")
def post_p115_share(
    body: P115ShareBody,
    _user: dict[str, Any] = Depends(require_user),
) -> JSONResponse:
    """对齐 sehua `/api/115/share`。"""
    try:
        prev = settings_store.get_setting(settings_store.P115_KEY) or {}
        cookie = str(prev.get("cookie") or "").strip()
        if not cookie:
            raise HTTPException(
                status_code=400,
                detail="尚未配置 115，请先打开「设置」填写 Cookie",
            )

        urls = [
            u.strip() for u in body.urls if p115_share_svc.is_115_share_link(u)
        ]
        if not urls:
            raise HTTPException(status_code=400, detail="没有可转存的 115 分享链接")

        folder_cid, _folder_name = _resolve_p115_folder(
            prev,
            source=body.source,
            folder_cid=body.folder_cid,
        )
        result = p115_share_svc.receive_115_shares(
            cookie,
            urls,
            folder_cid,
            (body.password or "").strip(),
        )
        status = 200 if result.get("ok") else 400
        return _p115_json_response(
            result=result,
            message=str(result.get("message") or ""),
            status=status,
        )
    except HTTPException:
        raise
    except Exception as e:
        return _p115_json_response(
            result={"ok": False},
            message=f"转存异常：{type(e).__name__}: {e}",
            status=400,
        )


def _proxy_host_port(raw: str | None) -> str:
    """规范化后的代理 → 展示用 host:port（可含 user:pass@）。"""
    full = _normalize_proxy_url(raw)
    if not full:
        return ""
    parsed = urlparse(full)
    return parsed.netloc or ""


def _flare_host_port(raw: str | None) -> str:
    """FlareSolverr 基址 → 展示用 host:port。"""
    from .outbound_http import normalize_flaresolverr_url

    full = normalize_flaresolverr_url(raw)
    if not full:
        return ""
    parsed = urlparse(full)
    return parsed.netloc or ""


def _as_bool(raw: Any, *, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off", ""):
        return False
    return default


def _network_public(raw: Any) -> dict[str, Any]:
    from .outbound_http import normalize_flaresolverr_url

    stored = ""
    enabled_raw: Any = None
    flare_stored = ""
    flare_enabled_raw: Any = None
    if isinstance(raw, dict):
        stored = _normalize_proxy_url(
            str(raw.get("proxyUrl") or raw.get("proxy_url") or "")
        )
        enabled_raw = raw.get("proxyEnabled")
        if enabled_raw is None:
            enabled_raw = raw.get("proxy_enabled")
        flare_stored = normalize_flaresolverr_url(
            str(
                raw.get("flareSolverrUrl")
                or raw.get("flare_solverr_url")
                or raw.get("flaresolverrUrl")
                or ""
            )
        )
        flare_enabled_raw = raw.get("flareSolverrEnabled")
        if flare_enabled_raw is None:
            flare_enabled_raw = raw.get("flare_solverr_enabled")
    if not stored:
        legacy = settings_store.get_setting("scrape") or {}
        if isinstance(legacy, dict):
            stored = _normalize_proxy_url(
                str(legacy.get("proxyUrl") or legacy.get("proxy_url") or "")
            )
            if enabled_raw is None:
                enabled_raw = legacy.get("proxyEnabled")
                if enabled_raw is None:
                    enabled_raw = legacy.get("proxy_enabled")
    # 有地址且未写开关时默认启用，兼容旧配置
    enabled = _as_bool(enabled_raw, default=bool(stored))
    active = bool(stored and enabled)
    flare_enabled = _as_bool(flare_enabled_raw, default=bool(flare_stored))
    flare_active = bool(flare_stored and flare_enabled)
    return {
        "proxyUrl": _proxy_host_port(stored),
        "proxyEnabled": enabled,
        "configured": active,
        "fromEnv": False,
        "effectiveProxyUrl": _proxy_host_port(stored if active else ""),
        "flareSolverrUrl": _flare_host_port(flare_stored),
        "flareSolverrEnabled": flare_enabled,
        "flareSolverrConfigured": flare_active,
        "effectiveFlareSolverrUrl": _flare_host_port(flare_stored if flare_active else ""),
    }


class NetworkConfig(BaseModel):
    proxy_url: str = Field(default="", alias="proxyUrl")
    proxy_enabled: bool | None = Field(default=None, alias="proxyEnabled")
    flare_solverr_url: str | None = Field(default=None, alias="flareSolverrUrl")
    flare_solverr_enabled: bool | None = Field(default=None, alias="flareSolverrEnabled")

    model_config = {"populate_by_name": True}


def _friendly_probe_error(exc: BaseException) -> str:
    msg = str(exc).strip() or exc.__class__.__name__
    low = msg.lower()
    if "connect" in low or "timeout" in low:
        return "无法连接代理或目标站超时"
    if "proxy" in low:
        return f"代理错误：{msg}"
    return msg


@router.get("/network", response_model=Envelope)
def get_network(_user: dict[str, Any] | None = Depends(get_optional_user)) -> Envelope:
    data = _network_public(settings_store.get_setting(settings_store.LIBRARY_KEY))
    return Envelope(
        data=data,
        message="configured" if data["configured"] else "not_configured",
    )


@router.put("/network", response_model=Envelope)
def put_network(
    body: NetworkConfig,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    from .outbound_http import normalize_flaresolverr_url

    prev = settings_store.get_setting(settings_store.LIBRARY_KEY) or {}
    if not isinstance(prev, dict):
        prev = {}
    next_val = dict(prev)
    # 代理：仅当请求显式带了 proxyUrl 字段时更新（Pydantic 总有默认 ""）
    # 前端保存会整包提交；空串表示清空
    next_val["proxyUrl"] = _normalize_proxy_url(body.proxy_url)
    if body.proxy_enabled is not None:
        next_val["proxyEnabled"] = bool(body.proxy_enabled)
    elif "proxyEnabled" not in next_val and "proxy_enabled" not in next_val:
        next_val["proxyEnabled"] = bool(next_val["proxyUrl"])

    if body.flare_solverr_url is not None:
        next_val["flareSolverrUrl"] = normalize_flaresolverr_url(body.flare_solverr_url)
    if body.flare_solverr_enabled is not None:
        next_val["flareSolverrEnabled"] = bool(body.flare_solverr_enabled)
    elif body.flare_solverr_url is not None and (
        "flareSolverrEnabled" not in next_val and "flare_solverr_enabled" not in next_val
    ):
        next_val["flareSolverrEnabled"] = bool(next_val.get("flareSolverrUrl"))

    saved = settings_store.put_setting(settings_store.LIBRARY_KEY, next_val)
    data = _network_public(saved["value"])
    data["updated_at"] = saved["updated_at"]
    return Envelope(data=data, message="saved")


@router.post("/network/test", response_model=Envelope)
def test_network(
    body: NetworkConfig,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    raw = settings_store.get_setting(settings_store.LIBRARY_KEY) or {}
    proxy = _normalize_proxy_url(
        body.proxy_url
        if body.proxy_url is not None and str(body.proxy_url).strip()
        else (
            (raw.get("proxyUrl") or raw.get("proxy_url"))
            if isinstance(raw, dict)
            else ""
        )
    )
    if not proxy:
        raise HTTPException(status_code=400, detail="请先填写代理地址")

    sample_urls = [
        "https://httpbin.org/ip",
        "https://api.ipify.org?format=json",
        "https://api.themoviedb.org/3",
    ]
    last_err = ""
    try:
        with httpx.Client(timeout=12.0, trust_env=False, proxy=proxy) as client:
            for sample_url in sample_urls:
                try:
                    r = client.get(sample_url)
                    ok = r.status_code < 500
                    detail: Any
                    try:
                        detail = r.json() if r.content else {"status": r.status_code}
                    except Exception:
                        detail = {"status": r.status_code}
                    return Envelope(
                        data={
                            "ok": ok,
                            "proxyUrl": _proxy_host_port(proxy),
                            "detail": detail if isinstance(detail, dict) else {"status": r.status_code},
                        },
                        message="代理正常" if ok else f"代理失败（HTTP {r.status_code}）",
                    )
                except Exception as e:
                    last_err = _friendly_probe_error(e)
                    continue
        raise HTTPException(status_code=502, detail=f"代理测试失败：{last_err}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"代理测试失败：{_friendly_probe_error(e)}",
        ) from e


@router.post("/network/flare-test", response_model=Envelope)
def test_flaresolverr(
    body: NetworkConfig,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    from .outbound_http import flaresolverr_ping, normalize_flaresolverr_url

    raw = settings_store.get_setting(settings_store.LIBRARY_KEY) or {}
    flare = ""
    if body.flare_solverr_url is not None and str(body.flare_solverr_url).strip():
        flare = normalize_flaresolverr_url(body.flare_solverr_url)
    elif isinstance(raw, dict):
        flare = normalize_flaresolverr_url(
            str(
                raw.get("flareSolverrUrl")
                or raw.get("flare_solverr_url")
                or ""
            )
        )
    if not flare:
        raise HTTPException(status_code=400, detail="请先填写 FlareSolverr 地址")
    try:
        detail = flaresolverr_ping(flare)
        return Envelope(
            data={
                "ok": True,
                "flareSolverrUrl": _flare_host_port(flare),
                "detail": detail,
            },
            message="FlareSolverr 正常",
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"FlareSolverr 测试失败：{_friendly_probe_error(e)}",
        ) from e


# —— 片商管理（数据源链接） ——


class MakersCatalogBody(BaseModel):
    javbus: dict[str, Any] | None = None
    iqqtv: dict[str, Any] | None = None
    missav: dict[str, Any] | None = None
    sevenmmtv: dict[str, Any] | None = Field(default=None, alias="7mmtv")
    madou: dict[str, Any] | None = None
    sourceOrder: list[str] | None = None

    model_config = {"populate_by_name": True}


class MakersProbeBody(BaseModel):
    source: str = "javbus"
    persist: bool = True
    javbus: dict[str, Any] | None = None
    iqqtv: dict[str, Any] | None = None
    missav: dict[str, Any] | None = None
    sevenmmtv: dict[str, Any] | None = Field(default=None, alias="7mmtv")
    madou: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


@router.get("/makers", response_model=Envelope)
def get_makers_catalog(
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> Envelope:
    from . import makers_settings

    data = makers_settings.makers_catalog_public()
    return Envelope(
        data=data,
        message="configured" if data.get("configured") else "not_configured",
    )


@router.post("/makers/refresh", response_model=Envelope)
def refresh_makers_mirrors(
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    """强制发现最新落地镜像并写入全局缓存；片商拉页立即改用。"""
    from . import makers_settings
    from . import site_mirror

    cfg = makers_settings.resolve_makers_catalog()
    refresh: dict[str, Any] = {}

    jobs: list[tuple[str, list[str], callable]] = []
    if cfg["javbus"].get("enabled"):
        jobs.append(("javbus", list(cfg["javbus"].get("bases") or []), lambda b: b))
    if cfg["iqqtv"].get("enabled"):
        jobs.append(
            ("iqqtv", list(cfg["iqqtv"].get("seeds") or []), lambda b: f"{b}/cn")
        )
    if cfg["missav"].get("enabled"):
        jobs.append(
            ("missav", list(cfg["missav"].get("seeds") or []), lambda b: f"{b}/cn")
        )
    if cfg["7mmtv"].get("enabled"):
        jobs.append(("7mmtv", list(cfg["7mmtv"].get("seeds") or []), lambda b: b))
    if cfg["madou"].get("enabled"):
        jobs.append(("madou", list(cfg["madou"].get("seeds") or []), lambda b: b))

    for sid, seeds, fmt in jobs:
        t0 = time.perf_counter()
        try:
            base = site_mirror.resolve(sid, seeds=seeds, force=True)
            refresh[sid] = {
                "ok": True,
                "activeBase": fmt(base),
                "root": base,
                "ms": int((time.perf_counter() - t0) * 1000),
            }
        except Exception as e:
            refresh[sid] = {
                "ok": False,
                "error": str(e),
                "ms": int((time.perf_counter() - t0) * 1000),
            }

    data = makers_settings.makers_catalog_public()
    data["refresh"] = refresh
    ok_n = sum(1 for v in refresh.values() if isinstance(v, dict) and v.get("ok"))
    return Envelope(
        data=data,
        message=f"refreshed · {ok_n}/{len(refresh)}" if refresh else "noop",
    )


@router.put("/makers", response_model=Envelope)
def put_makers_catalog(
    body: MakersCatalogBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    from . import makers_settings
    from .makers_catalog_routes import _clear_makers_cache

    payload = body.model_dump(exclude_none=True, by_alias=True)
    # 兼容未走 alias 的字段名
    if "sevenmmtv" in payload and "7mmtv" not in payload:
        payload["7mmtv"] = payload.pop("sevenmmtv")
    if "miss_av" in payload and "missav" not in payload:
        payload["missav"] = payload.pop("miss_av")
    data = makers_settings.save_makers_catalog(payload)
    try:
        # 只清列表缓存，保留 live 镜像；新种子会在下次 refresh / 拉页时优先探测
        _clear_makers_cache(wipe_mirrors=False)
    except Exception:
        pass
    return Envelope(data=data, message="saved")


@router.post("/makers/test", response_model=Envelope)
def test_makers_catalog(
    body: MakersProbeBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    """测通数据源：优先用请求体临时配置，否则读已保存配置。

    persist=True 时写入全局镜像缓存，拉页会优先用最新落地基址。
    """
    from bs4 import BeautifulSoup

    from . import makers_settings
    from . import site_mirror
    from .makers_catalog_routes import _TIMEOUT, _UA
    from .outbound_http import resolve_scrape_proxy_url

    src = (body.source or "javbus").strip().lower()
    persist = bool(body.persist)
    base_cfg = makers_settings.resolve_makers_catalog()
    if isinstance(body.javbus, dict):
        base_cfg["javbus"] = makers_settings._provider_block(
            {**base_cfg["javbus"], **body.javbus},
            default_enabled=True,
            default_urls=makers_settings.DEFAULT_JAVBUS_BASES,
            url_key="bases",
            cookie_default=makers_settings.DEFAULT_JAVBUS_COOKIE,
        )
    if isinstance(body.iqqtv, dict):
        base_cfg["iqqtv"] = makers_settings._provider_block(
            {**base_cfg["iqqtv"], **body.iqqtv},
            default_enabled=True,
            default_urls=makers_settings.DEFAULT_IQQTV_SEEDS,
            url_key="seeds",
        )
    missav_body = body.missav
    if isinstance(missav_body, dict):
        base_cfg["missav"] = makers_settings._provider_block(
            {**base_cfg["missav"], **missav_body},
            default_enabled=True,
            default_urls=makers_settings.DEFAULT_MISSAV_SEEDS,
            url_key="seeds",
        )
    seven_body = body.sevenmmtv
    if isinstance(seven_body, dict):
        base_cfg["7mmtv"] = makers_settings._provider_block(
            {**base_cfg["7mmtv"], **seven_body},
            default_enabled=True,
            default_urls=makers_settings.DEFAULT_SEVENMM_SEEDS,
            url_key="seeds",
        )
    if isinstance(body.madou, dict):
        base_cfg["madou"] = makers_settings._provider_block(
            {**base_cfg["madou"], **body.madou},
            default_enabled=True,
            default_urls=makers_settings.DEFAULT_MADOU_SEEDS,
            url_key="seeds",
        )

    proxy = resolve_scrape_proxy_url()

    def _probe_simple_origin(
        *,
        sid: str,
        seeds: list[str],
        path: str,
        looks: callable,
        label: str,
        active_fmt: callable | None = None,
    ) -> Envelope:
        last_err = ""
        if persist and len(seeds) > 1:
            t0 = time.perf_counter()
            try:
                live = site_mirror.resolve(sid, seeds=seeds, force=True)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                active = active_fmt(live) if active_fmt else live
                return Envelope(
                    data={
                        "ok": True,
                        "source": sid,
                        "base": live,
                        "activeBase": active,
                        "via": "proxy" if proxy else "direct",
                        "ms": elapsed_ms,
                    },
                    message=f"{label} 通 · {elapsed_ms}ms · {active}",
                )
            except Exception as e:
                last_err = str(e)

        for seed in seeds:
            root = site_mirror.origin(seed) or seed.rstrip("/")
            if sid == "missav" and site_mirror.is_missav_dead_host(root):
                last_err = "missav.com 已失效（ThisAV 占位），请换 .ws/.ai 镜像"
                continue
            url = f"{root}{path}"
            opts_list: list[dict[str, Any]] = []
            if proxy:
                opts_list.append({"proxy": proxy, "verify": False})
            opts_list.append({"verify": False})
            html = ""
            via = "direct"
            elapsed_ms = 0
            final_url = url
            for opts in opts_list:
                try:
                    t0 = time.perf_counter()
                    with httpx.Client(
                        timeout=_TIMEOUT,
                        trust_env=False,
                        follow_redirects=True,
                        **opts,
                    ) as client:
                        r = client.get(
                            url,
                            headers={"User-Agent": _UA, "Accept": "text/html"},
                        )
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    if r.status_code >= 400:
                        last_err = f"HTTP {r.status_code}"
                        continue
                    html = r.text or ""
                    final_url = str(r.url)
                    via = "proxy" if "proxy" in opts else "direct"
                    if html:
                        break
                except Exception as e:
                    last_err = str(e)
                    continue
            if not html or len(html) < 200:
                last_err = last_err or "页面过短"
                continue
            if re.search(r"just a moment|attention required", html, re.I):
                last_err = "CF 盾拦截（代理自适应未过）"
                continue
            if not looks(html):
                # 尽量带上可观测计数，方便区分空壳 vs 结构变化
                n = 0
                if sid == "missav":
                    n = site_mirror.missav_content_count(html)
                elif sid == "7mmtv":
                    n = site_mirror.sevenmm_content_count(html)
                elif sid == "madou":
                    n = site_mirror.madou_content_count(html)
                last_err = f"无有效列表（items={n}）"
                continue
            landed = site_mirror.origin(final_url) or root
            if sid == "missav" and site_mirror.is_missav_dead_host(landed):
                last_err = "missav.com 已失效（ThisAV 占位），请换 .ws/.ai 镜像"
                continue
            # 跟到落地站后，若 host 变了再验一次，日常直连 landed
            if site_mirror.origin(landed) != site_mirror.origin(root):
                try:
                    t1 = time.perf_counter()
                    with httpx.Client(
                        timeout=_TIMEOUT,
                        trust_env=False,
                        follow_redirects=True,
                        **({"proxy": proxy, "verify": False} if proxy else {"verify": False}),
                    ) as client:
                        r2 = client.get(
                            f"{landed}{path}",
                            headers={"User-Agent": _UA, "Accept": "text/html"},
                        )
                    elapsed_ms = int((time.perf_counter() - t1) * 1000)
                    if r2.status_code < 400 and looks(r2.text or ""):
                        landed = site_mirror.origin(str(r2.url)) or landed
                        html = r2.text or html
                    else:
                        last_err = "落地站无有效列表"
                        continue
                except Exception as e:
                    last_err = str(e)
                    continue
            if sid == "iqqtv" and site_mirror.is_iqqtv_redirect_seed(landed):
                last_err = "仍为跳转网关，未得到直连站"
                continue
            if sid == "missav" and site_mirror.is_missav_dead_host(landed):
                last_err = "missav.com 已失效（ThisAV 占位），请换 .ws/.ai 镜像"
                continue
            if persist:
                site_mirror.remember(sid, landed, discovered_from=seed)
            active = active_fmt(landed) if active_fmt else landed
            items = 0
            if sid == "missav":
                items = site_mirror.missav_content_count(html)
            elif sid == "7mmtv":
                items = site_mirror.sevenmm_content_count(html)
            elif sid == "madou":
                items = site_mirror.madou_content_count(html)
            return Envelope(
                data={
                    "ok": True,
                    "source": sid,
                    "seed": seed,
                    "base": landed,
                    "activeBase": active,
                    "via": via,
                    "items": items,
                    "ms": elapsed_ms,
                },
                message=f"{label} 通 · {elapsed_ms}ms · {via} · {items}条",
            )
        raise HTTPException(
            status_code=502,
            detail=f"{label} 测通失败：{last_err or '全部种子不可用'}",
        )

    if src == "javbus":
        jav = base_cfg["javbus"]
        seeds = list(jav.get("bases") or makers_settings.DEFAULT_JAVBUS_BASES)
        cookie = str(jav.get("cookie") or makers_settings.DEFAULT_JAVBUS_COOKIE)
        last_err = ""
        # 全局发现：按种子顺序找第一个可用并可选落盘
        if persist and len(seeds) > 1:
            t0 = time.perf_counter()
            try:
                live = site_mirror.resolve("javbus", seeds=seeds, force=True)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                return Envelope(
                    data={
                        "ok": True,
                        "source": "javbus",
                        "base": live,
                        "activeBase": live,
                        "via": "proxy" if proxy else "direct",
                        "ms": elapsed_ms,
                    },
                    message=f"JavBus 通 · {elapsed_ms}ms · {live}",
                )
            except Exception as e:
                last_err = str(e)

        for base in seeds:
            headers = {
                "User-Agent": _UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": f"{base}/",
            }
            if cookie:
                headers["Cookie"] = cookie
            opts_list: list[dict[str, Any]] = []
            if proxy:
                opts_list.append({"proxy": proxy, "verify": False})
            opts_list.append({"verify": False})
            html = ""
            via = "direct"
            elapsed_ms = 0
            final_url = base
            for opts in opts_list:
                try:
                    t0 = time.perf_counter()
                    with httpx.Client(
                        timeout=_TIMEOUT,
                        trust_env=False,
                        follow_redirects=True,
                        **opts,
                    ) as client:
                        r = client.get(f"{base}/", headers=headers)
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    if r.status_code >= 400:
                        last_err = f"HTTP {r.status_code}"
                        continue
                    html = r.text or ""
                    final_url = str(r.url)
                    via = "proxy" if "proxy" in opts else "direct"
                    if html:
                        break
                except Exception as e:
                    last_err = str(e)
                    continue
            if not html or len(html) < 200:
                last_err = last_err or "页面过短"
                continue
            if re.search(r"Age Verification|年齡驗證|年龄验证", html, re.I) and not re.search(
                r"movie-box|bigImage", html, re.I
            ):
                last_err = "年龄门未过，请检查 Cookie"
                continue
            if "just a moment" in html.lower():
                last_err = "CF 盾拦截"
                continue
            soup = BeautifulSoup(html, "lxml")
            boxes = len(soup.select("a.movie-box"))
            if boxes < 3:
                # 停放页/空壳也会 200，必须有真实列表才算可用
                last_err = f"无有效列表（movie-box={boxes}）"
                continue
            landed = site_mirror.origin(final_url) or base
            # 统一 https 展示（探测可用后）
            if landed.startswith("http://"):
                landed = "https://" + landed[len("http://") :]
            if persist:
                site_mirror.remember("javbus", landed, discovered_from=base)
            return Envelope(
                data={
                    "ok": True,
                    "source": "javbus",
                    "base": landed,
                    "activeBase": landed,
                    "via": via,
                    "movieBoxes": boxes,
                    "ms": elapsed_ms,
                },
                message=f"JavBus 通 · {elapsed_ms}ms · {via} · {boxes}条",
            )
        raise HTTPException(
            status_code=502,
            detail=f"JavBus 测通失败：{last_err or '全部镜像不可用'}",
        )

    if src == "iqqtv":
        seeds = list(
            base_cfg["iqqtv"].get("seeds") or makers_settings.DEFAULT_IQQTV_SEEDS
        )
        last_err = ""
        if persist and len(seeds) > 1:
            t0 = time.perf_counter()
            try:
                root = site_mirror.resolve("iqqtv", seeds=seeds, force=True)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                active = f"{root}/cn"
                return Envelope(
                    data={
                        "ok": True,
                        "source": "iqqtv",
                        "seed": seeds[0],
                        "base": root,
                        "activeBase": active,
                        "ms": elapsed_ms,
                    },
                    message=f"iQQTV 通 · {elapsed_ms}ms · {active}",
                )
            except Exception as e:
                last_err = str(e)

        for seed in seeds:
            try:
                opts_list: list[dict[str, Any]] = []
                if proxy:
                    opts_list.append({"proxy": proxy, "verify": False})
                opts_list.append({"verify": False})
                html = ""
                via = "direct"
                elapsed_ms = 0
                final = ""
                for opts in opts_list:
                    try:
                        t0 = time.perf_counter()
                        with httpx.Client(
                            timeout=_TIMEOUT,
                            trust_env=False,
                            follow_redirects=True,
                            **opts,
                        ) as client:
                            r = client.get(
                                f"{seed}/cn/",
                                headers={"User-Agent": _UA, "Accept": "text/html"},
                            )
                        elapsed_ms = int((time.perf_counter() - t0) * 1000)
                        if r.status_code >= 400:
                            last_err = f"HTTP {r.status_code}"
                            continue
                        html = r.text or ""
                        final = str(r.url)
                        via = "proxy" if "proxy" in opts else "direct"
                        if html:
                            break
                    except Exception as e:
                        last_err = str(e)
                        continue
                if not html or len(html) < 200:
                    last_err = last_err or "页面过短"
                    continue
                if re.search(r"just a moment|attention required", html, re.I):
                    last_err = "CF 盾拦截"
                    continue
                items = site_mirror.iqqtv_content_count(html)
                if items < 3:
                    last_err = f"无有效列表（items={items}）"
                    continue
                # 再以真实列表解析为准，避免模板里残留 /h/ 链误判
                from .makers_catalog_routes import _parse_iqqtv_list

                root_guess = site_mirror.origin(final) or site_mirror.origin(seed) or ""
                parsed = _parse_iqqtv_list(html, root_guess) if root_guess else []
                if len(parsed) < 3:
                    last_err = f"无有效列表（parsed={len(parsed)}）"
                    continue
                items = len(parsed)
                root = root_guess
                if not root:
                    last_err = "无效落地"
                    continue
                if site_mirror.is_iqqtv_redirect_seed(root):
                    last_err = "仍为跳转网关，未得到直连站"
                    continue
                if persist:
                    remembered = site_mirror.remember(
                        "iqqtv", root, discovered_from=seed
                    )
                    if remembered:
                        root = remembered
                    elif site_mirror.is_iqqtv_redirect_seed(root):
                        root = site_mirror.resolve("iqqtv", seeds=[seed], force=True)
                if site_mirror.is_iqqtv_redirect_seed(root):
                    last_err = "仍为跳转网关，未得到直连站"
                    continue
                active = f"{root}/cn"
                return Envelope(
                    data={
                        "ok": True,
                        "source": "iqqtv",
                        "seed": seed,
                        "base": root,
                        "activeBase": active,
                        "items": items,
                        "via": via,
                        "ms": elapsed_ms,
                    },
                    message=f"iQQTV 通 · {elapsed_ms}ms · {via} · {items}条",
                )
            except Exception as e:
                last_err = str(e)
                continue
        raise HTTPException(
            status_code=502,
            detail=f"iQQTV 测通失败：{last_err or '全部种子不可用'}",
        )

    if src == "missav":
        from . import makers_providers_extra as makers_extra

        seeds = list(
            base_cfg["missav"].get("seeds") or makers_settings.DEFAULT_MISSAV_SEEDS
        )
        return _probe_simple_origin(
            sid="missav",
            seeds=seeds,
            path="/cn/",
            looks=makers_extra.looks_missav,
            label="MissAV",
            active_fmt=lambda b: f"{b}/cn",
        )

    if src in ("7mmtv", "sevenmmtv"):
        from . import makers_providers_extra as makers_extra

        seeds = list(
            base_cfg["7mmtv"].get("seeds") or makers_settings.DEFAULT_SEVENMM_SEEDS
        )
        return _probe_simple_origin(
            sid="7mmtv",
            seeds=seeds,
            path="/zh/",
            looks=makers_extra.looks_sevenmm,
            label="7MMTV",
        )

    if src == "madou":
        from . import makers_providers_extra as makers_extra

        seeds = list(
            base_cfg["madou"].get("seeds") or makers_settings.DEFAULT_MADOU_SEEDS
        )
        return _probe_simple_origin(
            sid="madou",
            seeds=seeds,
            path="/",
            looks=makers_extra.looks_madou,
            label="Madou",
        )

    raise HTTPException(status_code=400, detail=f"未知数据源: {src}")

