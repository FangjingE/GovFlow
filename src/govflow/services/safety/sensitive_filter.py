"""
敏感词 / 合规前置过滤（P0 占位）。

TODO: 接入政务网安审词库、正则策略、白名单；命中后可审计日志、熔断或人工复核队列。
"""

from dataclasses import dataclass


@dataclass
class FilterResult:
    allowed: bool
    reason: str | None = None


class SensitiveContentFilter:
    """极简占位：生产应替换为可配置策略引擎。"""

    def __init__(self, blocked_keywords: tuple[str, ...] = ("暴力", "恐怖")) -> None:
        self._blocked = blocked_keywords

    def check(self, text: str) -> FilterResult:
        # TODO: 分词 + AC 自动机 / 第三方审核 API
        for w in self._blocked:
            if w in text:
                return FilterResult(allowed=False, reason=f"命中敏感词占位规则: {w}")
        return FilterResult(allowed=True)
