"""
政务通 API 入口（包名 GovFlow）。

启动：在项目根目录执行
  uvicorn govflow.main:app --reload --app-dir src

Web：根路径 / 为统一政务对话；旧书签 /bmt 重定向至首页。分步填报 API：`POST /v1/zwt/turn`。

TODO: CORS 白名单、请求 ID 中间件、限流、健康检查探针、OpenAPI 鉴权。
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse

from govflow.api.routes.chat import router as chat_router
from govflow.api.routes.zhengwutong import router as zhengwutong_router

app = FastAPI(
    title="政务通",
    version="0.1.0",
    description="本地政务 AI 办事助手（统一对话 POST /v1/chat；互市类分步填报见 POST /v1/zwt/turn）",
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"

app.include_router(chat_router)
app.include_router(zhengwutong_router)


@app.get("/")
def serve_ui() -> FileResponse:
    """单页聊天界面（静态 HTML，仅开发/本地使用）。"""
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/bmt")
def legacy_bmt_path_redirect() -> RedirectResponse:
    """旧路径重定向至首页（统一政务通对话）。"""
    return RedirectResponse(url="/", status_code=302)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
