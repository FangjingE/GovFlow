"""政务通分步填报内嵌「政策/名词」问答：关键词粗筛 RAG + LLM，不推进分步采槽位。"""

from __future__ import annotations

import re

from govflow.zhengwutong.domain import BMTSession
from govflow.config import Settings
from govflow.domain.messages import RetrievedChunk
from govflow.services.llm.protocols import AnswerAuditor, LLMClient
from govflow.services.rag.protocols import Retriever

_STEP_CN: dict[str, str] = {
    "import_export": "进出境(进口/出口)",
    "goods_name": "品名",
    "weight_kg": "净重(主数量,kg)",
    "gross_kg": "毛重(kg)",
    "piece_count": "件/箱数",
    "package": "包装",
    "transport": "携运方式",
    "origin": "产地/国别",
    "value_cny": "价值(元)",
    "value_basis": "价格依据",
    "purpose": "使用性质(自用/代购等)",
    "preview": "预览/核对",
    "confirm": "最终确认",
    "done": "已提交",
}


# 问句/咨询意图；短答槽位不触发，避免与「30」「进口」冲突
_QUES_MARK = re.compile(r"[?？]")
_SLOT_EXACT: frozenset[str] = frozenset(
    {
        "进口",
        "出口",
        "进",
        "出",
        "同净重",
        "确认",
        "确认提交",
        "自用",
        "代购",
    }
)
_NUMish = re.compile(r"^[\d.,，]+\s*(kg|公斤|g|G)?$")


def looks_like_knowledge_query(user_text: str) -> bool:
    """是否为申报过程中的「要解释/政策/怎么办」类问题，而非槽位值。"""
    t = (user_text or "").strip()
    if not t:
        return False
    t_flat = t.replace(" ", "").replace("　", "")
    if t_flat in _SLOT_EXACT:
        return False
    if _NUMish.match(t_flat) or re.fullmatch(r"[\d.,，]+", t_flat):
        return False
    if _QUES_MARK.search(t) or t.endswith("吗") or t.endswith("么") or t.endswith("嘛"):
        if len(t) >= 2:
            return True
    if len(t) < 3:
        return False
    triggers: tuple[str, ...] = (
        "什么",
        "怎么",
        "如何",
        "为什么",
        "哪",
        "哪些",
        "是否",
        "能否",
        "可不可以",
        "可以吗",
        "请",
        "解释",
        "说明",
        "政策",
        "规定",
        "依据",
        "条件",
        "要求",
        "办理",
        "需要",
        "注意",
        "限",
        "额",
        "税",
        "检",
        "疫",
    )
    if any(x in t for x in ("区别", "异同", "不同点", "有何不同")) and len(t) >= 4:
        return True
    if "多少" in t and len(t) >= 3:
        return True
    if "怎么办" in t or "如何填" in t or "怎么填" in t:
        return True
    return any(k in t for k in triggers)


def build_zwt_rag_query(
    user_text: str, session: BMTSession, extra_hint: str = ""
) -> str:
    """在检索中拼接当前步与品名，提高 RAG 命中率。"""
    g = (session.form.goods_name or "").strip() or "（未填品名）"
    step = _STEP_CN.get(session.step.value, session.step.value)
    h = f"（政务通填报上下文：{step}；品名 {g}）"
    u = (user_text or "").strip()
    if extra_hint:
        return f"{u}\n{h}\n{extra_hint}"
    return f"{u}\n{h}"


def _source_dicts(chunks: list[RetrievedChunk]) -> list[dict[str, object]]:
    return [
        {
            "title": c.source_title,
            "uri": c.source_uri,
            "score": c.score,
        }
        for c in chunks
    ]


def run_zwt_faq(
    user_text: str,
    session: BMTSession,
    retriever: Retriever,
    llm: LLMClient,
    auditor: AnswerAuditor,
    settings: Settings,
) -> tuple[str, list[dict], str | None, str] | None:
    """
    对咨询类问句做检索 + 生成。返回
    (reply, rag_sources, field_explanation, kind) ，kind 一般为 knowledge；
    若本句不是知识问答则返回 None，由主引擎继续分步采槽。
    """
    if not looks_like_knowledge_query(user_text):
        return None

    hist: list[str] = []
    for line in getattr(session, "recent_user_lines", None) or []:
        s = (line or "").strip()
        if s:
            hist.append(s)
    history_snippets: list[str] = hist[-4:]

    rag_q = build_zwt_rag_query(user_text, session)
    chunks = retriever.retrieve(rag_q, top_k=5)
    hotline = settings.default_hotline
    # 分步表单的 field_explanation 不用于知识问答；主回复在 reply
    fe: str | None = None

    if not chunks:
        reply = (
            "当前「政务通」演示知识库中，没有和您的问题直接对应的可引用条目，"
            "这里无法做有据答复。请补充关键词或更换问法，也可拨打"
            f" {hotline} 或到口岸/互市服务窗口现场咨询。"
        )
        return reply, [], fe, "knowledge"

    answer = llm.generate_answer(rag_q, history_snippets, chunks)
    ok, reason = auditor.audit(answer, chunks)
    sources = _source_dicts(chunks)
    if ok and answer.strip():
        return answer.strip(), sources, fe, "knowledge"

    # 与主对话编排器一致：审核不通过时返回兜底说明（仍回传片段供前端来源）
    reply = (
        f"已检索到{len(chunks)}条边民/互市相关说明，但本次生成结果未能通过校验"
        f"（{reason or '未知原因'}）。请改述问题、缩短问题，"
        f"或致电 {hotline} 获取权威解释。"
    )
    return reply, sources, fe, "knowledge"
