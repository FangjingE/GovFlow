"""HTTP / JSON 契约层（与领域模型分离，便于版本演进）。"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str | None = Field(
        default=None,
        description="多轮对话会话 ID；首次可为空，由服务端创建",
    )
    message: str = Field(..., min_length=1, description="用户自然语言输入")


class SourceRef(BaseModel):
    title: str
    uri: str | None = None
    score: float | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    kind: str = Field(description="answer | clarification | blocked | fallback")
    sources: list[SourceRef] = Field(default_factory=list)
    official_hotline: str
    stages_executed: list[str] = Field(default_factory=list)
