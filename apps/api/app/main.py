"""

Meta API — auth + settings + resource search (all Postgres).

"""



from __future__ import annotations



import logging
import os

from contextlib import asynccontextmanager

from typing import Any



from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel, Field

import psycopg



from .auth_routes import (
    require_admin,
    require_user,
    router as auth_router,
)

from .bootstrap import seed_admin_from_config, seed_settings_from_config

from .config_loader import config_paths

from .db import close_meta_pool, init_db, meta_dsn_label

from .pg import close_pool
from .bitmagnet_pg import close_pool as close_bitmagnet_pool

from .resource_routes import router as resource_router
from .conn_settings_routes import router as conn_settings_router
from .ai_settings_routes import router as ai_settings_router
from .ai_chat_routes import router as ai_chat_router
from .ai_assistant_routes import router as ai_assistant_router
from .ai_chat_preset_routes import router as ai_chat_preset_router
from .magnet_routes import router as magnet_router
from .pansou_routes import router as pansou_router
from .cloudsaver_routes import router as cloudsaver_router
from .translate_routes import router as translate_router
from .cover_focus_routes import router as cover_focus_router
from .media_routes import router as media_router
from .makers_catalog_routes import router as makers_catalog_router
from .prefix_catalog_routes import router as prefix_catalog_router
from .scrap_library_embed_routes import router as scrap_library_embed_router
from .scrape_sources_routes import router as scrape_sources_router
from .favorites_routes import router as favorites_router

from . import (
    pg_data_backup,
    prefix_ranges,
    settings_store,
)



logging.basicConfig(level=logging.INFO)





class ResourceDbConfig(BaseModel):

    enabled: bool = False

    dsn: str = Field(

        default="",

        description="Postgres DSN, e.g. postgresql://user:pass@host:5432/ed2k",

    )

    note: str = ""


class BitmagnetDbConfig(BaseModel):

    enabled: bool = False

    dsn: str = Field(

        default="",

        description="Bitmagnet Postgres DSN, e.g. postgresql://user:pass@host:5432/bitmagnet",

    )

    note: str = ""





class Envelope(BaseModel):

    data: Any = None

    message: str = "ok"

    status: int = 200





@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_admin_from_config()
    seed_settings_from_config()
    prefix_ranges.start_daily_scheduler()
    from .outbound_http import start_flare_monitor, stop_flare_monitor

    start_flare_monitor()
    yield
    stop_flare_monitor()
    prefix_ranges.stop_daily_scheduler()
    close_pool()
    close_bitmagnet_pool()
    close_meta_pool()



def _cors_origins() -> list[str]:
    """CORS 允许来源：默认通配（同源 rewrite 场景不需要 CORS）；可经 SNS_CORS_ORIGINS 收紧。"""
    raw = os.environ.get("SNS_CORS_ORIGINS", "").strip()
    if not raw:
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


app = FastAPI(title="资源仓库 API", version="0.3.0", lifespan=lifespan)



app.add_middleware(

    CORSMiddleware,

    # 允许跨域来源（逗号分隔，如 SNS_CORS_ORIGINS=http://192.168.2.38:3020）
    allow_origins=_cors_origins(),

    allow_credentials=False,

    allow_methods=["*"],

    allow_headers=["*"],

)



app.include_router(auth_router)

app.include_router(resource_router)

app.include_router(conn_settings_router)
app.include_router(ai_settings_router)
app.include_router(ai_chat_router)
app.include_router(ai_assistant_router)
app.include_router(ai_chat_preset_router)

app.include_router(magnet_router)
app.include_router(pansou_router)
app.include_router(cloudsaver_router)

app.include_router(translate_router)

app.include_router(cover_focus_router)
app.include_router(media_router)
app.include_router(makers_catalog_router)
app.include_router(prefix_catalog_router)
app.include_router(scrap_library_embed_router)
app.include_router(scrape_sources_router)
app.include_router(favorites_router)





@app.get("/health")

def health() -> dict[str, Any]:

    return {

        "ok": True,

        "service": "sehua-next-search-api",

        "meta_db": meta_dsn_label(),

        "config": [str(p) for p in config_paths()],

        "phase": "search",

    }





@app.get("/settings/resource-db", response_model=Envelope)

def get_resource_db(

    _user: dict[str, Any] = Depends(require_user),

) -> Envelope:

    raw = settings_store.get_setting(settings_store.RESOURCE_DB_KEY)

    cfg = ResourceDbConfig.model_validate(raw or {})

    public = cfg.model_dump()

    configured = bool(cfg.enabled and cfg.dsn.strip())

    return Envelope(

        data={**public, "configured": configured},

        message="configured" if configured else "not_configured",

    )





@app.put("/settings/resource-db", response_model=Envelope)

def put_resource_db(

    body: ResourceDbConfig,

    _user: dict[str, Any] = Depends(require_admin),

) -> Envelope:

    saved = settings_store.put_setting(

        settings_store.RESOURCE_DB_KEY,

        body.model_dump(),

    )

    close_pool()  # DSN 变更后重建连接池

    configured = bool(body.enabled and body.dsn.strip())

    return Envelope(

        data={

            **saved["value"],

            "configured": configured,

            "updated_at": saved["updated_at"],

        },

        message="saved",

    )




@app.post("/settings/resource-db/test", response_model=Envelope)

def test_resource_db(

    body: ResourceDbConfig,

    _user: dict[str, Any] = Depends(require_admin),

) -> Envelope:

    dsn = body.dsn.strip()

    if not dsn:

        raise HTTPException(status_code=400, detail="请填写连接信息")

    try:

        with psycopg.connect(dsn, connect_timeout=5) as conn:

            conn.execute("SELECT 1")

        return Envelope(data={"ok": True}, message="可以连接")

    except Exception as e:

        raw = str(e) or "连接失败"

        low = raw.lower()

        if "password authentication failed" in low:

            msg = "密码认证失败：密码不对，或该库实际需要密码"

        elif "no password supplied" in low:

            msg = (
                "服务器要求密码：本机 psql 可能免密，"
                "但从本机 API 连 192.168.x 等远程地址通常必须填密码"
            )

        elif "could not translate host" in low or "name or service not known" in low:

            msg = "主机无法解析：请检查主机地址"

        elif "connection refused" in low:

            msg = "连接被拒绝：请确认 Postgres 已启动且端口正确（色花常用 5435）"

        elif "timeout" in low:

            msg = "连接超时：请确认主机/防火墙/端口可达"

        else:

            msg = raw

        return Envelope(

            data={"ok": False},

            message=msg,

            status=200,

        )


def _resource_dsn_or_400() -> str:
    raw = settings_store.get_setting(settings_store.RESOURCE_DB_KEY) or {}
    dsn = str(raw.get("dsn") or "").strip()
    if not bool(raw.get("enabled")) or not dsn:
        raise HTTPException(status_code=400, detail="请先启用并保存色花资源库连接")
    return dsn


@app.get("/settings/resource-db/backups", response_model=Envelope)
def list_resource_db_backups(
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    return Envelope(data={"items": pg_data_backup.list_backups(pg_data_backup.KIND_RESOURCE)})


@app.post("/settings/resource-db/backups/export", response_model=Envelope)
def export_resource_db_backup(
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    try:
        result = pg_data_backup.export_resource_zip(
            _resource_dsn_or_400(),
            kind=pg_data_backup.KIND_RESOURCE,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败：{e}") from e
    return Envelope(data=result, message="已导出到 backups")


class ResourceDbBackupImportBody(BaseModel):
    filename: str = Field(..., min_length=1, description="backups/resource-db 下的 zip 文件名")


@app.post("/settings/resource-db/backups/import", response_model=Envelope)
def import_resource_db_backup(
    body: ResourceDbBackupImportBody,
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    try:
        result = pg_data_backup.import_resource_zip(
            _resource_dsn_or_400(),
            body.filename.strip(),
            kind=pg_data_backup.KIND_RESOURCE,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败：{e}") from e
    return Envelope(data=result, message="已从备份恢复资源数据")


@app.post("/settings/resource-db/backups/upload-import", response_model=Envelope)
async def upload_import_resource_db_backup(
    file: UploadFile = File(...),
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    dsn = _resource_dsn_or_400()
    saved: dict[str, Any] = {}
    restored: dict[str, Any] = {}
    try:
        saved = pg_data_backup.save_uploaded_zip(
            pg_data_backup.KIND_RESOURCE,
            source=file.file,
            original_name=file.filename or "",
        )
        restored = pg_data_backup.import_resource_zip(
            dsn,
            str(saved["filename"]),
            kind=pg_data_backup.KIND_RESOURCE,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败：{e}") from e
    finally:
        await file.close()
    return Envelope(
        data={**saved, **restored},
        message="已上传并恢复资源数据",
    )


class ResourceDbEmbedStartBody(BaseModel):
    force: bool = False


@app.get("/settings/resource-db/embed/stats", response_model=Envelope)
def resource_db_embed_stats(
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    from . import sehua_resource_embed_svc as embed_svc

    try:
        return Envelope(data=embed_svc.stats())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/settings/resource-db/embed/status", response_model=Envelope)
def resource_db_embed_status(
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    from . import sehua_resource_embed_svc as embed_svc

    return Envelope(data=embed_svc.get_job_status())


@app.post("/settings/resource-db/embed/start", response_model=Envelope)
def resource_db_embed_start(
    body: ResourceDbEmbedStartBody,
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    from . import sehua_resource_embed_svc as embed_svc

    _resource_dsn_or_400()
    try:
        result = embed_svc.start_ingest_job(force=bool(body.force))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return Envelope(data=result, message="已开始同步向量")


@app.post("/settings/resource-db/embed/stop", response_model=Envelope)
def resource_db_embed_stop(
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    from . import sehua_resource_embed_svc as embed_svc

    return Envelope(data=embed_svc.request_stop(), message="正在暂停")


@app.post("/settings/resource-db/embed/create-index", response_model=Envelope)
def resource_db_embed_create_index(
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    from . import sehua_resource_embed_svc as embed_svc

    _resource_dsn_or_400()
    try:
        return Envelope(data=embed_svc.create_hnsw_index(), message="索引已创建")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _bitmagnet_dsn_or_400() -> str:
    raw = settings_store.get_setting(settings_store.BITMAGNET_DB_KEY) or {}
    dsn = str(raw.get("dsn") or "").strip()
    if not bool(raw.get("enabled")) or not dsn:
        raise HTTPException(status_code=400, detail="请先启用并保存 Bitmagnet 连接")
    return dsn


@app.get("/settings/bitmagnet-db/backups", response_model=Envelope)
def list_bitmagnet_db_backups(
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    return Envelope(data={"items": pg_data_backup.list_backups(pg_data_backup.KIND_BITMAGNET)})


@app.post("/settings/bitmagnet-db/backups/export", response_model=Envelope)
def export_bitmagnet_db_backup(
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    try:
        result = pg_data_backup.export_resource_zip(
            _bitmagnet_dsn_or_400(),
            kind=pg_data_backup.KIND_BITMAGNET,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败：{e}") from e
    return Envelope(data=result, message="已导出到 backups")


class BitmagnetDbBackupImportBody(BaseModel):
    filename: str = Field(..., min_length=1, description="backups/bitmagnet-db 下的 zip 文件名")


@app.post("/settings/bitmagnet-db/backups/import", response_model=Envelope)
def import_bitmagnet_db_backup(
    body: BitmagnetDbBackupImportBody,
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    try:
        result = pg_data_backup.import_resource_zip(
            _bitmagnet_dsn_or_400(),
            body.filename.strip(),
            kind=pg_data_backup.KIND_BITMAGNET,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败：{e}") from e
    return Envelope(data=result, message="已从备份恢复资源数据")


@app.post("/settings/bitmagnet-db/backups/upload-import", response_model=Envelope)
async def upload_import_bitmagnet_db_backup(
    file: UploadFile = File(...),
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    dsn = _bitmagnet_dsn_or_400()
    saved: dict[str, Any] = {}
    restored: dict[str, Any] = {}
    try:
        saved = pg_data_backup.save_uploaded_zip(
            pg_data_backup.KIND_BITMAGNET,
            source=file.file,
            original_name=file.filename or "",
        )
        restored = pg_data_backup.import_resource_zip(
            dsn,
            str(saved["filename"]),
            kind=pg_data_backup.KIND_BITMAGNET,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败：{e}") from e
    finally:
        await file.close()
    return Envelope(
        data={**saved, **restored},
        message="已上传并恢复资源数据",
    )


class BitmagnetDbEmbedStartBody(BaseModel):
    force: bool = False


@app.get("/settings/bitmagnet-db/embed/stats", response_model=Envelope)
def bitmagnet_db_embed_stats(
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    from . import bitmagnet_embed_svc as embed_svc

    try:
        return Envelope(data=embed_svc.stats())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/settings/bitmagnet-db/embed/status", response_model=Envelope)
def bitmagnet_db_embed_status(
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    from . import bitmagnet_embed_svc as embed_svc

    return Envelope(data=embed_svc.get_job_status())


@app.post("/settings/bitmagnet-db/embed/start", response_model=Envelope)
def bitmagnet_db_embed_start(
    body: BitmagnetDbEmbedStartBody,
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    from . import bitmagnet_embed_svc as embed_svc

    _bitmagnet_dsn_or_400()
    try:
        result = embed_svc.start_ingest_job(force=bool(body.force))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return Envelope(data=result, message="已开始同步向量")


@app.post("/settings/bitmagnet-db/embed/stop", response_model=Envelope)
def bitmagnet_db_embed_stop(
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    from . import bitmagnet_embed_svc as embed_svc

    return Envelope(data=embed_svc.request_stop(), message="正在暂停")


@app.post("/settings/bitmagnet-db/embed/create-index", response_model=Envelope)
def bitmagnet_db_embed_create_index(
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    from . import bitmagnet_embed_svc as embed_svc

    _bitmagnet_dsn_or_400()
    try:
        return Envelope(data=embed_svc.create_hnsw_index(), message="索引已创建")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _test_postgres_dsn(dsn: str, *, refused_hint: str) -> Envelope:
    if not dsn.strip():
        raise HTTPException(status_code=400, detail="请填写连接信息")
    try:
        with psycopg.connect(dsn.strip(), connect_timeout=5) as conn:
            conn.execute("SELECT 1")
        return Envelope(data={"ok": True}, message="可以连接")
    except Exception as e:
        raw = str(e) or "连接失败"
        low = raw.lower()
        if "password authentication failed" in low:
            msg = "密码认证失败：密码不对，或该库实际需要密码"
        elif "no password supplied" in low:
            msg = (
                "服务器要求密码：本机 psql 可能免密，"
                "但从本机 API 连 192.168.x 等远程地址通常必须填密码"
            )
        elif "could not translate host" in low or "name or service not known" in low:
            msg = "主机无法解析：请检查主机地址"
        elif "connection refused" in low:
            msg = refused_hint
        elif "timeout" in low:
            msg = "连接超时：请确认主机/防火墙/端口可达"
        else:
            msg = raw
        return Envelope(data={"ok": False}, message=msg, status=200)


@app.get("/settings/bitmagnet-db", response_model=Envelope)
def get_bitmagnet_db(
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    raw = settings_store.get_setting(settings_store.BITMAGNET_DB_KEY)
    cfg = BitmagnetDbConfig.model_validate(raw or {})
    public = cfg.model_dump()
    configured = bool(cfg.enabled and cfg.dsn.strip())
    return Envelope(
        data={**public, "configured": configured},
        message="configured" if configured else "not_configured",
    )


@app.put("/settings/bitmagnet-db", response_model=Envelope)
def put_bitmagnet_db(
    body: BitmagnetDbConfig,
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    saved = settings_store.put_setting(
        settings_store.BITMAGNET_DB_KEY,
        body.model_dump(),
    )
    close_bitmagnet_pool()
    configured = bool(body.enabled and body.dsn.strip())
    return Envelope(
        data={
            **saved["value"],
            "configured": configured,
            "updated_at": saved["updated_at"],
        },
        message="saved",
    )


@app.post("/settings/bitmagnet-db/test", response_model=Envelope)
def test_bitmagnet_db(
    body: BitmagnetDbConfig,
    _user: dict[str, Any] = Depends(require_admin),
) -> Envelope:
    return _test_postgres_dsn(
        body.dsn,
        refused_hint="连接被拒绝：请确认 Bitmagnet Postgres 已启动且端口正确（默认 5432）",
    )


