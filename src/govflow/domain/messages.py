"""对话域模型：与传输层解耦，便于单测与替换存储。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class PipelineStage(str, Enum):
    """流水线阶段（用于日志、可观测性扩展）。"""

    FILTER = "sensitive_filter"
    INTENT = "intent"
    CLARIFY = "clarification"
    RAG = "rag"
    LLM = "llm"
    AUDIT = "answer_audit"


@dataclass
class ChatTurn:
    """单轮用户输入在领域层的表示。"""

    role: str  # "user" | "assistant"
    content: str
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RetrievedChunk:
    """RAG 检索片段（未来对齐 Chroma metadata）。"""

    text: str
    source_title: str
    source_uri: str | None = None
    score: float | None = None


@dataclass
class ClarificationState:
    """多轮澄清状态：槽位未填满前不进入 RAG+LLM 主生成。"""

    topic: str | None = None
    pending_slots: list[str] = field(default_factory=list)
    filled_slots: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "pending_slots": self.pending_slots,
            "filled_slots": self.filled_slots,
        }
