"""数据驱动评测集：默认栈 + 仓库 knowledge_base，无外网。

用例数据：``tests/fixtures/eval_cases.json``

运行::

    pytest tests/test_eval_cases.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from govflow.domain.messages import ChatTurn
from govflow.repositories.session_store import InMemorySessionStore
from govflow.services.pipeline.orchestrator import ChatOrchestrator, OrchestratorResult


def _fixtures_path() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "eval_cases.json"


def _load_cases() -> list[dict[str, Any]]:
    raw = json.loads(_fixtures_path().read_text(encoding="utf-8"))
    cases = raw.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("eval_cases.json must contain a non-empty 'cases' array")
    return cases


def _assert_turn(case_id: str, turn_index: int, expect: dict[str, Any], result: OrchestratorResult) -> None:
   
    prefix = f"[{case_id} turn {turn_index}]"
    want_kind = expect.get("kind")
    assert want_kind is not None, f"{prefix} missing expect.kind"
    assert result.kind == want_kind, f"{prefix} kind: got {result.kind!r}, want {want_kind!r}"

    for sub in expect.get("reply_contains", []) or []:
        assert sub in result.reply, f"{prefix} reply missing substring {sub!r}"

    if expect.get("sources_non_empty") is True:
        assert len(result.sources) > 0, f"{prefix} expected non-empty sources"

    if expect.get("sources_empty") is True:
        assert len(result.sources) == 0, f"{prefix} expected empty sources"

    for stage in expect.get("stages_contains", []) or []:
        assert stage in result.stages_executed, (
            f"{prefix} stages_executed missing {stage!r}, got {result.stages_executed!r}"
        )


def _run_case(case: dict[str, Any]) -> None:
    case_id = case["id"]
    turns = case["turns"]
    store = InMemorySessionStore()
    orch = ChatOrchestrator(session_store=store)
    session = store.create()

    for i, turn in enumerate(turns):
        msg = turn["message"]
        expect = turn["expect"]
        store.append_turn(session.id, ChatTurn(role="user", content=msg))
        result = orch.handle_message(session, msg)
        store.append_turn(session.id, ChatTurn(role="assistant", content=result.reply))
        _assert_turn(case_id, i, expect, result)


CASES = _load_cases()

#装饰器，给测试函数添加参数，参数是CASES中的每个元素，ids是每个元素的id，c是CASES中每个元素的值
@pytest.mark.parametrize("case", CASES, ids=lambda c: str(c["id"]))
def test_eval_case(case: dict[str, Any]) -> None:
    _run_case(case)
