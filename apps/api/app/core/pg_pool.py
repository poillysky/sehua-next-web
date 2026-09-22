"""通用 Postgres 连接池。

此前 ``app.core.pg``（资源库）与 ``app.search.bitmagnet_pg``（Bitmagnet 库）是同一套
连接池逻辑写了两遍——建池、DSN 变更重建、``query``、服务端游标 ``iter_batches``、
``close_pool`` 逐块相同，差异只集中在几个参数上。这里收敛为 ``DbPool``，
两个模块各自持有一个实例并转发历史符号名（调用方零改动）。
"""

from __future__ import annotations

from typing import Any, Iterator

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import app.core.settings_store as settings_store


class DbPool:
    """按设置项（enabled + dsn）惰性建立的连接池。

    参数说明（与原两份实现逐项对应）：
    - ``setting_key``：从 ``settings_store`` 取 DSN 的设置键
    - ``unavailable_cls``：DSN 未配置时抛出的异常类（各库一个，供上层 ``except`` 区分）
    - ``max_size`` / ``min_size`` / ``pool_timeout``：``ConnectionPool`` 参数
    - ``default_query_timeout_ms`` / ``default_iter_timeout_ms``：``query`` / ``iter_batches`` 的
      默认 statement_timeout（``None`` 表示不设置，即沿用服务端默认）
    - ``cursor_name``：服务端游标名（便于在 pg_stat_activity 里区分是哪个库在扫）
    """

    def __init__(
        self,
        *,
        setting_key: str,
        unavailable_cls: type[Exception],
        dsn_required_message: str,
        min_size: int = 1,
        max_size: int = 8,
        pool_timeout: float | None = None,
        default_query_timeout_ms: int | None = None,
        default_iter_timeout_ms: int | None = None,
        cursor_name: str = "db_scan_batch",
    ) -> None:
        self._setting_key = setting_key
        self._unavailable_cls = unavailable_cls
        self._dsn_required_message = dsn_required_message
        self._min_size = min_size
        self._max_size = max_size
        self._pool_timeout = pool_timeout
        self._default_query_timeout_ms = default_query_timeout_ms
        self._default_iter_timeout_ms = default_iter_timeout_ms
        self._cursor_name = cursor_name
        self._pool: ConnectionPool | None = None
        self._pool_dsn: str | None = None

    # ---- DSN ---------------------------------------------------------------

    def load_dsn(self) -> str:
        raw = settings_store.get_setting(self._setting_key) or {}
        enabled = bool(raw.get("enabled"))
        dsn = str(raw.get("dsn") or "").strip()
        if not enabled or not dsn:
            raise self._unavailable_cls(self._dsn_required_message)
        return dsn

    def is_configured(self) -> bool:
        raw = settings_store.get_setting(self._setting_key) or {}
        return bool(raw.get("enabled") and str(raw.get("dsn") or "").strip())

    # ---- pool --------------------------------------------------------------

    def get_pool(self) -> ConnectionPool:
        dsn = self.load_dsn()
        if self._pool is None or self._pool_dsn != dsn:
            self.close_pool()
            extra: dict[str, Any] = {}
            if self._pool_timeout is not None:
                extra["timeout"] = self._pool_timeout
            self._pool = ConnectionPool(
                conninfo=dsn,
                min_size=self._min_size,
                max_size=self._max_size,
                kwargs={"row_factory": dict_row},
                open=True,
                **extra,
            )
            self._pool_dsn = dsn
        return self._pool

    def close_pool(self) -> None:
        if self._pool is not None:
            try:
                self._pool.close()
            except Exception:
                pass
        self._pool = None
        self._pool_dsn = None

    # ---- queries -----------------------------------------------------------

    def query(
        self,
        sql: str,
        params: list[Any] | tuple[Any, ...] | None = None,
        *,
        statement_timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        timeout = self._default_query_timeout_ms if statement_timeout_ms is None else statement_timeout_ms
        pool = self.get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                if timeout is not None and timeout > 0:
                    # SET LOCAL 仅当前事务；pool.connection() 会开事务
                    cur.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        [f"{int(timeout)}ms"],
                    )
                cur.execute(sql, params or [])
                if cur.description is None:
                    return []
                return list(cur.fetchall())

    def iter_batches(
        self,
        sql: str,
        params: list[Any] | tuple[Any, ...] | None = None,
        *,
        batch_size: int = 2000,
        statement_timeout_ms: int | None = None,
    ) -> Iterator[list[dict[str, Any]]]:
        """服务端游标分批吐行，避免全表 fetchall 把 API 进程撑爆。"""
        timeout = self._default_iter_timeout_ms if statement_timeout_ms is None else statement_timeout_ms
        size = max(200, int(batch_size or 2000))
        pool = self.get_pool()
        with pool.connection() as conn:
            if timeout is not None and timeout > 0:
                with conn.cursor() as setup:
                    setup.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        [f"{int(timeout)}ms"],
                    )
            with conn.cursor(name=self._cursor_name) as cur:
                cur.itersize = size
                cur.execute(sql, params or [])
                while True:
                    rows = cur.fetchmany(size)
                    if not rows:
                        break
                    yield rows
