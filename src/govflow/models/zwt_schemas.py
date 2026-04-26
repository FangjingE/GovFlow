"""政务通：互市类分步填报 HTTP 契约（与主聊天统一品牌）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ZwtTurnRequest(BaseModel):
    """一轮对话：首次不传 session_id；可选 start_only 仅取开场白。"""

    session_id: str | None = Field(default=None, description="政务通分步填报会话 ID")
    message: str = Field(default="", max_length=12_000, description="用户语音/文字；start_only 时可为空")
    locale: str = Field(
        default="zh-CN",
        description="zh-CN | vi-VN（越文内容待接入，越文 locale 时部分句回退中文）",
    )
    start_only: bool = Field(
        default=False,
        description="仅创建会话并返回开场白，不处理 message",
    )


class ZwtTurnResponse(BaseModel):
    session_id: str
    reply: str
    kind: str = Field(
        description="collecting | preview | submitted | need_human | cancelled | knowledge",
    )
    step: str
    form: dict = Field(default_factory=dict)
    form_preview: str = ""
    plan_remaining: list[str] = Field(default_factory=list)
    submit_receipt: str | None = None
    validation_warnings: list[str] = Field(default_factory=list)
    field_explanation: str | None = Field(
        default=None,
        description="本步复杂字段的通俗/模板说明，可接大模型扩写；无则 null",
    )
    rag_sources: list[dict] | None = Field(
        default=None,
        description="knowledge 类 RAG 答问时返回的引用（title/uri/score 等）",
    )
    locale: str = "zh-CN"
    product: str = Field(default="zhengwutong", description="产品标识：政务通")
