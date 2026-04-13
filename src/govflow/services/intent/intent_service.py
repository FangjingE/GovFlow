"""
意图识别 + 槽位需求判断（P0：模糊意图澄清的入口）。

TODO: 用分类模型或小样本 prompt 识别 topic（社保/户籍/企业…）；
      用规则或 NER 抽取槽位；与 ClarificationPolicy 配置化联动。
"""

from dataclasses import dataclass
from enum import Enum
import re


class IntentStatus(str, Enum):
    """是否具备进入 RAG 的条件。"""

    NEEDS_CLARIFICATION = "needs_clarification"
    READY_FOR_RAG = "ready_for_rag"


@dataclass
class IntentAnalysis:
    status: IntentStatus
    topic: str | None
    missing_slots: list[str]
    suggested_questions: list[str]


class IntentService:
    """
    MVP 模拟：关键词触发「信息不全」分支，否则认为可检索。

    设计意图：
    - 当用户只说大类（如「办社保」）→ 追问子意图
    - 当已能映射到知识域 + 必要槽位 → READY
    """

    _SOCIAL_HINT = re.compile(r"社保|医保|养老保险|断缴|补缴", re.I)
    _VAGUE_SOCIAL = re.compile(r"^(我想)?办社保$|办社保$|社保怎么办", re.I)

    def analyze(self, user_text: str, session_topic: str | None) -> IntentAnalysis:
        text = user_text.strip()
        topic = session_topic

        if self._VAGUE_SOCIAL.search(text) or (self._SOCIAL_HINT.search(text) and len(text) < 8):
            return IntentAnalysis(
                status=IntentStatus.NEEDS_CLARIFICATION,
                topic=topic or "社保",
                missing_slots=["social_sub_intent"],
                suggested_questions=[
                    "请问您是办社保卡、查社保记录、还是办社保转移？",
                    "若涉及断缴补缴，请说明是本地户口还是外地户口、断缴大约多久？",
                ],
            )

        if self._SOCIAL_HINT.search(text):
            topic = topic or "社保"

        return IntentAnalysis(
            status=IntentStatus.READY_FOR_RAG,
            topic=topic or "通用政务",
            missing_slots=[],
            suggested_questions=[],
        )
