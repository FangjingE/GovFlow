"""按 docs/ARCHITECTURE.md「六、输出模板」渲染纯文本（不经大模型）。"""

from __future__ import annotations

from jinja2 import Environment, BaseLoader, select_autoescape

from govflow.services.gov_types import GovServiceRow, MaterialRow, ProcessRow
from govflow.services.retrieval_policy import build_clarify_question, build_option_label

_TEMPLATE = """事项名称：{{ service_name }}
办理部门：{{ department }}
办理地点：{{ handle_address }}
通办范围：{{ general_scope }}
服务对象：{{ service_object }}
法定时限：{{ legal_days }}个工作日
承诺时限：{{ promise_days }}个工作日
到现场次数：{{ on_site_times }}次
是否收费：{{ is_charge }}{% if is_charge == '是' %}
办理方式：{{ handle_way }}（线上/线下/自助）
是否网办：{{ is_online }}
查询方式：{{ query_way }}
办件类型: {{ item_type }}
办理时间: {{ handle_time }}
咨询方式: {{ consult_way }}
监督投诉方式: {{ complaint_way }}
{% endif %}
【申请材料】
{% for item in materials %}
- {{ item.material_name }}
{% endfor %}

【办理流程】
{% for step in processes %}
- {{ loop.index }}. {{ step.step_name }}：{{ step.step_desc }}
{% endfor %}

用户问题：{{ query }}
"""

_env = Environment(
    loader=BaseLoader(),
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _fmt_days(v: int | None) -> str:
    if v is None:
        return "—"
    return str(v)


def _derive_online(handle_form: str | None) -> str:
    if not handle_form:
        return "—"
    return "是" if "网" in handle_form else "否"


def render_service_answer(
    *,
    service: GovServiceRow,
    materials: list[MaterialRow],
    processes: list[ProcessRow],
    query: str,
) -> str:
    is_charge = "是" if service.is_charge else "否"
    ctx = {
        "service_name": service.service_name,
        "department": service.department or "—",
        "handle_address": service.handle_address or "—",
        "general_scope": service.general_scope or "—",
        "service_object": service.service_object or "—",
        "legal_days": _fmt_days(service.legal_days),
        "promise_days": _fmt_days(service.promise_days),
        "on_site_times": _fmt_days(service.on_site_times),
        "is_charge": is_charge,
        "handle_way": service.handle_form or "—",
        "is_online": _derive_online(service.handle_form),
        "query_way": service.query_way or "—",
        "item_type": service.item_type or "—",
        "handle_time": service.handle_time or "—",
        "consult_way": service.consult_way or "—",
        "complaint_way": service.complaint_way or "—",
        "materials": materials,
        "processes": processes,
        "query": query.strip(),
    }
    return _env.from_string(_TEMPLATE).render(**ctx).strip() + "\n"


def render_clarify_prompt(
    *,
    candidates: list[GovServiceRow],
    hotline: str,
) -> tuple[str, str, list[str]]:
    question = build_clarify_question(candidates)
    show_department = len({svc.department for svc in candidates if svc.department}) > 1
    show_service_object = len({svc.service_object for svc in candidates if svc.service_object}) > 1
    option_labels = [
        build_option_label(
            svc,
            show_department=show_department,
            show_service_object=show_service_object,
        )
        for svc in candidates
    ]
    lines = [question, "你要查询的是否是以下事项之一？"]
    lines.extend(f"{idx}. {label}" for idx, label in enumerate(option_labels, start=1))
    lines.append("你可以直接发送更接近的事项名称，或补充更具体的关键词。")
    lines.append(f"咨询电话：{hotline}")
    return "\n".join(lines), question, option_labels


def render_fallback_prompt(
    *,
    candidates: list[GovServiceRow],
    hotline: str,
) -> str:
    lines = ["未在事项库中匹配到足够相关的一条政务事项。"]
    if candidates:
        show_department = len({svc.department for svc in candidates if svc.department}) > 1
        show_service_object = len({svc.service_object for svc in candidates if svc.service_object}) > 1
        lines.append("如果接近你的问题，可参考以下事项：")
        lines.extend(
            f"{idx}. {build_option_label(svc, show_department=show_department, show_service_object=show_service_object)}"
            for idx, svc in enumerate(candidates, start=1)
        )
    else:
        lines.append("请尝试补充更准确的事项关键词。")
    lines.append("请尝试更准确地描述，或拨打政务服务热线咨询。")
    lines.append(f"咨询电话：{hotline}")
    return "\n".join(lines)
