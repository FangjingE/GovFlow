"""检索结果判定：answer / clarify / fallback。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from govflow.services.gov_types import GovServiceRow

DecisionKind = Literal["answer", "clarify", "fallback"]

_STAGE_HINT_TERMS = (
    "新办",
    "补办",
    "补领",
    "换领",
    "变更",
    "注销",
    "延续",
    "复审",
    "年审",
)


@dataclass(frozen=True)
class RetrievalDecision:
    kind: DecisionKind
    top_candidate: GovServiceRow | None
    candidates: list[GovServiceRow]


def choose_retrieval_decision(
    candidates: list[GovServiceRow],
    *,
    fallback_min_score: float,
    answer_min_score: float,
    clarify_min_score_gap: float,
) -> RetrievalDecision:
    if not candidates:
        return RetrievalDecision(kind="fallback", top_candidate=None, candidates=[])

    top1 = candidates[0]
    score1 = float(top1.match_score or 0.0)
    score2 = float(candidates[1].match_score or 0.0) if len(candidates) > 1 else 0.0
    score_gap = score1 - score2 if len(candidates) > 1 else 1.0

    if score1 < fallback_min_score:
        return RetrievalDecision(kind="fallback", top_candidate=None, candidates=candidates)

    if score1 < answer_min_score:
        return RetrievalDecision(kind="clarify", top_candidate=None, candidates=candidates)

    if len(candidates) > 1 and score_gap < clarify_min_score_gap:
        return RetrievalDecision(kind="clarify", top_candidate=None, candidates=candidates)

    return RetrievalDecision(kind="answer", top_candidate=top1, candidates=candidates)


def build_option_label(
    service: GovServiceRow,
    *,
    show_department: bool,
    show_service_object: bool,
) -> str:
    extras: list[str] = []
    if show_department and service.department:
        extras.append(service.department)
    if show_service_object and service.service_object:
        extras.append(service.service_object)
    if not extras:
        return service.service_name
    return f"{service.service_name}（{'；'.join(extras)}）"


def build_clarify_question(candidates: list[GovServiceRow]) -> str:
    if not candidates:
        return "我还不能确认你要办理的是哪一项，请补充更具体的事项关键词。"

    departments = {svc.department for svc in candidates if svc.department}
    service_objects = {svc.service_object for svc in candidates if svc.service_object}
    stage_terms = [term for term in _STAGE_HINT_TERMS if any(term in svc.service_name for svc in candidates)]

    hints: list[str] = []
    if stage_terms:
        hints.append(f"补充业务阶段，如{'、'.join(stage_terms[:4])}")
    if len(service_objects) > 1:
        hints.append("说明是个人事项还是企业事项")
    if len(departments) > 1:
        hints.append("补充办理部门")

    if not hints:
        return "我找到了几条相近的事项，还不能确认你要办理的是哪一项。"

    return "我找到了几条相近的事项，还不能确认你要办理的是哪一项。请" + "；".join(hints) + "。"
