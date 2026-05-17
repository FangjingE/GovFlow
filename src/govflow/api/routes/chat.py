"""对话与工具路由。"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from psycopg_pool import ConnectionPool

from govflow.api.deps import get_pool
from govflow.config import get_settings
from govflow.models.schemas import (
    ChatRequest,
    ChatResponse,
    ClarifyOption,
    GetServiceDetailRequest,
    GetServiceDetailResponse,
    SearchServicesRequest,
    SearchServicesResponse,
    ServiceBasicDetail,
    ServiceCandidate,
    ServiceMaterialDetail,
    ServiceProcessDetail,
    SourceRef,
)
from govflow.services.embedding_client import embed_query
from govflow.services import gov_retrieval as gr
from govflow.services.gov_types import EMBEDDING_DIM
from govflow.services.llm_ranker import (
    assess_user_intent_with_llm,
    decide_dialog_with_llm,
    explain_fallback_with_llm,
    generate_service_answer_with_llm,
    get_last_llm_decide_error,
    rank_candidates_with_llm,
    plan_next_step_with_llm,
)
from govflow.services.retrieval_policy import choose_retrieval_decision
from govflow.services.template_render import render_clarify_prompt, render_service_answer

router = APIRouter(prefix="/v1/chat", tags=["chat"])
tools_router = APIRouter(prefix="/v1/tools", tags=["tools"])
logger = logging.getLogger(__name__)


@dataclass
class _ConversationSessionState:
    session_id: str
    state: str = "init"
    retry_count: int = 0
    original_query: str = ""
    last_user_message: str = ""
    last_assessment: str = ""
    last_rewritten_query: str = ""
    last_clarify_question: str = ""
    last_reply: str = ""
    last_reason: str = ""
    last_candidates: list[gr.GovServiceRow] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_SESSION_STORE: dict[str, _ConversationSessionState] = {}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _session_ttl() -> timedelta:
    settings = get_settings()
    return timedelta(minutes=getattr(settings, "conversation_session_ttl_minutes", 30))


def _expired(session: _ConversationSessionState) -> bool:
    return _now_utc() - session.updated_at > _session_ttl()


def _open_session(session_id: str | None, *, user_message: str) -> _ConversationSessionState:
    sid = session_id or str(uuid.uuid4())
    existing = _SESSION_STORE.get(sid)
    if existing is None or _expired(existing) or existing.state in {"answer", "fallback"}:
        existing = _ConversationSessionState(session_id=sid)
        _SESSION_STORE[sid] = existing
    if not existing.original_query:
        existing.original_query = user_message
    existing.last_user_message = user_message
    existing.updated_at = _now_utc()
    return existing


def _touch(session: _ConversationSessionState) -> None:
    session.updated_at = _now_utc()


def _log_session_transition(session: _ConversationSessionState, old_state: str, new_state: str, *, reason: str) -> None:
    if old_state == new_state:
        logger.info(
            "[session][%s] state=%s retry=%d reason=%s",
            session.session_id[:8],
            new_state,
            session.retry_count,
            reason,
        )
        return
    logger.info(
        "[session][%s] state %s -> %s retry=%d reason=%s",
        session.session_id[:8],
        old_state,
        new_state,
        session.retry_count,
        reason,
    )


def _log_session_snapshot(session: _ConversationSessionState, *, stage: str) -> None:
    logger.info(
        "[session][%s][%s] state=%s retry=%d original=%s last_query=%s last_reason=%s",
        session.session_id[:8],
        stage,
        session.state,
        session.retry_count,
        session.original_query,
        session.last_user_message,
        session.last_reason,
    )


def _set_session_state(session: _ConversationSessionState, new_state: str, *, reason: str) -> None:
    old_state = session.state
    session.state = new_state
    _log_session_transition(session, old_state, new_state, reason=reason)


def _build_sources(candidates: list[gr.GovServiceRow], *, limit: int) -> list[SourceRef]:
    return [
        SourceRef(
            title=svc.service_name,
            uri=svc.source_url,
            score=float(svc.match_score) if svc.match_score is not None else None,
        )
        for svc in candidates[:limit]
    ]


def _candidate_from_service(svc: gr.GovServiceRow) -> ServiceCandidate:
    return ServiceCandidate(
        id=svc.id,
        service_name=svc.service_name,
        department=svc.department,
        service_object=svc.service_object,
        accept_condition=svc.accept_condition,
        handle_form=svc.handle_form,
        item_type=svc.item_type,
        source_url=svc.source_url,
        match_score=float(svc.match_score) if svc.match_score is not None else None,
        keyword_hits=svc.keyword_hits,
    )


def _basic_detail_from_service(svc: gr.GovServiceRow) -> ServiceBasicDetail:
    return ServiceBasicDetail(
        id=svc.id,
        service_name=svc.service_name,
        source_url=svc.source_url,
        department=svc.department,
        service_object=svc.service_object,
        promise_days=svc.promise_days,
        legal_days=svc.legal_days,
        on_site_times=svc.on_site_times,
        is_charge=svc.is_charge,
        accept_condition=svc.accept_condition,
        general_scope=svc.general_scope,
        handle_form=svc.handle_form,
        item_type=svc.item_type,
        handle_address=svc.handle_address,
        handle_time=svc.handle_time,
        consult_way=svc.consult_way,
        complaint_way=svc.complaint_way,
        query_way=svc.query_way,
    )


def _material_detail_from_row(row: gr.MaterialRow) -> ServiceMaterialDetail:
    return ServiceMaterialDetail(
        material_name=row.material_name,
        is_required=row.is_required,
        material_form=row.material_form,
        original_num=row.original_num,
        copy_num=row.copy_num,
        note=row.note,
    )


def _process_detail_from_row(row: gr.ProcessRow) -> ServiceProcessDetail:
    return ServiceProcessDetail(
        step_name=row.step_name,
        step_desc=row.step_desc,
        sort=row.sort,
    )


def _session_summary(session: _ConversationSessionState) -> str:
    parts: list[str] = []
    if session.original_query:
        parts.append(f"原始问题：{session.original_query}")
    if session.last_clarify_question:
        parts.append(f"最近追问：{session.last_clarify_question}")
    if session.last_rewritten_query:
        parts.append(f"最近改写：{session.last_rewritten_query}")
    if session.last_assessment:
        parts.append(f"最近判断：{session.last_assessment}")
    if session.last_reason:
        parts.append(f"最近原因：{session.last_reason}")
    return " | ".join(parts)


def _plain_clarify_reply(message: str) -> str:
    return f"我还不够确定你要咨询的具体事项。请补充事项名称、办理对象或办理阶段：{message}"


def _plain_fallback_reply(reason: str, hotline: str) -> str:
    return f"暂时无法准确确认事项，原因：{reason}\n建议拨打政务服务热线咨询：{hotline}"


def _plain_answer_reply(
    *,
    service: gr.GovServiceRow,
    materials: list[gr.MaterialRow],
    processes: list[gr.ProcessRow],
    query: str,
) -> str:
    lines = [
        f"事项名称：{service.service_name}",
        f"办理部门：{service.department or '—'}",
        f"办理地点：{service.handle_address or '—'}",
        f"办理方式：{service.handle_form or '—'}",
        f"办理时间：{service.handle_time or '—'}",
        f"咨询方式：{service.consult_way or '—'}",
        f"监督投诉方式：{service.complaint_way or '—'}",
        f"原网址：{service.source_url or '—'}",
        f"申请材料：{', '.join(m.material_name for m in materials if m.material_name) or '—'}",
        f"办理流程：{', '.join(p.step_name for p in processes if p.step_name) or '—'}",
        f"用户问题：{query}",
    ]
    return "\n".join(lines)


def _load_service_detail(conn: object, service_id: int) -> tuple[gr.GovServiceRow, list[gr.MaterialRow], list[gr.ProcessRow]]:
    service = gr.find_service_by_id(conn, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="事项不存在或已下线")
    materials = gr.load_materials(conn, service.id)
    processes = gr.load_processes(conn, service.id)
    return service, materials, processes


def _select_candidate(
    candidates: list[gr.GovServiceRow],
    *,
    best_id: int | None,
    cited_ids: list[int],
) -> gr.GovServiceRow | None:
    valid = {svc.id for svc in candidates}
    if best_id in valid:
        return next((svc for svc in candidates if svc.id == best_id), None)
    for cid in cited_ids:
        if cid in valid:
            return next((svc for svc in candidates if svc.id == cid), None)
    return candidates[0] if candidates else None


def _retrieve_candidates(
    conn: object,
    query: str,
    *,
    settings,
    query_vector: list[float] | None = None,
    limit: int = 10,
) -> tuple[list[gr.GovServiceRow], str]:
    vec = query_vector or embed_query(query, settings)
    if vec is not None:
        return (
            gr.find_topk_services_vector(
                conn,
                vec,
                limit=limit,
                query_text=query,
                ivfflat_probes=settings.vector_ivfflat_probes,
                keyword_ranking_enabled=settings.retrieval_keyword_ranking_enabled,
            ),
            "vector",
        )
    return gr.find_topk_services_text(conn, query, limit=limit), "text"


def _make_response(
    *,
    session: _ConversationSessionState,
    reply: str,
    kind: str,
    hotline: str,
    sources: list[SourceRef] | None = None,
    clarify_question: str | None = None,
    clarify_options: list[ClarifyOption] | None = None,
    stages_executed: list[str] | None = None,
) -> ChatResponse:
    return ChatResponse(
        session_id=session.session_id,
        reply=reply,
        kind=kind,
        session_state=session.state,
        retry_count=session.retry_count,
        sources=sources or [],
        official_hotline=hotline,
        clarify_question=clarify_question,
        clarify_options=clarify_options or [],
        stages_executed=stages_executed or [],
    )


def _reactive_chat(body: ChatRequest, pool: ConnectionPool, settings) -> ChatResponse:
    hotline = settings.default_hotline
    msg = body.message.strip()
    session = _open_session(body.session_id, user_message=msg)
    session.last_reply = ""
    session.last_reason = ""
    session.last_assessment = ""
    _touch(session)
    logger.info(
        "[session][%s] open state=%s retry=%d msg=%s",
        session.session_id[:8],
        session.state,
        session.retry_count,
        msg,
    )

    with pool.connection() as conn:
        summary = _session_summary(session)
        stages: list[str] = ["assess_intent"]
        _log_session_snapshot(session, stage="before_assess")

        assessment = assess_user_intent_with_llm(
            msg,
            settings=settings,
            session_summary=summary,
        )
        if assessment is None:
            _set_session_state(session, "clarify", reason="intent_assessment_unavailable")
            session.last_clarify_question = _plain_clarify_reply(msg)
            session.last_reason = "LLM 意图判断不可用"
            _touch(session)
            logger.info(
                "[llm][%s][intent] unavailable fallback_clarify reply=%s",
                session.session_id[:8],
                session.last_clarify_question,
            )
            return _make_response(
                session=session,
                reply=session.last_clarify_question,
                kind="clarify",
                hotline=hotline,
                clarify_question=session.last_clarify_question,
                stages_executed=stages + ["intent_unavailable"],
            )

        session.last_assessment = assessment.reason or ("清楚" if assessment.is_clear else "不清楚")
        logger.info(
            "[llm][%s][intent] clear=%s rewritten=%s missing=%s reason=%s reply=%s",
            session.session_id[:8],
            assessment.is_clear,
            assessment.rewritten_query,
            assessment.missing_info,
            assessment.reason,
            assessment.reply,
        )
        if not assessment.is_clear:
            _set_session_state(session, "clarify", reason="intent_not_clear")
            session.last_clarify_question = assessment.reply or _plain_clarify_reply(msg)
            session.last_reason = assessment.reason or "用户输入不够明确"
            _touch(session)
            return _make_response(
                session=session,
                reply=session.last_clarify_question,
                kind="clarify",
                hotline=hotline,
                clarify_question=session.last_clarify_question,
                stages_executed=stages + ["llm_clarify"],
            )

        search_query = assessment.rewritten_query or msg
        retry_count = session.retry_count
        max_retries = getattr(settings, "conversation_max_retries", 3)

        for attempt in range(max_retries + 1):
            logger.info(
                "[session][%s] attempt=%d retry=%d query=%s",
                session.session_id[:8],
                attempt,
                retry_count,
                search_query,
            )
            candidates, search_mode = _retrieve_candidates(
                conn,
                search_query,
                settings=settings,
                limit=max(settings.retrieval_candidate_limit, settings.llm_ranker_top_k),
            )
            session.last_candidates = candidates
            session.last_rewritten_query = search_query
            stages.append(f"retrieve_{search_mode}")
            logger.info(
                "[retrieve][%s] mode=%s candidates=%d top=%s",
                session.session_id[:8],
                search_mode,
                len(candidates),
                ",".join(f"{svc.id}:{svc.service_name}" for svc in candidates[: settings.retrieval_candidate_limit]),
            )

            plan = plan_next_step_with_llm(
                search_query,
                candidates[: settings.llm_ranker_top_k],
                settings=settings,
                session_summary=_session_summary(session),
                retry_count=retry_count,
            )
            if plan is None:
                reason = get_last_llm_decide_error() or "LLM 决策不可用"
                _set_session_state(session, "fallback", reason="plan_unavailable")
                session.last_reason = reason
                reply = explain_fallback_with_llm(
                    search_query,
                    f"{reason}，无法继续判断候选事项是否足够回答用户问题。请明确给出 fallback 原因。",
                    hotline=hotline,
                    settings=settings,
                ) or _plain_fallback_reply(reason, hotline)
                session.last_reply = reply
                _touch(session)
                logger.info(
                    "[llm][%s][plan] unavailable reason=%s reply=%s",
                    session.session_id[:8],
                    reason,
                    reply,
                )
                return _make_response(
                    session=session,
                    reply=reply,
                    kind="fallback",
                    hotline=hotline,
                    sources=_build_sources(candidates, limit=settings.retrieval_candidate_limit),
                    stages_executed=stages + ["llm_plan_unavailable"],
                )

            stages.append("llm_plan")
            session.last_reason = plan.reason or session.last_reason
            logger.info(
                "[llm][%s][plan] action=%s best_id=%s rewritten=%s cited=%s reason=%s reply=%s",
                session.session_id[:8],
                plan.action,
                plan.best_id,
                plan.rewritten_query,
                plan.cited_ids,
                plan.reason,
                plan.reply,
            )

            if plan.action == "answer":
                selected = _select_candidate(
                    candidates,
                    best_id=plan.best_id,
                    cited_ids=plan.cited_ids,
                )
                if selected is None:
                    session.last_reason = "LLM 选中了不存在的候选项"
                    _set_session_state(session, "fallback", reason="invalid_answer_choice")
                    reply = explain_fallback_with_llm(
                        search_query,
                        "LLM 选择的候选项不在当前备选中，无法安全作答。请明确给出 fallback 原因。",
                        hotline=hotline,
                        settings=settings,
                    ) or _plain_fallback_reply("LLM 选择的候选项无效", hotline)
                    session.state = "fallback"
                    session.last_reply = reply
                    _touch(session)
                    return _make_response(
                        session=session,
                        reply=reply,
                        kind="fallback",
                        hotline=hotline,
                        sources=_build_sources(candidates, limit=settings.retrieval_candidate_limit),
                        stages_executed=stages + ["invalid_answer_choice"],
                    )

                service, materials, processes = _load_service_detail(conn, selected.id)
                answer = generate_service_answer_with_llm(
                    search_query,
                    service,
                    materials,
                    processes,
                    settings=settings,
                ) or _plain_answer_reply(
                    service=service,
                    materials=materials,
                    processes=processes,
                        query=search_query,
                    )
                _set_session_state(session, "answer", reason="answer_selected")
                session.retry_count = retry_count
                session.last_reply = answer
                _touch(session)
                return _make_response(
                    session=session,
                    reply=answer,
                    kind="answer",
                    hotline=hotline,
                    sources=_build_sources([selected], limit=1),
                    stages_executed=stages + ["load_detail", "llm_answer"],
                )

            if plan.action == "clarify":
                _set_session_state(session, "clarify", reason="plan_clarify")
                session.last_clarify_question = plan.reply or _plain_clarify_reply(search_query)
                session.last_reply = session.last_clarify_question
                session.retry_count = retry_count
                _touch(session)
                return _make_response(
                    session=session,
                    reply=session.last_clarify_question,
                    kind="clarify",
                    hotline=hotline,
                    sources=_build_sources(candidates, limit=settings.retrieval_candidate_limit),
                    clarify_question=session.last_clarify_question,
                    stages_executed=stages + ["llm_clarify"],
                )

            if plan.action == "retry_search":
                if retry_count >= max_retries:
                    logger.info(
                        "[session][%s] retry_limit_reached retry=%d max=%d",
                        session.session_id[:8],
                        retry_count,
                        max_retries,
                    )
                    break
                search_query = plan.rewritten_query or search_query
                retry_count += 1
                session.retry_count = retry_count
                stages.append("rewrite_query")
                _set_session_state(session, "init", reason="plan_retry_search")
                continue

            if plan.action == "fallback":
                _set_session_state(session, "fallback", reason="plan_fallback")
                break

        reason = session.last_reason or "多次重试后仍无法确认具体事项"
        reply = explain_fallback_with_llm(
            search_query,
            f"{reason}。请明确给出 fallback 原因。",
            hotline=hotline,
            settings=settings,
        ) or _plain_fallback_reply(reason, hotline)
        _set_session_state(session, "fallback", reason="exhausted_retry")
        session.last_reply = reply
        _touch(session)
        logger.info(
            "[llm][%s][fallback] reason=%s reply=%s",
            session.session_id[:8],
            reason,
            reply,
        )
        return _make_response(
            session=session,
            reply=reply,
            kind="fallback",
            hotline=hotline,
            sources=_build_sources(session.last_candidates, limit=settings.retrieval_candidate_limit),
            stages_executed=stages + ["llm_fallback"],
        )


def _legacy_chat(body: ChatRequest, pool: ConnectionPool, settings) -> ChatResponse:
    hotline = settings.default_hotline
    msg = body.message.strip()
    session = _open_session(body.session_id, user_message=msg)
    session.last_reply = ""
    _touch(session)

    use_vector = body.query_vector is not None and len(body.query_vector) == EMBEDDING_DIM
    if body.query_vector is not None and not use_vector:
        raise HTTPException(
            status_code=400,
            detail=f"若提供 query_vector，其长度必须为 {EMBEDDING_DIM}",
        )

    auto_vector: list[float] | None = None
    if not use_vector:
        auto_vector = embed_query(msg, settings)
        if auto_vector is not None:
            use_vector = True

    with pool.connection() as conn:
        exact_service = gr.find_service_by_exact_name(conn, msg)
        if exact_service is not None:
            materials = gr.load_materials(conn, exact_service.id)
            processes = gr.load_processes(conn, exact_service.id)
            reply = render_service_answer(
                service=exact_service,
                materials=materials,
                processes=processes,
                query=msg,
            )
            session.state = "answer"
            session.last_reply = reply
            _touch(session)
            return _make_response(
                session=session,
                reply=reply,
                kind="answer",
                hotline=hotline,
                sources=[SourceRef(title=exact_service.service_name, uri=exact_service.source_url, score=1.0)],
                stages_executed=["retrieve_exact_name", "load_detail", "template"],
            )

        if use_vector:
            query_vec = body.query_vector if body.query_vector is not None else auto_vector
            candidates = gr.find_topk_services_vector(
                conn,
                query_vec,  # type: ignore[arg-type]
                limit=max(settings.retrieval_candidate_limit, settings.llm_ranker_top_k),
                query_text=msg,
                ivfflat_probes=settings.vector_ivfflat_probes,
                keyword_ranking_enabled=settings.retrieval_keyword_ranking_enabled,
            )
            search_mode = "vector"
        else:
            candidates = gr.find_topk_services_text(
                conn,
                msg,
                limit=max(settings.retrieval_candidate_limit, settings.llm_ranker_top_k),
            )
            search_mode = "text"

        decision = choose_retrieval_decision(
            candidates,
            fallback_min_score=(
                settings.vector_fallback_min_score if search_mode == "vector" else settings.text_match_min_score
            ),
            answer_min_score=(
                settings.vector_answer_min_score if search_mode == "vector" else settings.text_match_min_score
            ),
            clarify_min_score_gap=settings.retrieval_clarify_min_score_gap,
        )
        if decision.kind == "answer" and decision.top_candidate is not None:
            svc = decision.top_candidate
            materials = gr.load_materials(conn, svc.id)
            processes = gr.load_processes(conn, svc.id)
            reply = render_service_answer(service=svc, materials=materials, processes=processes, query=msg)
            session.state = "answer"
            session.last_reply = reply
            _touch(session)
            return _make_response(
                session=session,
                reply=reply,
                kind="answer",
                hotline=hotline,
                sources=[SourceRef(title=svc.service_name, uri=svc.source_url, score=float(svc.match_score or 0.0))],
                stages_executed=[f"retrieve_{search_mode}", "load_detail", "template"],
            )
        if decision.kind == "clarify":
            reply, question, option_labels = render_clarify_prompt(
                candidates=candidates[: settings.retrieval_candidate_limit],
                hotline=hotline,
            )
            session.state = "clarify"
            session.last_clarify_question = question
            session.last_reply = reply
            _touch(session)
            return _make_response(
                session=session,
                reply=reply,
                kind="clarify",
                hotline=hotline,
                sources=_build_sources(candidates, limit=settings.retrieval_candidate_limit),
                clarify_question=question,
                clarify_options=[
                    ClarifyOption(service_id=svc.id, label=label, value=svc.service_name)
                    for svc, label in zip(
                        candidates[: settings.retrieval_candidate_limit],
                        option_labels,
                        strict=False,
                    )
                ],
                stages_executed=[f"retrieve_{search_mode}", "plain_clarify"],
            )

        reason = f"LLM 决策不可用（{get_last_llm_decide_error() or 'legacy decision'}），且检索结果相关性不足"
        reply = _plain_fallback_reply(reason, hotline)
        session.state = "fallback"
        session.last_reason = reason
        session.last_reply = reply
        _touch(session)
        return _make_response(
            session=session,
            reply=reply,
            kind="fallback",
            hotline=hotline,
            sources=_build_sources(candidates, limit=settings.retrieval_candidate_limit),
            stages_executed=[f"retrieve_{search_mode}", "plain_fallback"],
        )


@router.post("", response_model=ChatResponse)
def post_chat(body: ChatRequest, pool: ConnectionPool = Depends(get_pool)) -> ChatResponse:
    settings = get_settings()
    if settings.llm_ranker_enabled:
        return _reactive_chat(body, pool, settings)
    return _legacy_chat(body, pool, settings)


@tools_router.post("/search-services", response_model=SearchServicesResponse)
def search_services(
    body: SearchServicesRequest,
    pool: ConnectionPool = Depends(get_pool),
) -> SearchServicesResponse:
    settings = get_settings()
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")

    use_vector = body.query_vector is not None and len(body.query_vector) == EMBEDDING_DIM
    if body.query_vector is not None and not use_vector:
        raise HTTPException(
            status_code=400,
            detail=f"若提供 query_vector，其长度必须为 {EMBEDDING_DIM}",
        )

    auto_vector: list[float] | None = None
    if not use_vector:
        auto_vector = embed_query(query, settings)
        if auto_vector is not None:
            use_vector = True

    with pool.connection() as conn:
        exact_service = gr.find_service_by_exact_name(conn, query)
        if exact_service is not None:
            return SearchServicesResponse(
                query=query,
                search_mode="exact",
                suggested_action="answer",
                exact_match_hit=True,
                used_supplied_query_vector=body.query_vector is not None,
                candidates=[_candidate_from_service(exact_service)],
                clarify_hint=None,
                stages_executed=["retrieve_exact_name"],
            )

        if use_vector:
            query_vec = body.query_vector if body.query_vector is not None else auto_vector
            if query_vec is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "当前检索模式需要向量，但自动向量化不可用。"
                        "请检查本地 embedding 模型配置/缓存，或提供 query_vector（768 维）。"
                    ),
                )
            candidates = gr.find_topk_services_vector(
                conn,
                query_vec,
                limit=body.top_k,
                query_text=query,
                ivfflat_probes=settings.vector_ivfflat_probes,
                keyword_ranking_enabled=settings.retrieval_keyword_ranking_enabled,
            )
            search_mode: gr.RetrievalMode = "vector"
        else:
            candidates = gr.find_topk_services_text(conn, query, limit=body.top_k)
            search_mode = "text"

    decision = choose_retrieval_decision(
        candidates,
        fallback_min_score=(
            settings.vector_fallback_min_score if search_mode == "vector" else settings.text_match_min_score
        ),
        answer_min_score=(
            settings.vector_answer_min_score if search_mode == "vector" else settings.text_match_min_score
        ),
        clarify_min_score_gap=settings.retrieval_clarify_min_score_gap,
    )
    if decision.kind == "answer":
        action: str = "answer"
        hint = None
    elif decision.kind == "clarify":
        action = "clarify"
        hint = "我找到了几条相近的事项，还不能确认你要办理的是哪一项。请补充更具体的事项名称或办理阶段。"
    else:
        action = "fallback"
        hint = "建议补充更准确的事项关键词，或切换更具体的办理阶段/对象/部门。"

    return SearchServicesResponse(
        query=query,
        search_mode=search_mode,
        suggested_action=action,  # type: ignore[arg-type]
        exact_match_hit=False,
        used_supplied_query_vector=body.query_vector is not None,
        clarify_hint=hint,
        candidates=[_candidate_from_service(svc) for svc in candidates[:body.top_k]],
        stages_executed=[f"retrieve_{search_mode}", "decide_retrieval"],
    )


@tools_router.post("/service-detail", response_model=GetServiceDetailResponse)
def get_service_detail(
    body: GetServiceDetailRequest,
    pool: ConnectionPool = Depends(get_pool),
) -> GetServiceDetailResponse:
    include = list(dict.fromkeys(body.include))
    if not include:
        include = ["basic", "materials", "processes"]

    with pool.connection() as conn:
        service = gr.find_service_by_id(conn, body.service_id)
        if service is None:
            raise HTTPException(status_code=404, detail="事项不存在或已下线")
        materials = gr.load_materials(conn, service.id) if "materials" in include else []
        processes = gr.load_processes(conn, service.id) if "processes" in include else []

    return GetServiceDetailResponse(
        service_id=service.id,
        included_sections=include,
        basic=_basic_detail_from_service(service) if "basic" in include else None,
        materials=[_material_detail_from_row(m) for m in materials],
        processes=[_process_detail_from_row(p) for p in processes],
        stages_executed=[
            "load_basic",
            *(["load_materials"] if "materials" in include else []),
            *(["load_processes"] if "processes" in include else []),
        ],
    )
