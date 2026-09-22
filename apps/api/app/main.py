"""Meta API — 应用装配入口。

这里**只做装配**：建 app、挂中间件、include 各域路由、启动/关闭生命周期。
具体端点实现请到对应域模块，例如 DB 设置端点在 ``app.core.db_settings_routes``。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.routes import router as auth_router
from app.core.bootstrap import seed_admin_from_config, seed_settings_from_config
from app.core.config_loader import config_paths
from app.core.db import close_meta_pool, init_db, meta_dsn_label
from app.core.pg import close_pool
from app.search.bitmagnet_pg import close_pool as close_bitmagnet_pool

from app.search.resource_routes import router as resource_router
from app.core.conn_settings_routes import router as conn_settings_router
from app.core.scrape_worker_proxy import ScrapeWorkerProxyMiddleware
from app.ai.settings_routes import router as ai_settings_router
from app.ai.chat_routes import router as ai_chat_router
from app.ai.assistant_routes import router as ai_assistant_router
from app.ai.chat_preset_routes import router as ai_chat_preset_router
from app.search.magnet_routes import router as magnet_router
from app.search.pansou_routes import router as pansou_router
from app.search.cloudsaver_routes import router as cloudsaver_router
from app.translate.routes import router as translate_router
from app.scrap_library.cover_focus_routes import router as cover_focus_router
from app.media.routes import router as media_router
from app.makers.catalog_routes import router as makers_catalog_router
from app.prefix.catalog_routes import router as prefix_catalog_router
from app.scrap_library.embed_routes import router as scrap_library_embed_router
from app.scrape.sources_routes import router as scrape_sources_router
from app.search.favorites_routes import router as favorites_router

# DB 连接设置端点：resource-db / bitmagnet-db 由同一个参数化工厂生成。
# Envelope / *DbConfig 在此重导出，保持 `app.main.X` 这一历史命名空间可用。
from app.core.db_settings_routes import (
    BitmagnetDbConfig as BitmagnetDbConfig,
    Envelope as Envelope,
    ResourceDbConfig as ResourceDbConfig,
    build_db_settings_router,
)

import app.core.pg_data_backup as pg_data_backup
import app.core.settings_store as settings_store
import app.prefix.ranges as prefix_ranges

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_admin_from_config()
    seed_settings_from_config()
    # 刮削策略迁移（补 regionSources / 升 coverLogicVersion）落库一次。
    # 放在启动期：`get_strategy()` 是纯读，不再在 GET/每番号路径上写库。
    try:
        from app.scrap_library import enrich_strategy as _enrich_strategy

        _enrich_strategy.migrate_strategy_settings()
    except Exception as e:  # noqa: BLE001
        log.warning("enrich strategy migrate skipped: %s", e)
    prefix_ranges.start_daily_scheduler()
    from app.core.outbound_http import start_flare_monitor, stop_flare_monitor

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


# 先挂代理（内层），再挂 CORS（外层），跨域时错误响应也带 CORS 头
app.add_middleware(ScrapeWorkerProxyMiddleware)
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

# /settings/resource-db/*：色花资源库（v1.2.21 前为手写的 7 个端点）
app.include_router(
    build_db_settings_router(
        prefix="/settings/resource-db",
        tag="settings",
        setting_key=settings_store.RESOURCE_DB_KEY,
        config_model=ResourceDbConfig,
        backup_kind=pg_data_backup.KIND_RESOURCE,
        dsn_required_detail="请先启用并保存色花资源库连接",
        refused_hint="连接被拒绝：请确认 Postgres 已启动且端口正确（色花常用 5435）",
        backup_filename_desc="backups/resource-db 下的 zip 文件名",
        close_pool=close_pool,
        embed_module="app.search.sehua_resource_embed_svc",
        operation_prefix="resource_db",
    )
)

# /settings/bitmagnet-db/*：Bitmagnet 磁力库（与上面同构，仅参数不同）
app.include_router(
    build_db_settings_router(
        prefix="/settings/bitmagnet-db",
        tag="settings",
        setting_key=settings_store.BITMAGNET_DB_KEY,
        config_model=BitmagnetDbConfig,
        backup_kind=pg_data_backup.KIND_BITMAGNET,
        dsn_required_detail="请先启用并保存 Bitmagnet 连接",
        refused_hint="连接被拒绝：请确认 Bitmagnet Postgres 已启动且端口正确（默认 5432）",
        backup_filename_desc="backups/bitmagnet-db 下的 zip 文件名",
        close_pool=close_bitmagnet_pool,
        embed_module="app.search.bitmagnet_embed_svc",
        operation_prefix="bitmagnet_db",
    )
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "sehua-next-search-api",
        "meta_db": meta_dsn_label(),
        "config": [str(p) for p in config_paths()],
        "phase": "search",
    }
