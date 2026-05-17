"""LLM-based candidate ranker.

The model is used only to choose the best candidate id and confidence.
Final response text is still rendered from structured DB fields.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from govflow.config import Settings
from govflow.services.gov_types import GovServiceRow, MaterialRow, ProcessRow

logger = logging.getLogger(__name__)
_LAST_LLM_DECIDE_ERROR: str | None = None


@dataclass(frozen=True)
class LLMRankResult:
    best_id: int | None
    confidence: float
    reason: str


@dataclass(frozen=True)
class LLMSoftAnswerResult:
    answer: str
    follow_up_question: str
    cited_ids: list[int]


@dataclass(frozen=True)
class LLMSlotExtractResult:
    slots: dict[str, str]
    summary: str


@dataclass(frozen=True)
class LLMDialogDecision:
    action: str  # answer | clarify | fallback
    best_id: int | None
    reply: str
    follow_up_question: str
    cited_ids: list[int]
    reason: str


@dataclass(frozen=True)
class LLMIntentAssessment:
    is_clear: bool
    rewritten_query: str
    reply: str
    missing_info: list[str]
    reason: str


@dataclass(frozen=True)
class LLMNextStepDecision:
    action: str  # answer | clarify | retry_search | fallback
    best_id: int | None
    reply: str
    rewritten_query: str
    cited_ids: list[int]
    reason: str


def _chat_url(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _clip(text: str | None, *, limit: int = 220) -> str:
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _short_candidates(candidates: list[GovServiceRow], *, limit: int = 15) -> str:
    if not candidates:
        return "EMPTY"
    return " | ".join(
        f"{svc.id}:{_clip(svc.service_name, limit=24)}"
        for svc in candidates[:limit]
    )


def _build_prompt(query: str, candidates: list[GovServiceRow]) -> str:
    lines = [
        "你是政务事项候选选择器。任务：从候选中选出最符合用户问题的一项。",
        "你必须只输出 JSON，不要输出任何额外文本。",
        'JSON 格式: {"best_id": <int|null>, "confidence": <0-1 float>, "reason": "<简短中文>"}',
        "规则：",
        "1) best_id 必须来自候选 id；不确定时返回 null。",
        "2) confidence 反映把握度；不确定时给低分。",
        "3) 不要编造候选外事项。",
        "",
        f"用户问题: {query}",
        "候选事项:",
    ]
    for svc in candidates:
        lines.append(
            f"- id={svc.id} | 名称={svc.service_name} | 部门={_clip(svc.department, limit=80)} "
            f"| 受理条件={_clip(svc.accept_condition)} | 对象={_clip(svc.service_object, limit=80)}"
        )
    return "\n".join(lines)


def rank_candidates_with_llm(
    query: str,
    candidates: list[GovServiceRow],
    settings: Settings,
) -> LLMRankResult | None:
    if not settings.llm_ranker_enabled:
        return None
    if not settings.llm_ranker_api_key:
        return None
    if not candidates:
        return None

    url = _chat_url(settings.llm_ranker_base_url)
    prompt = _build_prompt(query, candidates)
    logger.info(
        "[llm_rank][start] query=%s candidates=%s model=%s",
        _clip(query, limit=160),
        _short_candidates(candidates),
        settings.llm_ranker_model,
    )
    headers = {
        "Authorization": f"Bearer {settings.llm_ranker_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_ranker_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "仅输出JSON对象。"},
            {"role": "user", "content": prompt},
        ],
    }

    try:
        with httpx.Client(timeout=settings.llm_ranker_timeout_seconds) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
        data = resp.json()
        raw = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        obj = json.loads(raw) if isinstance(raw, str) else {}
        best_id_raw = obj.get("best_id")
        conf_raw = obj.get("confidence")
        reason = str(obj.get("reason") or "").strip()
        best_id = int(best_id_raw) if isinstance(best_id_raw, int) else None
        confidence = float(conf_raw) if isinstance(conf_raw, (int, float)) else 0.0
        confidence = max(0.0, min(1.0, confidence))
        logger.info(
            "[llm_rank][parsed] best_id=%s confidence=%.4f reason=%s",
            best_id,
            confidence,
            _clip(reason, limit=240),
        )
        return LLMRankResult(best_id=best_id, confidence=confidence, reason=reason)
    except Exception:
        logger.exception("[llm_rank][error] query=%s", _clip(query, limit=160))
        return None


def _build_answer_prompt(
    query: str,
    candidates: list[GovServiceRow],
    *,
    confidence: float,
    mode: str,
) -> str:
    lines = [
        "你是政务办事助手。请严格基于候选事项信息回复，不要编造候选外政策事实。",
        "你必须只输出 JSON，不要输出任何额外文本。",
        'JSON 格式: {"answer":"<给用户的话>","follow_up_question":"<可空>","cited_ids":[<int>,...]}',
        "约束：",
        "1) cited_ids 只能填写候选里的 id。",
        "2) answer 必须是中文自然表达，可读性优先。",
        "3) mode=answer 时给出可执行建议；mode=clarify 时用自然语言追问用户补充关键信息。",
        "4) 不要输出序号候选清单；追问不要像模板，不要机械化。",
        f"当前模式: {mode}",
        f"模型置信度: {confidence:.2f}",
        f"用户问题: {query}",
        "候选事项:",
    ]
    for svc in candidates:
        lines.append(
            f"- id={svc.id} | 名称={svc.service_name} | 部门={_clip(svc.department, limit=80)} "
            f"| 受理条件={_clip(svc.accept_condition)} | 对象={_clip(svc.service_object, limit=80)} "
            f"| 办理方式={_clip(svc.handle_form, limit=80)} | 来源={_clip(svc.source_url, limit=120)}"
        )
    if mode == "clarify":
        lines.append("请在 answer 中先简要说明仍需确认，再提出一个高质量追问。")
    return "\n".join(lines)


def generate_soft_answer_with_llm(
    query: str,
    candidates: list[GovServiceRow],
    *,
    confidence: float,
    mode: str,
    settings: Settings,
) -> LLMSoftAnswerResult | None:
    if not settings.llm_ranker_enabled:
        return None
    if not settings.llm_ranker_api_key:
        return None
    if not candidates:
        return None
    if mode not in {"answer", "clarify"}:
        return None

    url = _chat_url(settings.llm_ranker_base_url)
    prompt = _build_answer_prompt(query, candidates, confidence=confidence, mode=mode)
    logger.info(
        "[llm_soft_answer][start] mode=%s query=%s candidates=%s confidence=%.4f",
        mode,
        _clip(query, limit=160),
        _short_candidates(candidates),
        confidence,
    )
    headers = {
        "Authorization": f"Bearer {settings.llm_ranker_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_ranker_model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "仅输出JSON对象。"},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        with httpx.Client(timeout=settings.llm_ranker_timeout_seconds) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
        data = resp.json()
        raw = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        obj = json.loads(raw) if isinstance(raw, str) else {}
        answer = str(obj.get("answer") or "").strip()
        follow_up = str(obj.get("follow_up_question") or "").strip()
        cited_raw = obj.get("cited_ids")
        cited_ids = [int(x) for x in cited_raw if isinstance(x, int)] if isinstance(cited_raw, list) else []
        if not answer:
            return None
        logger.info(
            "[llm_soft_answer][parsed] answer=%s follow_up=%s cited=%s",
            _clip(answer, limit=240),
            _clip(follow_up, limit=160),
            cited_ids,
        )
        return LLMSoftAnswerResult(
            answer=answer,
            follow_up_question=follow_up,
            cited_ids=cited_ids,
        )
    except Exception:
        logger.exception("[llm_soft_answer][error] mode=%s query=%s", mode, _clip(query, limit=160))
        return None


def extract_slots_with_llm(
    query: str,
    candidates: list[GovServiceRow],
    *,
    existing_slots: dict[str, str] | None,
    settings: Settings,
) -> LLMSlotExtractResult | None:
    if not settings.llm_ranker_enabled:
        return None
    if not settings.llm_ranker_api_key:
        return None
    if not candidates:
        return None

    existing = existing_slots or {}
    url = _chat_url(settings.llm_ranker_base_url)
    logger.info(
        "[llm_slots][start] query=%s candidates=%s existing=%s",
        _clip(query, limit=160),
        _short_candidates(candidates),
        json.dumps(existing, ensure_ascii=False),
    )
    lines = [
        "你是政务对话槽位提取器。请从用户补充信息中抽取有助于事项判定的槽位。",
        "你必须只输出 JSON，不要输出任何额外文本。",
        'JSON 格式: {"slots":{"<槽位名>":"<槽位值>"}, "summary":"<一句话总结>"}',
        "规则：",
        "1) 仅提取用户明确表达或高置信推断的信息。",
        "2) 不要编造事实；无法确定就不填。",
        "3) 槽位名尽量通用，如 办理对象/参保类型/是否首次/险种/办理阶段/地区 等。",
        f"用户补充: {query}",
        f"现有槽位: {json.dumps(existing, ensure_ascii=False)}",
        "候选事项:",
    ]
    for svc in candidates:
        lines.append(
            f"- id={svc.id} | 名称={svc.service_name} | 部门={_clip(svc.department, limit=80)} "
            f"| 对象={_clip(svc.service_object, limit=80)} | 条件={_clip(svc.accept_condition)}"
        )
    payload = {
        "model": settings.llm_ranker_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "仅输出JSON对象。"},
            {"role": "user", "content": "\n".join(lines)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.llm_ranker_api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=settings.llm_ranker_timeout_seconds) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
        data = resp.json()
        raw = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        obj = json.loads(raw) if isinstance(raw, str) else {}
        slots_raw = obj.get("slots")
        slots: dict[str, str] = {}
        if isinstance(slots_raw, dict):
            for k, v in slots_raw.items():
                if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
                    slots[k.strip()] = v.strip()
        summary = str(obj.get("summary") or "").strip()
        logger.info(
            "[llm_slots][parsed] slots=%s summary=%s",
            json.dumps(slots, ensure_ascii=False),
            _clip(summary, limit=240),
        )
        return LLMSlotExtractResult(slots=slots, summary=summary)
    except Exception:
        logger.exception("[llm_slots][error] query=%s", _clip(query, limit=160))
        return None


def decide_dialog_with_llm(
    query: str,
    candidates: list[GovServiceRow],
    *,
    settings: Settings,
    slots: dict[str, str] | None = None,
) -> LLMDialogDecision | None:
    global _LAST_LLM_DECIDE_ERROR
    _LAST_LLM_DECIDE_ERROR = None
    enabled = bool(getattr(settings, "llm_ranker_enabled", False))
    api_key = getattr(settings, "llm_ranker_api_key", None)
    if not enabled or not api_key or not candidates:
        _LAST_LLM_DECIDE_ERROR = "llm_decide skipped: disabled or missing api key or empty candidates"
        logger.info(
            "[llm_decide] skip enabled=%s api_key_set=%s candidates=%d",
            enabled,
            bool(api_key),
            len(candidates),
        )
        return None

    slot_json = json.dumps(slots or {}, ensure_ascii=False)
    logger.info(
        "[llm_decide][start] query=%s candidates=%s slots=%s",
        _clip(query, limit=160),
        _short_candidates(candidates),
        slot_json,
    )
    lines = [
        "你是政务助手裁定器。必须仅基于候选事项与用户输入做决策。",
        "你必须只输出 JSON。",
        (
            'JSON 格式: {"action":"answer|clarify|fallback","best_id":<int|null>,'
            '"reply":"<给用户的话>","follow_up_question":"<可空>",'
            '"cited_ids":[<int>,...],"reason":"<简述依据>"}'
        ),
        "规则：",
        "1) answer: 你认为可以明确到具体事项并能给出办理指引。",
        "2) clarify: 你认为信息不足，主动追问最关键的一个问题。",
        "3) fallback: 你认为用户意图与候选差距过大或无法判断。",
        "4) 不要输出候选清单编号格式，不要编造候选之外的事项。",
        "5) 若 action=answer，best_id 必须来自候选 id。",
        f"用户输入: {query}",
        f"已知槽位: {slot_json}",
        "候选事项:",
    ]
    for svc in candidates:
        lines.append(
            f"- id={svc.id} | 名称={svc.service_name} | 部门={_clip(svc.department, limit=80)} "
            f"| 对象={_clip(svc.service_object, limit=80)} | 条件={_clip(svc.accept_condition)} "
            f"| 地点={_clip(svc.handle_address, limit=80)} | 时间={_clip(svc.handle_time, limit=80)}"
        )

    payload = {
        "model": getattr(settings, "llm_ranker_model", "gpt-4.1-mini"),
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "仅输出JSON对象。"},
            {"role": "user", "content": "\n".join(lines)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.llm_ranker_api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=settings.llm_ranker_timeout_seconds) as client:
            resp = client.post(
                _chat_url(getattr(settings, "llm_ranker_base_url", "")),
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
        data = resp.json()
        raw = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not isinstance(raw, str):
            _LAST_LLM_DECIDE_ERROR = f"llm_decide invalid raw type: {type(raw).__name__}"
            logger.warning("[llm_decide] invalid raw type: %s", type(raw).__name__)
            return None
        try:
            obj = json.loads(raw)
        except Exception as e:
            _LAST_LLM_DECIDE_ERROR = f"llm_decide json parse failed: {str(e)}"
            logger.warning("[llm_decide] json parse failed: %s | raw=%s", str(e), _clip(raw, limit=600))
            return None
        action = str(obj.get("action") or "").strip().lower()
        if action not in {"answer", "clarify", "fallback"}:
            _LAST_LLM_DECIDE_ERROR = f"llm_decide invalid action: {action or '<empty>'}"
            logger.warning(
                "[llm_decide] invalid action=%s | raw=%s",
                action,
                _clip(raw, limit=600),
            )
            return None
        best_raw = obj.get("best_id")
        best_id = int(best_raw) if isinstance(best_raw, int) else None
        reply = str(obj.get("reply") or "").strip()
        follow_up = str(obj.get("follow_up_question") or "").strip()
        reason = str(obj.get("reason") or "").strip()
        cited_raw = obj.get("cited_ids")
        cited_ids = [int(x) for x in cited_raw if isinstance(x, int)] if isinstance(cited_raw, list) else []
        if not reply:
            _LAST_LLM_DECIDE_ERROR = "llm_decide empty reply"
            logger.warning("[llm_decide] empty reply | raw=%s", _clip(raw, limit=600))
            return None
        logger.info(
            "[llm_decide][parsed] action=%s best_id=%s cited=%s reason=%s reply=%s follow_up=%s",
            action,
            best_id,
            cited_ids,
            _clip(reason, limit=220),
            _clip(reply, limit=220),
            _clip(follow_up, limit=160),
        )
        return LLMDialogDecision(
            action=action,
            best_id=best_id,
            reply=reply,
            follow_up_question=follow_up,
            cited_ids=cited_ids,
            reason=reason,
        )
    except Exception as e:
        _LAST_LLM_DECIDE_ERROR = f"llm_decide request failed: {str(e)}"
        logger.warning("[llm_decide] request failed: %s", str(e))
        return None


def get_last_llm_decide_error() -> str | None:
    return _LAST_LLM_DECIDE_ERROR


def assess_user_intent_with_llm(
    query: str,
    *,
    settings: Settings,
    session_summary: str = "",
) -> LLMIntentAssessment | None:
    enabled = bool(getattr(settings, "llm_ranker_enabled", False))
    api_key = getattr(settings, "llm_ranker_api_key", None)
    if not enabled or not api_key:
        return None

    logger.info(
        "[llm_intent][start] query=%s summary=%s",
        _clip(query, limit=160),
        _clip(session_summary, limit=220),
    )
    lines = [
        "你是政务对话入口判定器。",
        "任务：判断用户当前输入是否已经把想咨询的政务事项表述得足够清楚，可以直接进入检索。",
        "你必须只输出 JSON。",
        (
            'JSON 格式: {"is_clear":<true|false>,"rewritten_query":"<整理后的检索问题>",'
            '"reply":"<给用户的话>","missing_info":["<缺失信息>",...],"reason":"<简述依据>"}'
        ),
        "规则：",
        "1) is_clear=true 时，rewritten_query 必须是更规范、更利于检索的查询句。",
        "2) is_clear=false 时，reply 必须直接对用户发问，追问最关键的信息，不要模板腔。",
        "3) 不要编造用户未提供的事实。",
        "4) 如果已有上下文能补足当前省略表达，可以判定为 clear。",
        f"历史摘要: {session_summary or '无'}",
        f"用户输入: {query}",
    ]
    payload = {
        "model": getattr(settings, "llm_ranker_model", "gpt-4.1-mini"),
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "仅输出JSON对象。"},
            {"role": "user", "content": "\n".join(lines)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=getattr(settings, "llm_ranker_timeout_seconds", 20)) as client:
            resp = client.post(
                _chat_url(getattr(settings, "llm_ranker_base_url", "")),
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
        data = resp.json()
        raw = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        obj = json.loads(raw) if isinstance(raw, str) else {}
        is_clear = bool(obj.get("is_clear"))
        rewritten_query = str(obj.get("rewritten_query") or "").strip()
        reply = str(obj.get("reply") or "").strip()
        reason = str(obj.get("reason") or "").strip()
        missing_raw = obj.get("missing_info")
        missing_info = [str(x).strip() for x in missing_raw if str(x).strip()] if isinstance(missing_raw, list) else []
        if is_clear and not rewritten_query:
            rewritten_query = query.strip()
        if not is_clear and not reply:
            return None
        logger.info(
            "[llm_intent][parsed] is_clear=%s rewritten=%s missing=%s reason=%s reply=%s",
            is_clear,
            _clip(rewritten_query, limit=220),
            missing_info,
            _clip(reason, limit=220),
            _clip(reply, limit=220),
        )
        return LLMIntentAssessment(
            is_clear=is_clear,
            rewritten_query=rewritten_query,
            reply=reply,
            missing_info=missing_info,
            reason=reason,
        )
    except Exception:
        return None


def plan_next_step_with_llm(
    query: str,
    candidates: list[GovServiceRow],
    *,
    settings: Settings,
    session_summary: str = "",
    retry_count: int = 0,
) -> LLMNextStepDecision | None:
    enabled = bool(getattr(settings, "llm_ranker_enabled", False))
    api_key = getattr(settings, "llm_ranker_api_key", None)
    if not enabled or not api_key:
        return None

    logger.info(
        "[llm_plan][start] query=%s candidates=%s retry=%d summary=%s",
        _clip(query, limit=160),
        _short_candidates(candidates),
        retry_count,
        _clip(session_summary, limit=220),
    )
    lines = [
        "你是政务事项对话规划器。",
        "任务：基于用户问题和当前检索到的候选事项，决定下一步应该直接回答、继续追问、改写后重新检索，还是兜底。",
        "你必须只输出 JSON。",
        (
            'JSON 格式: {"action":"answer|clarify|retry_search|fallback","best_id":<int|null>,'
            '"reply":"<给用户的话>","rewritten_query":"<重试检索用问题，可空>",'
            '"cited_ids":[<int>,...],"reason":"<简述依据>"}'
        ),
        "规则：",
        "1) answer: 当前候选足够支撑回答，best_id 必须来自候选。",
        "2) clarify: 需要继续向用户追问；reply 里直接问最关键的问题。",
        "3) retry_search: 当前候选不够好，但可以把上下文整理成一个更适合检索的新问题再次查询；rewritten_query 必填。",
        "4) fallback: 多次尝试后仍不足以回答；reply 必须明确说明失败原因，不要套模板。",
        "5) 不要编造候选外事实；只有 answer 才能基于事项内容给办理指引。",
        f"当前重试次数: {retry_count}",
        f"历史摘要: {session_summary or '无'}",
        f"用户问题: {query}",
        "候选事项:",
    ]
    if candidates:
        for svc in candidates:
            lines.append(
                f"- id={svc.id} | 名称={svc.service_name} | 部门={_clip(svc.department, limit=80)} "
                f"| 对象={_clip(svc.service_object, limit=80)} | 条件={_clip(svc.accept_condition)} "
                f"| 办理方式={_clip(svc.handle_form, limit=80)} | 地点={_clip(svc.handle_address, limit=80)}"
            )
    else:
        lines.append("- 无候选事项")

    payload = {
        "model": getattr(settings, "llm_ranker_model", "gpt-4.1-mini"),
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "仅输出JSON对象。"},
            {"role": "user", "content": "\n".join(lines)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=getattr(settings, "llm_ranker_timeout_seconds", 20)) as client:
            resp = client.post(
                _chat_url(getattr(settings, "llm_ranker_base_url", "")),
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
        data = resp.json()
        raw = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        obj = json.loads(raw) if isinstance(raw, str) else {}
        action = str(obj.get("action") or "").strip().lower()
        if action not in {"answer", "clarify", "retry_search", "fallback"}:
            return None
        best_raw = obj.get("best_id")
        best_id = int(best_raw) if isinstance(best_raw, int) else None
        reply = str(obj.get("reply") or "").strip()
        rewritten_query = str(obj.get("rewritten_query") or "").strip()
        reason = str(obj.get("reason") or "").strip()
        cited_raw = obj.get("cited_ids")
        cited_ids = [int(x) for x in cited_raw if isinstance(x, int)] if isinstance(cited_raw, list) else []
        if action in {"clarify", "fallback", "answer"} and not reply:
            return None
        if action == "retry_search" and not rewritten_query:
            return None
        logger.info(
            "[llm_plan][parsed] action=%s best_id=%s rewritten=%s cited=%s reason=%s reply=%s",
            action,
            best_id,
            _clip(rewritten_query, limit=220),
            cited_ids,
            _clip(reason, limit=220),
            _clip(reply, limit=220),
        )
        return LLMNextStepDecision(
            action=action,
            best_id=best_id,
            reply=reply,
            rewritten_query=rewritten_query,
            cited_ids=cited_ids,
            reason=reason,
        )
    except Exception:
        return None


def explain_fallback_with_llm(
    query: str,
    error_reason: str,
    *,
    hotline: str,
    settings: Settings,
) -> str | None:
    enabled = bool(getattr(settings, "llm_ranker_enabled", False))
    api_key = getattr(settings, "llm_ranker_api_key", None)
    if not enabled or not api_key:
        return None
    logger.info(
        "[llm_fallback][start] query=%s reason=%s hotline=%s",
        _clip(query, limit=160),
        _clip(error_reason, limit=240),
        hotline,
    )
    payload = {
        "model": getattr(settings, "llm_ranker_model", "gpt-4.1-mini"),
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": "你是政务助手。请用简短中文向用户解释当前系统为何暂时无法准确回答，并给出下一步建议。",
            },
            {
                "role": "user",
                "content": (
                    f"用户问题：{query}\n"
                    f"系统失败原因：{error_reason}\n"
                    f"请输出 2 句话以内，不暴露内部栈信息。第二句给出咨询电话：{hotline}。"
                ),
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=getattr(settings, "llm_ranker_timeout_seconds", 20)) as client:
            resp = client.post(
                _chat_url(getattr(settings, "llm_ranker_base_url", "")),
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
        data = resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        out = str(text or "").strip()
        logger.info("[llm_fallback][parsed] reply=%s", _clip(out, limit=240))
        return out or None
    except Exception:
        logger.exception("[llm_fallback][error] query=%s", _clip(query, limit=160))
        return None


def generate_service_answer_with_llm(
    query: str,
    service: GovServiceRow,
    materials: list[MaterialRow],
    processes: list[ProcessRow],
    *,
    settings: Settings,
) -> str | None:
    enabled = bool(getattr(settings, "llm_ranker_enabled", False))
    api_key = getattr(settings, "llm_ranker_api_key", None)
    if not enabled or not api_key:
        return None
    logger.info(
        "[llm_answer][start] query=%s service=%s materials=%d processes=%d",
        _clip(query, limit=160),
        _clip(service.service_name, limit=160),
        len(materials),
        len(processes),
    )
    material_names = [m.material_name for m in materials if m.material_name][:8]
    step_names = [p.step_name for p in processes if p.step_name][:6]
    lines = [
        "你是政务助手，请基于给定结构化信息回答用户。",
        "要求：",
        "1) 自然中文，不用模板腔。",
        "2) 必须逐项给出以下关键信息：事项名称、办理地点、是否网办、办理时间、关键材料、联系方式、原网址链接。",
        "3) 强制规则：若字段值不是“—/空/null”，必须明确告知用户该字段内容，不允许省略。",
        "4) 仅当字段值是“—/空/null”时，才可以写“该信息暂未提供，以窗口最新公布为准”。",
        "5) 不要编造，不要补充候选外政策。",
        "6) 答复末尾单独一行输出：原网址：<url或暂未提供>。",
        f"用户问题: {query}",
        f"事项名称: {service.service_name}",
        f"办理部门: {service.department or '—'}",
        f"办理地点: {service.handle_address or '—'}",
        f"办理方式: {service.handle_form or '—'}",
        f"办理时间: {service.handle_time or '—'}",
        f"咨询方式: {service.consult_way or '—'}",
        f"监督投诉方式: {service.complaint_way or '—'}",
        f"原网址: {service.source_url or '—'}",
        f"申请材料: {', '.join(material_names) if material_names else '—'}",
        f"办理流程: {', '.join([x for x in step_names if x]) if step_names else '—'}",
        "请直接输出给用户的最终答复文本。",
    ]
    payload = {
        "model": getattr(settings, "llm_ranker_model", "gpt-4.1-mini"),
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "请直接输出答复正文，不要JSON。"},
            {"role": "user", "content": "\n".join(lines)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.llm_ranker_api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=settings.llm_ranker_timeout_seconds) as client:
            resp = client.post(
                _chat_url(getattr(settings, "llm_ranker_base_url", "")),
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
        data = resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        out = str(text or "").strip()
        logger.info("[llm_answer][parsed] reply=%s", _clip(out, limit=240))
        return out or None
    except Exception:
        logger.exception("[llm_answer][error] query=%s service=%s", _clip(query, limit=160), _clip(service.service_name, limit=120))
        return None
