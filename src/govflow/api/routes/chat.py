"""对话：PostgreSQL 检索 Top-1 事项 + 固定模板输出（不接大模型）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from psycopg_pool import ConnectionPool

from govflow.api.deps import get_pool
from govflow.config import get_settings
from govflow.models.schemas import ChatRequest, ChatResponse, ClarifyOption, SourceRef
from govflow.services.embedding_client import embed_query
from govflow.services import gov_retrieval as gr
from govflow.services.gov_types import EMBEDDING_DIM
from govflow.services.llm_ranker import rank_candidates_with_llm
from govflow.services.retrieval_policy import choose_retrieval_decision
from govflow.services.template_render import (
    render_clarify_prompt,
    render_fallback_prompt,
    render_service_answer,
)

router = APIRouter(prefix="/v1/chat", tags=["chat"])


def _build_sources(candidates: list[gr.GovServiceRow], *, limit: int) -> list[SourceRef]:
    return [
        SourceRef(
            title=svc.service_name,
            score=float(svc.match_score) if svc.match_score is not None else None,
        )
        for svc in candidates[:limit]
    ]


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
                        score=1.0,
                    )
                ],
                official_hotline=hotline,
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

        llm_candidates = candidates[: settings.llm_ranker_top_k]
        llm_rank = rank_candidates_with_llm(msg, llm_candidates, settings)
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
                return _clarify_response(
                    session_id=session_id,
                    hotline=hotline,
                    base_stages=base_stages + ["rank_llm"],
                    candidates=candidates,
                    limit=settings.retrieval_candidate_limit,
                )
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
    score = svc.match_score
    sources = [
        SourceRef(
            title=svc.service_name,
            score=float(score) if score is not None else None,
        )
    ]
    return ChatResponse(
        session_id=session_id,
        reply=reply,
        kind="answer",
        sources=sources,
        official_hotline=hotline,
        stages_executed=base_stages + llm_stage + ["load_detail", "template"],
    )
