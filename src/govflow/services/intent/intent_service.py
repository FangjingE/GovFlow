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
    - 边民通/互市相关表述 → 路由层先走政务答问并征求是否进入填报，确认后再切申报轨
    """

    _SOCIAL_HINT = re.compile(r"社保|医保|养老保险|断缴|补缴", re.I)
    _VAGUE_SOCIAL = re.compile(r"^(我想)?办社保$|办社保$|社保怎么办", re.I)
    # 与 knowledge_base/边民通 主题对齐（偏严，用于「仍在互市语境」判断）
    _BMT_ROUTE = re.compile(
        r"边民通|边民互市|互市(?:进口|出口|申报|贸易|商品|限额)?|口岸互市|"
        r"跨境(?:边贸|农产品)|火龙果检疫|互市参考价",
        re.I,
    )
    # 更宽：含「进口/出口商品」等口语，用于展示说明后征求是否进入填报
    _BMT_SOFT = re.compile(
        r"边民通|边民互市|互市(?:进口|出口|申报|贸易|商品|限额)?|口岸互市|"
        r"跨境(?:边贸|农产品)|火龙果检疫|互市参考价|"
        r"进口商品|出口商品|(?:我要|想|要|准备).{0,8}(?:进口|出口)(?:商品|货物|东西)?",
        re.I,
    )
    _DENY_BMT_START = re.compile(
        r"不用|不要|暂不|下次再说|算了|取消|否\b|不是|别(?:了|的)",
        re.I,
    )
    _GOV_STRONG = re.compile(
        r"社保|医保|养老保险|身份证|居住证|公积金|营业执照|税务|结婚登记|护照",
        re.I,
    )

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

    def hints_bianmintong_topic(self, user_text: str) -> bool:
        """是否与边民通/互市进口等话题相关（先答问，再征求是否进入填报）。"""
        t = user_text.strip()
        if len(t) < 3:
            return False
        return bool(self._BMT_SOFT.search(t))

    def confirms_bmt_declaration_start(self, user_text: str) -> bool:
        """用户明确同意开始辅助填写申报（短句或「好+进出口」）。"""
        t = user_text.strip()
        if not t or len(t) > 36:
            return False
        if self.denies_bmt_declaration_start(t):
            return False
        if any(x in t for x in ("是什么", "什么意思", "是否", "怎么填", "如何填")):
            return False
        tl = t.lower()
        if re.search(r"(是|好|行|可以|要|嗯).{0,5}(进|出)口", t):
            return True
        if re.match(
            r"^(是|好|行|嗯|可以|要|确认|开始|好的|要的|ok|yes)[\s!！。.…]*$",
            tl,
            re.I,
        ):
            return True
        if re.match(
            r"^(现在开始|开始吧|开始填写|现在填写|就现在|辅助填写|帮我填|现在办)[\s!！。.…]*$",
            t,
        ):
            return True
        if t in ("嗯嗯", "对对", "要的要的", "对对对"):
            return True
        return False

    def denies_bmt_declaration_start(self, user_text: str) -> bool:
        t = user_text.strip()
        if not t:
            return False
        return bool(self._DENY_BMT_START.search(t))

    def wants_leave_bmt_for_gov(self, user_text: str) -> bool:
        """
        已在边民通轨时，是否应回到通用政务（显式强政务词且本句无互市/边民通主题）。
        """
        t = user_text.strip()
        if not t:
            return False
        if self.hints_bianmintong_topic(t):
            return False
        return bool(self._GOV_STRONG.search(t))
