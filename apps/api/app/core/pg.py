"""Postgres pool for resource DB (DSN from meta settings).

连接池实现已收敛到 ``app.core.pg_pool.DbPool``；本模块保留**资源库**这一个实例
以及全部历史对外符号（``get_pool`` / ``query`` / ``iter_batches`` / ``close_pool`` /
``_load_dsn`` / ``ResourceDbUnavailable``），调用方无需改动。
"""

from __future__ import annotations

from typing import Any, Iterator

from psycopg_pool import ConnectionPool

import app.core.settings_store as settings_store
from app.core.pg_pool import DbPool


class ResourceDbUnavailable(Exception):
    def __init__(self, message: str = "资源库未配置或不可用"):
        super().__init__(message)
        self.message = message


_IMPL = DbPool(
    setting_key=settings_store.RESOURCE_DB_KEY,
    unavailable_cls=ResourceDbUnavailable,
    dsn_required_message="请先在设置中启用并填写资源库 DSN",
    min_size=1,
    max_size=14,
    # NAS 并行扫库时避免无限等连接；超时后由上层重试
    pool_timeout=60,
    # 资源库不设默认 statement_timeout（沿用服务端默认），由调用方按需指定
    default_query_timeout_ms=None,
    default_iter_timeout_ms=None,
    cursor_name="resource_scan_batch",
)


def _load_dsn() -> str:
    return _IMPL.load_dsn()


def get_pool() -> ConnectionPool:
    return _IMPL.get_pool()


def query(
    sql: str,
    params: list[Any] | tuple[Any, ...] | None = None,
    *,
    statement_timeout_ms: int | None = None,
) -> list[dict[str, Any]]:
    return _IMPL.query(sql, params, statement_timeout_ms=statement_timeout_ms)


def iter_batches(
    sql: str,
    params: list[Any] | tuple[Any, ...] | None = None,
    *,
    batch_size: int = 2000,
    statement_timeout_ms: int | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """服务端游标分批吐行，避免全表 fetchall 把 API 进程撑爆。"""
    return _IMPL.iter_batches(
        sql,
        params,
        batch_size=batch_size,
        statement_timeout_ms=statement_timeout_ms,
    )


def close_pool() -> None:
    _IMPL.close_pool()
