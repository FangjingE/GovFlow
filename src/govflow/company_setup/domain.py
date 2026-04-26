"""企业设立 P&E：步骤枚举与可变的会话态（仅存内存 store）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from govflow.services.integrations.company_setup.mock_clients import MockCompanySetupExternals
from govflow.services.integrations.company_setup.types import BusinessLicense


class CompanySetupStep(str, Enum):
    """主计划节点（与外部 mock 调用顺序对应）。"""

    ASK_COMPANY_TYPE = "ask_company_type"
    ASK_PROPOSED_NAME = "ask_proposed_name"
    ASK_ADDRESS = "ask_registered_address"
    ASK_SHAREHOLDERS = "ask_shareholders"
    ASK_BUSINESS_SCOPE = "ask_business_scope"
    NAME_RETRY = "name_retry"
    REVIEW_POLL = "establishment_review_poll"
    ASK_PERMIT_NEED = "ask_permit_need"
    COMPLETE = "complete"


@dataclass
class CompanySetupSession:
    """单用户一条企业设立演示轨。"""

    id: str
    locale: str = "zh-CN"
    step: CompanySetupStep = CompanySetupStep.ASK_COMPANY_TYPE
    externals: MockCompanySetupExternals = field(default_factory=MockCompanySetupExternals)
    company_type: str | None = None
    proposed_name: str | None = None
    registered_address: str | None = None
    shareholders_summary: str | None = None
    business_scope: str | None = None
    name_notice_no: str | None = None
    submission_id: str | None = None
    license: BusinessLicense | None = None
    permit_industry_code: str | None = None
