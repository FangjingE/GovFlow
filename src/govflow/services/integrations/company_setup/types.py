"""公司设立流程与政务外部系统交互的数据模型（与具体 HTTP/SDK 解耦）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CompanyType(str, Enum):
    """常见主体类型（演示枚举，真实系统以登记机关编码为准）。"""

    LLC = "有限责任公司"
    SOLE_PROP = "个人独资企业"
    BRANCH = "分公司"


class ReviewStatus(str, Enum):
    """一网通办设立审核状态（mock 与真实映射时可扩展）。"""

    SUBMITTED = "submitted"  # 已受理，审核中
    NEED_SUPPLEMENT = "need_supplement"  # 需补正
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CompanyBasicProfile:
    """节点 A：拟设立主体核心信息（P&E 采集槽位摘要）。"""

    company_type: str
    proposed_name: str
    registered_address: str
    shareholders_summary: str
    business_scope: str


@dataclass(frozen=True)
class NameReservationRequest:
    """市场监管：名称自主申报请求。"""

    proposed_name: str
    company_type: str | None = None
    applicant_id_no: str | None = None  # 真实接口常为经办人/投资人标识


@dataclass(frozen=True)
class NameReservationResult:
    """名称申报结果。"""

    approved: bool
    reservation_notice_no: str | None = None
    rejection_reason: str | None = None


@dataclass(frozen=True)
class EstablishmentMaterials:
    """一网通办：设立登记材料包（mock 为摘要字段）。"""

    profile: CompanyBasicProfile
    name_reservation_notice_no: str
    attachments_manifest: tuple[str, ...] = ()  # 如 "章程.pdf", "住所证明.pdf"


@dataclass(frozen=True)
class SubmissionReceipt:
    """提交受理回执。"""

    submission_id: str
    accepted_at_iso: str
    tracking_url_hint: str | None = None


@dataclass(frozen=True)
class ReviewPollResult:
    """审核轮询结果。"""

    status: ReviewStatus
    supplement_opinion: str | None = None  # NEED_SUPPLEMENT 时窗口意见


@dataclass(frozen=True)
class BusinessLicense:
    """营业执照（mock）。"""

    unified_social_credit_code: str
    legal_representative: str
    issued_at_iso: str
    license_no: str


@dataclass(frozen=True)
class SealFilingReceipt:
    """公安备案刻章回执。"""

    filing_no: str
    seal_types: tuple[str, ...]


@dataclass(frozen=True)
class BankAccountReceipt:
    """基本存款账户信息（mock）。"""

    account_no: str
    bank_name: str
    opened_at_iso: str


@dataclass(frozen=True)
class TaxRegistrationReceipt:
    """税务报到 / 核定信息（mock）。"""

    tax_id_hint: str
    invoice_channel_hint: str


@dataclass(frozen=True)
class SocialFundReceipt:
    """社保、公积金开户回执（mock）。"""

    social_unit_no: str | None
    fund_unit_no: str | None


@dataclass(frozen=True)
class IndustryPermitReceipt:
    """后置行业许可（mock）。"""

    permit_type: str
    permit_no: str
    valid_until_iso: str | None = None


@dataclass
class CompanySetupExternalState:
    """可选：由编排层持久化的跨节点上下文（mock 不强制使用）。"""

    profile: CompanyBasicProfile | None = None
    name_notice_no: str | None = None
    submission_id: str | None = None
    license: BusinessLicense | None = None
    extra: dict[str, str] = field(default_factory=dict)
