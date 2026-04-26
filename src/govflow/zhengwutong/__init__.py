"""
政务通 · 分步填报与互市申报演示（统一政务处理的一部分）。

- 首版：中文分步采集 + 规则校验 + 文本预览；越南语仅预留 i18n 键与 locale 字段。
- 暂缓：ASR/拍照/海关实链、真二维码图；以占位字段返回。
"""

from govflow.zhengwutong.domain import BMTSession, DeclarationForm, DeclarationLocale
from govflow.zhengwutong.engine import BMTDeclarationEngine, form_preview

__all__ = [
    "BMTSession",
    "DeclarationForm",
    "DeclarationLocale",
    "BMTDeclarationEngine",
    "form_preview",
]
