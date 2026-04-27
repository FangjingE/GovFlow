"""本地知识库上的 BM25 + 句向量混合检索，采用 RRF 融合排名。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

from govflow.config import Settings
from govflow.domain.messages import RetrievedChunk
from govflow.services.rag.kb_paths import default_knowledge_base_dir
from govflow.services.rag.sbert_embedder import SentenceTransformersEmbedder
from govflow.services.rag.protocols import Retriever

@runtime_checkable
class _QueryPassageEncoder(Protocol):
    """可注入的句向量：查询与段落可不同前缀，见 ``SentenceTransformersEmbedder``。"""

    def encode_queries(self, texts: list[str]) -> np.ndarray: ...
    def encode_passages(self, texts: list[str]) -> np.ndarray: ...


@dataclass(frozen=True)
class _KBDocs:
    paths: list[Path]
    rel_titles: list[str]
    texts: list[str]
    tokenized: list[list[str]]


def _rrf_fusion(
    rank_lists: list[list[int]],
    k: int,
) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion：多路列表合并为 (doc_index, 分数) 按分数降序。"""
    acc: dict[int, float] = {}
    for rlist in rank_lists:
        for r, did in enumerate(rlist):
            acc[did] = acc.get(did, 0.0) + 1.0 / (k + r + 1)
    return sorted(acc.items(), key=lambda x: (-x[1], x[0]))


def _source_line(text: str) -> str:
    for ln in text.splitlines():
        if ln.startswith("【来源】"):
            return ln
    return ""


def _load_docs(kb: Path) -> _KBDocs:
    if not kb.exists():
        return _KBDocs(paths=[], rel_titles=[], texts=[], tokenized=[])

    jieba.initialize()  # 首次加载词典

    paths: list[Path] = []
    rels: list[str] = []
    texts: list[str] = []
    toks: list[list[str]] = []
    for path in sorted(kb.rglob("*.txt"), key=lambda p: p.as_posix()):
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            continue
        rel = path.relative_to(kb)
        title = f"{rel.parent.as_posix()}/{path.stem}" if str(rel.parent) != "." else path.stem
        paths.append(path)
        rels.append(title)
        texts.append(raw)
        toks.append(jieba.lcut(raw))

    return _KBDocs(
        paths=paths,
        rel_titles=rels,
        texts=texts,
        tokenized=toks,
    )


def _resolve_kb_root(s: Settings) -> Path:
    if s.knowledge_base_dir and str(s.knowledge_base_dir).strip():
        return Path(s.knowledge_base_dir).expanduser().resolve()
    return default_knowledge_base_dir()


class HybridBm25VectorRetriever(Retriever):
    """
    从 ``knowledge_base/`` 加载 ``*.txt``，BM25（jieba 分词）+ 余弦相似度（BGE-zh 类模型），
    以 RRF 取最终 ``top_k`` 条。文本展示仍截断至 1200 字，与 ``MockKeywordRetriever`` 一致。
    """

    def __init__(
        self,
        settings: Settings,
        embedder: _QueryPassageEncoder | None = None,
    ) -> None:
        self._s = settings
        self._kb = _resolve_kb_root(settings)
        self._lock = threading.Lock()
        self._ready = False
        self._build_error: str | None = None

        self._docs: _KBDocs = _KBDocs([], [], [], [])
        self._bm25: BM25Okapi | None = None
        self._passage_emb: np.ndarray | None = None
        self._embedder: SentenceTransformersEmbedder | None = embedder
        # 延迟在首次 ``retrieve`` 中构建，避免 import 时拉模型
        self._init_pending = True

    def _build_index(self) -> None:
        self._docs = _load_docs(self._kb)
        n = len(self._docs.texts)
        if n == 0:
            self._bm25 = None
            self._passage_emb = None
            return

        self._bm25 = BM25Okapi(self._docs.tokenized)

        e = self._embedder
        if e is None:
            e = SentenceTransformersEmbedder(
                self._s.embedding_model,
                bge_instruct=self._s.bge_instruct,
            )
            self._embedder = e

        self._passage_emb = e.encode_passages(self._docs.texts)  # type: ignore[union-attr]

    def _ensure_built(self) -> None:
        with self._lock:
            if self._build_error is not None:
                return
            if not self._init_pending:
                return
            self._init_pending = False
            try:
                self._build_index()
            except Exception as ex:  # noqa: BLE001
                self._build_error = str(ex)
                self._bm25 = None
                self._passage_emb = None

    @classmethod
    def from_settings(cls, s: Settings) -> HybridBm25VectorRetriever:
        return cls(s)

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        self._ensure_built()
        if self._build_error is not None:
            return []
        n = len(self._docs.texts)
        if n == 0 or self._bm25 is None or self._passage_emb is None or self._embedder is None:
            return []

        q = (query or "").strip()
        if not q:
            return []

        q_tok = jieba.lcut(q)
        bm25_scores = np.array(self._bm25.get_scores(q_tok), dtype=np.float64)
        qv = self._embedder.encode_queries([q])  # type: ignore[no-untyped-call]
        if qv.ndim == 1:
            qv = qv.reshape(1, -1)
        vec_scores = (self._passage_emb @ qv.T).reshape(-1)

        cand = max(32, top_k * 6, min(n, 50))
        bm25_order = list(np.argsort(bm25_scores)[::-1][:cand].tolist())
        vec_order = list(np.argsort(vec_scores)[::-1][:cand].tolist())
        fused = _rrf_fusion([bm25_order, vec_order], k=self._s.hybrid_rrf_k)

        out: list[RetrievedChunk] = []
        for did, rrf_s in fused[: top_k * 2]:
            if len(out) >= top_k:
                break
            t = self._docs.texts[did]
            path = self._docs.paths[did]
            title = self._docs.rel_titles[did]
            sline = _source_line(t)
            chunk = RetrievedChunk(
                text=t[:1200],
                source_title=sline or f"知识库/{title}",
                source_uri=str(path),
                score=round(float(rrf_s), 5),
            )
            out.append(chunk)
        return out
