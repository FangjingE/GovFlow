"""企业设立 P&E 会话存（MVP 内存）。"""

from __future__ import annotations

import uuid
from threading import Lock

from govflow.company_setup.domain import CompanySetupSession


class InMemoryCompanySetupStore:
    def __init__(self) -> None:
        self._data: dict[str, CompanySetupSession] = {}
        self._lock = Lock()

    def create(self, locale: str = "zh-CN") -> CompanySetupSession:
        sid = str(uuid.uuid4())
        s = CompanySetupSession(id=sid, locale=locale)
        with self._lock:
            self._data[sid] = s
        return s

    def get(self, session_id: str) -> CompanySetupSession | None:
        with self._lock:
            return self._data.get(session_id)
