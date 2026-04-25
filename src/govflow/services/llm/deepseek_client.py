"""
DeepSeek 对话能力（OpenAI 兼容端点 `https://api.deepseek.com`）。

用法：设置 ``GOVFLOW_LLM_PROVIDER=deepseek``、``GOVFLOW_LLM_API_KEY`` 与可选的 ``GOVFLOW_LLM_MODEL``（默认 ``deepseek-chat``）。
"""

from __future__ import annotations

import logging

from openai import OpenAI

from govflow.config import Settings
from govflow.domain.messages import RetrievedChunk
from govflow.services.llm.protocols import LLMClient

log = logging.getLogger(__name__)

# 与编排器、审核器一致：无证据不调用本客户端；有证据时强约束
_SYSTEM = """你是中国县域政务办事大厅的智能引导助手。请**严格**依据用户消息中的【知识库摘录】回答，不得臆造政策、金额、地址或文号。若摘录不足以支撑准确结论，应明确说明并建议通过窗口或官方电话核实。回答用简体中文，分点简洁。"""

_MAX_CHUNK_CHARS = 12_000


def _pack_evidence(chunks: list[RetrievedChunk]) -> str:
    parts: list[str] = []
    for i, c in enumerate(chunks, 1):
        head = c.text.strip()[:_MAX_CHUNK_CHARS]
        src = c.source_title or "未标注来源"
        parts.append(f"#### 摘录 {i}（{src}）\n{head}")
    return "\n\n".join(parts)


def _user_payload(
    user_message: str,
    history_snippets: list[str],
    evidence_block: str,
) -> str:
    blocks: list[str] = []
    if history_snippets:
        blocks.append("【此前多轮中的用户原话要点】\n" + "\n".join(f"- {h}" for h in history_snippets if h.strip()))
    blocks.append("【知识库摘录】\n" + evidence_block)
    blocks.append("【当前用户问题】\n" + user_message.strip())
    return "\n\n".join(blocks)


class DeepSeekLLMClient(LLMClient):
    def __init__(self, settings: Settings) -> None:
        if not settings.llm_api_key or not str(settings.llm_api_key).strip():
            msg = "DeepSeek 需要设置 GOVFLOW_LLM_API_KEY"
            raise ValueError(msg)
        self._settings = settings
        self._base_url = (settings.llm_base_url or "https://api.deepseek.com").rstrip("/")
        self._model = (settings.llm_model or "deepseek-chat").strip()
        self._client: OpenAI = OpenAI(
            api_key=settings.llm_api_key.strip(),
            base_url=self._base_url,
            timeout=float(settings.llm_request_timeout_s),
        )

    def generate_answer(
        self,
        user_message: str,
        history_snippets: list[str],
        evidence_chunks: list[RetrievedChunk],
    ) -> str:
        if not evidence_chunks:
            return ""

        evidence = _pack_evidence(evidence_chunks)
        user_content = _user_payload(user_message, history_snippets, evidence)

        try:
            r = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user_content},
                ],
                temperature=float(self._settings.llm_temperature),
                max_tokens=int(self._settings.llm_max_tokens),
            )
        except Exception as e:
            log.exception("DeepSeek 调用失败: %s", e)
            return f"大模型服务暂时不可用（{e.__class__.__name__}）。请稍后重试或拨打 {self._settings.default_hotline} 咨询。"

        if not r.choices:
            return ""
        msg = r.choices[0].message
        if msg is None or msg.content is None:
            return ""
        return str(msg.content).strip()
