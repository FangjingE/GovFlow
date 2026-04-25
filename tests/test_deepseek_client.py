"""DeepSeek 客户端与 OpenAI SDK 的交互用 mock 验证，不访问外网。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from govflow.config import Settings
from govflow.domain.messages import RetrievedChunk
from govflow.services.llm.deepseek_client import DeepSeekLLMClient, _user_payload

_CHUNK = RetrievedChunk(
    text="一、带户口簿。\n二、现场拍照。",
    source_title="测试/知识",
    source_uri="file://test.txt",
    score=0.9,
)


def test_pack_user_payload_mentions_evidence_and_query() -> None:
    t = _user_payload("办身份证要啥", ["办社保", "想换话题"], "摘录正文")
    assert "办身份证" in t
    assert "办社保" in t
    assert "摘录正文" in t


def test_deepseek_requires_key() -> None:
    s = Settings(llm_api_key=None)
    with pytest.raises(ValueError, match="API_KEY"):
        DeepSeekLLMClient(s)


@patch("govflow.services.llm.deepseek_client.OpenAI")
def test_generate_answer_uses_openai_and_returns_stripped_text(mock_openai: MagicMock) -> None:
    s = Settings(
        llm_api_key="sk-test",
        llm_model="deepseek-chat",
        llm_base_url="https://api.deepseek.com",
    )
    m_client = MagicMock()
    mock_openai.return_value = m_client
    m_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="  根据知识库，需带户口簿。  "))],
    )

    c = DeepSeekLLMClient(s)
    out = c.generate_answer("补办要带什么", [], [_CHUNK])

    assert "户口簿" in out
    m_client.chat.completions.create.assert_called_once()
    call_kw = m_client.chat.completions.create.call_args[1]
    assert call_kw["model"] == "deepseek-chat"
    assert "【知识库摘录】" in call_kw["messages"][1]["content"]


@patch("govflow.services.llm.deepseek_client.OpenAI")
def test_api_error_returns_safe_reply(mock_openai: MagicMock) -> None:
    s = Settings(llm_api_key="sk-test", default_hotline="10000")
    m_client = MagicMock()
    mock_openai.return_value = m_client
    m_client.chat.completions.create.side_effect = RuntimeError("timeout")

    c = DeepSeekLLMClient(s)
    out = c.generate_answer("问", [], [_CHUNK])
    assert "大模型" in out or "不可用" in out
    assert "10000" in out
