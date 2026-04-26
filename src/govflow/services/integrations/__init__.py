"""与政务外系统对接的集成层（协议 + mock / 未来 HTTP 实现）。"""

from govflow.services.integrations.company_setup import (
    MockCompanySetupExternals,
    build_mock_company_setup_externals,
)

__all__ = [
    "MockCompanySetupExternals",
    "build_mock_company_setup_externals",
]
