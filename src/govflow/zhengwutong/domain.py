"""政务通分步填报领域对象：申报单与会话态（与 HTTP 解耦）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

DeclarationLocale = Literal["zh-CN", "vi-VN"]


class BMTStep(str, Enum):
    """当前待采集槽位 / 阶段（分步计划，顺序由引擎推进）。"""

    IO = "import_export"  # 进口 / 出口
    GOODS = "goods_name"
    WEIGHT = "weight_kg"  # 净重/主数量（kg）
    GROSS = "gross_kg"  # 毛重
    PIECES = "piece_count"  # 件数/箱数
    PACK = "package"  # 包装
    TRANS = "transport"  # 携运方式
    ORIGIN = "origin"
    VALUE = "value_cny"
    VALUE_BASIS = "value_basis"  # 价格依据
    PURPOSE = "purpose"  # 自用 / 代购
    PREVIEW = "preview"  # 已填完，展示并进入确认前
    CONFIRM = "confirm"  # 等用户最终确认
    DONE = "done"  # 已提交


@dataclass
class DeclarationForm:
    """边民互市申报单（含若干海关/贸易向字段；解释见 field_explanations）。"""

    applicant_name: str = ""
    border_pass_no: str = ""  # 边民证号，演示可空
    direction: str | None = None  # "import" | "export"
    goods_name: str = ""
    hs_code: str = ""
    # 净重/主数量（原「多少公斤」）
    weight_kg: float | None = None
    # 毛重（含包装），常≥净重
    gross_weight_kg: float | None = None
    # 件数、箱数
    piece_count: int | None = None
    # 包装：散装/箱装/袋装/筐装等
    package_type: str = ""
    # 携运：人身携带/自带车/委托运输等
    transport_mode: str = ""
    origin: str = ""  # 如：越南
    value_cny: float | None = None
    # 价格依据：有票/无票/指导价/其他
    value_basis: str = ""
    purpose: str = ""  # 自用 / 代购
    currency: str = "CNY"
    # 监管/税则/检疫向只读说明（由规则/知识生成，可后续接 LLM 扩写）
    regulatory_remark: str = ""
    notes: str = field(default="")


@dataclass
class BMTSession:
    id: str
    locale: DeclarationLocale = "zh-CN"
    step: BMTStep = BMTStep.IO
    form: DeclarationForm = field(default_factory=DeclarationForm)
    # 当用户答非所问、识别失败
    last_question_field: str | None = None
    misunderstand_count: int = 0
    validation_errors: list[str] = field(default_factory=list)
    submit_token: str | None = None  # 申报成功后的占位回执
    # 最近几轮用户原话（RAG/多轮 FAQ 用；不含当轮，由 API 在 handle 之后追加入库）
    recent_user_lines: list[str] = field(default_factory=list)
