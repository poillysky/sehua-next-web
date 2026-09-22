"""色花资源库向量灌库服务（resource_db / sehua_resource_embed）。

引擎见 `app.search.embed_ingest_base`；本模块只声明本库的差异。
"""

from __future__ import annotations

from typing import Any

import app.core.settings_store as settings_store
from app.search.embed_ingest_base import (
    BATCH_DEFAULT,
    FETCH_BATCH,
    EmbedIngestJob,
    EmbedSpec,
)
from app.search.sehua_embed import row_embed_payload

TABLE = "sehua_resource_embed"

_PENDING_SQL = """
    SELECT r.hash, r.filename, rs.title, rs.description, rs.board_name,
           e.content_sha AS existing_sha
    FROM ed2k_resources r
    JOIN resource_sources rs ON rs.hash = r.hash
    LEFT JOIN sehua_resource_embed e ON e.hash = r.hash
    WHERE e.hash IS NULL
    ORDER BY r.created_at DESC NULLS LAST
    LIMIT %s
"""

_FORCE_SELECT_SQL = """
                        SELECT r.hash, r.filename, rs.title, rs.description, rs.board_name,
                               e.content_sha AS existing_sha
                        FROM ed2k_resources r
                        JOIN resource_sources rs ON rs.hash = r.hash
                        LEFT JOIN sehua_resource_embed e ON e.hash = r.hash
                        ORDER BY r.hash
                        LIMIT %s OFFSET %s
"""

_SPEC = EmbedSpec(
    table=TABLE,
    pk="hash",
    pk_ddl=(
        "hash          text PRIMARY KEY "
        "REFERENCES ed2k_resources(hash) ON DELETE CASCADE"
    ),
    source_table="ed2k_resources",
    payload_fn=row_embed_payload,
    dsn_env="SEHUA_RESOURCE_DSN",
    dsn_setting_key=settings_store.RESOURCE_DB_KEY,
    dsn_required_message="请先启用并保存色花资源库连接",
    log_name="app.sehua_resource_embed",
    error_log="sehua resource embed failed",
    busy_message="色花资源向量灌库已在运行",
    thread_name="sehua-resource-embed",
    pending_sql=_PENDING_SQL,
    force_select_sql=_FORCE_SELECT_SQL,
    force_log_mod=1,
    force_log_with_skipped=True,
    loop_log_every=5,
    loop_log_with_batch=True,
    break_on_all_skipped=True,
)

_JOB = EmbedIngestJob(_SPEC)


def get_job_status() -> dict[str, Any]:
    return _JOB.get_job_status()


def request_stop() -> dict[str, Any]:
    return _JOB.request_stop()


def ensure_schema(*, recreate: bool = False) -> dict[str, Any]:
    return _JOB.ensure_schema(recreate=recreate)


def stats() -> dict[str, Any]:
    return _JOB.stats()


def create_hnsw_index() -> dict[str, Any]:
    return _JOB.create_hnsw_index()


def ingest(*, force: bool = False, build_index: bool = True) -> dict[str, Any]:
    return _JOB.ingest(force=force, build_index=build_index)


def start_ingest_job(*, force: bool = False) -> dict[str, Any]:
    return _JOB.start_ingest_job(force=force)
