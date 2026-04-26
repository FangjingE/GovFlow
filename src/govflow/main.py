"""
GovFlow API 入口。

启动：在项目根目录执行
  uvicorn govflow.main:app --reload --app-dir src

简单 Web 界面：根路径 / 为政务聊天；/bmt 为边民通申报演示页（与 /docs、/v1 并存）。

TODO: CORS 白名单、请求 ID 中间件、限流、健康检查探针、OpenAPI 鉴权。
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from govflow.api.routes.bianmintong import router as bianmintong_router
from govflow.api.routes.chat import router as chat_router

app = FastAPI(
    title="GovFlow",
    version="0.1.0",
    description="本地政务 AI 办事助手 MVP（P0）；边民通互市申报见 /v1/bmt",
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"

app.include_router(chat_router)
app.include_router(bianmintong_router)


@app.get("/")
def serve_ui() -> FileResponse:
    """单页聊天界面（静态 HTML，仅开发/本地使用）。"""
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/bmt")
def serve_bianmintong_ui() -> FileResponse:
    """边民通：对话式互市申报演示页。"""
    return FileResponse(_STATIC_DIR / "bmt.html")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
