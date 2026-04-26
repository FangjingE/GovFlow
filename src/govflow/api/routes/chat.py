"""对话 HTTP 接口（P0）；政务通分步填报与通用政务统一由本入口调度。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from govflow.api.deps import get_orchestrator, get_zwt_declaration_engine
from govflow.api.routes.zhengwutong import get_zwt_store, with_zwt_friendly_tail
from govflow.domain.messages import ChatTurn
from govflow.models.schemas import ChatRequest, ChatResponse, SourceRef
from govflow.services.intent.intent_service import IntentService
from govflow.services.pipeline.orchestrator import ChatOrchestrator
from govflow.zhengwutong.engine import BMTDeclarationEngine

router = APIRouter(prefix="/v1/chat", tags=["chat"])

ZWT_CONSENT_SUFFIX = (
    "\n\n---\n"
    "以上是就您问题的梳理与说明。**若您需要，我可以逐步带您填写互市类申报表预览（演示）。**\n"
    "是否**现在**就开始辅助填写？请回复「**是**」或「**开始**」；若暂不需要请回复「**不用**」或继续提其他问题。"
)


def _rag_dicts_to_sources(items: list[dict] | None) -> list[SourceRef]:
    if not items:
        return []
    out: list[SourceRef] = []
    for o in items:
        title = o.get("title")
        out.append(
            SourceRef(
                title=str(title) if title is not None else "",
                uri=o.get("uri") if isinstance(o.get("uri"), str) else None,
                score=float(o["score"]) if o.get("score") is not None else None,
            )
        )
    return out


def _zwt_first_turn_user_text(
    seed: str | None,
    user_text: str,
    intent: IntentService,
) -> str:
    """用户仅简短确认时，用首轮话题猜测进/出口，避免只答「是」卡在进出口步。"""
    t = user_text.strip()
    if intent.confirms_zwt_declaration_start(user_text) and len(t) <= 12:
        s = (seed or "").strip()
        if "出口" in s and "进口" not in s:
            return "出口"
        if "进口" in s:
            return "进口"
    return user_text


@router.post("", response_model=ChatResponse)
def post_chat(
    body: ChatRequest,
    orchestrator: ChatOrchestrator = Depends(get_orchestrator),
    zwt_engine: BMTDeclarationEngine = Depends(get_zwt_declaration_engine),
) -> ChatResponse:
    store = orchestrator.sessions
    zwt_store = get_zwt_store()
    intent = orchestrator.intent_service
    hotline = orchestrator.settings.default_hotline

    if body.session_id:
        session = store.get(body.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="session not found")
    else:
        session = store.create()

    user_text = body.message.strip()

    blocked = orchestrator.sensitive_block_result(user_text)
    if blocked:
        store.update_session(session.id, awaiting_zwt_consent=False, zwt_seed_hint=None)
        store.append_turn(session.id, ChatTurn(role="user", content=body.message))
        store.append_turn(session.id, ChatTurn(role="assistant", content=blocked.reply))
        return ChatResponse(
            session_id=session.id,
            reply=blocked.reply,
            kind=blocked.kind,
            sources=[SourceRef(**s) for s in blocked.sources],
            official_hotline=blocked.official_hotline,
            stages_executed=blocked.stages_executed,
        )

    def _gov_response(reply: str, kind: str, sources: list, stages: list[str]) -> ChatResponse:
        return ChatResponse(
            session_id=session.id,
            reply=reply,
            kind=kind,
            sources=[SourceRef(**s) for s in sources],
            official_hotline=hotline,
            stages_executed=stages,
        )

    def _zwt_response(
        reply: str,
        *,
        kind: str,
        form_preview: str,
        step: str,
        stages: list[str],
        rag_sources: list[dict] | None,
    ) -> ChatResponse:
        reply_out = with_zwt_friendly_tail(reply)
        return ChatResponse(
            session_id=session.id,
            reply=reply_out,
            kind=kind,
            sources=[],
            official_hotline=hotline,
            stages_executed=stages,
            zwt_sidebar_visible=True,
            zwt_form_preview=form_preview or None,
            zwt_step=step,
            zwt_track_kind=kind,
            zwt_rag_sources=_rag_dicts_to_sources(rag_sources),
        )

    if session.awaiting_zwt_consent:
        if intent.confirms_zwt_declaration_start(user_text):
            bs = zwt_store.create("zh-CN")
            msg_for_zwt = _zwt_first_turn_user_text(session.zwt_seed_hint, user_text, intent)
            store.update_session(
                session.id,
                awaiting_zwt_consent=False,
                zwt_seed_hint=None,
                active_track="zwt",
                zwt_session_id=bs.id,
            )
            store.append_turn(session.id, ChatTurn(role="user", content=body.message))
            r = zwt_engine.handle(bs, msg_for_zwt)
            bs.recent_user_lines = (getattr(bs, "recent_user_lines", None) or []) + [user_text]
            bs.recent_user_lines = bs.recent_user_lines[-8:]
            store.append_turn(session.id, ChatTurn(role="assistant", content=with_zwt_friendly_tail(r.reply)))
            return _zwt_response(
                r.reply,
                kind=r.kind,
                form_preview=r.form_preview,
                step=r.step,
                stages=["filter", "intent", "zwt"],
                rag_sources=r.rag_sources,
            )
        if intent.denies_zwt_declaration_start(user_text):
            store.update_session(session.id, awaiting_zwt_consent=False, zwt_seed_hint=None)
            store.append_turn(session.id, ChatTurn(role="user", content=body.message))
            decline_reply = "好的，已取消填报辅助。您可继续提问其他政务问题。"
            store.append_turn(session.id, ChatTurn(role="assistant", content=decline_reply))
            return _gov_response(decline_reply, "answer", [], ["filter", "intent", "zwt_consent_declined"])
        store.update_session(session.id, awaiting_zwt_consent=False, zwt_seed_hint=None)

    if session.active_track == "zwt" and session.zwt_session_id:
        bs = zwt_store.get(session.zwt_session_id)
        leave = intent.wants_leave_zwt_for_gov(user_text)
        if not bs or leave:
            store.update_session(
                session.id,
                active_track="gov",
                zwt_session_id=None,
                awaiting_zwt_consent=False,
                zwt_seed_hint=None,
                awaiting_clarification=False,
                pending_vague_text=None,
                clarification=None,
            )
        else:
            store.append_turn(session.id, ChatTurn(role="user", content=body.message))
            r = zwt_engine.handle(bs, user_text)
            bs.recent_user_lines = (getattr(bs, "recent_user_lines", None) or []) + [user_text]
            bs.recent_user_lines = bs.recent_user_lines[-8:]
            store.append_turn(session.id, ChatTurn(role="assistant", content=with_zwt_friendly_tail(r.reply)))
            return _zwt_response(
                r.reply,
                kind=r.kind,
                form_preview=r.form_preview,
                step=r.step,
                stages=["filter", "zwt"],
                rag_sources=r.rag_sources,
            )

    store.append_turn(session.id, ChatTurn(role="user", content=body.message))
    result = orchestrator.handle_message(session, user_text)
    reply_out = result.reply
    if intent.hints_zwt_declaration_topic(user_text) and result.kind != "blocked":
        reply_out = reply_out.rstrip() + ZWT_CONSENT_SUFFIX
        store.update_session(
            session.id,
            awaiting_zwt_consent=True,
            zwt_seed_hint=user_text,
        )
    store.append_turn(session.id, ChatTurn(role="assistant", content=reply_out))
    return _gov_response(
        reply_out,
        result.kind,
        result.sources,
        result.stages_executed,
    )
