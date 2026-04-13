"""
MVP 模拟 LLM：把检索片段拼接为「带引用」的说明，不调用外部模型。

TODO:
- 接入 OpenAI 兼容客户端（httpx + streaming）
- System prompt 强制「仅依据 context，无 context 则拒答」
- 引用格式与前端展示组件对齐
"""

from govflow.domain.messages import RetrievedChunk
from govflow.services.llm.protocols import AnswerAuditor, LLMClient


class MockLLMClient(LLMClient):
    def generate_answer(
        self,
        user_message: str,
        history_snippets: list[str],
        evidence_chunks: list[RetrievedChunk],
    ) -> str:
        if not evidence_chunks:
            # 真实 LLM 路径也不应编造；此处直接返回占位，由 orchestrator 统一兜底亦可
            return ""

        parts: list[str] = []
        parts.append("根据检索到的办事指南摘要，说明如下（示例生成，非真实推理）：\n")
        for i, ch in enumerate(evidence_chunks, 1):
            src = ch.source_title or "未知来源"
            parts.append(f"{i}. **来源**：{src}\n")
            excerpt = ch.text.strip().split("\n")[0:8]
            parts.append("\n".join(excerpt))
            parts.append("\n\n")
        parts.append("⚠️ 以上信息仅供参考，具体以窗口审核为准。\n")
        if history_snippets:
            parts.append("\n（已结合此前对话要点，完整多轮推理待接入真实 LLM。）\n")
        return "".join(parts)


class PassThroughAuditor(AnswerAuditor):
    """TODO: 检查答案是否包含「根据XX」、是否出现 evidence 外的具体数字等。"""

    def audit(self, answer: str, evidence_chunks: list[RetrievedChunk]) -> tuple[bool, str | None]:
        if not evidence_chunks:
            return False, "无检索证据，禁止输出臆测答案"
        if len(answer.strip()) < 20:
            return False, "答案过短或未生成"
        return True, None
