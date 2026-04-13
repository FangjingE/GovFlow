"""ChatOrchestrator 分支契约测试（固定 Stub，不依赖真实模型与 knowledge_base）。

HTTP 与 kind 约定（与路由 ``POST /v1/chat`` 一致，见 ``govflow.api.routes.chat``）：

- 任意编排结果（``blocked`` / ``clarification`` / ``fallback`` / ``answer``）均返回 **HTTP 200**；
  业务语义只看响应体中的 ``kind``、``reply``、``sources`` 等，不把拦截或兜底映射为 4xx。
- 仅当请求携带 ``session_id`` 且服务端会话 store 中不存在该 id 时返回 **HTTP 404**，
  ``detail == "session not found"``；与编排器内部分支无关。

细粒度分支用 Stub 覆盖；端到端烟测见 ``test_chat_smoke.py``。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from govflow.api.deps import get_orchestrator
from govflow.domain.messages import PipelineStage, RetrievedChunk
from govflow.main import app
from govflow.repositories.session_store import InMemorySessionStore
from govflow.services.intent.intent_service import IntentAnalysis, IntentStatus
from govflow.services.llm.mock_llm import PassThroughAuditor
from govflow.services.pipeline.orchestrator import ChatOrchestrator
from govflow.services.safety.sensitive_filter import FilterResult


class StubFilter:
    def __init__(self, allowed: bool, reason: str | None = None) -> None:
        self._allowed = allowed
        self._reason = reason

    def check(self, text: str) -> FilterResult:
        return FilterResult(allowed=self._allowed, reason=self._reason)


class StubIntent:
    def __init__(self, analyses: list[IntentAnalysis]) -> None:
        self._analyses = analyses
        self._i = 0

    def analyze(self, user_text: str, session_topic: str | None) -> IntentAnalysis:
        if self._i >= len(self._analyses):
            return self._analyses[-1]
        a = self._analyses[self._i]
        self._i += 1
        return a


class StubRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        return self._chunks[:top_k]


class StubLLM:
    def __init__(self, text: str) -> None:
        self._text = text

    def generate_answer(
        self,
        user_message: str,
        history_snippets: list[str],
        evidence_chunks: list[RetrievedChunk],
    ) -> str:
        return self._text


class StubAuditor:
    def __init__(self, ok: bool, reason: str | None = None) -> None:
        self._ok = ok
        self._reason = reason

    def audit(self, answer: str, evidence_chunks: list[RetrievedChunk]) -> tuple[bool, str | None]:
        return (self._ok, self._reason)


def _sample_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        text="社保卡申领需携带身份证原件。",
        source_title="办事指南/社保卡",
        source_uri="https://govflow.test/kb/socsec-card",
        score=0.95,
    )


def _orch(**kwargs: object) -> ChatOrchestrator:
    return ChatOrchestrator(**kwargs)


def test_blocked_branch() -> None:
    store = InMemorySessionStore()
    orch = _orch(
        session_store=store,
        sensitive_filter=StubFilter(False, "命中敏感词占位规则: 测试词"),
        intent_service=StubIntent(
            [IntentAnalysis(IntentStatus.READY_FOR_RAG, "通用政务", [], [])]
        ),
        retriever=StubRetriever([_sample_chunk()]),
    )
    session = store.create()
    r = orch.handle_message(session, "用户输入")

    assert r.kind == "blocked"
    assert r.sources == []
    assert "无法继续处理" in r.reply
    assert r.official_hotline
    assert PipelineStage.FILTER.value in r.stages_executed
    assert PipelineStage.INTENT.value not in r.stages_executed


def test_clarification_branch() -> None:
    store = InMemorySessionStore()
    orch = _orch(
        session_store=store,
        sensitive_filter=StubFilter(True),
        intent_service=StubIntent(
            [
                IntentAnalysis(
                    IntentStatus.NEEDS_CLARIFICATION,
                    "社保",
                    ["social_sub_intent"],
                    ["请问具体要办哪一项？"],
                )
            ]
        ),
        retriever=StubRetriever([_sample_chunk()]),
    )
    session = store.create()
    r = orch.handle_message(session, "办社保")

    assert r.kind == "clarification"
    assert r.sources == []
    assert "请问具体要办哪一项？" in r.reply
    assert PipelineStage.FILTER.value in r.stages_executed
    assert PipelineStage.INTENT.value in r.stages_executed
    assert PipelineStage.CLARIFY.value in r.stages_executed
    assert PipelineStage.RAG.value not in r.stages_executed


def test_fallback_no_retrieval_branch() -> None:
    store = InMemorySessionStore()
    orch = _orch(
        session_store=store,
        sensitive_filter=StubFilter(True),
        intent_service=StubIntent(
            [IntentAnalysis(IntentStatus.READY_FOR_RAG, "通用政务", [], [])]
        ),
        retriever=StubRetriever([]),
    )
    session = store.create()
    r = orch.handle_message(session, "已足够具体的长问题用于检索")

    assert r.kind == "fallback"
    assert r.sources == []
    assert "未找到与您问题直接匹配" in r.reply
    assert PipelineStage.RAG.value in r.stages_executed
    assert PipelineStage.LLM.value in r.stages_executed
    assert PipelineStage.AUDIT.value not in r.stages_executed


def test_fallback_audit_failed_branch() -> None:
    chunk = _sample_chunk()
    store = InMemorySessionStore()
    orch = _orch(
        session_store=store,
        sensitive_filter=StubFilter(True),
        intent_service=StubIntent(
            [IntentAnalysis(IntentStatus.READY_FOR_RAG, "通用政务", [], [])]
        ),
        retriever=StubRetriever([chunk]),
        llm=StubLLM("这是一条足够长的、用于通过长度启发式之前的生成文本。"),
        auditor=StubAuditor(False, "证据与答案不一致"),
    )
    session = store.create()
    r = orch.handle_message(session, "社保卡需要什么材料")

    assert r.kind == "fallback"
    assert len(r.sources) == 1
    assert r.sources[0]["title"] == chunk.source_title
    assert r.sources[0]["uri"] == chunk.source_uri
    assert "未能通过安全与证据校验" in r.reply
    assert "证据与答案不一致" in r.reply
    assert PipelineStage.AUDIT.value in r.stages_executed


def test_answer_branch() -> None:
    chunk = _sample_chunk()
    store = InMemorySessionStore()
    orch = _orch(
        session_store=store,
        sensitive_filter=StubFilter(True),
        intent_service=StubIntent(
            [IntentAnalysis(IntentStatus.READY_FOR_RAG, "社保", [], [])]
        ),
        retriever=StubRetriever([chunk]),
        llm=StubLLM("根据办事指南，请携带身份证原件到窗口办理社保卡，具体以现场审核为准。"),
        auditor=PassThroughAuditor(),
    )
    session = store.create()
    r = orch.handle_message(session, "我想办社保卡")

    assert r.kind == "answer"
    assert len(r.sources) == 1
    assert r.sources[0]["title"] == chunk.source_title
    assert r.reply == "根据办事指南，请携带身份证原件到窗口办理社保卡，具体以现场审核为准。"
    assert PipelineStage.AUDIT.value in r.stages_executed


def test_clarification_then_answer_two_hops() -> None:
    chunk = _sample_chunk()
    store = InMemorySessionStore()
    orch = _orch(
        session_store=store,
        sensitive_filter=StubFilter(True),
        intent_service=StubIntent(
            [
                IntentAnalysis(
                    IntentStatus.NEEDS_CLARIFICATION,
                    "社保",
                    ["slot_a"],
                    ["请说明要办社保卡还是查询缴费？"],
                ),
                IntentAnalysis(IntentStatus.READY_FOR_RAG, "社保", [], []),
            ]
        ),
        retriever=StubRetriever([chunk]),
        llm=StubLLM("请携带身份证到窗口办理社保卡，建议先在政务网预约取号以节省排队时间。"),
        auditor=PassThroughAuditor(),
    )
    session = store.create()

    r1 = orch.handle_message(session, "办社保")
    assert r1.kind == "clarification"
    assert r1.sources == []

    r2 = orch.handle_message(session, "我要办社保卡")
    assert r2.kind == "answer"
    assert len(r2.sources) == 1
    assert r2.sources[0]["uri"] == chunk.source_uri


@pytest.fixture(autouse=True)
def _reset_app_dependency_overrides() -> None:
    yield
    app.dependency_overrides.clear()
    get_orchestrator.cache_clear()


@pytest.fixture
def http_blocked_client() -> TestClient:
    store = InMemorySessionStore()
    orch = ChatOrchestrator(
        session_store=store,
        sensitive_filter=StubFilter(False, "stub block"),
        intent_service=StubIntent(
            [IntentAnalysis(IntentStatus.READY_FOR_RAG, "通用政务", [], [])]
        ),
        retriever=StubRetriever([]),
    )
    app.dependency_overrides[get_orchestrator] = lambda: orch
    yield TestClient(app)


def test_post_chat_blocked_returns_200_and_kind(http_blocked_client: TestClient) -> None:
    """路由层：blocked 仍为 HTTP 200，由 body.kind 表达。"""
    res = http_blocked_client.post("/v1/chat", json={"message": "hello"})
    assert res.status_code == 200
    body = res.json()
    assert body["kind"] == "blocked"
    assert body["sources"] == []


def test_post_chat_unknown_session_returns_404() -> None:
    """路由层：无效 session_id → 404，不经编排器。"""
    client = TestClient(app)
    res = client.post(
        "/v1/chat",
        json={"session_id": "00000000-0000-0000-0000-000000000000", "message": "hi"},
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "session not found"
