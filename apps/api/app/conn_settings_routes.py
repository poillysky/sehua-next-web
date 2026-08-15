"""Scrape / 115 connection settings (SQLite meta)."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .auth_routes import get_optional_user, require_user
from . import p115_client, p115_extract, settings_store
from . import p115_offline as p115_offline_svc
from . import p115_share as p115_share_svc
from .db import ROOT

_ARCHIVE_EXT_RE = re.compile(r"\.(zip|rar|7z)(?:\.[a-z0-9]+)?$", re.I)

router = APIRouter(prefix="/settings", tags=["settings"])

# 单容器默认：刮削本机回环；过盾/代理由环境变量注入，UI 不开放填写
DEFAULT_SCRAPE_ORIGIN = (
    os.environ.get("SCRAPE_ORIGIN", "http://127.0.0.1:9210").strip()
    or "http://127.0.0.1:9210"
)
DEFAULT_FLARESOLVERR_URL = (
    os.environ.get("FLARESOLVERR_URL", "").strip()
    or os.environ.get("SNS_FLARESOLVERR_URL", "").strip()
)
DEFAULT_PROXY_URL = (
    os.environ.get("SNS_PROXY_URL", "").strip()
    or os.environ.get("HTTPS_PROXY", "").strip()
    or os.environ.get("HTTP_PROXY", "").strip()
)
DEFAULT_LIBRARY_REL = "data/library"
_LIBRARY_SKIP_DIRS = frozenset({"maker-fs"})


def _normalize_flare_url(raw: str | None) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = f"http://{s}"
    s = s.rstrip("/")
    if not s.lower().endswith("/v1"):
        s = f"{s}/v1"
    return s


def _normalize_origin_url(raw: str | None) -> str:
    """支持 127.0.0.1:9210 / http://host:port；默认内置 scrape。"""
    s = str(raw or "").strip() or DEFAULT_SCRAPE_ORIGIN
    if "://" not in s:
        s = f"http://{s}"
    s = s.rstrip("/")
    parsed = urlparse(s)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return DEFAULT_SCRAPE_ORIGIN.rstrip("/")
    return s


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


def _library_options() -> list[dict[str, str]]:
    """扫描 data/ 下可用库目录（含嵌套，跳过 maker-fs）。"""
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "library").mkdir(parents=True, exist_ok=True)
    opts: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(rel: str, label: str | None = None) -> None:
        rel = rel.replace("\\", "/").strip("/")
        if not rel or rel in seen:
            return
        seen.add(rel)
        opts.append({"value": rel, "label": label or rel})

    add(DEFAULT_LIBRARY_REL, "data/library（默认）")
    try:
        for dirpath, dirnames, _filenames in os.walk(data_dir):
            # 跳过隐藏与 maker-fs 整棵
            base = Path(dirpath)
            try:
                rel_base = base.resolve().relative_to(data_dir.resolve()).as_posix()
            except ValueError:
                dirnames[:] = []
                continue
            parts = () if rel_base == "." else Path(rel_base).parts
            if parts and parts[0] in _LIBRARY_SKIP_DIRS:
                dirnames[:] = []
                continue
            dirnames[:] = sorted(
                (
                    n
                    for n in dirnames
                    if not n.startswith(".") and n not in _LIBRARY_SKIP_DIRS
                ),
                key=str.lower,
            )
            # 深度限制：data/a/b/c 最多 3 层
            if len(parts) >= 3:
                dirnames[:] = []
            for name in dirnames:
                child_parts = parts + (name,) if parts else (name,)
                add("data/" + "/".join(child_parts))
    except OSError:
        pass
    return opts


def _browse_library_dirs(raw_path: str | None) -> dict[str, Any]:
    """真实列出项目 data/ 下子目录，供默认库路径浏览。"""
    rel = _safe_data_rel(raw_path, default="data")
    abs_dir = (ROOT / rel).resolve()
    data_root = (ROOT / "data").resolve()
    try:
        abs_dir.relative_to(data_root)
    except ValueError:
        rel = "data"
        abs_dir = data_root
    abs_dir.mkdir(parents=True, exist_ok=True)

    crumbs: list[dict[str, str]] = []
    acc: list[str] = []
    for part in Path(rel).parts:
        acc.append(part)
        crumbs.append({"name": part, "path": "/".join(acc)})

    entries: list[dict[str, str]] = []
    try:
        children = sorted(
            (c for c in abs_dir.iterdir() if c.is_dir() and not c.name.startswith(".")),
            key=lambda x: x.name.lower(),
        )
        for child in children:
            child_rel = f"{rel}/{child.name}".replace("\\", "/")
            entries.append(
                {
                    "name": child.name,
                    "path": child_rel,
                    "absPath": str(child.resolve()),
                }
            )
    except OSError:
        pass

    parent: str | None = None
    parts = Path(rel).parts
    if len(parts) > 1:
        parent = "/".join(parts[:-1])

    return {
        "path": rel,
        "absPath": str(abs_dir),
        "parent": parent,
        "crumbs": crumbs,
        "entries": entries,
        "selectable": rel != "data",
    }


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


def _normalize_export_concurrency(raw: Any) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 4
    if n <= 0:
        n = 4
    return max(1, min(8, n))


def _pick_concurrency_raw(raw: dict[str, Any] | None, *keys: str) -> Any:
    d = raw or {}
    for k in keys:
        if k in d and d.get(k) is not None:
            return d.get(k)
    return None


def _resolve_channel_concurrency(
    raw: dict[str, Any] | None,
    *,
    fast: Any = None,
    slow: Any = None,
    legacy: Any = None,
) -> tuple[int, int, int]:
    """快/慢通道并发；缺省时回落到 exportConcurrency。返回 (fast, slow, legacy)。"""
    d = raw or {}
    leg = _normalize_export_concurrency(
        legacy
        if legacy is not None
        else _pick_concurrency_raw(d, "exportConcurrency", "export_concurrency")
    )
    fast_raw = (
        fast
        if fast is not None
        else _pick_concurrency_raw(
            d, "exportFastConcurrency", "export_fast_concurrency"
        )
    )
    slow_raw = (
        slow
        if slow is not None
        else _pick_concurrency_raw(
            d, "exportSlowConcurrency", "export_slow_concurrency"
        )
    )
    fast_n = _normalize_export_concurrency(
        fast_raw if fast_raw is not None else leg
    )
    slow_n = _normalize_export_concurrency(
        slow_raw if slow_raw is not None else leg
    )
    # legacy 字段保留为两者较大值，兼容旧客户端
    return fast_n, slow_n, max(fast_n, slow_n)


def _normalize_cover_download_strategy(raw: Any) -> str:
    """缩略图下载策略：priority=按源优先级；size=全候选比文件大小。"""
    s = str(raw or "").strip().lower()
    if s in {"size", "filesize", "quality", "largest"}:
        return "size"
    if s in _COVER_DOWNLOAD_STRATEGIES:
        return s
    return "priority"


class ScrapeConfig(BaseModel):
    enabled: bool = True
    origin: str = Field(default="127.0.0.1:9210")
    library_root: str | None = Field(default=None, alias="libraryRoot")
    flare_solverr_url: str | None = Field(
        default=None, alias="flareSolverrUrl"
    )
    proxy_url: str | None = Field(default=None, alias="proxyUrl")
    cover_download_strategy: str | None = Field(
        default=None, alias="coverDownloadStrategy"
    )
    export_concurrency: int | None = Field(
        default=None, alias="exportConcurrency"
    )
    export_fast_concurrency: int | None = Field(
        default=None, alias="exportFastConcurrency"
    )
    export_slow_concurrency: int | None = Field(
        default=None, alias="exportSlowConcurrency"
    )
    poster_crop: dict[str, Any] | None = Field(default=None, alias="posterCrop")
    naming: dict[str, Any] | None = None
    metadata_optimize: dict[str, Any] | None = Field(
        default=None, alias="metadataOptimize"
    )
    write_tree: bool | None = Field(default=None, alias="writeTree")
    write_emby: bool | None = Field(default=None, alias="writeEmby")
    region_profiles: dict[str, Any] | None = Field(default=None, alias="regionProfiles")
    kind_profiles: dict[str, Any] | None = Field(default=None, alias="kindProfiles")
    sources: dict[str, Any] | list[Any] | None = None
    field_priority: dict[str, Any] | None = Field(default=None, alias="fieldPriority")
    retry: dict[str, Any] | int | None = None
    scrape_tasks: list[Any] | None = Field(default=None, alias="scrapeTasks")

    model_config = {"populate_by_name": True}


class ScrapeFlareTestBody(BaseModel):
    origin: str | None = None
    flare_solverr_url: str | None = Field(default=None, alias="flareSolverrUrl")
    proxy_url: str | None = Field(default=None, alias="proxyUrl")
    sample_url: str | None = Field(default=None, alias="sampleUrl")

    model_config = {"populate_by_name": True}


class ScrapeProxyTestBody(BaseModel):
    origin: str | None = None
    proxy_url: str | None = Field(default=None, alias="proxyUrl")

    model_config = {"populate_by_name": True}


class ScrapeSourcesTestBody(BaseModel):
    ids: list[str] | None = None


class ScrapeSourcePatchBody(BaseModel):
    enabled: bool | None = None
    base_url: str | None = Field(default=None, alias="baseUrl")
    retry: int | None = None

    model_config = {"populate_by_name": True}


class TmdbConfig(BaseModel):
    api_key: str = Field(default="", alias="apiKey")

    model_config = {"populate_by_name": True}


_FORUM_REGIONS = frozenset({"japan", "china", "western", "mixed", "other"})


class ForumSehuatangConfig(BaseModel):
    """色花堂子板地区覆盖：key = fid:typeid（整板 typeid 为空）。
    地区：japan|china|western|mixed|other。"""

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


class P115Config(BaseModel):
    enabled: bool = False
    cookie: str = ""
    folder_cid: str = Field(default="0", alias="folderCid")
    folder_name: str = Field(default="", alias="folderName")
    label: str = ""
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
    password: str | None = None
    title_hint: str | None = Field(default=None, alias="titleHint")
    auto_extract: bool | None = Field(default=None, alias="autoExtract")

    model_config = {"populate_by_name": True}


class P115ShareBody(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=20)
    folder_cid: str | None = Field(default=None, alias="folderCid")
    password: str | None = None

    model_config = {"populate_by_name": True}


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


def _scrape_public(raw: dict[str, Any] | None) -> dict[str, Any]:
    from . import scrape_profiles

    cfg = ScrapeConfig.model_validate(raw or {})
    origin = _normalize_origin_url(cfg.origin)
    lib = _normalize_library_rel(cfg.library_root)
    configured = bool(origin)
    raw_profiles = (
        (raw or {}).get("kindProfiles")
        or (raw or {}).get("kind_profiles")
        or (raw or {}).get("regionProfiles")
        or (raw or {}).get("region_profiles")
    )
    if cfg.kind_profiles is not None:
        raw_profiles = cfg.kind_profiles
    elif cfg.region_profiles is not None:
        raw_profiles = cfg.region_profiles
    try:
        priority_schema = int(
            (raw or {}).get("kindPrioritySchema")
            or (raw or {}).get("kind_priority_schema")
            or 0
        )
    except (TypeError, ValueError):
        priority_schema = 0
    try:
        field_priority_schema = int(
            (raw or {}).get("fieldPrioritySchema")
            or (raw or {}).get("field_priority_schema")
            or 0
        )
    except (TypeError, ValueError):
        field_priority_schema = 0
    extras = scrape_profiles.profiles_public(
        raw_profiles,
        raw_sources=(raw or {}).get("sources"),
        raw_field_priority=(raw or {}).get("fieldPriority")
        or (raw or {}).get("field_priority"),
        raw_retry=(raw or {}).get("retry"),
        raw_tasks=(raw or {}).get("scrapeTasks")
        or (raw or {}).get("scrape_tasks"),
        priority_schema=priority_schema,
        field_priority_schema=field_priority_schema,
    )
    upgraded = bool(extras.pop("_upgradedPriority", False))
    upgraded_fp = bool(extras.pop("_upgradedFieldPriority", False))
    if upgraded or upgraded_fp:
        # 一次性写入新源序 / 字段默认，避免每次 GET 都判定升级
        next_raw = dict(raw or {})
        if upgraded or upgraded_fp:
            next_raw["kindProfiles"] = extras.get("kindProfiles")
            next_raw["regionProfiles"] = extras.get("kindProfiles")
        if upgraded:
            next_raw["kindPrioritySchema"] = scrape_profiles.KIND_PRIORITY_SCHEMA
        if upgraded or upgraded_fp:
            next_raw["fieldPriority"] = extras.get("fieldPriority")
            next_raw["fieldPrioritySchema"] = scrape_profiles.FIELD_PRIORITY_SCHEMA
        if upgraded_fp:
            next_raw["scrapeTasks"] = extras.get("scrapeTasks")
        try:
            settings_store.put_setting(settings_store.SCRAPE_KEY, next_raw)
        except Exception:
            pass
    raw_flare = (raw or {}).get("flareSolverrUrl")
    if raw_flare is None:
        raw_flare = (raw or {}).get("flare_solverr_url")
    if raw_flare is None and cfg.flare_solverr_url is None:
        flare = DEFAULT_FLARESOLVERR_URL
    else:
        flare = _normalize_flare_url(
            cfg.flare_solverr_url if cfg.flare_solverr_url is not None else raw_flare
        )
    raw_proxy = (raw or {}).get("proxyUrl")
    if raw_proxy is None:
        raw_proxy = (raw or {}).get("proxy_url")
    if raw_proxy is None and cfg.proxy_url is None:
        proxy = ""
    else:
        proxy = _normalize_proxy_url(
            cfg.proxy_url if cfg.proxy_url is not None else raw_proxy
        )
    raw_cover_strategy = (raw or {}).get("coverDownloadStrategy")
    if raw_cover_strategy is None:
        raw_cover_strategy = (raw or {}).get("cover_download_strategy")
    if cfg.cover_download_strategy is not None:
        cover_strategy = _normalize_cover_download_strategy(cfg.cover_download_strategy)
    else:
        cover_strategy = _normalize_cover_download_strategy(raw_cover_strategy)
    raw_export_conc = (raw or {}).get("exportConcurrency")
    if raw_export_conc is None:
        raw_export_conc = (raw or {}).get("export_concurrency")
    export_fast_concurrency, export_slow_concurrency, export_concurrency = (
        _resolve_channel_concurrency(
            raw if isinstance(raw, dict) else None,
            fast=(
                cfg.export_fast_concurrency
                if cfg.export_fast_concurrency is not None
                else None
            ),
            slow=(
                cfg.export_slow_concurrency
                if cfg.export_slow_concurrency is not None
                else None
            ),
            legacy=(
                cfg.export_concurrency
                if cfg.export_concurrency is not None
                else raw_export_conc
            ),
        )
    )
    raw_poster_crop = (raw or {}).get("posterCrop")
    if raw_poster_crop is None:
        raw_poster_crop = (raw or {}).get("poster_crop")
    if cfg.poster_crop is not None:
        poster_crop = scrape_profiles.normalize_poster_crop(cfg.poster_crop)
    else:
        poster_crop = scrape_profiles.normalize_poster_crop(raw_poster_crop)
    from . import scrape_naming

    # 路径固定；客户端 naming 一律忽略
    naming = scrape_naming.fixed_naming()
    from . import scrape_metadata_optimize

    raw_meta_opt = (raw or {}).get("metadataOptimize")
    if raw_meta_opt is None:
        raw_meta_opt = (raw or {}).get("metadata_optimize")
    if cfg.metadata_optimize is not None:
        metadata_optimize = scrape_metadata_optimize.normalize_metadata_optimize(
            cfg.metadata_optimize
        )
    else:
        metadata_optimize = scrape_metadata_optimize.normalize_metadata_optimize(
            raw_meta_opt
        )
    return {
        "enabled": True,
        "origin": origin,
        "libraryRoot": lib,
        "libraryAbs": _library_abs(lib),
        "libraryOptions": _library_options(),
        "flareSolverrUrl": flare,
        "proxyUrl": proxy,
        "coverDownloadStrategy": cover_strategy,
        "exportConcurrency": export_concurrency,
        "exportFastConcurrency": export_fast_concurrency,
        "exportSlowConcurrency": export_slow_concurrency,
        "posterCrop": poster_crop,
        "naming": naming,
        "metadataOptimize": metadata_optimize,
        "writeTree": bool(
            cfg.write_tree
            if cfg.write_tree is not None
            else (raw or {}).get("writeTree", (raw or {}).get("write_tree", True))
        ),
        "writeEmby": bool(
            cfg.write_emby
            if cfg.write_emby is not None
            else (raw or {}).get("writeEmby", (raw or {}).get("write_emby", True))
        ),
        "configured": configured,
        "sourcesLastAutoTestAt": (raw or {}).get("sourcesLastAutoTestAt")
        or (raw or {}).get("sources_last_auto_test_at"),
        "kindPrioritySchema": scrape_profiles.KIND_PRIORITY_SCHEMA,
        **extras,
    }


def _probe_scrape_online(origin: str, *, timeout: float = 1.5) -> bool:
    """探测刮削服务 /health 是否可达（短超时，供设置页状态）。"""
    base = _normalize_origin_url(origin)
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            res = client.get(f"{base}/health")
            return res.status_code < 400
    except Exception:
        return False


def _sync_network_to_scrape(origin: str, flare_url: str, proxy_url: str) -> bool:
    """把过盾/代理推到 :9210。成功 True，失败 False（不影响保存）。"""
    base = _normalize_origin_url(origin)
    try:
        with httpx.Client(timeout=3.0, trust_env=False) as client:
            r = client.put(
                f"{base}/api/config/network",
                json={
                    "flareSolverrUrl": flare_url or "",
                    "proxyUrl": proxy_url or "",
                },
            )
            return r.status_code < 400
    except Exception:
        return False


def ensure_scrape_network_synced(
    *,
    retries: int = 12,
    delay_sec: float = 1.5,
) -> bool:
    """把设置里的网络管理配置推到刮削服务；启动或刮削前自动同步。"""
    raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
    origin = _normalize_origin_url(raw.get("origin") or DEFAULT_SCRAPE_ORIGIN)
    flare = _normalize_flare_url(
        str(raw.get("flareSolverrUrl") or DEFAULT_FLARESOLVERR_URL)
    )
    proxy = _normalize_proxy_url(
        str(raw.get("proxyUrl") or raw.get("proxy_url") or "")
    )

    for i in range(max(1, retries)):
        if _sync_network_to_scrape(origin, flare, proxy):
            if i > 0:
                logging.getLogger("sns.api").info(
                    "scrape network synced after %s tries", i + 1
                )
            return True
        time.sleep(delay_sec)
    logging.getLogger("sns.api").warning(
        "scrape network sync failed origin=%s", origin
    )
    return False


def _p115_public(raw: dict[str, Any] | None, *, include_cookie: bool = False) -> dict[str, Any]:
    # raw uses snake_case from sqlite
    cookie = str((raw or {}).get("cookie") or "").strip()
    configured = bool(cookie and "UID=" in cookie.upper())
    data = {
        "enabled": bool((raw or {}).get("enabled")),
        "folderCid": str((raw or {}).get("folder_cid") or "0"),
        "folderName": str((raw or {}).get("folder_name") or ""),
        "label": str((raw or {}).get("label") or ""),
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
    key = body.api_key.strip()
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
    try:
        async with httpx.AsyncClient(
            timeout=12.0, trust_env=True, follow_redirects=True
        ) as client:
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


@router.get("/scrape", response_model=Envelope)
def get_scrape(_user: dict[str, Any] | None = Depends(get_optional_user)) -> Envelope:
    data = _scrape_public(settings_store.get_setting(settings_store.SCRAPE_KEY))
    data["online"] = _probe_scrape_online(str(data.get("origin") or ""))
    return Envelope(
        data=data,
        message="online"
        if data["online"]
        else ("configured" if data["configured"] else "not_configured"),
    )


@router.get("/scrape/poster-crop", response_model=Envelope)
def get_scrape_poster_crop(
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> Envelope:
    """仅返回海报取景配置（不探测刮削在线、不展开整包 profiles）。"""
    from . import scrape_profiles

    raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
    pc = scrape_profiles.normalize_poster_crop(
        raw.get("posterCrop") or raw.get("poster_crop")
    )
    return Envelope(data=pc, message="ok")


class PosterCropBody(BaseModel):
    poster_crop: dict[str, Any] | None = Field(default=None, alias="posterCrop")

    model_config = {"populate_by_name": True}


@router.put("/scrape/poster-crop", response_model=Envelope)
def put_scrape_poster_crop(
    body: PosterCropBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    """只更新 posterCrop，避免整包 scrape 保存 + 在线探测。"""
    from . import scrape_profiles

    if body.poster_crop is None:
        raise HTTPException(status_code=400, detail="缺少 posterCrop")
    prev = dict(settings_store.get_setting(settings_store.SCRAPE_KEY) or {})
    pc = scrape_profiles.normalize_poster_crop(body.poster_crop)
    prev["posterCrop"] = pc
    settings_store.put_setting(settings_store.SCRAPE_KEY, prev)
    return Envelope(data=pc, message="saved")


@router.get("/scrape/library-dirs", response_model=Envelope)
def browse_scrape_library_dirs(
    path: str = "data",
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    """浏览项目 data/ 下真实目录，供默认库路径选择。"""
    return Envelope(data=_browse_library_dirs(path), message="ok")


@router.put("/scrape", response_model=Envelope)
def put_scrape(
    body: ScrapeConfig,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    # 单镜像：刮削地址固定内置，忽略客户端填写
    origin = _normalize_origin_url(DEFAULT_SCRAPE_ORIGIN)
    from . import scrape_profiles

    prev = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
    # 未传 libraryRoot 时保留旧值，避免「只存任务」把库路径打回默认
    if body.library_root is not None and str(body.library_root).strip():
        lib = _normalize_library_rel(body.library_root)
    else:
        lib = _normalize_library_rel(
            prev.get("libraryRoot") or prev.get("library_root") or DEFAULT_LIBRARY_REL
        )
    if body.kind_profiles is not None:
        try:
            prev_schema = int(
                prev.get("kindPrioritySchema")
                or prev.get("kind_priority_schema")
                or 0
            )
        except (TypeError, ValueError):
            prev_schema = 0
        gfp = None
        if body.field_priority is not None:
            gfp = scrape_profiles.normalize_field_priority(body.field_priority)
        # 用已存 schema 判断是否升级源序；勿传当前 SCHEMA（会跳过升级）
        profiles = scrape_profiles.normalize_kind_profiles(
            body.kind_profiles,
            priority_schema=prev_schema,
            global_field_priority=gfp,
        )
    elif body.region_profiles is not None:
        try:
            prev_schema = int(
                prev.get("kindPrioritySchema")
                or prev.get("kind_priority_schema")
                or 0
            )
        except (TypeError, ValueError):
            prev_schema = 0
        gfp = None
        if body.field_priority is not None:
            gfp = scrape_profiles.normalize_field_priority(body.field_priority)
        profiles = scrape_profiles.normalize_kind_profiles(
            body.region_profiles,
            priority_schema=prev_schema,
            global_field_priority=gfp,
        )
    else:
        try:
            prev_schema = int(
                prev.get("kindPrioritySchema")
                or prev.get("kind_priority_schema")
                or 0
            )
        except (TypeError, ValueError):
            prev_schema = 0
        gfp = None
        if body.field_priority is not None:
            gfp = scrape_profiles.normalize_field_priority(body.field_priority)
        profiles = scrape_profiles.normalize_kind_profiles(
            prev.get("kindProfiles")
            or prev.get("kind_profiles")
            or prev.get("regionProfiles")
            or prev.get("region_profiles"),
            priority_schema=prev_schema,
            global_field_priority=gfp,
        )
    if body.sources is not None:
        # 允许传 list（卡片数组）或 map
        if isinstance(body.sources, list):
            src_map = {str(x.get("id")): x for x in body.sources if isinstance(x, dict) and x.get("id")}
        else:
            src_map = body.sources
        sources = scrape_profiles.normalize_sources_map(src_map)
    else:
        sources = scrape_profiles.normalize_sources_map(prev.get("sources"))
    if body.field_priority is not None:
        field_priority = scrape_profiles.normalize_field_priority(body.field_priority)
    else:
        ref = profiles.get("japan_censored") or {}
        field_priority = scrape_profiles.normalize_field_priority(
            ref.get("fieldPriority")
        )
    if body.retry is not None:
        retry = scrape_profiles.normalize_retry(body.retry)
    else:
        retry = scrape_profiles.normalize_retry(prev.get("retry"))
    if body.flare_solverr_url is not None:
        flare = _normalize_flare_url(body.flare_solverr_url) or DEFAULT_FLARESOLVERR_URL
    else:
        prev_flare = prev.get("flareSolverrUrl")
        if prev_flare is None:
            prev_flare = prev.get("flare_solverr_url")
        flare = (
            DEFAULT_FLARESOLVERR_URL
            if prev_flare is None
            else _normalize_flare_url(str(prev_flare))
        )
    if body.proxy_url is not None:
        proxy = _normalize_proxy_url(body.proxy_url) or DEFAULT_PROXY_URL
    else:
        prev_proxy = prev.get("proxyUrl")
        if prev_proxy is None:
            prev_proxy = prev.get("proxy_url")
        proxy = _normalize_proxy_url(str(prev_proxy or "")) or DEFAULT_PROXY_URL
    if body.cover_download_strategy is not None:
        cover_strategy = _normalize_cover_download_strategy(body.cover_download_strategy)
    else:
        prev_cover = prev.get("coverDownloadStrategy")
        if prev_cover is None:
            prev_cover = prev.get("cover_download_strategy")
        cover_strategy = _normalize_cover_download_strategy(prev_cover)
    if (
        body.export_fast_concurrency is not None
        or body.export_slow_concurrency is not None
    ):
        prev_fast, prev_slow, _ = _resolve_channel_concurrency(
            prev if isinstance(prev, dict) else None
        )
        export_fast_concurrency = _normalize_export_concurrency(
            body.export_fast_concurrency
            if body.export_fast_concurrency is not None
            else prev_fast
        )
        export_slow_concurrency = _normalize_export_concurrency(
            body.export_slow_concurrency
            if body.export_slow_concurrency is not None
            else prev_slow
        )
        export_concurrency = max(
            export_fast_concurrency, export_slow_concurrency
        )
    elif body.export_concurrency is not None:
        # 旧客户端只传 exportConcurrency：快/慢一起改
        n = _normalize_export_concurrency(body.export_concurrency)
        export_fast_concurrency = n
        export_slow_concurrency = n
        export_concurrency = n
    else:
        export_fast_concurrency, export_slow_concurrency, export_concurrency = (
            _resolve_channel_concurrency(
                prev if isinstance(prev, dict) else None
            )
        )
    if body.poster_crop is not None:
        poster_crop = scrape_profiles.normalize_poster_crop(body.poster_crop)
    else:
        prev_pc = prev.get("posterCrop")
        if prev_pc is None:
            prev_pc = prev.get("poster_crop")
        poster_crop = scrape_profiles.normalize_poster_crop(prev_pc)
    from . import scrape_naming

    # 路径固定；忽略客户端自定义 naming
    naming = scrape_naming.fixed_naming()
    from . import scrape_metadata_optimize

    if body.metadata_optimize is not None:
        metadata_optimize = scrape_metadata_optimize.normalize_metadata_optimize(
            body.metadata_optimize
        )
    else:
        metadata_optimize = scrape_metadata_optimize.normalize_metadata_optimize(
            prev.get("metadataOptimize") or prev.get("metadata_optimize")
        )
    if body.scrape_tasks is not None:
        scrape_tasks = scrape_profiles.normalize_scrape_tasks(body.scrape_tasks)
    else:
        scrape_tasks = scrape_profiles.normalize_scrape_tasks(
            prev.get("scrapeTasks") or prev.get("scrape_tasks")
        )
    if body.write_tree is not None:
        write_tree = bool(body.write_tree)
    else:
        write_tree = bool(prev.get("writeTree", prev.get("write_tree", True)))
    if body.write_emby is not None:
        write_emby = bool(body.write_emby)
    else:
        write_emby = bool(prev.get("writeEmby", prev.get("write_emby", True)))
    saved = settings_store.put_setting(
        settings_store.SCRAPE_KEY,
        {
            "enabled": True,
            "origin": origin,
            "libraryRoot": lib,
            "flareSolverrUrl": flare,
            "proxyUrl": proxy,
            "coverDownloadStrategy": cover_strategy,
            "exportConcurrency": export_concurrency,
            "exportFastConcurrency": export_fast_concurrency,
            "exportSlowConcurrency": export_slow_concurrency,
            "posterCrop": poster_crop,
            "naming": naming,
            "metadataOptimize": metadata_optimize,
            "writeTree": write_tree,
            "writeEmby": write_emby,
            "kindProfiles": profiles,
            "regionProfiles": profiles,
            "sources": sources,
            "fieldPriority": field_priority,
            "retry": retry,
            "scrapeTasks": scrape_tasks,
            "kindPrioritySchema": scrape_profiles.KIND_PRIORITY_SCHEMA,
            "fieldPrioritySchema": scrape_profiles.FIELD_PRIORITY_SCHEMA,
        },
    )
    _sync_network_to_scrape(origin, flare, proxy)
    # 暂停/进行中：任务卡改动立即热更新到当前导出
    if body.scrape_tasks is not None:
        try:
            from . import scrape_export

            scrape_export.sync_running_task_from_settings()
        except Exception:
            logging.getLogger("sns.settings").exception(
                "sync running scrape task failed"
            )
    data = _scrape_public(saved["value"])
    data["updated_at"] = saved["updated_at"]
    data["online"] = _probe_scrape_online(origin)
    return Envelope(data=data, message="saved")


@router.post("/scrape/test", response_model=Envelope)
def test_scrape(
    body: ScrapeConfig,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    origin = _normalize_origin_url(body.origin)
    try:
        with httpx.Client(timeout=4.0, trust_env=False) as client:
            res = client.get(f"{origin}/health")
            if res.status_code >= 500:
                raise HTTPException(status_code=502, detail=f"刮削服务异常 {res.status_code}")
            ok = res.status_code < 400
            return Envelope(
                data={"ok": ok, "status": res.status_code, "origin": origin},
                message="在线" if ok else f"HTTP {res.status_code}",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"无法连接：{e}") from e


def _friendly_probe_error(raw: str | Exception | None) -> str:
    """把 WinError / httpx 连接异常收成短中文。"""
    msg = str(raw or "").strip()
    if not msg:
        return "探测失败"
    if re.search(r"10054|ECONNRESET|ConnectionReset|强迫关闭|forcibly closed", msg, re.I):
        return "连接被重置"
    if re.search(r"10061|ECONNREFUSED|ConnectError", msg, re.I):
        return "无法连接刮削服务"
    if re.search(r"timed?\s*out|Timeout", msg, re.I):
        return "探测超时"
    return msg[:160]


def _is_transient_probe_error(exc: BaseException) -> bool:
    """刮削热重载 / 瞬时断连，可重试。"""
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.CloseError,
        ),
    ):
        return True
    msg = str(exc)
    return bool(
        re.search(
            r"10054|10061|ECONNRESET|ECONNREFUSED|ConnectionReset|强迫关闭|"
            r"forcibly closed|Server disconnected|Connection refused",
            msg,
            re.I,
        )
    )


def _probe_one_source(origin: str, sid: str, base_url: str) -> dict[str, Any]:
    """调 :9210 探测；forum 本地视为 ok。

    探测路径禁止全量镜像发现；过盾单枪约 ≤28s，直连 ≤12s。
    httpx 留一点余量。遇连接重置（刮削热重载）自动重试。
    """
    import time

    if sid == "forum":
        return {"id": sid, "status": "ok", "lastError": None, "cooldownSec": 0}
    payload = {"id": sid, "baseUrl": base_url}
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=45.0, trust_env=False) as client:
                r = client.post(
                    f"{origin.rstrip('/')}/api/sources/probe", json=payload
                )
                if r.status_code >= 400:
                    return {
                        "id": sid,
                        "status": "error",
                        "lastError": f"probe HTTP {r.status_code}",
                        "cooldownSec": 10,
                    }
                body = r.json() if r.content else {}
                data = body.get("data") if isinstance(body, dict) else None
                if isinstance(data, dict):
                    try:
                        cd = int(data.get("cooldownSec") or 0)
                    except (TypeError, ValueError):
                        cd = 0
                    err = data.get("lastError") or data.get("last_error")
                    if err:
                        err = _friendly_probe_error(str(err))
                    resolved = data.get("resolvedBaseUrl") or data.get(
                        "resolved_base_url"
                    )
                    hit: dict[str, Any] = {
                        "id": sid,
                        "status": str(data.get("status") or "unknown"),
                        "lastError": err,
                        "cooldownSec": cd,
                    }
                    if resolved:
                        hit["resolvedBaseUrl"] = str(resolved).strip()
                    return hit
                return {
                    "id": sid,
                    "status": "error",
                    "lastError": "bad probe response",
                    "cooldownSec": 10,
                }
        except httpx.TimeoutException:
            return {
                "id": sid,
                "status": "error",
                "lastError": "探测超时",
                "cooldownSec": 10,
            }
        except Exception as e:
            last_err = e
            if attempt < 2 and _is_transient_probe_error(e):
                time.sleep(0.6 * (attempt + 1))
                continue
            return {
                "id": sid,
                "status": "error",
                "lastError": _friendly_probe_error(e),
                "cooldownSec": 10,
            }
    return {
        "id": sid,
        "status": "error",
        "lastError": _friendly_probe_error(last_err),
        "cooldownSec": 10,
    }


def run_scrape_sources_test(
    ids: list[str] | None = None,
    *,
    auto: bool = False,
) -> tuple[dict[str, Any], str]:
    """探测已启用源（或指定 ids），写回 settings。供路由与定时任务共用。"""
    from datetime import datetime, timezone

    from . import scrape_profiles

    raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
    origin = _normalize_origin_url(raw.get("origin"))
    _sync_network_to_scrape(
        origin,
        _normalize_flare_url(
            str(raw.get("flareSolverrUrl") or DEFAULT_FLARESOLVERR_URL)
        ),
        _normalize_proxy_url(
            str(raw.get("proxyUrl") or raw.get("proxy_url") or "")
        ),
    )
    sources = scrape_profiles.normalize_sources_map(raw.get("sources"))
    want = [str(x).strip().lower() for x in (ids or []) if str(x).strip()]
    if want:
        probe_ids = [sid for sid in want if sid in sources]
    else:
        probe_ids = [
            sid
            for sid, cfg in sources.items()
            if cfg.get("enabled") or sid == "forum"
        ]
    ok_n = 0
    err_n = 0

    def _job(sid: str) -> tuple[str, dict[str, Any]]:
        try:
            hit = _probe_one_source(
                origin, sid, str(sources[sid].get("baseUrl") or "")
            )
            return sid, hit
        except httpx.TimeoutException:
            return sid, {
                "id": sid,
                "status": "error",
                "lastError": "探测超时",
                "cooldownSec": 10,
            }
        except Exception as e:
            return sid, {
                "id": sid,
                "status": "error",
                "lastError": _friendly_probe_error(e),
                "cooldownSec": 10,
            }

    # 一个一个测：过盾单飞，并行只会互相空等/误报超时，还容易拖垮 Flare
    for sid in probe_ids:
        sid, hit = _job(sid)
        st = str(hit.get("status") or "unknown")
        try:
            cd = int(hit.get("cooldownSec") or 0)
        except (TypeError, ValueError):
            cd = 0
        sources = scrape_profiles.apply_source_probe(
            sources,
            sid,
            status=st,
            last_error=hit.get("lastError"),
            cooldown_sec=cd,
            resolved_base_url=hit.get("resolvedBaseUrl"),
        )
        if st == "ok":
            ok_n += 1
        elif st == "error":
            err_n += 1

    raw["sources"] = sources
    if auto:
        raw["sourcesLastAutoTestAt"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    saved = settings_store.put_setting(settings_store.SCRAPE_KEY, raw)
    data = _scrape_public(saved["value"])
    data["updated_at"] = saved["updated_at"]
    # 探测会在 Flare 里留下脏浏览器会话；测完重启腾干净环境。
    # 刮削侧 cf_clearance 落在磁盘，重启 Flare 不会丢掉过盾 Cookie。
    flare_msg = _restart_flare_after_source_probe(origin)
    return data, f"测试完成 · 正常 {ok_n} · 异常 {err_n} · {flare_msg}"


def _restart_flare_after_source_probe(origin: str) -> str:
    """数据源测完后重启 Flare；刮削进行中则跳过，避免打断过盾。"""
    try:
        from . import scrape_export

        st = scrape_export.export_status(event_limit=0)
        if st.get("running"):
            return "跳过重启 Flare（刮削进行中）"
    except Exception:
        pass
    try:
        _data, msg = _scrape_flare_proxy(
            origin,
            "/api/config/flaresolverr/restart",
            method="POST",
            timeout=90.0,
        )
        return str(msg or "").strip() or "已重启 Flare"
    except Exception as e:
        return f"重启 Flare 失败：{e}"


@router.post("/scrape/flaresolverr/test", response_model=Envelope)
def test_scrape_flaresolverr(
    body: ScrapeFlareTestBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
    origin = _normalize_origin_url(body.origin or raw.get("origin"))
    flare = _normalize_flare_url(
        body.flare_solverr_url
        if body.flare_solverr_url is not None
        else raw.get("flareSolverrUrl") or DEFAULT_FLARESOLVERR_URL
    )
    proxy = _normalize_proxy_url(
        body.proxy_url
        if body.proxy_url is not None
        else raw.get("proxyUrl") or raw.get("proxy_url")
    )
    try:
        with httpx.Client(timeout=90.0, trust_env=False) as client:
            # 先确认刮削服务在线
            try:
                hr = client.get(f"{origin}/health")
                if hr.status_code >= 500:
                    raise HTTPException(
                        status_code=502,
                        detail="刮削服务异常，请先重启 apps/scrape",
                    )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"刮削服务未启动（:9210）：{e}",
                ) from e

            client.put(
                f"{origin}/api/config/network",
                json={"flareSolverrUrl": flare, "proxyUrl": proxy},
            )
            r = client.post(
                f"{origin}/api/config/flaresolverr/test",
                json={
                    "flareSolverrUrl": flare,
                    "proxyUrl": proxy,
                    "sampleUrl": body.sample_url or "https://javdb.com/",
                },
            )
            payload = r.json() if r.content else {}
            data = payload.get("data") if isinstance(payload, dict) else None
            msg = (
                str(payload.get("message") or "")
                if isinstance(payload, dict)
                else ""
            )
            if r.status_code >= 400:
                raise HTTPException(
                    status_code=502, detail=msg or f"过盾测试 HTTP {r.status_code}"
                )
            ok = bool(isinstance(data, dict) and data.get("ok"))
            sample_ok = data.get("sampleOk") if isinstance(data, dict) else None
            return Envelope(
                data={
                    "ok": ok,
                    "sampleOk": sample_ok,
                    "flareSolverrUrl": flare,
                    "proxyUrl": proxy or (data.get("proxyUrl") if isinstance(data, dict) else ""),
                    "detail": data,
                },
                message=msg or ("过盾正常" if ok else "过盾失败"),
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"过盾测试失败：{e}") from e


def _scrape_flare_proxy(
    origin: str,
    path: str,
    *,
    method: str = "GET",
    timeout: float = 60.0,
) -> tuple[dict[str, Any], str]:
    """转发到 scrape worker 的 FlareSolverr 监控接口。"""
    url = f"{origin.rstrip('/')}{path}"
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            if method.upper() == "POST":
                r = client.post(url)
            else:
                r = client.get(url)
            payload = r.json() if r.content else {}
            data = payload.get("data") if isinstance(payload, dict) else None
            msg = (
                str(payload.get("message") or "")
                if isinstance(payload, dict)
                else ""
            )
            if r.status_code >= 400:
                raise HTTPException(
                    status_code=502, detail=msg or f"过盾监控 HTTP {r.status_code}"
                )
            return (data if isinstance(data, dict) else {}), msg
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"过盾监控失败：{e}") from e


@router.get("/scrape/flaresolverr/monitor", response_model=Envelope)
def get_scrape_flaresolverr_monitor(
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
    origin = _normalize_origin_url(raw.get("origin"))
    data, msg = _scrape_flare_proxy(
        origin, "/api/config/flaresolverr/monitor", method="GET", timeout=20.0
    )
    return Envelope(data=data, message=msg or "ok")


@router.post("/scrape/flaresolverr/recycle", response_model=Envelope)
def post_scrape_flaresolverr_recycle(
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
    origin = _normalize_origin_url(raw.get("origin"))
    data, msg = _scrape_flare_proxy(
        origin, "/api/config/flaresolverr/recycle", method="POST", timeout=60.0
    )
    return Envelope(data=data, message=msg or "已回收")


@router.post("/scrape/flaresolverr/restart", response_model=Envelope)
def post_scrape_flaresolverr_restart(
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
    origin = _normalize_origin_url(raw.get("origin"))
    data, msg = _scrape_flare_proxy(
        origin, "/api/config/flaresolverr/restart", method="POST", timeout=90.0
    )
    return Envelope(data=data, message=msg or "已重启")


@router.post("/scrape/proxy/test", response_model=Envelope)
def test_scrape_proxy(
    body: ScrapeProxyTestBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
    origin = _normalize_origin_url(body.origin or raw.get("origin"))
    proxy = _normalize_proxy_url(
        body.proxy_url
        if body.proxy_url is not None
        else raw.get("proxyUrl") or raw.get("proxy_url")
    )
    try:
        with httpx.Client(timeout=30.0, trust_env=False) as client:
            try:
                hr = client.get(f"{origin}/health")
                if hr.status_code >= 500:
                    raise HTTPException(
                        status_code=502,
                        detail="刮削服务异常，请先重启 apps/scrape",
                    )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"刮削服务未启动（:9210）：{e}",
                ) from e

            r = client.post(
                f"{origin}/api/config/proxy/test",
                json={"proxyUrl": proxy},
            )
            payload = r.json() if r.content else {}
            data = payload.get("data") if isinstance(payload, dict) else None
            msg = (
                str(payload.get("message") or "")
                if isinstance(payload, dict)
                else ""
            )
            if r.status_code >= 400:
                raise HTTPException(
                    status_code=502, detail=msg or f"代理测试 HTTP {r.status_code}"
                )
            ok = bool(
                (isinstance(data, dict) and data.get("ok"))
                or (isinstance(payload, dict) and payload.get("ok"))
            )
            return Envelope(
                data={
                    "ok": ok,
                    "proxyUrl": proxy
                    or (data.get("proxyUrl") if isinstance(data, dict) else ""),
                    "detail": data,
                },
                message=msg or ("代理正常" if ok else "代理失败"),
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"代理测试失败：{e}") from e


@router.post("/scrape/sources/test", response_model=Envelope)
def test_scrape_sources(
    body: ScrapeSourcesTestBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    try:
        want = [
            str(x).strip().lower() for x in (body.ids or []) if str(x).strip()
        ]
        data, message = run_scrape_sources_test(want or None, auto=False)
        return Envelope(data=data, message=message)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"测试失败：{e}") from e


@router.patch("/scrape/sources/{source_id}", response_model=Envelope)
def patch_scrape_source(
    source_id: str,
    body: ScrapeSourcePatchBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    from . import scrape_profiles

    sid = (source_id or "").strip().lower()
    raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
    sources = scrape_profiles.normalize_sources_map(raw.get("sources"))
    if sid not in sources:
        raise HTTPException(status_code=404, detail="未知数据源")
    if body.enabled is not None and sid != "forum":
        sources[sid]["enabled"] = bool(body.enabled)
    if body.base_url is not None:
        sources[sid]["baseUrl"] = body.base_url.strip()
    if body.retry is not None:
        sources[sid]["retry"] = max(0, min(8, int(body.retry)))
    raw["sources"] = sources
    saved = settings_store.put_setting(settings_store.SCRAPE_KEY, raw)
    data = _scrape_public(saved["value"])
    data["updated_at"] = saved["updated_at"]
    return Envelope(data=data, message="saved")


@router.get("/p115", response_model=Envelope)
def get_p115(_user: dict[str, Any] | None = Depends(get_optional_user)) -> Envelope:
    raw = settings_store.get_setting(settings_store.P115_KEY)
    data = _p115_public(raw)
    # 已配置时拉取云转存额度 + 网盘空间
    if data.get("configured"):
        cookie = str((raw or {}).get("cookie") or "").strip()
        if cookie:
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
    return Envelope(
        data=data,
        message="configured" if data["configured"] else "not_configured",
    )


@router.put("/p115", response_model=Envelope)
def put_p115(
    body: P115Config,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    prev = settings_store.get_setting(settings_store.P115_KEY) or {}
    cookie = (body.cookie or "").strip()
    if not cookie:
        cookie = str(prev.get("cookie") or "").strip()
    folder_cid = (body.folder_cid or "0").strip() or "0"
    folder_name = (body.folder_name or "").strip()
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

        folder_cid = (
            (
                body.folder_cid
                or str(prev.get("folder_cid") or prev.get("folderCid") or "0")
            ).strip()
            or "0"
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

        folder_cid = (
            (
                body.folder_cid
                or str(prev.get("folder_cid") or prev.get("folderCid") or "0")
            ).strip()
            or "0"
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
