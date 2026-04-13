"""
MVP 模拟检索器：按关键词返回 knowledge_base 中的示例条目。

TODO:
- 接入 Chroma + 持久化目录（见 Settings.chroma_persist_dir）
- 文档切分、metadata（部门、发布日期、文号）
- 混合检索（BM25 + 向量）
"""

from pathlib import Path

from govflow.domain.messages import RetrievedChunk
from govflow.services.rag.protocols import Retriever


class MockKeywordRetriever(Retriever):
    """从本地 knowledge_base/ 目录读取 .txt，简单子串匹配。"""

    def __init__(self, kb_root: Path | None = None) -> None:
        # mock_retriever.py → rag → services → govflow → src → <repo>
        root = kb_root or Path(__file__).resolve().parents[4] / "knowledge_base"
        self._root = root

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        hits: list[RetrievedChunk] = []
        if not self._root.exists():
            return hits

        q = query.strip().lower()
        for path in self._root.rglob("*.txt"):
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(self._root)
            title = f"{rel.parent.as_posix()}/{path.stem}"
            # 极简匹配：查询词出现在文档中，或文档关键词在查询中
            keywords = ("社保", "卡", "身份证", "补办", "户籍")
            if any(k in query for k in keywords) and any(k in text for k in keywords):
                if "社保" in query and "社保" not in text:
                    continue
                if "身份证" in query and "身份证" not in text:
                    continue
                source_line = next((ln for ln in text.splitlines() if ln.startswith("【来源】")), "")
                hits.append(
                    RetrievedChunk(
                        text=text[:1200],
                        source_title=source_line or f"知识库/{title}",
                        source_uri=str(path),
                        score=0.9,
                    )
                )
            elif any(part in text for part in q.split()) and len(q) > 2:
                hits.append(
                    RetrievedChunk(
                        text=text[:1200],
                        source_title=f"知识库/{title}",
                        source_uri=str(path),
                        score=0.5,
                    )
                )
            if len(hits) >= top_k:
                break

        if not hits:
            # 无命中时返回空列表 → 上层必须走「无法确定 + 兜底」路径（P0）
            return []

        return hits[:top_k]
