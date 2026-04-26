"""模拟检索：互市/火龙果等词能命中政务知识条。"""

from govflow.services.rag.mock_retriever import MockKeywordRetriever


def test_import_dragon_fruit_from_vietnam_hits_kb() -> None:
    r = MockKeywordRetriever()
    hits = r.retrieve("我想从越南进口火龙果", top_k=3)
    assert hits, "应命中政务通知识库互市相关条目"
    blob = hits[0].text + (hits[0].source_title or "")
    assert "火龙果" in blob or "互市" in blob
