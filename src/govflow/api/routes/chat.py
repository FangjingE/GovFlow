"""对话：PostgreSQL 检索 Top-1 事项 + 固定模板输出（不接大模型）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from psycopg_pool import ConnectionPool

from govflow.api.deps import get_pool
from govflow.config import get_settings
from govflow.models.schemas import ChatRequest, ChatResponse, SourceRef
from govflow.services.embedding_client import embed_query
from govflow.services import gov_retrieval as gr
from govflow.services.gov_types import EMBEDDING_DIM
from govflow.services.template_render import render_service_answer

router = APIRouter(prefix="/v1/chat", tags=["chat"])


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
        if use_vector:
            query_vec = body.query_vector if body.query_vector is not None else auto_vector
            svc = gr.find_top1_service_vector(
                conn,
                query_vec,  # type: ignore[arg-type]
                ivfflat_probes=settings.vector_ivfflat_probes,
            )
            stages = ["retrieve_vector", "load_detail", "template"]
        else:
            if settings.retrieval_mode == "vector":
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "当前 GOVFLOW_RETRIEVAL_MODE=vector，但后端自动向量化不可用。"
                        "请检查本地 embedding 模型配置/缓存，或在请求体提供 query_vector（768 维）。"
                    ),
                )
            svc = gr.find_top1_service_text(
                conn, msg, min_score=settings.text_match_min_score
            )
            stages = ["retrieve_text", "load_detail", "template"]

        if svc is None:
            suggestions: list[str]
            if use_vector:
                query_vec = body.query_vector if body.query_vector is not None else auto_vector
                suggestions = gr.find_topk_service_names_vector(
                    conn, query_vec, limit=3, query_text=msg  # type: ignore[arg-type]
                )
            else:
                suggestions = gr.find_topk_service_names_text(conn, msg, limit=3)

            if suggestions:
                maybe = "、".join(suggestions[:3])
                suggestion_line = f"你要查询的是否是：{maybe}？"
            else:
                suggestion_line = "你要查询的是否是：请尝试补充更具体的事项关键词？"

            reply = (
                "未在事项库中匹配到足够相关的一条政务事项。\n"
                f"{suggestion_line}\n"
                "请尝试更准确地描述，或拨打政务服务热线咨询。\n"
                f"咨询电话：{hotline}"
            )
            return ChatResponse(
                session_id=session_id,
                reply=reply,
                kind="fallback",
                sources=[],
                official_hotline=hotline,
                stages_executed=stages[:-1] + ["template_fallback"],
            )

        materials = gr.load_materials(conn, svc.id)
        processes = gr.load_processes(conn, svc.id)

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
        stages_executed=stages,
    )
