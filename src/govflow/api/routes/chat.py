"""对话 HTTP 接口（P0）。"""

from fastapi import APIRouter, Depends, HTTPException

from govflow.api.deps import get_orchestrator
from govflow.domain.messages import ChatTurn
from govflow.models.schemas import ChatRequest, ChatResponse, SourceRef
from govflow.services.pipeline.orchestrator import ChatOrchestrator

router = APIRouter(prefix="/v1/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def post_chat(
    body: ChatRequest,
    orchestrator: ChatOrchestrator = Depends(get_orchestrator),
) -> ChatResponse:
    store = orchestrator.sessions
    if body.session_id:
        session = store.get(body.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="session not found")
    else:
        session = store.create()

    store.append_turn(session.id, ChatTurn(role="user", content=body.message))
    result = orchestrator.handle_message(session, body.message)
    store.append_turn(session.id, ChatTurn(role="assistant", content=result.reply))

    return ChatResponse(
        session_id=session.id,
        reply=result.reply,
        kind=result.kind,
        sources=[SourceRef(**s) for s in result.sources],
        official_hotline=result.official_hotline,
        stages_executed=result.stages_executed,
    )
