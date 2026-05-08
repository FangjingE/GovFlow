"""FastAPI 依赖：数据库连接池。"""

from fastapi import Request

from govflow.config import get_settings
from psycopg_pool import ConnectionPool


def get_pool(request: Request) -> ConnectionPool:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise RuntimeError("数据库连接池未初始化")
    return pool
