"""应用配置。后续可接入 Vault / K8s ConfigMap。"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AnswerAuditorMode = Literal["pass_through", "grounded"]
LlmProvider = Literal["mock", "deepseek"]


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
