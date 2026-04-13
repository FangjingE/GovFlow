"""
槽位追问引擎（P0）：在多轮对话中收敛用户意图。

TODO: 从 YAML/DB 加载「主题 → 必填槽位 → 追问模板」；
      支持用户中途切换主题时重置状态。
"""

from govflow.domain.messages import ClarificationState


class SlotClarificationEngine:
    """根据 IntentService 给出的 missing_slots 维护 ClarificationState。"""

    def apply_user_reply(
        self,
        state: ClarificationState | None,
        user_text: str,
        missing_slots: list[str],
        topic: str | None,
    ) -> ClarificationState:
        s = state or ClarificationState(topic=topic)
        if topic:
            s.topic = topic
        if not missing_slots:
            s.pending_slots = []
            return s

        # MVP：用户补充一句话即视为填槽完成（生产应结构化抽取）
        if missing_slots:
            slot = missing_slots[0]
            s.filled_slots[slot] = user_text.strip()
            s.pending_slots = missing_slots[1:]
        return s

    def still_missing(self, state: ClarificationState | None, required: list[str]) -> list[str]:
        if not required:
            return []
        filled = (state.filled_slots if state else {}) or {}
        return [k for k in required if k not in filled]
