"""LLM-based candidate ranker.

The model is used only to choose the best candidate id and confidence.
Final response text is still rendered from structured DB fields.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from govflow.config import Settings
from govflow.services.gov_types import GovServiceRow


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
        return LLMRankResult(best_id=best_id, confidence=confidence, reason=reason)
    except Exception:
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
        return LLMSoftAnswerResult(
            answer=answer,
            follow_up_question=follow_up,
            cited_ids=cited_ids,
        )
    except Exception:
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
        return LLMSlotExtractResult(slots=slots, summary=summary)
    except Exception:
        return None
