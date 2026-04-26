"""
政务通分步填报文案。首版仅实现 zh-CN；vi-VN 留键位，翻译可后续接入或机翻服务。

使用方式：t("key", locale) -> 主显示语文案；越南语未就绪时回退中文并可选前缀。
"""

from __future__ import annotations

from typing import Any

# 可逐步替换为真实越文；未填时 t() 回退 zh
MESSAGES: dict[str, dict[str, str]] = {
    "opening": {
        "zh-CN": "您好，我是您的申报助手小边。请问您今天要申报的是【进口】还是【出口】？",
        "vi-VN": "",  # TODO: 越文全量
    },
    "ask_io_clarify": {
        "zh-CN": "没听清呢。请直接说「进口」或「出口」。",
        "vi-VN": "",
    },
    "ask_goods": {
        "zh-CN": "请告诉我您带的是什么商品？例如：火龙果、木薯淀粉。",
        "vi-VN": "",
    },
    "ask_weight": {
        "zh-CN": "请问{goods}大概有多少【公斤】？说数字就可以，比如：30。",
        "vi-VN": "",
    },
    "ask_origin": {
        "zh-CN": "这批货是从哪里（国家/地区）来的？例如：越南。",
        "vi-VN": "",
    },
    "ask_value": {
        "zh-CN": "这批货总价值大概多少【人民币】？比如：450。",
        "vi-VN": "",
    },
    "ask_gross": {
        "zh-CN": "毛重含包装大概多少【公斤】？若与刚说的净重差不多，也可以直接说「同净重」或报一个数。",
        "vi-VN": "",
    },
    "ask_pieces": {
        "zh-CN": "这批货分【几箱、几袋、几件】？说整数即可，如：3 箱。",
        "vi-VN": "",
    },
    "ask_package": {
        "zh-CN": "包装是【散装、箱装、袋装、竹筐加膜】等哪一种？用您平时说法说即可。",
        "vi-VN": "",
    },
    "ask_transport": {
        "zh-CN": "货是【怎么运/带到口岸】的？例如：自己背、骑摩托、小货车、托人运。",
        "vi-VN": "",
    },
    "ask_value_basis": {
        "zh-CN": "您刚报的总价，主要是依据【有发票/有收据/无票估价/按互市参考价】里的哪一种？说一种即可。",
        "vi-VN": "",
    },
    "ask_purpose": {
        "zh-CN": "是【自己用】还是【帮别人带】？可以说：自用、代购。",
        "vi-VN": "",
    },
    "preview_intro": {
        "zh-CN": "好的，请核对下面申报单摘要。说「确认」提交，说「修改」可改某一项。",
        "vi-VN": "",
    },
    "confirm_readback": {
        "zh-CN": "小边为您读一下：{readback}。若无误请说「确认提交」。",
        "vi-VN": "",
    },
    "submitted": {
        "zh-CN": "申报已受理（演示）。回执号：{token}。请截图保存，通关时出示给工作人员。",
        "vi-VN": "",
    },
    "cancelled": {
        "zh-CN": "已取消本次申报，欢迎再次使用政务通。",
        "vi-VN": "",
    },
    "off_topic": {
        "zh-CN": "小边没听懂。{hint}",
        "vi-VN": "",
    },
    "need_human": {
        "zh-CN": "多次未识别您的意思，已为您转接【远程协助】（演示：请至窗口找工作人员或拨打热线）。",
        "vi-VN": "",
    },
    "not_in_catalog": {
        "zh-CN": "该商品【{name}】不在当前互市目录示例内，无法走边民互市，请咨询一般贸易渠道。",
        "vi-VN": "",
    },
    "over_limit": {
        "zh-CN": "您申报金额超过边民互市单票示例限额（{limit} 元），需走一般贸易或改报。是否修改金额？",
        "vi-VN": "",
    },
    "suspicious_qty": {
        "zh-CN": "数量较大（{w} 公斤），请向工作人员说明或拆分申报。可先说「继续」或修改。",
        "vi-VN": "",
    },
}


def t(key: str, locale: str, **kwargs: Any) -> str:
    row = MESSAGES.get(key) or {"zh-CN": key}
    zh = row.get("zh-CN", key)
    if kwargs:
        try:
            zh = str(zh).format(**kwargs)
        except (KeyError, ValueError):
            pass
    if locale != "vi-VN":
        return zh
    vi = (row.get("vi-VN") or "").strip()
    if not vi:
        return "【越文待发布】" + zh
    if kwargs:
        return str(vi).format(**kwargs)
    return vi
