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

# 用户问题与文档各命中其一即进入粗筛（再经锚词与计分）
BROAD_KEYWORDS: tuple[str, ...] = (
    "政务通",
    "社保",
    "毛重",
    "净重",
    "边民",
    "互市",
    "进口",
    "出口",
    "越南",
    "火龙果",
    "卡",
    "身份证",
    "补办",
    "户籍",
    "医保",
    "养老",
    "养老保险",
    "转移",
    "灵活",
    "补缴",
    "退休",
    "失业",
    "征地",
    "生育",
    "工伤",
    "缴费",
    "待遇",
    "五险一金",
)

# 与 query、正文、路径求交叠计分（长词优先多给分由顺序体现）
_SCORE_TERMS: tuple[str, ...] = (
    "边民互市",
    "政务通",
    "毛重",
    "净重",
    "互市",
    "火龙果",
    "边民",
    "进口",
    "越南",
    "社会保障卡",
    "社保卡",
    "城乡居民",
    "职工养老",
    "灵活就业",
    "转移",
    "跨省",
    "补缴",
    "掌上12333",
    "广西人社",
    "深圳",
    "广东",
    "上思",
    "被征地",
    "征地",
    "失业",
    "退休",
    "医保",
    "社保",
    "养老",
    "五险",
    "身份证",
    "户口簿",
    "材料",
    "大厅",
    "办卡",
)


def _anchors_ok(query: str, text: str) -> bool:
    """问题显式锚定某类词时，正文须能对应，减少错配。"""
    if "身份证" in query and "身份证" not in text:
        return False
    if "社保" in query and "社保" not in text:
        return False
    if "医保" in query and "医保" not in text:
        return False
    return True


def _score(path: Path, text: str, query: str) -> float:
    path_s = path.as_posix() + "/" + path.stem
    score = 0.0
    for term in _SCORE_TERMS:
        if term not in query:
            continue
        if term in text:
            score += 3.0
        if term in path_s:
            score += 1.5
    if "社保卡" in query or "社会保障卡" in query:
        if "社保卡" in path.stem or "社会保障卡" in text:
            score += 12.0
    if ("办理社保卡" in query or "补办社保卡" in query) and "社保卡" in path.stem:
        score += 8.0
    return score


# 边贸/边民等：query 与正文同时含同一词时允许弱召回（不依赖分词）
_CROSS_TRADE_HINTS: tuple[str, ...] = (
    "政务通",
    "边民",
    "互市",
    "互贸",
    "火龙果",
    "进口",
    "出口",
    "越南",
    "东兴",
    "口岸",
)


def _cn_cross_match(query: str, text: str) -> bool:
    return any(w in query and w in text for w in _CROSS_TRADE_HINTS)


class MockKeywordRetriever(Retriever):
    """从本地 knowledge_base/ 目录读取 .txt，关键词粗筛 + 简单计分排序。"""

    def __init__(self, kb_root: Path | None = None) -> None:
        # mock_retriever.py → rag → services → govflow → src → <repo>
        root = kb_root or Path(__file__).resolve().parents[4] / "knowledge_base"
        self._root = root

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        if not self._root.exists():
            return []

        q_lower = query.strip().lower()
        candidates: list[tuple[float, RetrievedChunk]] = []

        for path in sorted(self._root.rglob("*.txt"), key=lambda p: p.as_posix()):
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(self._root)
            title = f"{rel.parent.as_posix()}/{path.stem}"

            broad = any(k in query for k in BROAD_KEYWORDS) and any(k in text for k in BROAD_KEYWORDS)
            split_fallback = len(q_lower) > 2 and any(part in text for part in q_lower.split())
            cross_tr = _cn_cross_match(query, text)

            if not broad and not split_fallback and not cross_tr:
                continue

            if broad and not _anchors_ok(query, text):
                continue
            if not broad and cross_tr and not _anchors_ok(query, text):
                continue

            source_line = next((ln for ln in text.splitlines() if ln.startswith("【来源】")), "")
            chunk = RetrievedChunk(
                text=text[:1200],
                source_title=source_line or f"知识库/{title}",
                source_uri=str(path),
                score=None,
            )
            sc = _score(path, text, query)
            if not broad:
                sc = max(sc, 0.4)
                if cross_tr and sc < 0.4:
                    sc = 0.5
            elif sc < 0.01:
                sc = 0.9
            chunk.score = sc
            candidates.append((sc, chunk))

        if not candidates:
            return []

        candidates.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in candidates[:top_k]]
