"""应用配置。"""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RetrievalMode = Literal["text", "vector"]
EmbeddingProvider = Literal["local", "api"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GOVFLOW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "dev"
    default_hotline: str = "12345"
    # 例：postgresql://govflow:govflow@127.0.0.1:5432/govflow
    database_url: str = Field(
        default="postgresql://govflow:govflow@127.0.0.1:5433/govflow",
        description="PostgreSQL 连接串（需已安装 pgvector、执行 sql/schema.sql）",
    )
    # vector：仅向量检索；text：pg_trgm + ILIKE（调试用途）
    retrieval_mode: RetrievalMode = Field(default="vector")
    retrieval_candidate_limit: int = Field(default=15, ge=2, le=50)
    retrieval_clarify_min_score_gap: float = Field(default=0.03, ge=0.0, le=1.0)
    retrieval_keyword_ranking_enabled: bool = Field(default=False)
    # 文本检索最低得分，低于此视为未命中（见 service_embedding / gov_service 相似度）
    text_match_min_score: float = Field(default=0.05, ge=0.0, le=1.0)
    # ivfflat 召回探测桶数（越大召回越准，查询越慢）
    vector_ivfflat_probes: int = Field(default=10, ge=1, le=10000)
    vector_fallback_min_score: float = Field(default=0.70, ge=0.0, le=1.0)
    vector_answer_min_score: float = Field(default=0.78, ge=0.0, le=1.0)
    # 自动向量化检索配置（OpenAI 兼容 Embeddings API）
    embedding_enabled: bool = Field(default=True)
    embedding_provider: EmbeddingProvider = Field(default="local")
    embedding_api_key: str | None = Field(default=None)
    embedding_base_url: str = Field(default="https://api.openai.com/v1")
    embedding_model: str = Field(default="text-embedding-3-small")
    embedding_timeout_seconds: int = Field(default=20, ge=1, le=120)
    # 旧版 LLM 配置（兼容）：将映射到 llm_ranker_*，避免已有 .env 失效
    llm_provider: str | None = Field(default=None)
    llm_api_key: str | None = Field(default=None)
    # 候选判定（LLM）配置：只用于在候选中选择 best_id，不直接生成政策回答
    llm_ranker_enabled: bool = Field(default=False)
    llm_ranker_api_key: str | None = Field(default=None)
    llm_ranker_base_url: str = Field(default="https://api.deepseek.com/v1")
    llm_ranker_model: str = Field(default="deepseek-v4-pro")
    llm_ranker_timeout_seconds: int = Field(default=40, ge=1, le=120)
    llm_ranker_top_k: int = Field(default=15, ge=3, le=30)
    llm_ranker_answer_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    llm_ranker_clarify_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    conversation_session_ttl_minutes: int = Field(default=30, ge=1, le=1440)
    conversation_max_retries: int = Field(default=3, ge=1, le=10)
    # 本地向量化配置（sentence-transformers）
    embedding_local_model: str = Field(default="BAAI/bge-base-zh-v1.5")
    embedding_local_device: str = Field(default="auto")
    embedding_local_files_only: bool = Field(default=True)

    @model_validator(mode="after")
    def _apply_llm_compat(self) -> "Settings":
        # 1) API Key：优先新变量，缺失时回退旧变量
        if not self.llm_ranker_api_key and self.llm_api_key:
            self.llm_ranker_api_key = self.llm_api_key

        # 2) Provider/Base URL：仅在未显式配置 llm_ranker_base_url 时尝试推断
        default_ranker_base = "https://api.openai.com/v1"
        if (
            self.llm_provider
            and self.llm_ranker_base_url.strip() == default_ranker_base
        ):
            p = self.llm_provider.strip().lower()
            if p == "deepseek":
                self.llm_ranker_base_url = "https://api.deepseek.com/v1"

        # 3) 自动启用：如果已有可用 key 且用户配置了 provider，则默认启用 ranker
        if not self.llm_ranker_enabled and self.llm_ranker_api_key and self.llm_provider:
            self.llm_ranker_enabled = True

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
