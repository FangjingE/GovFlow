"""会话存储：MVP 用内存 dict；未来可换 Redis / PG。"""

from dataclasses import dataclass, field
from threading import Lock
import uuid

from govflow.domain.messages import ChatTurn, ClarificationState


@dataclass
class ConversationSession:
    id: str
    turns: list[ChatTurn] = field(default_factory=list)
    clarification: ClarificationState | None = None
    awaiting_clarification: bool = False
    # 用户首轮过于模糊时暂存，待补充后与下文合并再检索
    pending_vague_text: str | None = None
    # 主聊天内嵌政务通分步填报：与独立 /v1/zwt 会话 ID 关联
    active_track: str = "gov"  # "gov" | "zwt"
    zwt_session_id: str | None = None
    # 已答互市/政务相关咨询，正等待用户确认是否进入分步填报
    awaiting_zwt_consent: bool = False
    # 触发「是否开始填报」追问时的用户原话（用于「是」后推断进/出口等）
    zwt_seed_hint: str | None = None


class InMemorySessionStore:
    def __init__(self) -> None:
        self._data: dict[str, ConversationSession] = {}
        self._lock = Lock()

    def create(self) -> ConversationSession:
        sid = str(uuid.uuid4())
        s = ConversationSession(id=sid)
        with self._lock:
            self._data[sid] = s
        return s

    def get(self, session_id: str) -> ConversationSession | None:
        with self._lock:
            return self._data.get(session_id)

    def append_turn(self, session_id: str, turn: ChatTurn) -> None:
        with self._lock:
            s = self._data.get(session_id)
            if not s:
                return
            s.turns.append(turn)

    def update_session(self, session_id: str, **kwargs: object) -> None:
        with self._lock:
            s = self._data.get(session_id)
            if not s:
                return
            for k, v in kwargs.items():
                setattr(s, k, v)
