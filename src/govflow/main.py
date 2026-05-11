"""
政务事项检索 API（PostgreSQL + pgvector）。

启动（在仓库根目录）：
  uvicorn govflow.main:app --reload --app-dir src
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from govflow.api.routes.chat import router as chat_router
from govflow.config import get_settings
from govflow.db.pool import create_pool

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    pool = create_pool(settings.database_url)
    app.state.db_pool = pool
    try:
        yield
    finally:
        pool.close()


app = FastAPI(
    title="GovFlow",
    version="0.2.0",
    description="政务事项存储与检索：候选判定 + 澄清/模板输出（不接大模型生成）",
    lifespan=lifespan,
)

app.include_router(chat_router)


@app.get("/")
def serve_ui() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
