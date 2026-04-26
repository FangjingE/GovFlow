"""
公司设立相关政务外部接口的 **Mock** 实现。

行为约定（便于联调与单测）：
- 名称含子串 ``mock_reject`` 或仅空白 → 不通过。
- 设立 ``submission_id`` 含 ``mock_supplement`` → 首轮审核为需补正，再次轮询通过。
- ``submission_id`` 含 ``mock_reject`` → 审核驳回。
- 其余：第 1 次 ``poll_review`` 为审核中，第 2 次起为通过（可配置 ``review_rounds_until_approve``）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from govflow.services.integrations.company_setup.protocols import (
    BasicBankAccountClient,
    EstablishmentReviewClient,
    IndustryPermitClient,
    LicenseIssuanceClient,
    MarketSupervisionNameClient,
    SealFilingClient,
    SocialAndHousingFundClient,
    TaxRegistrationClient,
    UnifiedEstablishmentPortalClient,
)
from govflow.services.integrations.company_setup.types import (
    BankAccountReceipt,
    BusinessLicense,
    EstablishmentMaterials,
    IndustryPermitReceipt,
    NameReservationRequest,
    NameReservationResult,
    ReviewPollResult,
    ReviewStatus,
    SealFilingReceipt,
    SocialFundReceipt,
    SubmissionReceipt,
    TaxRegistrationReceipt,
)


def _now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


class MockMarketSupervisionNameClient:
    """模拟名称自主申报接口。"""

    def reserve_name(self, req: NameReservationRequest) -> NameReservationResult:
        name = (req.proposed_name or "").strip()
        if not name or "mock_reject" in name:
            return NameReservationResult(
                approved=False,
                rejection_reason="（mock）名称不符合规则或与现有字号冲突，请更换后重试。",
            )
        notice = f"SCJD-MOCK-{uuid.uuid4().hex[:10].upper()}"
        return NameReservationResult(approved=True, reservation_notice_no=notice)


class MockUnifiedEstablishmentPortalClient:
    """模拟一网通办提交设立材料。"""

    def submit_establishment(self, materials: EstablishmentMaterials) -> SubmissionReceipt:
        sid = f"YWTB-MOCK-{uuid.uuid4().hex[:12]}"
        return SubmissionReceipt(
            submission_id=sid,
            accepted_at_iso=_now_iso(),
            tracking_url_hint="https://example.gov.cn/mock-portal/track",
        )


@dataclass
class MockEstablishmentReviewClient:
    """模拟审核轮询：带内存计数。"""

    review_rounds_until_approve: int = 2
    _poll_counts: dict[str, int] = field(default_factory=dict)

    def poll_review(self, submission_id: str) -> ReviewPollResult:
        if "mock_reject" in submission_id:
            return ReviewPollResult(status=ReviewStatus.REJECTED, supplement_opinion="（mock）登记机关驳回。")
        if "mock_supplement" in submission_id:
            n = self._poll_counts.get(submission_id, 0)
            self._poll_counts[submission_id] = n + 1
            if n == 0:
                return ReviewPollResult(
                    status=ReviewStatus.NEED_SUPPLEMENT,
                    supplement_opinion="（mock）请补充住所使用证明、股东签章页。",
                )
            return ReviewPollResult(status=ReviewStatus.APPROVED)

        n = self._poll_counts.get(submission_id, 0)
        self._poll_counts[submission_id] = n + 1
        if n + 1 < self.review_rounds_until_approve:
            return ReviewPollResult(status=ReviewStatus.SUBMITTED)
        return ReviewPollResult(status=ReviewStatus.APPROVED)


class MockLicenseIssuanceClient:
    """模拟制发营业执照。"""

    def issue_business_license(self, submission_id: str, legal_name: str) -> BusinessLicense:
        uscc = f"91{uuid.uuid4().hex[:14].upper()}"
        return BusinessLicense(
            unified_social_credit_code=uscc,
            legal_representative=legal_name or "（mock）法定代表人",
            issued_at_iso=_now_iso(),
            license_no=f"ABCMOCK{uuid.uuid4().hex[:8].upper()}",
        )


class MockSealFilingClient:
    def file_seals(self, unified_social_credit_code: str, company_name: str) -> SealFilingReceipt:
        return SealFilingReceipt(
            filing_no=f"GA-MOCK-SEAL-{uuid.uuid4().hex[:8]}",
            seal_types=("公章", "财务专用章", "法定代表人章"),
        )


class MockBasicBankAccountClient:
    def open_basic_account(
        self, unified_social_credit_code: str, company_name: str, legal_person_name: str
    ) -> BankAccountReceipt:
        return BankAccountReceipt(
            account_no=f"6222{uuid.uuid4().int % 10**13:013d}",
            bank_name="（mock）示例银行营业部",
            opened_at_iso=_now_iso(),
        )


class MockTaxRegistrationClient:
    def register_tax(self, unified_social_credit_code: str, company_name: str) -> TaxRegistrationReceipt:
        return TaxRegistrationReceipt(
            tax_id_hint=uscc_tail(unified_social_credit_code),
            invoice_channel_hint="电子税务局 — 数电票（mock）",
        )


class MockSocialAndHousingFundClient:
    def open_social_and_fund(
        self, unified_social_credit_code: str, company_name: str
    ) -> SocialFundReceipt:
        return SocialFundReceipt(
            social_unit_no=f"SI-MOCK-{uuid.uuid4().hex[:8]}",
            fund_unit_no=f"HF-MOCK-{uuid.uuid4().hex[:8]}",
        )


class MockIndustryPermitClient:
    def apply_post_permit(
        self, unified_social_credit_code: str, company_name: str, industry_code: str
    ) -> IndustryPermitReceipt:
        return IndustryPermitReceipt(
            permit_type=f"后置许可-{industry_code}",
            permit_no=f"SP-MOCK-{uuid.uuid4().hex[:10].upper()}",
            valid_until_iso=None,
        )


def uscc_tail(uscc: str) -> str:
    return uscc[-6:] if len(uscc) >= 6 else uscc


@dataclass
class MockCompanySetupExternals:
    """打包注入 P&E 编排器：全部接口均为内存 mock。"""

    names: MarketSupervisionNameClient = field(default_factory=MockMarketSupervisionNameClient)
    portal: UnifiedEstablishmentPortalClient = field(
        default_factory=MockUnifiedEstablishmentPortalClient
    )
    review: EstablishmentReviewClient = field(default_factory=MockEstablishmentReviewClient)
    license_: LicenseIssuanceClient = field(default_factory=MockLicenseIssuanceClient)
    seal: SealFilingClient = field(default_factory=MockSealFilingClient)
    bank: BasicBankAccountClient = field(default_factory=MockBasicBankAccountClient)
    tax: TaxRegistrationClient = field(default_factory=MockTaxRegistrationClient)
    social: SocialAndHousingFundClient = field(default_factory=MockSocialAndHousingFundClient)
    permit: IndustryPermitClient = field(default_factory=MockIndustryPermitClient)


def build_mock_company_setup_externals(
    *, review_rounds_until_approve: int = 2
) -> MockCompanySetupExternals:
    return MockCompanySetupExternals(
        review=MockEstablishmentReviewClient(review_rounds_until_approve=review_rounds_until_approve),
    )
