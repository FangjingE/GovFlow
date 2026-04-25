"""答案审核工厂与 ``grounded`` 规则。"""

from govflow.config import Settings
from govflow.domain.messages import RetrievedChunk
from govflow.repositories.session_store import InMemorySessionStore
from govflow.services.intent.intent_service import IntentAnalysis, IntentStatus
from govflow.services.llm.auditors import GroundedAnswerAuditor, build_answer_auditor
from govflow.services.llm.mock_llm import PassThroughAuditor
from govflow.services.pipeline.orchestrator import ChatOrchestrator

from test_chat_orchestrator import StubFilter, StubIntent, StubRetriever, StubLLM


def test_build_answer_auditor_pass_through() -> None:
    s = Settings(answer_auditor_mode="pass_through")
    aud = build_answer_auditor(s)
    assert isinstance(aud, PassThroughAuditor)


def test_build_answer_auditor_grounded() -> None:
    s = Settings(answer_auditor_mode="grounded")
    aud = build_answer_auditor(s)
    assert isinstance(aud, GroundedAnswerAuditor)


def test_pass_through_respects_min_length_from_settings() -> None:
    s = Settings(answer_auditor_mode="pass_through", answer_auditor_min_answer_length=200)
    aud = build_answer_auditor(s)
    chunk = RetrievedChunk(text="x", source_title="t", source_uri=None, score=1.0)
    ok, _ = aud.audit("短", [chunk])
    assert not ok


def test_grounded_rejects_digit_run_not_in_evidence() -> None:
    s = Settings(answer_auditor_mode="grounded")
    aud = build_answer_auditor(s)
    chunk = RetrievedChunk(text="窗口咨询电话见现场公示。", source_title="指南", source_uri=None, score=1.0)
    long_ok = "根据办事指南，请携带身份证原件到窗口办理，具体以现场审核为准。"
    ok, reason = aud.audit(long_ok + " 虚构热线 9888888888888888。", [chunk])
    assert not ok
    assert reason and "数字" in reason


def test_grounded_accepts_digits_present_in_evidence() -> None:
    aud = GroundedAnswerAuditor(min_answer_length=20)
    chunk = RetrievedChunk(
        text="咨询电话 12345 转公安窗口，2025 年修订。",
        source_title="指引",
        source_uri=None,
        score=1.0,
    )
    ok, _ = aud.audit("请拨打 12345 办理，政策依据见 2025 年修订文本说明。", [chunk])
    assert ok


def test_orchestrator_grounded_fallback_on_invented_number() -> None:
    chunk = RetrievedChunk(
        text="需携带身份证原件。",
        source_title="知识/test",
        source_uri="https://govflow.test/kb",
        score=0.9,
    )
    store = InMemorySessionStore()
    s = Settings(answer_auditor_mode="grounded")
    orch = ChatOrchestrator(
        settings=s,
        session_store=store,
        sensitive_filter=StubFilter(True),
        intent_service=StubIntent(
            [IntentAnalysis(IntentStatus.READY_FOR_RAG, "通用政务", [], [])]
        ),
        retriever=StubRetriever([chunk]),
        llm=StubLLM(
            "根据办事指南请携带身份证到窗口办理，另可拨打热线 1000000000001 咨询。"
        ),
    )
    session = store.create()
    r = orch.handle_message(session, "我想补办身份证要带什么")
    assert r.kind == "fallback"
    assert "数字" in (r.reply + "")
