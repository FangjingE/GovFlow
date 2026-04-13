"""端到端烟测：澄清 → 回答、敏感词拦截、无知识兜底。

编排器各分支与 HTTP/kind 契约（固定 Stub）见 ``test_chat_orchestrator.py``。

运行本文件（在仓库根目录 GovFlow/ 下，已安装 dev 依赖）::

    pytest tests/test_chat_smoke.py -v

只跑单个用例::

    pytest tests/test_chat_smoke.py::test_healthz -v
"""

from fastapi.testclient import TestClient

from govflow.main import app

client = TestClient(app)


def test_healthz() -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_clarification_then_answer() -> None:
    r1 = client.post("/v1/chat", json={"message": "办社保"})
    assert r1.status_code == 200
    j1 = r1.json()
    assert j1["kind"] == "clarification"
    sid = j1["session_id"]

    r2 = client.post("/v1/chat", json={"session_id": sid, "message": "我想办理社保卡需要带什么材料"})
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["kind"] == "answer"
    assert j2["sources"]


def test_sensitive_block() -> None:
    r = client.post("/v1/chat", json={"message": "暴力测试"})
    assert r.status_code == 200
    j = r.json()
    assert j["kind"] == "blocked"
