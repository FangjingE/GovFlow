"""RAG 抽象：未来可替换为 Chroma / Milvus / ES 混合检索。"""

from typing import Protocol

from govflow.domain.messages import RetrievedChunk


class Retriever(Protocol):
    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        """返回带来源信息的片段，供 LLM 严格 grounded 生成。"""
        ...


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """TODO: BGE-large-zh 等向量模型。"""
        ...
