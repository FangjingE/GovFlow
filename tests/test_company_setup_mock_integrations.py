"""公司设立外部接口 mock：名称、一网通办、审核轮询、执照与后续节点。"""

from govflow.services.integrations.company_setup import (
    CompanyBasicProfile,
    EstablishmentMaterials,
    NameReservationRequest,
    ReviewStatus,
    build_mock_company_setup_externals,
)


def _profile() -> CompanyBasicProfile:
    return CompanyBasicProfile(
        company_type="有限责任公司",
        proposed_name="广西示例科技有限公司",
        registered_address="南宁市青秀区示例路1号",
        shareholders_summary="张三 90%；李四 10%",
        business_scope="软件开发；技术咨询。",
    )


def test_name_reserve_approve_and_reject() -> None:
    ext = build_mock_company_setup_externals()
    ok = ext.names.reserve_name(NameReservationRequest(proposed_name="好名字公司", company_type="有限责任公司"))
    assert ok.approved and ok.reservation_notice_no and ok.reservation_notice_no.startswith("SCJD-MOCK-")

    bad = ext.names.reserve_name(NameReservationRequest(proposed_name="含mock_reject字号", company_type="有限责任公司"))
    assert not bad.approved and bad.rejection_reason


def test_submit_poll_license_happy_path() -> None:
    ext = build_mock_company_setup_externals(review_rounds_until_approve=2)
    p = _profile()
    n = ext.names.reserve_name(NameReservationRequest(proposed_name=p.proposed_name))
    assert n.reservation_notice_no
    sub = ext.portal.submit_establishment(
        EstablishmentMaterials(
            profile=p,
            name_reservation_notice_no=n.reservation_notice_no or "",
            attachments_manifest=("章程.pdf",),
        )
    )
    r1 = ext.review.poll_review(sub.submission_id)
    assert r1.status == ReviewStatus.SUBMITTED
    r2 = ext.review.poll_review(sub.submission_id)
    assert r2.status == ReviewStatus.APPROVED

    lic = ext.license_.issue_business_license(sub.submission_id, legal_name="张三")
    assert len(lic.unified_social_credit_code) >= 10
    seal = ext.seal.file_seals(lic.unified_social_credit_code, p.proposed_name)
    assert seal.filing_no.startswith("GA-MOCK-SEAL-")
    bank = ext.bank.open_basic_account(lic.unified_social_credit_code, p.proposed_name, "张三")
    assert bank.account_no.isdigit() or bank.account_no.isalnum()
    tax = ext.tax.register_tax(lic.unified_social_credit_code, p.proposed_name)
    assert tax.tax_id_hint
    soc = ext.social.open_social_and_fund(lic.unified_social_credit_code, p.proposed_name)
    assert soc.social_unit_no and soc.fund_unit_no
    perm = ext.permit.apply_post_permit(lic.unified_social_credit_code, p.proposed_name, "F5211")
    assert "F5211" in perm.permit_type or perm.permit_no


def test_review_supplement_then_approve() -> None:
    ext = build_mock_company_setup_externals()
    sub_id = "YWTB-MOCK-mock_supplement-abc"
    r0 = ext.review.poll_review(sub_id)
    assert r0.status == ReviewStatus.NEED_SUPPLEMENT
    r1 = ext.review.poll_review(sub_id)
    assert r1.status == ReviewStatus.APPROVED
