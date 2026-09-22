"""Postgres pool for Bitmagnet DB (separate DSN from resource_db).

连接池实现已收敛到 ``app.core.pg_pool.DbPool``；本模块保留**Bitmagnet 库**这一个实例
以及全部历史对外符号（``get_pool`` / ``query`` / ``iter_batches`` / ``close_pool`` /
``is_configured`` / ``_load_dsn`` / ``BitmagnetDbUnavailable``），调用方无需改动。
"""

from __future__ import annotations

from typing import Any, Iterator

from psycopg_pool import ConnectionPool

import app.core.settings_store as settings_store
from app.core.pg_pool import DbPool

# 默认查询超时（毫秒）：bitmagnet 仅 name B-tree 索引，缺 pg_trgm 时子串检索可能全表扫
_DEFAULT_STATEMENT_TIMEOUT_MS = 20_000


class BitmagnetDbUnavailable(Exception):
    def __init__(self, message: str = "Bitmagnet 库未配置或不可用"):
        super().__init__(message)
        self.message = message


_IMPL = DbPool(
    setting_key=settings_store.BITMAGNET_DB_KEY,
    unavailable_cls=BitmagnetDbUnavailable,
    dsn_required_message="请先在设置中启用并填写 Bitmagnet 库 DSN",
    min_size=1,
    max_size=8,
    pool_timeout=None,
    default_query_timeout_ms=_DEFAULT_STATEMENT_TIMEOUT_MS,
    default_iter_timeout_ms=600_000,
    cursor_name="bitmagnet_scan_batch",
)


def _load_dsn() -> str:
    return _IMPL.load_dsn()


def get_pool() -> ConnectionPool:
    return _IMPL.get_pool()


def query(
    sql: str,
    params: list[Any] | tuple[Any, ...] | None = None,
    *,
    statement_timeout_ms: int = _DEFAULT_STATEMENT_TIMEOUT_MS,
) -> list[dict[str, Any]]:
    return _IMPL.query(sql, params, statement_timeout_ms=statement_timeout_ms)


def iter_batches(
    sql: str,
    params: list[Any] | tuple[Any, ...] | None = None,
    *,
    batch_size: int = 2000,
    statement_timeout_ms: int = 600_000,
) -> Iterator[list[dict[str, Any]]]:
    """服务端游标分批吐行。全表扫描不要 query()+fetchall。"""
    return _IMPL.iter_batches(
        sql,
        params,
        batch_size=batch_size,
        statement_timeout_ms=statement_timeout_ms,
    )


def close_pool() -> None:
    _IMPL.close_pool()


def is_configured() -> bool:
    return _IMPL.is_configured()
