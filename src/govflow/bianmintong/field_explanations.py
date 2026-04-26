"""
边民通复杂字段的通俗说明（MVP 为模板，后续可接 DeepSeek/专用模型动态生成 field_explanation）。

与 domain.BMTStep 中「需解释」的槽位一一对应；键名用 step 的 .value 字符串，便于按步查找。
"""

from __future__ import annotations

# 可单独展示在 UI「说明区」；勿替代法律/海关具有效力的解释。
FIELD_EXPLANATIONS: dict[str, str] = {
    "gross_kg": (
        "【净重与毛重】净重多指**可计价的商品本体重量**（如水果可食部分+必要损耗）；"
        "毛重含**所有包装、筐、箱、绑扎物**。边民互市在统计、计税或抽查时，两者都可能用到；以当日口岸要求为准。"
    ),
    "piece_count": (
        "【件数/箱数】本批货分成**几箱、几袋、几件**申报，有利于现场核对称重与**单件限额**核对；若就一箱可填 1 或说「一筐」。"
    ),
    "package": (
        "【包装方式】如散装、箱装、袋装、**竹筐+薄膜**等，会影响**检疫处理**、毛重及是否原包装入境；用日常说法即可，以窗口归类为准。"
    ),
    "transport": (
        "【运输/携运方式】例如：**人身携带、肩挑背驮、自用小汽车、委托货车**等。不同方式在**通道、查验、额度**上可能有差异，请如实说「怎么把货运到口岸」的。"
    ),
    "value_basis": (
        "【价格依据/审价】关员**审价**时常用。有发票/收据请尽量携带；**无票**时可能按指导价/估价/同类价等规则（演示说明，以现场执行为准）。"
    ),
    "regulatory_remark": (
        "【监管/检疫条件提示】此处为**知识库与商品举例生成的说明**，不具法律效力。涉及检疫证书、C 证、R/S 等监管条件**必须**以税则+总署公告+现场关员认定为准。"
    ),
}

# 在尚未进入某一步时，也可用于知识卡展示
EXPLANATION_TITLES: dict[str, str] = {
    "gross_kg": "毛重(kg) / 与净重区别",
    "piece_count": "件数或箱数",
    "package": "包装方式",
    "transport": "运输与携运方式",
    "value_basis": "申报价格依据与审价",
    "regulatory_remark": "税则/监管/检疫（展示用）",
}


def get_explanation_for_step(step_value: str) -> str | None:
    return FIELD_EXPLANATIONS.get(step_value) or None
