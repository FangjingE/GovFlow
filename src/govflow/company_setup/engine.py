"""
企业设立主计划（P&E）：固定步骤采集 → 名称 mock → 一网通办提交 → 审核轮询 →
执照与后续节点批量 mock → 后置许可询问。

节点内复杂政策问答可后续接 RAG/ReAct；本模块只推进计划与调用 integrations mock。
"""

from __future__ import annotations

from dataclasses import dataclass

from govflow.company_setup.domain import CompanySetupSession, CompanySetupStep
from govflow.services.integrations.company_setup.types import (
    CompanyBasicProfile,
    EstablishmentMaterials,
    NameReservationRequest,
    ReviewStatus,
)


@dataclass
class CompanyTurnResult:
    reply: str
    kind: str
    step: str
    progress_preview: str


def _preview(sess: CompanySetupSession) -> str:
    lines = [
        "【企业设立演示进度】",
        f"步骤: {sess.step.value}",
        f"类型: {sess.company_type or '（待填）'}",
        f"拟定名称: {sess.proposed_name or '（待填）'}",
        f"住所: {sess.registered_address or '（待填）'}",
        f"股东: {sess.shareholders_summary or '（待填）'}",
        f"经营范围: {sess.business_scope or '（待填）'}",
    ]
    if sess.name_notice_no:
        lines.append(f"名称通知书: {sess.name_notice_no}")
    if sess.submission_id:
        lines.append(f"设立受理号: {sess.submission_id}")
    if sess.license:
        lines.append(f"统一社会信用代码: {sess.license.unified_social_credit_code}")
        lines.append(f"法定代表人: {sess.license.legal_representative}")
    return "\n".join(lines)


def _has_company_type_signal(t: str) -> bool:
    u = t.strip()
    if len(u) < 2:
        return False
    keys = ("公司", "独资", "合伙", "分公司", "有限", "责任", "企业", "个体")
    return any(k in u for k in keys)


class CompanySetupPAndE:
    """无状态引擎：每轮读写传入的 CompanySetupSession。"""

    def handle(self, sess: CompanySetupSession, user_text: str) -> CompanyTurnResult:
        t = (user_text or "").strip()
        ext = sess.externals
        pv = _preview(sess)

        if sess.step == CompanySetupStep.COMPLETE:
            return CompanyTurnResult(
                reply="当前会话中的企业设立演示已办结。如需重新开始，请新开对话并再次选择「办企业」流程。",
                kind="company_complete",
                step=sess.step.value,
                progress_preview=pv,
            )

        if sess.step == CompanySetupStep.ASK_COMPANY_TYPE:
            if not _has_company_type_signal(t):
                return CompanyTurnResult(
                    reply="请用一句话说明拟设立主体的**类型**（例如：有限责任公司、个人独资企业、分公司）。",
                    kind="company_collecting",
                    step=sess.step.value,
                    progress_preview=pv,
                )
            sess.company_type = t
            sess.step = CompanySetupStep.ASK_PROPOSED_NAME
            pv = _preview(sess)
            return CompanyTurnResult(
                reply="已记录。请提供**拟定企业名称**（行政区划 + 字号 + 行业 + 组织形式，可按当地习惯口述）。",
                kind="company_collecting",
                step=sess.step.value,
                progress_preview=pv,
            )

        if sess.step == CompanySetupStep.ASK_PROPOSED_NAME:
            if len(t) < 4:
                return CompanyTurnResult(
                    reply="名称过短，请提供完整的**拟定名称**（至少四个字以上较易通过演示核名）。",
                    kind="company_collecting",
                    step=sess.step.value,
                    progress_preview=pv,
                )
            sess.proposed_name = t
            sess.step = CompanySetupStep.ASK_ADDRESS
            pv = _preview(sess)
            return CompanyTurnResult(
                reply="已记录。请填写**住所（注册地址）**或主要经营场所，精确到市、区与道路门牌（演示可简写）。",
                kind="company_collecting",
                step=sess.step.value,
                progress_preview=pv,
            )

        if sess.step == CompanySetupStep.ASK_ADDRESS:
            if len(t) < 4:
                return CompanyTurnResult(
                    reply="请补充更具体的**住所**信息（省市区 + 路街巷门牌或园区楼栋）。",
                    kind="company_collecting",
                    step=sess.step.value,
                    progress_preview=pv,
                )
            sess.registered_address = t
            sess.step = CompanySetupStep.ASK_SHAREHOLDERS
            pv = _preview(sess)
            return CompanyTurnResult(
                reply="已记录。请简述**股东及出资比例**（自然人姓名 + 百分比即可，演示用）。",
                kind="company_collecting",
                step=sess.step.value,
                progress_preview=pv,
            )

        if sess.step == CompanySetupStep.ASK_SHAREHOLDERS:
            if len(t) < 2:
                return CompanyTurnResult(
                    reply="请至少填写一名股东或出资人及大致比例。",
                    kind="company_collecting",
                    step=sess.step.value,
                    progress_preview=pv,
                )
            sess.shareholders_summary = t
            sess.step = CompanySetupStep.ASK_BUSINESS_SCOPE
            pv = _preview(sess)
            return CompanyTurnResult(
                reply="已记录。请描述**经营范围**（可写大类，如：软件开发、技术咨询；演示无需与国民经济行业分类逐条对齐）。",
                kind="company_collecting",
                step=sess.step.value,
                progress_preview=pv,
            )

        if sess.step == CompanySetupStep.ASK_BUSINESS_SCOPE:
            if len(t) < 4:
                return CompanyTurnResult(
                    reply="经营范围请稍具体一些（至少一句业务描述）。",
                    kind="company_collecting",
                    step=sess.step.value,
                    progress_preview=pv,
                )
            sess.business_scope = t
            return self._reserve_submit_and_poll(sess)

        if sess.step == CompanySetupStep.NAME_RETRY:
            if len(t) < 4:
                return CompanyTurnResult(
                    reply="请重新提供完整的**拟定名称**（避免使用演示禁名「mock_reject」子串）。",
                    kind="company_collecting",
                    step=sess.step.value,
                    progress_preview=pv,
                )
            sess.proposed_name = t
            return self._reserve_submit_and_poll(sess)

        if sess.step == CompanySetupStep.REVIEW_POLL:
            sid = sess.submission_id or ""
            pr = ext.review.poll_review(sid)
            pv = _preview(sess)
            if pr.status == ReviewStatus.REJECTED:
                sess.step = CompanySetupStep.COMPLETE
                return CompanyTurnResult(
                    reply="（演示）登记机关已驳回本次设立申请。可咨询当地窗口或修改材料后重新发起。\n"
                    + (pr.supplement_opinion or ""),
                    kind="company_rejected",
                    step=sess.step.value,
                    progress_preview=pv,
                )
            if pr.status == ReviewStatus.NEED_SUPPLEMENT:
                op = pr.supplement_opinion or "请按窗口意见补正材料。"
                return CompanyTurnResult(
                    reply=f"（演示）审核状态：**需补正**。\n{op}\n\n补正后请发送「**继续**」以再次查询审核结果。",
                    kind="company_review",
                    step=sess.step.value,
                    progress_preview=pv,
                )
            if pr.status == ReviewStatus.SUBMITTED:
                return CompanyTurnResult(
                    reply="（演示）申请仍在**审核中**。请稍后发送「**继续**」查询进度。",
                    kind="company_review",
                    step=sess.step.value,
                    progress_preview=pv,
                )
            if pr.status == ReviewStatus.APPROVED:
                return self._post_approval_batch(sess)

        if sess.step == CompanySetupStep.ASK_PERMIT_NEED:
            t2 = t.strip()
            neg = (
                "不是" in t
                or "没有" in t
                or "不要" in t
                or "不用" in t
                or "不需要" in t
                or t2 in ("否", "不", "无", "跳过", "暂不", "n", "no")
            )
            pos = t2 in ("是", "好", "要", "行", "嗯", "y", "yes") or t2.startswith(
                ("好的", "需要", "要办", "办理")
            )
            if neg:
                sess.step = CompanySetupStep.COMPLETE
                pv = _preview(sess)
                return CompanyTurnResult(
                    reply="已跳过后置许可环节。企业设立演示流程结束。",
                    kind="company_complete",
                    step=sess.step.value,
                    progress_preview=pv,
                )
            if pos:
                code = sess.permit_industry_code or "F5211"
                lic = sess.license
                uscc = lic.unified_social_credit_code if lic else ""
                name = sess.proposed_name or "未命名主体"
                rec = ext.permit.apply_post_permit(uscc, name, code)
                sess.step = CompanySetupStep.COMPLETE
                pv = _preview(sess)
                return CompanyTurnResult(
                    reply=(
                        "已为您模拟办理**后置许可**：\n"
                        f"- 类型：{rec.permit_type}\n"
                        f"- 许可证编号：{rec.permit_no}\n\n"
                        "企业设立演示流程已全部完成。实际以主管部门系统为准。"
                    ),
                    kind="company_complete",
                    step=sess.step.value,
                    progress_preview=pv,
                )
            return CompanyTurnResult(
                reply="请直接回复是否需要办理食品经营等**后置许可**：「**是**」或「**否**」。",
                kind="company_collecting",
                step=sess.step.value,
                progress_preview=pv,
            )

        return CompanyTurnResult(
            reply="（内部状态异常）请新开对话重试。",
            kind="company_error",
            step=sess.step.value,
            progress_preview=pv,
        )

    def _reserve_submit_and_poll(self, sess: CompanySetupSession) -> CompanyTurnResult:
        ext = sess.externals
        assert sess.proposed_name and sess.company_type and sess.registered_address
        assert sess.shareholders_summary and sess.business_scope
        nr = ext.names.reserve_name(
            NameReservationRequest(proposed_name=sess.proposed_name, company_type=sess.company_type)
        )
        if not nr.approved:
            sess.step = CompanySetupStep.NAME_RETRY
            pv = _preview(sess)
            reason = nr.rejection_reason or "名称未通过"
            return CompanyTurnResult(
                reply=f"（演示）市场监管名称申报未通过：{reason}\n请发送**新的拟定名称**（整句即可）。",
                kind="company_name_reject",
                step=sess.step.value,
                progress_preview=pv,
            )
        sess.name_notice_no = nr.reservation_notice_no
        prof = CompanyBasicProfile(
            company_type=sess.company_type,
            proposed_name=sess.proposed_name,
            registered_address=sess.registered_address,
            shareholders_summary=sess.shareholders_summary,
            business_scope=sess.business_scope,
        )
        sub = ext.portal.submit_establishment(
            EstablishmentMaterials(
                profile=prof,
                name_reservation_notice_no=sess.name_notice_no or "",
                attachments_manifest=("章程（演示）.pdf", "住所证明（演示）.pdf"),
            )
        )
        sess.submission_id = sub.submission_id
        sess.step = CompanySetupStep.REVIEW_POLL
        pr = ext.review.poll_review(sess.submission_id)
        pv = _preview(sess)
        if pr.status == ReviewStatus.APPROVED:
            return self._post_approval_batch(sess)
        if pr.status == ReviewStatus.NEED_SUPPLEMENT:
            return CompanyTurnResult(
                reply=(
                    "（演示）已通过**名称申报**并在一网通办**提交设立材料**。\n"
                    f"受理号：`{sess.submission_id}`\n"
                    f"当前审核：**需补正** — {pr.supplement_opinion or ''}\n\n"
                    "补正完成后请发送「**继续**」再次查询审核结果。"
                ),
                kind="company_review",
                step=sess.step.value,
                progress_preview=pv,
            )
        return CompanyTurnResult(
            reply=(
                "（演示）已通过**名称申报**并在一网通办**提交设立材料**。\n"
                f"受理号：`{sess.submission_id}`\n"
                "当前状态：**审核中**。请发送「**继续**」查询进度。"
            ),
            kind="company_review",
            step=sess.step.value,
            progress_preview=pv,
        )

    def _post_approval_batch(self, sess: CompanySetupSession) -> CompanyTurnResult:
        ext = sess.externals
        sub_id = sess.submission_id or ""
        name = sess.proposed_name or "未命名主体"
        legal = "法定代表人（演示）"
        if sess.shareholders_summary and len(sess.shareholders_summary) <= 32:
            legal = sess.shareholders_summary.split("；")[0].split("%")[0].strip() or legal

        lic = ext.license_.issue_business_license(sub_id, legal_name=legal)
        sess.license = lic
        ext.seal.file_seals(lic.unified_social_credit_code, name)
        ext.bank.open_basic_account(lic.unified_social_credit_code, name, legal)
        ext.tax.register_tax(lic.unified_social_credit_code, name)
        ext.social.open_social_and_fund(lic.unified_social_credit_code, name)

        sess.step = CompanySetupStep.ASK_PERMIT_NEED
        sess.permit_industry_code = "F5211"
        pv = _preview(sess)
        return CompanyTurnResult(
            reply=(
                "（演示）设立申请**已核准**。以下为模拟串联结果（非真实政务数据）：\n"
                f"- 统一社会信用代码：`{lic.unified_social_credit_code}`\n"
                f"- 执照编号：`{lic.license_no}`\n"
                "- 已完成：公安刻章备案、基本户开立、税务报到、社保与公积金开户（均为 mock）。\n\n"
                "**是否涉及**需办理的后置许可（如食品经营许可）？请回复「**是**」或「**否**」。"
            ),
            kind="company_post_reg",
            step=sess.step.value,
            progress_preview=pv,
        )
