"""
答案审核实现与工厂：由 ``Settings.answer_auditor_mode`` 选择策略。

- ``pass_through``：与历史 ``PassThroughAuditor`` 一致（长度 + 非空证据）。
- ``grounded``：在 pass-through 规则基础上，拒绝答案中出现「证据拼接文本」里不存在的连续 4 位及以上数字（抑制编造电话、文号等）。
"""

from __future__ import annotations

import re

from govflow.config import Settings
from govflow.domain.messages import RetrievedChunk
from govflow.services.llm.mock_llm import PassThroughAuditor
from govflow.services.llm.protocols import AnswerAuditor

_DIGIT_RUN = re.compile(r"\d{4,}")


class GroundedAnswerAuditor:
    """规则审核：证据非空、最短长度、数字片段须能在证据中找到。"""

    def __init__(self, min_answer_length: int = 20) -> None:
        self._min_len = min_answer_length

    def audit(self, answer: str, evidence_chunks: list[RetrievedChunk]) -> tuple[bool, str | None]:
        if not evidence_chunks:
            return False, "无检索证据，禁止输出臆测答案"
        text = answer.strip()
        if len(text) < self._min_len:
            return False, "答案过短或未生成"
        blob = "\n".join(
            f"{c.source_title or ''}\n{c.text}" for c in evidence_chunks
        )
        for m in _DIGIT_RUN.finditer(text):
            if m.group() not in blob:
                return False, f"答案含证据中未出现的数字片段: {m.group()}"
        return True, None


def build_answer_auditor(settings: Settings) -> AnswerAuditor:
    """按应用配置构造审核器（编排器 ``auditor=None`` 时使用）。"""
    mode = settings.answer_auditor_mode
    if mode == "pass_through":
        return PassThroughAuditor(min_answer_length=settings.answer_auditor_min_answer_length)
    if mode == "grounded":
        return GroundedAnswerAuditor(min_answer_length=settings.answer_auditor_min_answer_length)
    raise ValueError(f"unknown answer_auditor_mode: {mode!r}")
