"""主对话内嵌：企业设立 P&E 与 consent。"""

from fastapi.testclient import TestClient

from govflow.main import app

client = TestClient(app)


def test_company_setup_consent_then_collect_type() -> None:
    r1 = client.post("/v1/chat", json={"message": "我想办企业"})
    assert r1.status_code == 200
    j1 = r1.json()
    assert j1["kind"] == "answer"
    assert "企业设立" in j1["reply"] or "全流程演示" in j1["reply"]
    sid = j1["session_id"]

    r2 = client.post("/v1/chat", json={"session_id": sid, "message": "是"})
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2.get("company_sidebar_visible") is True
    assert "类型" in j2["reply"] or "公司类型" in j2["reply"]


def test_company_setup_happy_path_core() -> None:
    r0 = client.post("/v1/chat", json={"message": "注册公司"})
    sid = r0.json()["session_id"]
    client.post("/v1/chat", json={"session_id": sid, "message": "开始"})
    msgs = (
        "有限责任公司",
        "广西演示科技有限公司",
        "南宁市青秀区民族大道1号示例大厦",
        "张三70%李四30%",
        "软件开发与技术咨询服务",
        "继续",
        "否",
    )
    last = None
    for m in msgs:
        last = client.post("/v1/chat", json={"session_id": sid, "message": m})
        assert last.status_code == 200, last.text
    j = last.json()
    assert j.get("company_sidebar_visible") is True or j.get("company_sidebar_visible") is False
    assert "跳过后置许可" in j["reply"] or "流程结束" in j["reply"] or "统一社会信用代码" in j["reply"]


def test_company_setup_leave_via_gov_topic() -> None:
    r1 = client.post("/v1/chat", json={"message": "开公司"})
    sid = r1.json()["session_id"]
    client.post("/v1/chat", json={"session_id": sid, "message": "是"})
    r3 = client.post("/v1/chat", json={"session_id": sid, "message": "办社保卡需要带什么材料"})
    assert r3.status_code == 200
    j3 = r3.json()
    assert j3.get("company_sidebar_visible") is False
