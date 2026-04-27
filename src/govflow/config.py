"""应用配置。后续可接入 Vault / K8s ConfigMap。"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AnswerAuditorMode = Literal["pass_through", "grounded"]
LlmProvider = Literal["mock", "deepseek"]
RagMode = Literal["hybrid", "mock"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GOVFLOW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "dev"
    default_hotline: str = "12345"
    # LLM：默认 mock，不联外网。接入 DeepSeek 时设 provider=deepseek 并填 API Key（OpenAI 兼容）
    llm_provider: LlmProvider = Field(
        default="mock",
        description="mock=本地模拟生成；deepseek=调用 DeepSeek API（OpenAI 兼容）",
    )
    llm_base_url: str | None = Field(
        default=None,
        description="如 https://api.deepseek.com ；留空则使用 DeepSeek 官方地址",
    )
    llm_api_key: str | None = None
    llm_model: str | None = Field(
        default=None,
        description="如 deepseek-chat、deepseek-reasoner；未填时客户端默认 deepseek-chat",
    )
    llm_request_timeout_s: float = Field(default=60.0, ge=5.0, le=300.0)
    llm_temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    llm_max_tokens: int = Field(default=2048, ge=256, le=32_000)
    # 未来向量库
    chroma_persist_dir: str | None = None
    # RAG：hybrid=本地 BM25+向量+RRF；mock=仅关键词（旧 MVP，便于无模型环境测试）
    rag_mode: RagMode = Field(
        default="hybrid",
        description="hybrid=BM25+句向量+RRF；mock=仅关键词",
    )
    # 与 sentence-transformers 常见中文检索模型名一致；可换本机已缓存模型
    embedding_model: str = Field(
        default="BAAI/bge-small-zh-v1.5",
        description="sentence-transformers 模型名或本机目录",
    )
    # 相对路径时相对于工作目录，否则按绝对路径；None=默认使用仓库下 knowledge_base/
    knowledge_base_dir: str | None = Field(
        default=None,
        description="知识库根目录，None=默认 <repo>/knowledge_base",
    )
    # RRF 中排名权重（与混合检索常见取值一致）
    hybrid_rrf_k: int = Field(default=60, ge=1, le=500)
    # BGE 中文小模型检索时常用的查询/文档前缀
    bge_instruct: bool = Field(
        default=True,
        description="BGE-zh 检索时使用官方推荐的查询与段落前缀",
    )
    # 答案审核：pass_through=仅长度+非空证据；grounded=额外校验证据外长数字
    answer_auditor_mode: AnswerAuditorMode = Field(
        default="pass_through",
        description="pass_through | grounded",
    )
    answer_auditor_min_answer_length: int = Field(
        default=20,
        ge=1,
        le=50_000,
        description="审核：答案最短字符数（grounded / pass_through 均生效）",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
