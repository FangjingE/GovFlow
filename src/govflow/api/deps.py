"""FastAPI 依赖注入：单例编排器、未来可接 DB 会话。"""

from functools import lru_cache

from govflow.config import get_settings
from govflow.services.llm.deepseek_client import DeepSeekLLMClient
from govflow.services.llm.mock_llm import MockLLMClient
from govflow.services.llm.protocols import LLMClient
from govflow.services.pipeline.orchestrator import ChatOrchestrator


@lru_cache
def get_orchestrator() -> ChatOrchestrator:
    s = get_settings()
    if s.llm_provider == "deepseek":
        if not (s.llm_api_key and str(s.llm_api_key).strip()):
            raise RuntimeError("GOVFLOW_LLM_PROVIDER=deepseek 但未设置有效的 GOVFLOW_LLM_API_KEY")
        impl: LLMClient = DeepSeekLLMClient(s)
    else:
        impl = MockLLMClient()
    return ChatOrchestrator(settings=s, llm=impl)
