"""Bitmagnet 磁力库向量灌库服务（bitmagnet_torrent_embed）。

引擎见 `app.search.embed_ingest_base`；本模块只声明本库的差异。
"""

from __future__ import annotations

from typing import Any

import app.core.settings_store as settings_store
from app.search.bitmagnet_embed import row_embed_payload
from app.search.embed_ingest_base import (
    BATCH_DEFAULT,
    FETCH_BATCH,
    EmbedIngestJob,
    EmbedSpec,
)

TABLE = "bitmagnet_torrent_embed"

_PENDING_SQL = """
    SELECT
      encode(t.info_hash, 'hex') AS info_hash,
      t.name,
      c.title,
      c.overview,
      c.type,
      tc.content_type,
      tc.video_resolution,
      e.content_sha AS existing_sha
    FROM torrents t
    LEFT JOIN LATERAL (
      SELECT content_type, content_source, content_id, video_resolution
      FROM torrent_contents tc0
      WHERE tc0.info_hash = t.info_hash
      LIMIT 1
    ) tc ON true
    LEFT JOIN content c
      ON c.id = tc.content_id AND c.source = tc.content_source
    LEFT JOIN bitmagnet_torrent_embed e
      ON e.info_hash = encode(t.info_hash, 'hex')
    WHERE e.info_hash IS NULL
    ORDER BY t.created_at DESC NULLS LAST
    LIMIT %s
"""

_FORCE_SELECT_SQL = """
                        SELECT
                          encode(t.info_hash, 'hex') AS info_hash,
                          t.name,
                          c.title,
                          c.overview,
                          c.type,
                          tc.content_type,
                          tc.video_resolution,
                          e.content_sha AS existing_sha
                        FROM torrents t
                        LEFT JOIN LATERAL (
                          SELECT content_type, content_source, content_id, video_resolution
                          FROM torrent_contents tc0
                          WHERE tc0.info_hash = t.info_hash
                          LIMIT 1
                        ) tc ON true
                        LEFT JOIN content c
                          ON c.id = tc.content_id AND c.source = tc.content_source
                        LEFT JOIN bitmagnet_torrent_embed e
                          ON e.info_hash = encode(t.info_hash, 'hex')
                        ORDER BY t.info_hash
                        LIMIT %s OFFSET %s
"""

_SPEC = EmbedSpec(
    table=TABLE,
    pk="info_hash",
    pk_ddl="info_hash     text PRIMARY KEY",
    source_table="torrents",
    payload_fn=row_embed_payload,
    dsn_env="BITMAGNET_DSN",
    dsn_setting_key=settings_store.BITMAGNET_DB_KEY,
    dsn_required_message="请先启用并保存 Bitmagnet 连接",
    log_name="app.bitmagnet_embed",
    error_log="bitmagnet embed failed",
    busy_message="Bitmagnet 向量灌库已在运行",
    thread_name="bitmagnet-embed",
    pending_sql=_PENDING_SQL,
    force_select_sql=_FORCE_SELECT_SQL,
    skip_empty_pk=True,
    force_log_mod=10,
    force_log_with_skipped=False,
    loop_log_every=10,
    loop_log_with_batch=False,
    break_on_all_skipped=False,
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
