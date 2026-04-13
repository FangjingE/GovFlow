"""LLM 抽象：本地 vLLM / Ollama / 商业 API 均可实现同一协议。"""

from typing import Protocol

from govflow.domain.messages import RetrievedChunk


class LLMClient(Protocol):
    def generate_answer(
        self,
        user_message: str,
        history_snippets: list[str],
        evidence_chunks: list[RetrievedChunk],
    ) -> str:
        """基于证据生成回答；无证据时由上层禁止自由发挥（P0）。"""
        ...


class AnswerAuditor(Protocol):
    def audit(self, answer: str, evidence_chunks: list[RetrievedChunk]) -> tuple[bool, str | None]:
        """答案审核：是否包含引用、是否越界等。TODO: 二次 LLM 或规则引擎。"""
        ...
