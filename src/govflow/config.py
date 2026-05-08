"""应用配置。"""

from functools import lru_cache
from typing import Literal

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
    # 文本检索最低得分，低于此视为未命中（见 service_embedding / gov_service 相似度）
    text_match_min_score: float = Field(default=0.05, ge=0.0, le=1.0)
    # ivfflat 召回探测桶数（越大召回越准，查询越慢）
    vector_ivfflat_probes: int = Field(default=10, ge=1, le=10000)
    # 自动向量化检索配置（OpenAI 兼容 Embeddings API）
    embedding_enabled: bool = Field(default=True)
    embedding_provider: EmbeddingProvider = Field(default="local")
    embedding_api_key: str | None = Field(default=None)
    embedding_base_url: str = Field(default="https://api.openai.com/v1")
    embedding_model: str = Field(default="text-embedding-3-small")
    embedding_timeout_seconds: int = Field(default=20, ge=1, le=120)
    # 本地向量化配置（sentence-transformers）
    embedding_local_model: str = Field(default="BAAI/bge-base-zh-v1.5")
    embedding_local_device: str = Field(default="auto")
    embedding_local_files_only: bool = Field(default=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
