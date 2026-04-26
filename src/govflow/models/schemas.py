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
    kind: str = Field(
        description="answer | clarification | blocked | fallback；政务通分步轨为 collecting|preview|submitted|…"
    )
    sources: list[SourceRef] = Field(default_factory=list)
    official_hotline: str
    stages_executed: list[str] = Field(default_factory=list)
    # 政务通：互市类分步填报侧栏（意图命中并确认后 true）
    zwt_sidebar_visible: bool = False
    zwt_form_preview: str | None = None
    zwt_step: str | None = None
    zwt_track_kind: str | None = Field(
        default=None,
        description="分步填报引擎 kind（collecting、knowledge 等）",
    )
    zwt_rag_sources: list[SourceRef] = Field(default_factory=list)
