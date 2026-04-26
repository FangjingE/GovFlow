"""边民通申报引擎与 HTTP（中文；vi 仅占位）。"""

from fastapi.testclient import TestClient

from govflow.bianmintong.i18n import t
from govflow.main import app

client = TestClient(app)


def test_i18n_vi_fallback() -> None:
    s = t("opening", "vi-VN")
    assert "越文" in s or "进口" in s


def test_bmt_start_only() -> None:
    r = client.post("/v1/bmt/turn", json={"start_only": True, "locale": "zh-CN"})
    assert r.status_code == 200
    j = r.json()
    assert "session_id" in j
    assert "进口" in j["reply"] or "出口" in j["reply"]


def test_bmt_happy_path_submit() -> None:
    a = client.post("/v1/bmt/turn", json={"message": ""})
    sid = a.json()["session_id"]
    msgs = (
        "进口",
        "火龙果",
        "30",
        "同净重",
        "2",
        "袋装",
        "自己背",
        "越南",
        "450",
        "有发票",
        "自用",
    )
    for msg in msgs:
        r = client.post("/v1/bmt/turn", json={"session_id": sid, "message": msg})
        assert r.status_code == 200, r.text
    j = r.json()
    assert j["kind"] == "preview"
    assert "火龙果" in j["form_preview"]
    assert "毛重" in j["form_preview"] or "kg" in j["form_preview"]
    assert j.get("field_explanation")  # 监管说明
    c1 = client.post("/v1/bmt/turn", json={"session_id": sid, "message": "确认提交"})
    assert c1.status_code == 200
    c2 = client.post("/v1/bmt/turn", json={"session_id": sid, "message": "确认提交"})
    out = c2.json()
    assert out["kind"] == "submitted"
    assert out.get("submit_receipt")


def test_bmt_faq_rag_during_form() -> None:
    """申报途中咨询类问句走 RAG+LLM，不推进当前槽位（演示知识库/ mock 大模型）。"""
    a = client.post("/v1/bmt/turn", json={"message": ""})
    sid = a.json()["session_id"]
    for msg in ("进口", "火龙果"):
        r0 = client.post("/v1/bmt/turn", json={"session_id": sid, "message": msg})
        assert r0.status_code == 200, r0.text
    r = client.post(
        "/v1/bmt/turn",
        json={"session_id": sid, "message": "毛重和净重有什么区别？请简要说明。"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["kind"] == "knowledge"
    assert j["step"] == "weight_kg"
    assert "毛重" in j["reply"] or "净重" in j["reply"] or "摘要" in j["reply"] or "指南" in j["reply"]
    assert j.get("rag_sources")
    r2 = client.post("/v1/bmt/turn", json={"session_id": sid, "message": "30"})
    assert r2.status_code == 200, r2.text
    j2 = r2.json()
    assert j2["step"] == "gross_kg"
    assert j2["kind"] == "collecting"


def test_bmt_400_empty_message_with_session() -> None:
    a = client.post("/v1/bmt/turn", json={})
    sid = a.json()["session_id"]
    bad = client.post("/v1/bmt/turn", json={"session_id": sid, "message": "   "})
    assert bad.status_code == 400
