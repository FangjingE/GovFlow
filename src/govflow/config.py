"""应用配置。后续可接入 Vault / K8s ConfigMap。"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AnswerAuditorMode = Literal["pass_through", "grounded"]


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
