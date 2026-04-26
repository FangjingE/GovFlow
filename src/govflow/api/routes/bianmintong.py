"""边民通：对话式互市申报（/v1/bmt）。"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException

from govflow.api.deps import get_bmt_engine
from govflow.bianmintong.domain import BMTSession, DeclarationForm
from govflow.bianmintong.engine import BMTDeclarationEngine, BMTResult, form_preview
from govflow.bianmintong.store import BMTSessionStore
from govflow.models.bmt_schemas import BmtTurnRequest, BmtTurnResponse

router = APIRouter(prefix="/v1/bmt", tags=["边民通"])

# 统一附在助手回复末尾（原右侧「字段说明」区已下线）
_BMT_FRIENDLY_TAIL = "\n\n如有不明白的，可以直接问我。"


def _with_friendly_tail(text: str) -> str:
    t = (text or "").rstrip()
    if not t:
        return t
    if "可以直接问我" in t:
        return t
    return t + _BMT_FRIENDLY_TAIL


@lru_cache
def get_bmt_store() -> BMTSessionStore:
    return BMTSessionStore()


def _to_resp(s: BMTSession, r: BMTResult) -> BmtTurnResponse:
    return BmtTurnResponse(
        session_id=s.id,
        reply=_with_friendly_tail(r.reply),
        kind=r.kind,
        step=r.step,
        form=r.form,
        form_preview=r.form_preview,
        plan_remaining=r.plan_remaining,
        submit_receipt=r.submit_receipt,
        validation_warnings=r.validation_warnings,
        field_explanation=r.field_explanation,
        rag_sources=r.rag_sources,
        locale=s.locale,  # type: ignore[arg-type]
    )


@router.post("/turn", response_model=BmtTurnResponse)
def bmt_turn(
    body: BmtTurnRequest,
    store: BMTSessionStore = Depends(get_bmt_store),
    eng: BMTDeclarationEngine = Depends(get_bmt_engine),
) -> BmtTurnResponse:
    loc: str = body.locale if body.locale in ("zh-CN", "vi-VN") else "zh-CN"
    s: BMTSession
    if body.session_id:
        got = store.get(body.session_id)
        if not got:
            raise HTTPException(status_code=404, detail="bmt session not found")
        s = got
        s.locale = loc  # type: ignore[assignment]
    else:
        s = store.create(loc)

    def _opening() -> BmtTurnResponse:
        em = DeclarationForm()
        return BmtTurnResponse(
            session_id=s.id,
            reply=_with_friendly_tail(eng.opening_message(s)),
            kind="collecting",
            step=s.step.value,
            form={},
            form_preview=form_preview(em),
            plan_remaining=[],
            field_explanation=None,
            rag_sources=None,
        )

    if body.start_only:
        return _opening()

    msg = (body.message or "").strip()
    if not msg:
        if body.session_id:
            raise HTTPException(status_code=400, detail="message is required when session_id is set")
        return _opening()

    r = eng.handle(s, msg)
    s.recent_user_lines = (getattr(s, "recent_user_lines", None) or []) + [msg]
    s.recent_user_lines = s.recent_user_lines[-8:]
    return _to_resp(s, r)
