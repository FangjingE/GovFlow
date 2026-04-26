"""
GovFlow API 入口。

启动：在项目根目录执行
  uvicorn govflow.main:app --reload --app-dir src

简单 Web 界面：根路径 / 为政务聊天（边民通互市申报已并入同一对话）；/bmt 重定向至首页。

TODO: CORS 白名单、请求 ID 中间件、限流、健康检查探针、OpenAPI 鉴权。
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse

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
def bianmintong_ui_redirect() -> RedirectResponse:
    """边民通申报已并入主页聊天；保留路径以免旧书签失效。"""
    return RedirectResponse(url="/", status_code=302)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
