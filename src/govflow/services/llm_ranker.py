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
