"""企业设立 P&E：区分「填槽回答」与「解释/提问/换话题」等话轮（规则，可后续换分类模型）。"""

from __future__ import annotations

import re

from govflow.company_setup.domain import CompanySetupStep

# 问句、澄清、转去别的话题（非本步字段值）
_META_OR_CLARIFY = re.compile(
    r"[?？]"
    r"|什么|怎么|为什么|啥|哪[个里些]|"
    r"吗\s*$|嘛\s*$|呢\s*[?？]?"
    r"|什么意思|啥意思|不懂|解释一下|请问|是否|如何(?:办|理)?"
    r"|什么是|指什么|是啥|哪个"
    r"|还有一个问题|另外想问|想问一下|先说|顺便问|搞不清楚|不明白|不太懂"
)

_TOPIC_DEFERRAL = re.compile(
    r"换个话题|不说这个|先不聊|不聊这个|先问别的|别的话题|打住|停一下|等会|等等|晚点再说|"
    r"先不填|暂时不填|跳过这步|不想填"
)


def looks_like_meta_or_clarify(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 2:
        return False
    return bool(_META_OR_CLARIFY.search(t))


def looks_like_topic_deferral(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 2:
        return False
    return bool(_TOPIC_DEFERRAL.search(t))


def is_collecting_step(step: CompanySetupStep) -> bool:
    return step in (
        CompanySetupStep.ASK_COMPANY_TYPE,
        CompanySetupStep.ASK_PROPOSED_NAME,
        CompanySetupStep.ASK_ADDRESS,
        CompanySetupStep.ASK_SHAREHOLDERS,
        CompanySetupStep.ASK_BUSINESS_SCOPE,
        CompanySetupStep.NAME_RETRY,
    )


def review_poll_should_advance(text: str) -> bool:
    """审核轮询步：仅当用户显式推进时才调用外部 poll（避免闲聊误推进）。"""
    t = (text or "").strip()
    if not t:
        return False
    if looks_like_meta_or_clarify(t) or looks_like_topic_deferral(t):
        return False
    keys = ("继续", "下一步", "查询", "查一下", "好了", "再看", "推进", "刷新")
    return any(k in t for k in keys)


_FIELD_LABELS: dict[CompanySetupStep, tuple[str, str]] = {
    CompanySetupStep.ASK_COMPANY_TYPE: ("主体类型", "如：有限责任公司、个人独资企业、分公司"),
    CompanySetupStep.ASK_PROPOSED_NAME: ("拟定企业名称", "行政区划 + 字号 + 行业表述 + 组织形式，可按习惯口述"),
    CompanySetupStep.ASK_ADDRESS: ("住所（注册地址）", "省市区 + 道路门牌或园区楼栋，演示可简写"),
    CompanySetupStep.ASK_SHAREHOLDERS: ("股东及出资比例", "自然人姓名 + 百分比，如：张三 60%、李四 40%"),
    CompanySetupStep.ASK_BUSINESS_SCOPE: ("经营范围", "业务大类即可，如：软件开发、技术咨询"),
    CompanySetupStep.NAME_RETRY: ("拟定企业名称（重报）", "整句新名称；勿含演示禁名子串 mock_reject"),
}


def field_label_and_hint(step: CompanySetupStep) -> tuple[str, str]:
    return _FIELD_LABELS.get(step, ("本步信息", "请按上一步提示直接填写"))
