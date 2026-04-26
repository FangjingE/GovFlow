"""政务通分步填报会话存（MVP 内存，与会话 store 可合并或换 Redis）。"""

from __future__ import annotations

import uuid
from threading import Lock

from govflow.zhengwutong.domain import BMTSession


class BMTSessionStore:
    def __init__(self) -> None:
        self._d: dict[str, BMTSession] = {}
        self._lock = Lock()

    def create(self, locale: str = "zh-CN") -> BMTSession:
        sid = str(uuid.uuid4())
        s = BMTSession(id=sid, locale=locale if locale in ("zh-CN", "vi-VN") else "zh-CN")  # type: ignore[arg-type]
        with self._lock:
            self._d[sid] = s
        return s

    def get(self, sid: str) -> BMTSession | None:
        with self._lock:
            return self._d.get(sid)

    def update(self, s: BMTSession) -> None:
        with self._lock:
            if s.id in self._d:
                self._d[s.id] = s
