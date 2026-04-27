"""混合检索单测：注入可重复向量，不拉取真实模型。"""

from __future__ import annotations

import numpy as np

from govflow.config import Settings
from govflow.services.rag.hybrid_retriever import HybridBm25VectorRetriever


class _ConstEncoder:
    """可重复、已单位化的定维向量，便于断言语义分数顺序。"""

    def __init__(self) -> None:
        self._dim = 4

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        t = (texts[0] or "").lower()
        if "火龙果" in t or "进境" in t:
            v = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
        elif "毛重" in t:
            v = np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32)
        else:
            v = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
        v = v / (np.linalg.norm(v) + 1e-9)
        if len(texts) > 1:
            raise NotImplementedError
        return v.reshape(1, -1)

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        rows: list[np.ndarray] = []
        for raw in texts:
            t = (raw or "").lower()
            if "火龙果" in t or "植物检疫" in t:
                v = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
            elif "毛重" in t and "净重" in t:
                v = np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32)
            else:
                v = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
            v = v / (np.linalg.norm(v) + 1e-9)
            rows.append(v)
        return np.stack(rows, axis=0)


def _settings_with_kb(kb) -> Settings:
    return Settings(
        rag_mode="hybrid",
        knowledge_base_dir=str(kb),
    )


def test_hybrid_fuses_and_returns_top_k(tmp_path) -> None:
    kb = tmp_path / "kb"
    (kb / "a").mkdir(parents=True)
    (kb / "a" / "fruit.txt").write_text(
        "进境植物与水果检疫 火龙果须符合海关规定。\n【来源】测试",
        encoding="utf-8",
    )
    (kb / "b" / "weight.txt").parent.mkdir(exist_ok=True, parents=True)
    (kb / "b" / "weight.txt").write_text("毛重与净重 区别说明 演示。\n【来源】试", encoding="utf-8")

    r = HybridBm25VectorRetriever(_settings_with_kb(kb), embedder=_ConstEncoder())
    hits = r.retrieve("从越南进火龙果 检疫 要什么", top_k=2)
    assert len(hits) >= 1
    # 与火龙果段落语义对齐 + BM25
    top = (hits[0].source_title or "") + (hits[0].text or "")
    assert "火龙果" in top or "检疫" in top
