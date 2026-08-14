"""

Meta API — auth + settings + resource search (Postgres via DSN in SQLite).

"""



from __future__ import annotations



import logging
import threading

from contextlib import asynccontextmanager

from typing import Any



from fastapi import Depends, FastAPI, HTTPException

from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel, Field

import psycopg



from .auth_routes import (
    get_optional_user,
    require_admin,
    require_user,
    router as auth_router,
)

from .bootstrap import seed_admin_from_config, seed_settings_from_config

from .config_loader import config_paths

from .db import db_path, init_db

from .pg import close_pool
from .bitmagnet_pg import close_pool as close_bitmagnet_pool

from .resource_routes import router as resource_router
from .conn_settings_routes import router as conn_settings_router
from .magnet_routes import router as magnet_router
from .translate_routes import router as translate_router
from .zone_folder_routes import router as zone_folder_router
from .maker_fs_routes import router as maker_fs_router
from .scrape_export_routes import router as scrape_export_router
from .cover_focus_routes import router as cover_focus_router

from . import (
    prefix_ranges,
    scrape_export,
    scrape_source_probe,
    scrape_watch,
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

    from . import maker_fs_auto

    maker_fs_auto.start_daily_scheduler()

    scrape_watch.start_watch_scheduler()

    scrape_source_probe.start_source_probe_scheduler()

    def _sync_scrape_network() -> None:
        try:
            from .conn_settings_routes import ensure_scrape_network_synced

            ensure_scrape_network_synced(retries=20, delay_sec=1.5)
        except Exception:
            logging.getLogger("sns.api").exception("scrape network auto-sync failed")

    threading.Thread(
        target=_sync_scrape_network, name="scrape-network-sync", daemon=True
    ).start()

    yield

    # 热重载/退出：先打断刮削，避免 Windows process.join 卡死
    try:
        scrape_export.prepare_process_shutdown()
    except Exception:
        logging.getLogger('sns.api').exception('prepare_process_shutdown failed')

    scrape_source_probe.stop_source_probe_scheduler()

    scrape_watch.stop_watch_scheduler()

    try:
        from . import maker_fs_auto

        maker_fs_auto.stop_daily_scheduler()
    except Exception:
        logging.getLogger('sns.api').exception('stop maker_fs_auto failed')

    prefix_ranges.stop_daily_scheduler()
    close_pool()
    close_bitmagnet_pool()





app = FastAPI(title="资源仓库 API", version="0.3.0", lifespan=lifespan)



app.add_middleware(

    CORSMiddleware,

    allow_origins=["*"],

    allow_credentials=False,

    allow_methods=["*"],

    allow_headers=["*"],

)



app.include_router(auth_router)

app.include_router(resource_router)

app.include_router(conn_settings_router)

app.include_router(magnet_router)

app.include_router(translate_router)

app.include_router(zone_folder_router)

app.include_router(maker_fs_router)
app.include_router(scrape_export_router)
app.include_router(cover_focus_router)





@app.get("/health")

def health() -> dict[str, Any]:

    return {

        "ok": True,

        "service": "sehua-next-search-api",

        "meta_db": str(db_path()),

        "config": [str(p) for p in config_paths()],

        "phase": "search",

    }





@app.get("/settings/resource-db", response_model=Envelope)

def get_resource_db(

    _user: dict[str, Any] | None = Depends(get_optional_user),

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
    _user: dict[str, Any] | None = Depends(get_optional_user),
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


