"""单测环境：默认使用 ``mock`` RAG，不下载/加载句向量模型（可 ``GOVFLOW_RAG_MODE=hybrid`` 覆写）。"""

import os

os.environ.setdefault("GOVFLOW_RAG_MODE", "mock")
