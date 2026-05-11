"""HTTP / JSON 契约。"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str | None = Field(
        default=None,
        description="会话 ID（可选，仅回显；检索为无状态）",
    )
    message: str = Field(..., min_length=1, description="用户自然语言输入")
    query_vector: list[float] | None = Field(
        default=None,
        description="可选：768 维查询向量；提供时优先按余弦距离检索（不经过大模型生成）",
    )


class SourceRef(BaseModel):
    title: str
    uri: str | None = None
    score: float | None = None


class ClarifyOption(BaseModel):
    service_id: int
    label: str
    value: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    kind: str = Field(description="answer | clarify | fallback")
    sources: list[SourceRef] = Field(default_factory=list)
    official_hotline: str
    clarify_question: str | None = None
    clarify_options: list[ClarifyOption] = Field(default_factory=list)
    stages_executed: list[str] = Field(default_factory=list)
