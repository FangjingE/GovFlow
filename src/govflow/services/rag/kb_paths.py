"""knowledge_base 根目录：与 `MockKeywordRetriever` 的默认路径一致。"""

from __future__ import annotations

from pathlib import Path

# 本文件位于 services/rag/，向上 4 级到仓库根
_REPO_ROOT = Path(__file__).resolve().parents[4]


def default_knowledge_base_dir() -> Path:
    return _REPO_ROOT / "knowledge_base"
