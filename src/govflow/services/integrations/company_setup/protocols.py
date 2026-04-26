"""政务外部接口协议：默认实现为 mock，后续可换 httpx 真实客户端。"""

from __future__ import annotations

from typing import Protocol

from govflow.services.integrations.company_setup.types import (
    BankAccountReceipt,
    BusinessLicense,
    EstablishmentMaterials,
    IndustryPermitReceipt,
    NameReservationRequest,
    NameReservationResult,
    ReviewPollResult,
    SealFilingReceipt,
    SocialFundReceipt,
    SubmissionReceipt,
    TaxRegistrationReceipt,
)


class MarketSupervisionNameClient(Protocol):
    """市场监管：名称自主申报 / 查重（真实多为省局或总局开放接口）。"""

    def reserve_name(self, req: NameReservationRequest) -> NameReservationResult:
        ...


class UnifiedEstablishmentPortalClient(Protocol):
    """一网通办：设立材料提交。"""

    def submit_establishment(self, materials: EstablishmentMaterials) -> SubmissionReceipt:
        ...


class EstablishmentReviewClient(Protocol):
    """登记机关：设立审核状态查询。"""

    def poll_review(self, submission_id: str) -> ReviewPollResult:
        ...


class LicenseIssuanceClient(Protocol):
    """执照制发与领取（电子执照 / 窗口）。"""

    def issue_business_license(self, submission_id: str, legal_name: str) -> BusinessLicense:
        ...


class SealFilingClient(Protocol):
    """公安备案刻章。"""

    def file_seals(self, unified_social_credit_code: str, company_name: str) -> SealFilingReceipt:
        ...


class BasicBankAccountClient(Protocol):
    """商业银行：基本户开立（真实需预约、面签）。"""

    def open_basic_account(
        self, unified_social_credit_code: str, company_name: str, legal_person_name: str
    ) -> BankAccountReceipt:
        ...


class TaxRegistrationClient(Protocol):
    """税务：新办纳税人报到 / 发票通道（电子税务局）。"""

    def register_tax(self, unified_social_credit_code: str, company_name: str) -> TaxRegistrationReceipt:
        ...


class SocialAndHousingFundClient(Protocol):
    """人社 / 公积金：单位开户。"""

    def open_social_and_fund(
        self, unified_social_credit_code: str, company_name: str
    ) -> SocialFundReceipt:
        ...


class IndustryPermitClient(Protocol):
    """行业主管部门：后置许可（如食品经营）。"""

    def apply_post_permit(
        self, unified_social_credit_code: str, company_name: str, industry_code: str
    ) -> IndustryPermitReceipt:
        ...
