"""
互市示例知识：HS 与目录、限额（示范数据，可换 YAML/库表）。
"""

from __future__ import annotations

# 元组：(HS 显示码, 是否在边民互市「示例」目录)
GOODS_CATALOG: dict[str, tuple[str, bool]] = {
    "火龙果": ("0810.60", True),
    "木薯淀粉": ("1108.13", True),
    "木薯": ("0714.20", True),
    "汽车": ("8703.23", False),
    "牛": ("0102.14", True),
}

MUT_SHI_CNY_PER_TICKET = 8000.0
# 单票超此重量仅告警（演示）
SUSPICIOUS_WEIGHT_KG = 200.0
MAX_MISUNDERSTAND = 2


def norm_goods(s: str) -> str:
    t = s.strip()
    for k in GOODS_CATALOG:
        if k in t or t in k:
            return k
    return t[:64]


def regulatory_remark_for(goods_name: str, hs_code: str) -> str:
    """
    监管/税则/检疫**展示用**一句话（可后续用 LLM 据 HS 与政策库扩写）。
    不具法律效力。
    """
    g = (goods_name or "") + (hs_code or "")
    if "火龙果" in goods_name or (hs_code and "0810" in hs_code):
        return "鲜火龙果属植物产品；R/S/检疫以总署及口岸动植检最新要求为准。本行由政务通规则生成，仅供参考。"
    if "木薯" in goods_name:
        return "块茎类可涉检疫与归类合并申报；以现场关员与检疫机构解释为准。本行由政务通规则生成。"
    if "牛" in goods_name or "活牛" in goods_name:
        return "活动物、鲜冷肉类监管条件更严，互市未必适用。本行由政务通规则生成，请优先咨询一般贸易/检疫要求。"
    return "税则号列、监管与检疫条件以《海关进出口税则》与现场关员认定为准。本行由政务通规则生成，仅供参考。"
