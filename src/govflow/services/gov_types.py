"""政务事项行模型（无数据库驱动依赖）。"""

from __future__ import annotations

from dataclasses import dataclass

EMBEDDING_DIM = 768


@dataclass
class GovServiceRow:
    id: int
    service_name: str
    department: str | None
    service_object: str | None
    promise_days: int | None
    legal_days: int | None
    on_site_times: int | None
    is_charge: bool | None
    accept_condition: str | None
    general_scope: str | None
    handle_form: str | None
    item_type: str | None
    handle_address: str | None
    handle_time: str | None
    consult_way: str | None
    complaint_way: str | None
    query_way: str | None
    match_score: float | None = None


@dataclass
class MaterialRow:
    material_name: str
    is_required: bool | None
    material_form: str | None
    original_num: int | None
    copy_num: int | None
    note: str | None


@dataclass
class ProcessRow:
    step_name: str | None
    step_desc: str | None
    sort: int
