"""sentence-transformers 实现 ``Embedder`` 协议，供可注入单测与可选索引脚本。"""

from __future__ import annotations

import numpy as np

from govflow.services.rag.protocols import Embedder


class SentenceTransformersEmbedder(Embedder):
    def __init__(
        self,
        model_name: str,
        *,
        bge_instruct: bool = True,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name, trust_remote_code=True)
        self._bge = bge_instruct

    def _encode_for_retrieval(
        self,
        texts: list[str],
        *,
        is_query: bool,
    ) -> np.ndarray:
        if not self._bge:
            return self._model.encode(  # type: ignore[no-untyped-call]
                texts,
                normalize_embeddings=True,
            )
        if is_query:
            pfx = "为这个句子生成表示以用于检索查询："
            t = [pfx + s for s in texts]
        else:
            pfx = "为这个句子生成表示："
            t = [pfx + s for s in texts]
        return self._model.encode(  # type: ignore[no-untyped-call]
            t,
            normalize_embeddings=True,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        v = self._encode_for_retrieval(texts, is_query=False)
        return v.tolist()  # type: ignore[union-attr]

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode_for_retrieval(texts, is_query=True)

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        return self._encode_for_retrieval(texts, is_query=False)
