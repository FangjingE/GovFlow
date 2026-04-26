"""模拟检索：边民/互市/火龙果等词能命中知识条。"""

from govflow.services.rag.mock_retriever import MockKeywordRetriever


def test_import_dragon_fruit_from_vietnam_hits_kb() -> None:
    r = MockKeywordRetriever()
    hits = r.retrieve("我想从越南进口火龙果", top_k=3)
    assert hits, "应命中边民通/互市知识条"
    blob = hits[0].text + (hits[0].source_title or "")
    assert "火龙果" in blob or "互市" in blob
