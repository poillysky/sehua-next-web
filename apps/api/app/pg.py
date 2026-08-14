"""Postgres pool for resource DB (DSN from SQLite settings)."""



from __future__ import annotations



from typing import Any



from psycopg.rows import dict_row

from psycopg_pool import ConnectionPool



from . import settings_store



_pool: ConnectionPool | None = None

_pool_dsn: str | None = None





class ResourceDbUnavailable(Exception):

    def __init__(self, message: str = "资源库未配置或不可用"):

        super().__init__(message)

        self.message = message





def _load_dsn() -> str:

    raw = settings_store.get_setting(settings_store.RESOURCE_DB_KEY) or {}

    enabled = bool(raw.get("enabled"))

    dsn = str(raw.get("dsn") or "").strip()

    if not enabled or not dsn:

        raise ResourceDbUnavailable("请先在设置中启用并填写资源库 DSN")

    return dsn





def get_pool() -> ConnectionPool:

    global _pool, _pool_dsn

    dsn = _load_dsn()

    if _pool is None or _pool_dsn != dsn:

        if _pool is not None:

            try:

                _pool.close()

            except Exception:

                pass

        _pool = ConnectionPool(

            conninfo=dsn,

            min_size=1,

            max_size=10,

            kwargs={"row_factory": dict_row},

            open=True,

        )

        _pool_dsn = dsn

    return _pool





def query(
    sql: str,
    params: list[Any] | tuple[Any, ...] | None = None,
    *,
    statement_timeout_ms: int | None = None,
) -> list[dict[str, Any]]:

    pool = get_pool()

    with pool.connection() as conn:

        with conn.cursor() as cur:

            if statement_timeout_ms is not None and statement_timeout_ms > 0:

                # SET LOCAL 仅当前事务；pool.connection() 会开事务
                cur.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    [f"{int(statement_timeout_ms)}ms"],
                )

            cur.execute(sql, params or [])

            if cur.description is None:

                return []

            return list(cur.fetchall())





def close_pool() -> None:

    global _pool, _pool_dsn

    if _pool is not None:

        try:

            _pool.close()

        except Exception:

            pass

    _pool = None

    _pool_dsn = None


