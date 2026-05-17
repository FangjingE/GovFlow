"""HTTP / JSON 契约。"""

from typing import Literal

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
    session_state: str = Field(default="init", description="init | clarify | answer | fallback")
    retry_count: int = Field(default=0, ge=0)
    sources: list[SourceRef] = Field(default_factory=list)
    official_hotline: str
    clarify_question: str | None = None
    clarify_options: list[ClarifyOption] = Field(default_factory=list)
    stages_executed: list[str] = Field(default_factory=list)


ToolSearchMode = Literal["exact", "vector", "text"]
ToolAction = Literal["answer", "clarify", "fallback"]
DetailSection = Literal["basic", "materials", "processes"]


class SearchServicesRequest(BaseModel):
    query: str = Field(..., min_length=1, description="用户查询文本")
    top_k: int = Field(default=5, ge=1, le=20, description="返回候选数")
    query_vector: list[float] | None = Field(
        default=None,
        description="可选：768 维查询向量；提供时优先按余弦距离检索",
    )


class ServiceCandidate(BaseModel):
    id: int
    service_name: str
    department: str | None = None
    service_object: str | None = None
    accept_condition: str | None = None
    handle_form: str | None = None
    item_type: str | None = None
    source_url: str | None = None
    match_score: float | None = None
    keyword_hits: int | None = None


class SearchServicesResponse(BaseModel):
    query: str
    search_mode: ToolSearchMode
    suggested_action: ToolAction
    exact_match_hit: bool = False
    used_supplied_query_vector: bool = False
    clarify_hint: str | None = None
    candidates: list[ServiceCandidate] = Field(default_factory=list)
    stages_executed: list[str] = Field(default_factory=list)


class GetServiceDetailRequest(BaseModel):
    service_id: int = Field(..., ge=1, description="事项 ID")
    include: list[DetailSection] = Field(
        default_factory=lambda: ["basic", "materials", "processes"],
        description="需要返回的详情区块",
    )


class ServiceBasicDetail(BaseModel):
    id: int
    service_name: str
    source_url: str | None = None
    department: str | None = None
    service_object: str | None = None
    promise_days: int | None = None
    legal_days: int | None = None
    on_site_times: int | None = None
    is_charge: bool | None = None
    accept_condition: str | None = None
    general_scope: str | None = None
    handle_form: str | None = None
    item_type: str | None = None
    handle_address: str | None = None
    handle_time: str | None = None
    consult_way: str | None = None
    complaint_way: str | None = None
    query_way: str | None = None


class ServiceMaterialDetail(BaseModel):
    material_name: str
    is_required: bool | None = None
    material_form: str | None = None
    original_num: int | None = None
    copy_num: int | None = None
    note: str | None = None


class ServiceProcessDetail(BaseModel):
    step_name: str | None = None
    step_desc: str | None = None
    sort: int


class GetServiceDetailResponse(BaseModel):
    service_id: int
    included_sections: list[DetailSection] = Field(default_factory=list)
    basic: ServiceBasicDetail | None = None
    materials: list[ServiceMaterialDetail] = Field(default_factory=list)
    processes: list[ServiceProcessDetail] = Field(default_factory=list)
    stages_executed: list[str] = Field(default_factory=list)
