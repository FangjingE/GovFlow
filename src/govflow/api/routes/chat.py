"""对话：PostgreSQL 检索 Top-1 事项 + 固定模板输出（不接大模型）。"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from psycopg_pool import ConnectionPool

from govflow.api.deps import get_pool
from govflow.config import get_settings
from govflow.models.schemas import ChatRequest, ChatResponse, ClarifyOption, SourceRef
from govflow.services.embedding_client import embed_query
from govflow.services import gov_retrieval as gr
from govflow.services.gov_types import EMBEDDING_DIM
from govflow.services.llm_ranker import (
    extract_slots_with_llm,
    generate_soft_answer_with_llm,
    rank_candidates_with_llm,
)
from govflow.services.retrieval_policy import choose_retrieval_decision
from govflow.services.template_render import (
    render_clarify_prompt,
    render_fallback_prompt,
    render_service_answer,
)

router = APIRouter(prefix="/v1/chat", tags=["chat"])
logger = logging.getLogger(__name__)


@dataclass
class _ClarifySessionState:
    session_id: str
    candidates: list[gr.GovServiceRow]
    slots: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_CLARIFY_SESSIONS: dict[str, _ClarifySessionState] = {}
_CLARIFY_TTL = timedelta(minutes=30)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _get_clarify_state(session_id: str) -> _ClarifySessionState | None:
    st = _CLARIFY_SESSIONS.get(session_id)
    if st is None:
        return None
    if _now_utc() - st.updated_at > _CLARIFY_TTL:
        _CLARIFY_SESSIONS.pop(session_id, None)
        return None
    return st


def _save_clarify_state(
    *,
    session_id: str,
    candidates: list[gr.GovServiceRow],
    slots: dict[str, str] | None = None,
) -> None:
    _CLARIFY_SESSIONS[session_id] = _ClarifySessionState(
        session_id=session_id,
        candidates=candidates,
        slots=slots or {},
        created_at=_now_utc(),
        updated_at=_now_utc(),
    )


def _clear_clarify_state(session_id: str) -> None:
    _CLARIFY_SESSIONS.pop(session_id, None)


def _build_sources(candidates: list[gr.GovServiceRow], *, limit: int) -> list[SourceRef]:
    return [
        SourceRef(
            title=svc.service_name,
            uri=svc.source_url,
            score=float(svc.match_score) if svc.match_score is not None else None,
        )
        for svc in candidates[:limit]
    ]


def _log_topk(session_id: str, stage: str, candidates: list[gr.GovServiceRow], *, limit: int) -> None:
    show = candidates[:limit]
    if not show:
        logger.info("[chat][%s][%s] topk=EMPTY", session_id[:8], stage)
        return
    joined = " | ".join(
        f"{idx + 1}.{svc.service_name}(score={float(svc.match_score or 0.0):.4f})"
        for idx, svc in enumerate(show)
    )
    logger.info("[chat][%s][%s] topk=%s", session_id[:8], stage, joined)


def _log_llm_rank(
    session_id: str,
    stage: str,
    llm_rank: object | None,
) -> None:
    if llm_rank is None:
        logger.info("[chat][%s][%s] llm_rank=NONE", session_id[:8], stage)
        return
    best_id = getattr(llm_rank, "best_id", None)
    confidence = float(getattr(llm_rank, "confidence", 0.0) or 0.0)
    reason = str(getattr(llm_rank, "reason", "") or "")
    logger.info(
        "[chat][%s][%s] llm_rank best_id=%s confidence=%.4f reason=%s",
        session_id[:8],
        stage,
        best_id,
        confidence,
        reason,
    )


def _fallback_response(
    *,
    session_id: str,
    hotline: str,
    base_stages: list[str],
    candidates: list[gr.GovServiceRow],
    limit: int,
) -> ChatResponse:
    reply = render_fallback_prompt(
        candidates=candidates[:limit],
        hotline=hotline,
    )
    return ChatResponse(
        session_id=session_id,
        reply=reply,
        kind="fallback",
        sources=_build_sources(candidates, limit=limit),
        official_hotline=hotline,
        stages_executed=base_stages + ["template_fallback"],
    )


def _clarify_response(
    *,
    session_id: str,
    hotline: str,
    base_stages: list[str],
    candidates: list[gr.GovServiceRow],
    limit: int,
) -> ChatResponse:
    clarify_candidates = candidates[:limit]
    reply, question, option_labels = render_clarify_prompt(
        candidates=clarify_candidates,
        hotline=hotline,
    )
    clarify_options = [
        ClarifyOption(service_id=svc.id, label=label, value=svc.service_name)
        for svc, label in zip(clarify_candidates, option_labels, strict=False)
    ]
    return ChatResponse(
        session_id=session_id,
        reply=reply,
        kind="clarify",
        sources=_build_sources(clarify_candidates, limit=limit),
        official_hotline=hotline,
        clarify_question=question,
        clarify_options=clarify_options,
        stages_executed=base_stages + ["template_clarify"],
    )


@router.post("", response_model=ChatResponse)
def post_chat(body: ChatRequest, pool: ConnectionPool = Depends(get_pool)) -> ChatResponse:
    settings = get_settings()
    session_id = body.session_id or str(uuid.uuid4())
    hotline = settings.default_hotline
    msg = body.message.strip()
    clarify_state = _get_clarify_state(session_id)

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
            return ChatResponse(
                session_id=session_id,
                reply=reply,
                kind="answer",
                sources=[
                    SourceRef(
                        title=exact_service.service_name,
                        uri=exact_service.source_url,
                        score=1.0,
                    )
                ],
                official_hotline=hotline,
                stages_executed=["retrieve_exact_name", "load_detail", "template"],
            )
        if clarify_state is not None:
            llm_candidates = clarify_state.candidates[: settings.llm_ranker_top_k]
            _log_topk(session_id, "clarify_resume_candidates", llm_candidates, limit=len(llm_candidates))
            slot_extract = extract_slots_with_llm(
                msg,
                llm_candidates,
                existing_slots=clarify_state.slots,
                settings=settings,
            )
            if slot_extract is not None and slot_extract.slots:
                clarify_state.slots.update(slot_extract.slots)
                clarify_state.updated_at = _now_utc()
            rank_query = msg
            if clarify_state.slots:
                rank_query = f"{msg}\n已知条件: " + "；".join(
                    f"{k}={v}" for k, v in clarify_state.slots.items()
                )
            llm_rank = rank_candidates_with_llm(rank_query, llm_candidates, settings)
            _log_llm_rank(session_id, "clarify_resume_rank", llm_rank)
            if llm_rank is not None:
                valid_ids = {svc.id for svc in llm_candidates}
                if (
                    llm_rank.best_id is not None
                    and llm_rank.best_id in valid_ids
                    and llm_rank.confidence >= settings.llm_ranker_answer_threshold
                ):
                    selected = next((svc for svc in llm_candidates if svc.id == llm_rank.best_id), None)
                    if selected is not None:
                        materials = gr.load_materials(conn, selected.id)
                        processes = gr.load_processes(conn, selected.id)
                        soft = generate_soft_answer_with_llm(
                            msg,
                            llm_candidates,
                            confidence=llm_rank.confidence,
                            mode="answer",
                            settings=settings,
                        )
                        _clear_clarify_state(session_id)
                        if soft is not None:
                            picked = [
                                row for row in llm_candidates if row.id in set(soft.cited_ids) & valid_ids
                            ]
                            source_rows = picked or [selected]
                            return ChatResponse(
                                session_id=session_id,
                                reply=soft.answer,
                                kind="answer",
                                sources=_build_sources(
                                    source_rows, limit=settings.retrieval_candidate_limit
                                ),
                                official_hotline=hotline,
                                stages_executed=["clarify_resume", "rank_llm", "load_detail", "llm_soft_template"],
                            )
                        reply = render_service_answer(
                            service=selected, materials=materials, processes=processes, query=msg
                        )
                        return ChatResponse(
                            session_id=session_id,
                            reply=reply,
                            kind="answer",
                            sources=_build_sources([selected], limit=1),
                            official_hotline=hotline,
                            stages_executed=["clarify_resume", "rank_llm", "load_detail", "template"],
                        )
                if llm_rank.confidence >= settings.llm_ranker_clarify_threshold:
                    soft = generate_soft_answer_with_llm(
                        msg,
                        llm_candidates,
                        confidence=llm_rank.confidence,
                        mode="clarify",
                        settings=settings,
                    )
                    if soft is not None:
                        return ChatResponse(
                            session_id=session_id,
                            reply=soft.answer,
                            kind="clarify",
                            sources=_build_sources(
                                llm_candidates, limit=settings.retrieval_candidate_limit
                            ),
                            official_hotline=hotline,
                            clarify_question=soft.follow_up_question
                            or "请补充一个最关键的信息，我就能为你确认具体事项。",
                            clarify_options=[],
                            stages_executed=["clarify_resume", "rank_llm", "llm_soft_clarify"],
                        )
                _clear_clarify_state(session_id)

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
            base_stages = ["retrieve_vector"]
        else:
            if settings.retrieval_mode == "vector":
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "当前 GOVFLOW_RETRIEVAL_MODE=vector，但后端自动向量化不可用。"
                        "请检查本地 embedding 模型配置/缓存，或在请求体提供 query_vector（768 维）。"
                    ),
                )
            candidates = gr.find_topk_services_text(
                conn,
                msg,
                limit=max(settings.retrieval_candidate_limit, settings.llm_ranker_top_k),
            )
            base_stages = ["retrieve_text"]
        _log_topk(session_id, base_stages[0], candidates, limit=min(len(candidates), settings.llm_ranker_top_k))

        llm_candidates = candidates[: settings.llm_ranker_top_k]
        llm_rank = rank_candidates_with_llm(msg, llm_candidates, settings)
        _log_llm_rank(session_id, "rank_llm", llm_rank)
        if llm_rank is not None:
            valid_ids = {svc.id for svc in llm_candidates}
            if llm_rank.best_id is None or llm_rank.best_id not in valid_ids:
                return _fallback_response(
                    session_id=session_id,
                    hotline=hotline,
                    base_stages=base_stages + ["rank_llm"],
                    candidates=candidates,
                    limit=settings.retrieval_candidate_limit,
                )
            if llm_rank.confidence < settings.llm_ranker_clarify_threshold:
                return _fallback_response(
                    session_id=session_id,
                    hotline=hotline,
                    base_stages=base_stages + ["rank_llm"],
                    candidates=candidates,
                    limit=settings.retrieval_candidate_limit,
                )
            if llm_rank.confidence < settings.llm_ranker_answer_threshold:
                soft = generate_soft_answer_with_llm(
                    msg,
                    llm_candidates,
                    confidence=llm_rank.confidence,
                    mode="clarify",
                    settings=settings,
                )
                if soft is not None:
                    valid_ids = {svc.id for svc in llm_candidates}
                    picked = [svc for svc in llm_candidates if svc.id in set(soft.cited_ids) & valid_ids]
                    source_rows = picked or candidates[: settings.retrieval_candidate_limit]
                    _save_clarify_state(
                        session_id=session_id,
                        candidates=llm_candidates,
                        slots={},
                    )
                    return ChatResponse(
                        session_id=session_id,
                        reply=soft.answer,
                        kind="clarify",
                        sources=_build_sources(source_rows, limit=settings.retrieval_candidate_limit),
                        official_hotline=hotline,
                        clarify_question=soft.follow_up_question or "请补充更具体的办理场景（对象、部门或关键条件）。",
                        clarify_options=[],
                        stages_executed=base_stages + ["rank_llm", "llm_soft_clarify"],
                    )
                return _clarify_response(
                    session_id=session_id,
                    hotline=hotline,
                    base_stages=base_stages + ["rank_llm"],
                    candidates=candidates,
                    limit=settings.retrieval_candidate_limit,
                )
            _clear_clarify_state(session_id)
            selected = next((svc for svc in llm_candidates if svc.id == llm_rank.best_id), None)
            if selected is None:
                return _fallback_response(
                    session_id=session_id,
                    hotline=hotline,
                    base_stages=base_stages + ["rank_llm"],
                    candidates=candidates,
                    limit=settings.retrieval_candidate_limit,
                )
            materials = gr.load_materials(conn, selected.id)
            processes = gr.load_processes(conn, selected.id)
            svc = selected
            llm_stage = ["rank_llm"]
        else:
            decision = choose_retrieval_decision(
                candidates,
                fallback_min_score=(
                    settings.vector_fallback_min_score if use_vector else settings.text_match_min_score
                ),
                answer_min_score=(
                    settings.vector_answer_min_score if use_vector else settings.text_match_min_score
                ),
                clarify_min_score_gap=settings.retrieval_clarify_min_score_gap,
            )
            if decision.kind == "fallback":
                return _fallback_response(
                    session_id=session_id,
                    hotline=hotline,
                    base_stages=base_stages,
                    candidates=candidates,
                    limit=settings.retrieval_candidate_limit,
                )
            if decision.kind == "clarify":
                return _clarify_response(
                    session_id=session_id,
                    hotline=hotline,
                    base_stages=base_stages,
                    candidates=candidates,
                    limit=settings.retrieval_candidate_limit,
                )
            svc = decision.top_candidate
            if svc is None:
                raise HTTPException(status_code=500, detail="检索判定异常：缺少命中事项")
            materials = gr.load_materials(conn, svc.id)
            processes = gr.load_processes(conn, svc.id)
            llm_stage = []

        if svc is None:
            raise HTTPException(status_code=500, detail="检索判定异常：缺少命中事项")

    reply = render_service_answer(
        service=svc, materials=materials, processes=processes, query=msg
    )
    stages = base_stages + llm_stage + ["load_detail", "template"]
    if llm_stage:
        soft = generate_soft_answer_with_llm(
            msg,
            llm_candidates,
            confidence=1.0,
            mode="answer",
            settings=settings,
        )
        if soft is not None:
            valid_ids = {svc.id for svc in llm_candidates}
            picked = [row for row in llm_candidates if row.id in set(soft.cited_ids) & valid_ids]
            source_rows = picked or [svc]
            return ChatResponse(
                session_id=session_id,
                reply=soft.answer,
                kind="answer",
                sources=_build_sources(source_rows, limit=settings.retrieval_candidate_limit),
                official_hotline=hotline,
                stages_executed=base_stages + llm_stage + ["load_detail", "llm_soft_template"],
            )
    score = svc.match_score
    sources = [
        SourceRef(
            title=svc.service_name,
            uri=svc.source_url,
            score=float(score) if score is not None else None,
        )
    ]
    return ChatResponse(
        session_id=session_id,
        reply=reply,
        kind="answer",
        sources=sources,
        official_hotline=hotline,
        stages_executed=stages,
    )
