"""应用配置。后续可接入 Vault / K8s ConfigMap。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GOVFLOW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "dev"
    default_hotline: str = "12345"
    # 未来 LLM（OpenAI 兼容）
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    # 未来向量库
    chroma_persist_dir: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
