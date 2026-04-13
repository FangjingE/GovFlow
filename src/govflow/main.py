"""
GovFlow API 入口。

启动：在项目根目录执行
  uvicorn govflow.main:app --reload --app-dir src

TODO: CORS 白名单、请求 ID 中间件、限流、健康检查探针、OpenAPI 鉴权。
"""

from fastapi import FastAPI

from govflow.api.routes.chat import router as chat_router

app = FastAPI(title="GovFlow", version="0.1.0", description="本地政务 AI 办事助手 MVP（P0）")

app.include_router(chat_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
