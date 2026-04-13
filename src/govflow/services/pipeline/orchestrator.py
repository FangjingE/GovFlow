"""
对话编排器：实现需求文档中的主数据流（P0）。

用户提问 → 敏感词过滤 → 意图识别 → 槽位追问（信息不全）
    → RAG 检索 → LLM 生成 → 答案审核 → 返回用户

TODO:
- 异步化（async def）与超时控制（≤3s SLA）
- 可观测性：OpenTelemetry span 按 PipelineStage 打点
- 熔断与降级策略（检索失败 / LLM 超时）
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from govflow.config import Settings, get_settings
from govflow.domain.messages import ClarificationState, PipelineStage, RetrievedChunk
from govflow.repositories.session_store import ConversationSession, InMemorySessionStore
from govflow.services.clarification.slot_engine import SlotClarificationEngine
from govflow.services.intent.intent_service import IntentService, IntentStatus
from govflow.services.llm.mock_llm import MockLLMClient, PassThroughAuditor
from govflow.services.rag.mock_retriever import MockKeywordRetriever
from govflow.services.safety.sensitive_filter import SensitiveContentFilter

if TYPE_CHECKING:
    from govflow.services.llm.protocols import AnswerAuditor, LLMClient
    from govflow.services.rag.protocols import Retriever


@dataclass
class OrchestratorResult:
    """API 层可直接映射为 JSON 的结构。"""

    reply: str
    kind: str  # "answer" | "clarification" | "blocked" | "fallback"
    sources: list[dict[str, object]]
    official_hotline: str
    stages_executed: list[str]


class ChatOrchestrator:
    def __init__(
        self,
        settings: Settings | None = None,
        session_store: InMemorySessionStore | None = None,
        sensitive_filter: SensitiveContentFilter | None = None,
        intent_service: IntentService | None = None,
        slot_engine: SlotClarificationEngine | None = None,
        retriever: "Retriever | None" = None,
        llm: "LLMClient | None" = None,
        auditor: "AnswerAuditor | None" = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._sessions = session_store or InMemorySessionStore()
        self._filter = sensitive_filter or SensitiveContentFilter()
        self._intent = intent_service or IntentService()
        self._slots = slot_engine or SlotClarificationEngine()
        self._retriever = retriever or MockKeywordRetriever()
        self._llm = llm or MockLLMClient()
        self._auditor = auditor or PassThroughAuditor()

    @property
    def sessions(self) -> InMemorySessionStore:
        return self._sessions

    def handle_message(self, session: ConversationSession, user_text: str) -> OrchestratorResult:
        stages: list[str] = []
        hotline = self._settings.default_hotline

        fr = self._filter.check(user_text)
        stages.append(PipelineStage.FILTER.value)
        if not fr.allowed:
            return OrchestratorResult(
                reply=f"该问题无法继续处理。{fr.reason or ''} 如需帮助请拨打 {hotline}。",
                kind="blocked",
                sources=[],
                official_hotline=hotline,
                stages_executed=stages,
            )

        # 澄清轮：将首轮模糊问法与后续补充合并后再做意图/检索
        combined_for_intent = user_text
        if session.awaiting_clarification and session.pending_vague_text:
            combined_for_intent = f"{session.pending_vague_text}\n{user_text}".strip()

        topic_hint = session.clarification.topic if session.clarification else None
        analysis = self._intent.analyze(combined_for_intent, topic_hint)
        stages.append(PipelineStage.INTENT.value)

        if analysis.status == IntentStatus.NEEDS_CLARIFICATION:
            clar = ClarificationState(topic=analysis.topic, pending_slots=list(analysis.missing_slots))
            if not session.awaiting_clarification:
                self._sessions.update_session(
                    session.id,
                    clarification=clar,
                    awaiting_clarification=True,
                    pending_vague_text=user_text,
                )
            else:
                # 多轮仍不清晰：累积上下文并继续追问（TODO：槽位级追问而非重复整段）
                self._sessions.update_session(
                    session.id,
                    clarification=clar,
                    pending_vague_text=combined_for_intent,
                )
            reply = "\n".join(analysis.suggested_questions)
            stages.append(PipelineStage.CLARIFY.value)
            return OrchestratorResult(
                reply=reply,
                kind="clarification",
                sources=[],
                official_hotline=hotline,
                stages_executed=stages,
            )

        if session.awaiting_clarification:
            self._sessions.update_session(
                session.id,
                awaiting_clarification=False,
                pending_vague_text=None,
                clarification=self._slots.apply_user_reply(
                    session.clarification,
                    user_text,
                    [],
                    analysis.topic,
                ),
            )

        rag_query = self._build_rag_query(session, user_text, combined_for_intent)
        chunks = self._retriever.retrieve(rag_query, top_k=5)
        stages.append(PipelineStage.RAG.value)

        if not chunks:
            stages.append(PipelineStage.LLM.value)
            return OrchestratorResult(
                reply=(
                    "当前知识库中未找到与您问题直接匹配的官方办事指南条目，"
                    "为避免不准确答复，建议您拨打官方咨询电话或前往政务大厅现场咨询。\n"
                    f"📞 政务服务便民热线：{hotline}\n"
                    f"📞 人社政策咨询：12333（如涉及社保医保）"
                ),
                kind="fallback",
                sources=[],
                official_hotline=hotline,
                stages_executed=stages,
            )

        history_snippets = [t.content for t in session.turns[-6:] if t.role == "user"]
        answer = self._llm.generate_answer(rag_query, history_snippets, chunks)
        stages.append(PipelineStage.LLM.value)

        ok, reason = self._auditor.audit(answer, chunks)
        stages.append(PipelineStage.AUDIT.value)
        if not ok:
            return OrchestratorResult(
                reply=(
                    f"答案未能通过安全与证据校验（{reason or '未知原因'}）。"
                    f"请致电 {hotline} 或转人工服务获取权威指引。"
                ),
                kind="fallback",
                sources=_chunks_to_sources(chunks),
                official_hotline=hotline,
                stages_executed=stages,
            )

        self._sessions.update_session(session.id, clarification=None)

        return OrchestratorResult(
            reply=answer,
            kind="answer",
            sources=_chunks_to_sources(chunks),
            official_hotline=hotline,
            stages_executed=stages,
        )

    def _build_rag_query(self, session: ConversationSession, user_text: str, combined: str) -> str:
        # 取最近若干轮用户发言，增强多轮场景下的检索召回（TODO：查询改写 QR）
        recent = [t.content for t in session.turns if t.role == "user"][-3:]
        base = "\n".join([*recent, user_text]).strip() if recent else combined
        return base or user_text


def _chunks_to_sources(chunks: list[RetrievedChunk]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for c in chunks:
        out.append(
            {
                "title": c.source_title,
                "uri": c.source_uri,
                "score": c.score,
            }
        )
    return out
