"""政务通：互市类分步填报独立 API（/v1/zwt），与主聊天同一品牌与配置。"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException

from govflow.api.deps import get_zwt_declaration_engine
from govflow.models.zwt_schemas import ZwtTurnRequest, ZwtTurnResponse
from govflow.zhengwutong.domain import BMTSession, DeclarationForm
from govflow.zhengwutong.engine import BMTDeclarationEngine, BMTResult, form_preview
from govflow.zhengwutong.store import BMTSessionStore

router = APIRouter(prefix="/v1/zwt", tags=["政务通"])

_ZWT_FRIENDLY_TAIL = "\n\n如有不明白的，可以直接问我。"


def with_zwt_friendly_tail(text: str) -> str:
    t = (text or "").rstrip()
    if not t:
        return t
    if "可以直接问我" in t:
        return t
    return t + _ZWT_FRIENDLY_TAIL


@lru_cache
def get_zwt_store() -> BMTSessionStore:
    return BMTSessionStore()


def _to_resp(s: BMTSession, r: BMTResult) -> ZwtTurnResponse:
    return ZwtTurnResponse(
        session_id=s.id,
        reply=with_zwt_friendly_tail(r.reply),
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


@router.post("/turn", response_model=ZwtTurnResponse)
def zwt_turn(
    body: ZwtTurnRequest,
    store: BMTSessionStore = Depends(get_zwt_store),
    eng: BMTDeclarationEngine = Depends(get_zwt_declaration_engine),
) -> ZwtTurnResponse:
    loc: str = body.locale if body.locale in ("zh-CN", "vi-VN") else "zh-CN"
    s: BMTSession
    if body.session_id:
        got = store.get(body.session_id)
        if not got:
            raise HTTPException(status_code=404, detail="zwt session not found")
        s = got
        s.locale = loc  # type: ignore[assignment]
    else:
        s = store.create(loc)

    def _opening() -> ZwtTurnResponse:
        em = DeclarationForm()
        return ZwtTurnResponse(
            session_id=s.id,
            reply=with_zwt_friendly_tail(eng.opening_message(s)),
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
