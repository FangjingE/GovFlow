"""FastAPI 依赖注入：单例编排器、未来可接 DB 会话。"""

from functools import lru_cache

from govflow.services.pipeline.orchestrator import ChatOrchestrator


@lru_cache
def get_orchestrator() -> ChatOrchestrator:
    # TODO: 从环境注入真实 Retriever / LLMClient 实现
    return ChatOrchestrator()
