"""
GovFlow API 入口。

启动：在项目根目录执行
  uvicorn govflow.main:app --reload --app-dir src

简单 Web 界面：浏览器打开根路径 /（与 /docs、/v1 并存）。

TODO: CORS 白名单、请求 ID 中间件、限流、健康检查探针、OpenAPI 鉴权。
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from govflow.api.routes.chat import router as chat_router

app = FastAPI(title="GovFlow", version="0.1.0", description="本地政务 AI 办事助手 MVP（P0）")

_STATIC_DIR = Path(__file__).resolve().parent / "static"

app.include_router(chat_router)


@app.get("/")
def serve_ui() -> FileResponse:
    """单页聊天界面（静态 HTML，仅开发/本地使用）。"""
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
