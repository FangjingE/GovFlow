"""FastAPI 依赖注入：单例编排器、未来可接 DB 会话。"""

from functools import lru_cache

from govflow.config import get_settings
from govflow.services.llm.auditors import build_answer_auditor
from govflow.services.llm.deepseek_client import DeepSeekLLMClient
from govflow.services.llm.mock_llm import MockLLMClient
from govflow.services.llm.protocols import LLMClient
from govflow.services.pipeline.orchestrator import ChatOrchestrator
from govflow.services.rag.mock_retriever import MockKeywordRetriever
from govflow.company_setup.engine import CompanySetupPAndE
from govflow.company_setup.store import InMemoryCompanySetupStore
from govflow.zhengwutong.engine import BMTDeclarationEngine


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


@lru_cache
def get_company_setup_store() -> InMemoryCompanySetupStore:
    return InMemoryCompanySetupStore()


@lru_cache
def get_company_setup_engine() -> CompanySetupPAndE:
    return CompanySetupPAndE()


@lru_cache
def get_zwt_declaration_engine() -> BMTDeclarationEngine:
    """政务通分步填报：与主对话共用 provider / API Key；RAG 为本地 knowledge_base 关键词召回。"""
    s = get_settings()
    if s.llm_provider == "deepseek":
        if not (s.llm_api_key and str(s.llm_api_key).strip()):
            raise RuntimeError("GOVFLOW_LLM_PROVIDER=deepseek 但未设置有效的 GOVFLOW_LLM_API_KEY")
        llm: LLMClient = DeepSeekLLMClient(s)
    else:
        llm = MockLLMClient()
    return BMTDeclarationEngine(
        retriever=MockKeywordRetriever(),
        llm=llm,
        auditor=build_answer_auditor(s),
        settings=s,
    )
