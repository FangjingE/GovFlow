"""PostgreSQL 连接池（psycopg 3）。"""

from psycopg_pool import ConnectionPool


def create_pool(dsn: str, *, min_size: int = 1, max_size: int = 10) -> ConnectionPool:
    if not dsn or not str(dsn).strip():
        raise ValueError("database DSN is empty")
    return ConnectionPool(
        conninfo=dsn,
        min_size=min_size,
        max_size=max_size,
        kwargs={"connect_timeout": 15},
    )
