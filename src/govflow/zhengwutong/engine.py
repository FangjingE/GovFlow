"""
政务通分步填报引擎：分步计划（固定槽位顺序）+ 每轮执行一步（P&E 风格，无 LLM 工具环）。

越南语：通过 i18n + session.locale 扩展；NLU 仅中文规则，越文轮次后续可接翻译再进同一管道。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from govflow.zhengwutong.domain import BMTSession, BMTStep, DeclarationForm
from govflow.zhengwutong.field_explanations import get_explanation_for_step
from govflow.zhengwutong.i18n import t
from govflow.zhengwutong import knowledge as kn
from govflow.zhengwutong.faq_rag import run_zwt_faq
from govflow.config import Settings
from govflow.services.llm.protocols import AnswerAuditor, LLMClient
from govflow.services.rag.protocols import Retriever


@dataclass
class BMTResult:
    reply: str
    kind: str  # collecting | preview | submitted | need_human | cancelled | knowledge
    step: str
    form: dict
    form_preview: str
    plan_remaining: list[str]  # 仅用于调试/客户端展示「还剩几步」
    submit_receipt: str | None
    validation_warnings: list[str]
    # 本步「复杂名词」的通俗/模板说明，可供前端高亮；后续可接 LLM 扩写/替换
    field_explanation: str | None = None
    # RAG 答问时返回的引用条（knowledge 类回复）
    rag_sources: list[dict] | None = None


def _num(s: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", s.replace("，", ""))
    if not m:
        return None
    return float(m.group(1))


def _int_word(s: str) -> int | None:
    m = re.search(r"(\d+)", s)
    if not m:
        return None
    return int(m.group(1))


def _parse_gross_weight(text: str, net_kg: float | None) -> float | None:
    t = text.strip()
    if any(
        k in t
        for k in (
            "同净",
            "同净重",
            "和净重",
            "同上面",
            "一样",
            "相等",
        )
    ):
        return float(net_kg) if net_kg is not None and net_kg > 0 else None
    return _num(t)


def _parse_package(text: str) -> str:
    t = text.strip()[:32]
    if "散" in t:
        return "散装"
    if "箱" in t:
        return "箱装"
    if "袋" in t:
        return "袋装"
    if "筐" in t or "竹" in t or "篾" in t:
        return "筐装/竹筐等"
    return t or "—"


def _parse_transport(text: str) -> str:
    s = text.strip()[:64]
    if "委托" in s or "物流" in s or "大货" in s:
        return "委托/货运"
    if "小轿" in s or "私家" in s or "自用车" in s:
        return "自用汽车"
    if "摩托" in s or "电瓶" in s:
        return "摩托车/非机动车"
    if any(k in s for k in ("背", "提", "扛", "拎", "随身", "走路", "人带")):
        return "人身携运"
    if "边民" in s and "车" in s:
        return "边民自用车(演示分类)"
    return s or "—"


def _parse_value_basis(text: str) -> str:
    s = text.strip()
    if any(x in s for x in ("有票", "有发", "发票", "收据", "小票", "有单")):
        return "有发票/收据(演示)"
    if "无票" in s or "没票" in s or "估价" in s:
        return "无票/估价(演示)"
    if "指导" in s or "参考" in s or "牌" in s:
        return "互市参考价/指导价(演示)"
    if not s:
        return "—"
    return s[:32]


def _blank_tail(f: DeclarationForm) -> None:
    """自净重起后续字段（修改申报时自此处重采）。"""
    f.weight_kg = None
    f.gross_weight_kg = None
    f.piece_count = None
    f.package_type = ""
    f.transport_mode = ""
    f.origin = ""
    f.value_cny = None
    f.value_basis = ""
    f.purpose = ""
    f.regulatory_remark = ""


def _parse_io(text: str) -> str | None:
    s = text.strip()
    if "进口" in s:
        return "import"
    if "出口" in s:
        return "export"
    if s.startswith("进"):
        return "import"
    if s.startswith("出"):
        return "export"
    return None


def _form_to_dict(f: DeclarationForm) -> dict:
    return {
        "applicant_name": f.applicant_name,
        "border_pass_no": f.border_pass_no,
        "direction": f.direction,
        "goods_name": f.goods_name,
        "hs_code": f.hs_code,
        "weight_kg": f.weight_kg,
        "gross_weight_kg": f.gross_weight_kg,
        "piece_count": f.piece_count,
        "package_type": f.package_type,
        "transport_mode": f.transport_mode,
        "origin": f.origin,
        "value_cny": f.value_cny,
        "value_basis": f.value_basis,
        "currency": f.currency,
        "purpose": f.purpose,
        "regulatory_remark": f.regulatory_remark,
    }


def form_preview(f: DeclarationForm) -> str:
    """给客户端展示的申报单文本块（可替换为截屏/模板渲染）。"""
    return _preview_text(f)


def _preview_text(f: DeclarationForm) -> str:
    d = "进口" if f.direction == "import" else ("出口" if f.direction == "export" else "—")
    wn = f"{f.weight_kg:g}" if f.weight_kg is not None else "—"
    wg = f"{f.gross_weight_kg:g}" if f.gross_weight_kg is not None else "—"
    v = f"{f.value_cny:g}" if f.value_cny is not None else "—"
    pc = f"{f.piece_count}" if f.piece_count is not None else "—"
    reg = f.regulatory_remark or "—"
    if len(reg) > 64:
        reg = reg[:61] + "…"
    return (
        f"┌ 边境互市申报单（预览/演示，含税则/监管**展示**字段）\n"
        f"├ 申报人：{f.applicant_name or '—'}  证号：{f.border_pass_no or '（未登记）'}\n"
        f"├ 进出境：{d}  币制：{f.currency or 'CNY'}\n"
        f"├ 品名：{f.goods_name or '—'}  HS(示例)：{f.hs_code or '—'}\n"
        f"├ 净重(kg)：{wn}  毛重(kg)：{wg}  件/箱数：{pc}\n"
        f"├ 包装：{f.package_type or '—'}  携运方式：{f.transport_mode or '—'}\n"
        f"├ 产地：{f.origin or '—'}  总价(元)：{v}  价格依据：{f.value_basis or '—'}\n"
        f"├ 使用性质：{f.purpose or '—'}\n"
        f"├ 监管/检疫(展示)：[ {reg} ]\n"
        f"└ (上述 HS/监管 以海关认定为准)\n"
    )


def _plan_list(step: BMTStep) -> list[str]:
    order = [
        BMTStep.IO,
        BMTStep.GOODS,
        BMTStep.WEIGHT,
        BMTStep.GROSS,
        BMTStep.PIECES,
        BMTStep.PACK,
        BMTStep.TRANS,
        BMTStep.ORIGIN,
        BMTStep.VALUE,
        BMTStep.VALUE_BASIS,
        BMTStep.PURPOSE,
        BMTStep.PREVIEW,
        BMTStep.CONFIRM,
        BMTStep.DONE,
    ]
    if step in order:
        i = order.index(step)
        return [s.value for s in order[i:]]
    return [step.value]


class BMTDeclarationEngine:
    def __init__(
        self,
        retriever: Retriever | None = None,
        llm: LLMClient | None = None,
        auditor: AnswerAuditor | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._retriever: Retriever | None = retriever
        self._llm: LLMClient | None = llm
        self._auditor: AnswerAuditor | None = auditor
        self._settings: Settings | None = settings

    def handle(self, session: BMTSession, user_text: str) -> BMTResult:
        loc = session.locale
        text = user_text.strip()
        form = session.form
        warnings: list[str] = []

        def ok(reply: str, st: BMTStep) -> BMTResult:
            session.step = st
            session.misunderstand_count = 0
            _k = "collecting"
            if st == BMTStep.DONE:
                _k = "submitted"
            elif st == BMTStep.PREVIEW:
                _k = "preview"
            fe = get_explanation_for_step(st.value)
            return BMTResult(
                reply=reply,
                kind=_k,
                step=st.value,
                form=_form_to_dict(session.form),
                form_preview=_preview_text(session.form),
                plan_remaining=_plan_list(st),
                submit_receipt=session.submit_token,
                validation_warnings=warnings,
                field_explanation=fe,
            )

        if session.step == BMTStep.DONE:
            return BMTResult(
                reply=t("submitted", loc, token=session.submit_token or "—") if session.submit_token else "已结束。",
                kind="submitted",
                step=BMTStep.DONE.value,
                form=_form_to_dict(form),
                form_preview=_preview_text(form),
                plan_remaining=[],
                submit_receipt=session.submit_token,
                validation_warnings=[],
                field_explanation=None,
            )

        # 取消
        if "取消" in text or "不报了" in text:
            return BMTResult(
                reply=t("cancelled", loc),
                kind="cancelled",
                step=session.step.value,
                form=_form_to_dict(form),
                form_preview=_preview_text(form),
                plan_remaining=[],
                submit_receipt=None,
                validation_warnings=[],
                field_explanation=None,
            )

        # 咨询类问句：RAG + 大模型（不推进分步，会话步与已填表不变）
        if self._retriever and self._llm and self._auditor and self._settings:
            rfaq = run_zwt_faq(
                text, session, self._retriever, self._llm, self._auditor, self._settings
            )
            if rfaq is not None:
                rep, rsrc, fe, knd = rfaq
                return BMTResult(
                    reply=rep,
                    kind=knd,
                    step=session.step.value,
                    form=_form_to_dict(form),
                    form_preview=_preview_text(form),
                    plan_remaining=_plan_list(session.step),
                    submit_receipt=session.submit_token,
                    validation_warnings=warnings,
                    field_explanation=fe,
                    rag_sources=rsrc,
                )

        # 确认阶段
        if session.step == BMTStep.CONFIRM:
            if any(k in text for k in ("确认", "提交", "对", "没错")) and "不" not in text[:2]:
                session.step = BMTStep.DONE
                session.submit_token = f"ZWT-{uuid.uuid4().hex[:12].upper()}"
                return BMTResult(
                    reply=t("submitted", loc, token=session.submit_token),
                    kind="submitted",
                    step=BMTStep.DONE.value,
                    form=_form_to_dict(form),
                    form_preview=_preview_text(form),
                    plan_remaining=[],
                    submit_receipt=session.submit_token,
                    validation_warnings=[],
                    field_explanation=None,
                )
            if "改" in text or "修" in text or "重填" in text:
                session.step = BMTStep.WEIGHT
                _blank_tail(form)
                return ok(t("ask_weight", loc, goods=form.goods_name or "该商品"), BMTStep.WEIGHT)
            session.misunderstand_count += 1
            if session.misunderstand_count >= kn.MAX_MISUNDERSTAND:
                return self._need_human(session, loc, warnings)
            return BMTResult(
                reply="请说「确认提交」完成，或说「修改」返回调整。",
                kind="collecting",
                step=BMTStep.CONFIRM.value,
                form=_form_to_dict(form),
                form_preview=_preview_text(form),
                plan_remaining=_plan_list(BMTStep.CONFIRM),
                submit_receipt=None,
                validation_warnings=[],
                field_explanation=None,
            )

        if session.step == BMTStep.PREVIEW:
            v = _validate_all(form, warnings, loc)
            if not v.get("ok") and v.get("block"):
                session.misunderstand_count = 0
                return ok(
                    t("not_in_catalog", loc, name=form.goods_name) if "not catalog" in str(v.get("msg")) else (str(v.get("msg")) or "请调整。"),
                    BMTStep.GOODS,
                )
            if "读" in text or "念" in text or ("看" in text and "表" in text) or ("对" in text and "一下" in text):
                readback = f"商品{form.goods_name}，{form.weight_kg}公斤，价值{form.value_cny}元，{form.origin}"
                session.misunderstand_count = 0
                return BMTResult(
                    reply=t("confirm_readback", loc, readback=readback) + " 说「确认提交」即可上报（演示）。",
                    kind="preview",
                    step=BMTStep.PREVIEW.value,
                    form=_form_to_dict(form),
                    form_preview=_preview_text(form),
                    plan_remaining=_plan_list(BMTStep.PREVIEW),
                    submit_receipt=None,
                    validation_warnings=warnings,
                    field_explanation=get_explanation_for_step("regulatory_remark"),
                )
            if any(k in text for k in ("对", "确认", "提交", "是", "好")) and "不" not in text[:1]:
                session.misunderstand_count = 0
                return ok(
                    "为防误报，请明确说：【确认提交】四个字。或说【修改】改内容。",
                    BMTStep.CONFIRM,
                )
            if "改" in text or "重" in text:
                session.step = BMTStep.WEIGHT
                _blank_tail(form)
                return ok(t("ask_weight", loc, goods=form.goods_name or "商品"), BMTStep.WEIGHT)
            session.misunderstand_count += 1
            r = t("preview_intro", loc) if session.misunderstand_count < 2 else t("need_human", loc)
            if session.misunderstand_count >= kn.MAX_MISUNDERSTAND:
                return self._need_human(session, loc, warnings)
            return BMTResult(
                reply=r,
                kind="preview",
                step=BMTStep.PREVIEW.value,
                form=_form_to_dict(form),
                form_preview=_preview_text(form),
                plan_remaining=_plan_list(BMTStep.PREVIEW),
                submit_receipt=None,
                validation_warnings=warnings,
                field_explanation=get_explanation_for_step("regulatory_remark"),
            )

        st = session.step
        if st == BMTStep.IO:
            io = _parse_io(text)
            if not io:
                session.misunderstand_count = (session.misunderstand_count or 0) + 1
                if session.misunderstand_count >= kn.MAX_MISUNDERSTAND:
                    return self._need_human(session, loc, warnings)
                return BMTResult(
                    reply=t("ask_io_clarify", loc),
                    kind="collecting",
                    step=BMTStep.IO.value,
                    form=_form_to_dict(form),
                    form_preview=_preview_text(form),
                    plan_remaining=_plan_list(BMTStep.IO),
                    submit_receipt=None,
                    validation_warnings=[],
                    field_explanation=None,
                )
            form.direction = io
            return ok(t("ask_goods", loc), BMTStep.GOODS)

        if st == BMTStep.GOODS:
            g = kn.norm_goods(text)
            if len(g) < 2:
                session.misunderstand_count += 1
                if session.misunderstand_count >= kn.MAX_MISUNDERSTAND:
                    return self._need_human(session, loc, warnings)
                return BMTResult(
                    reply="请说清楚商品名称，如：火龙果。",
                    kind="collecting",
                    step=BMTStep.GOODS.value,
                    form=_form_to_dict(form),
                    form_preview=_preview_text(form),
                    plan_remaining=_plan_list(BMTStep.GOODS),
                    submit_receipt=None,
                    validation_warnings=[],
                    field_explanation=None,
                )
            form.goods_name = g
            code, in_cat = kn.GOODS_CATALOG.get(g, ("", True))
            if g in kn.GOODS_CATALOG and not in_cat:
                return ok(t("not_in_catalog", loc, name=g), BMTStep.GOODS)
            form.hs_code = code or "见窗口归类"
            return ok(t("ask_weight", loc, goods=g), BMTStep.WEIGHT)

        if st == BMTStep.WEIGHT:
            w = _num(text)
            if w is None or w <= 0:
                session.misunderstand_count += 1
                if session.misunderstand_count >= kn.MAX_MISUNDERSTAND:
                    return self._need_human(session, loc, warnings)
                return BMTResult(
                    reply="小边需要【净重/主数量，公斤数】，请说数字，如：30。",
                    kind="collecting",
                    step=BMTStep.WEIGHT.value,
                    form=_form_to_dict(form),
                    form_preview=_preview_text(form),
                    plan_remaining=_plan_list(BMTStep.WEIGHT),
                    submit_receipt=None,
                    validation_warnings=[],
                    field_explanation=None,
                )
            form.weight_kg = w
            if w > kn.SUSPICIOUS_WEIGHT_KG:
                warnings.append(f"数量{w}公斤偏大（演示仅提示）")
            return ok(t("ask_gross", loc), BMTStep.GROSS)

        if st == BMTStep.GROSS:
            gw = _parse_gross_weight(text, form.weight_kg)
            if gw is None or gw <= 0:
                session.misunderstand_count += 1
                if session.misunderstand_count >= kn.MAX_MISUNDERSTAND:
                    return self._need_human(session, loc, warnings)
                return BMTResult(
                    reply="请说毛重公斤数，或说「同净重」。",
                    kind="collecting",
                    step=BMTStep.GROSS.value,
                    form=_form_to_dict(form),
                    form_preview=_preview_text(form),
                    plan_remaining=_plan_list(BMTStep.GROSS),
                    submit_receipt=None,
                    validation_warnings=[],
                    field_explanation=get_explanation_for_step(BMTStep.GROSS.value),
                )
            form.gross_weight_kg = gw
            if form.weight_kg and gw + 0.01 < form.weight_kg:
                warnings.append("毛重小于净重(演示请核对)")
            return ok(t("ask_pieces", loc), BMTStep.PIECES)

        if st == BMTStep.PIECES:
            pc = _int_word(text)
            if pc is None or pc < 1 or pc > 9_999:
                session.misunderstand_count += 1
                if session.misunderstand_count >= kn.MAX_MISUNDERSTAND:
                    return self._need_human(session, loc, warnings)
                return BMTResult(
                    reply="请说【整数】件数或箱数，如：1、3。",
                    kind="collecting",
                    step=BMTStep.PIECES.value,
                    form=_form_to_dict(form),
                    form_preview=_preview_text(form),
                    plan_remaining=_plan_list(BMTStep.PIECES),
                    submit_receipt=None,
                    validation_warnings=[],
                    field_explanation=get_explanation_for_step(BMTStep.PIECES.value),
                )
            form.piece_count = pc
            return ok(t("ask_package", loc), BMTStep.PACK)

        if st == BMTStep.PACK:
            if len(text) < 1:
                session.misunderstand_count += 1
                if session.misunderstand_count >= kn.MAX_MISUNDERSTAND:
                    return self._need_human(session, loc, warnings)
                return BMTResult(
                    reply="请说包装，如：袋装。",
                    kind="collecting",
                    step=BMTStep.PACK.value,
                    form=_form_to_dict(form),
                    form_preview=_preview_text(form),
                    plan_remaining=_plan_list(BMTStep.PACK),
                    submit_receipt=None,
                    validation_warnings=[],
                    field_explanation=get_explanation_for_step(BMTStep.PACK.value),
                )
            form.package_type = _parse_package(text)
            return ok(t("ask_transport", loc), BMTStep.TRANS)

        if st == BMTStep.TRANS:
            if len(text) < 1:
                session.misunderstand_count += 1
                if session.misunderstand_count >= kn.MAX_MISUNDERSTAND:
                    return self._need_human(session, loc, warnings)
                return BMTResult(
                    reply="请说怎么把货运到口岸的，如：自己背。",
                    kind="collecting",
                    step=BMTStep.TRANS.value,
                    form=_form_to_dict(form),
                    form_preview=_preview_text(form),
                    plan_remaining=_plan_list(BMTStep.TRANS),
                    submit_receipt=None,
                    validation_warnings=[],
                    field_explanation=get_explanation_for_step(BMTStep.TRANS.value),
                )
            form.transport_mode = _parse_transport(text)
            return ok(t("ask_origin", loc), BMTStep.ORIGIN)

        if st == BMTStep.ORIGIN:
            if len(text) < 2:
                session.misunderstand_count += 1
                if session.misunderstand_count >= kn.MAX_MISUNDERSTAND:
                    return self._need_human(session, loc, warnings)
                return BMTResult(
                    reply="请说国家或地区，如：越南。",
                    kind="collecting",
                    step=BMTStep.ORIGIN.value,
                    form=_form_to_dict(form),
                    form_preview=_preview_text(form),
                    plan_remaining=_plan_list(BMTStep.ORIGIN),
                    submit_receipt=None,
                    validation_warnings=[],
                    field_explanation=None,
                )
            form.origin = text[:32]
            return ok(t("ask_value", loc), BMTStep.VALUE)

        if st == BMTStep.VALUE:
            v = _num(text)
            if v is None or v < 0:
                session.misunderstand_count += 1
                if session.misunderstand_count >= kn.MAX_MISUNDERSTAND:
                    return self._need_human(session, loc, warnings)
                return BMTResult(
                    reply="请说【人民币】金额，如：450。",
                    kind="collecting",
                    step=BMTStep.VALUE.value,
                    form=_form_to_dict(form),
                    form_preview=_preview_text(form),
                    plan_remaining=_plan_list(BMTStep.VALUE),
                    submit_receipt=None,
                    validation_warnings=[],
                    field_explanation=None,
                )
            form.value_cny = v
            if v > kn.MUT_SHI_CNY_PER_TICKET:
                return BMTResult(
                    reply=t("over_limit", loc, limit=int(kn.MUT_SHI_CNY_PER_TICKET)),
                    kind="collecting",
                    step=BMTStep.VALUE.value,
                    form=_form_to_dict(form),
                    form_preview=_preview_text(form),
                    plan_remaining=_plan_list(BMTStep.VALUE),
                    submit_receipt=None,
                    validation_warnings=[f"已超{kn.MUT_SHI_CNY_PER_TICKET}元示例限额"],
                    field_explanation=None,
                )
            return ok(t("ask_value_basis", loc), BMTStep.VALUE_BASIS)

        if st == BMTStep.VALUE_BASIS:
            if len(text) < 1:
                session.misunderstand_count += 1
                if session.misunderstand_count >= kn.MAX_MISUNDERSTAND:
                    return self._need_human(session, loc, warnings)
                return BMTResult(
                    reply="请说价格依据，如有发票、无票、指导价等。",
                    kind="collecting",
                    step=BMTStep.VALUE_BASIS.value,
                    form=_form_to_dict(form),
                    form_preview=_preview_text(form),
                    plan_remaining=_plan_list(BMTStep.VALUE_BASIS),
                    submit_receipt=None,
                    validation_warnings=[],
                    field_explanation=get_explanation_for_step(BMTStep.VALUE_BASIS.value),
                )
            form.value_basis = _parse_value_basis(text)
            return ok(t("ask_purpose", loc), BMTStep.PURPOSE)

        if st == BMTStep.PURPOSE:
            if ("代购" in text) or ("带别人" in text) or ("帮" in text and "人" in text):
                form.purpose = "代购"
            else:
                form.purpose = "自用"
            session.misunderstand_count = 0
            wlist: list[str] = []
            vres = _validate_all(form, wlist, loc)
            if vres.get("ok") is False and vres.get("block"):
                return ok(
                    t("not_in_catalog", loc, name=form.goods_name),
                    BMTStep.GOODS,
                )
            form.regulatory_remark = kn.regulatory_remark_for(
                form.goods_name, form.hs_code or ""
            )
            session.step = BMTStep.PREVIEW
            r = t("preview_intro", loc) + "\n" + _preview_text(form)
            if wlist:
                r += "\n提示：" + "；".join(wlist)
            return BMTResult(
                reply=r,
                kind="preview",
                step=BMTStep.PREVIEW.value,
                form=_form_to_dict(form),
                form_preview=_preview_text(form),
                plan_remaining=_plan_list(BMTStep.PREVIEW),
                submit_receipt=None,
                validation_warnings=wlist,
                field_explanation=get_explanation_for_step("regulatory_remark"),
            )

        return BMTResult(
            reply="（演示）请从进口/出口开始。",
            kind="collecting",
            step=session.step.value,
            form=_form_to_dict(form),
            form_preview=_preview_text(form),
            plan_remaining=_plan_list(BMTStep.IO),
            submit_receipt=None,
            validation_warnings=[],
            field_explanation=None,
        )

    def _need_human(self, session: BMTSession, loc: str, warnings: list[str]) -> BMTResult:
        return BMTResult(
            reply=t("need_human", loc),
            kind="need_human",
            step=session.step.value,
            form=_form_to_dict(session.form),
            form_preview=_preview_text(session.form),
            plan_remaining=[],
            submit_receipt=None,
            validation_warnings=warnings,
            field_explanation=None,
        )

    def opening_message(self, session: BMTSession) -> str:
        return t("opening", session.locale)


def _validate_all(
    f: DeclarationForm, warnings: list[str], _loc: str
) -> dict:
    g = f.goods_name
    if g in kn.GOODS_CATALOG and not kn.GOODS_CATALOG[g][1]:
        return {"ok": False, "msg": f"not catalog {g}", "block": True}
    w = f.weight_kg
    if w and w > kn.SUSPICIOUS_WEIGHT_KG:
        warnings.append(f"重量{w}kg 偏大")
    v = f.value_cny
    if v and v > kn.MUT_SHI_CNY_PER_TICKET:
        return {"ok": False, "msg": "over", "block": False}
    return {"ok": True, "msg": None}
