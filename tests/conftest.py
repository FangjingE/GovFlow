"""单测会加载本地 .env；强制使用 Mock LLM，避免烟测与 HTTP 用例打真实大模型外网。"""

from __future__ import annotations

import os

# 须在任何 `import govflow` 之前
os.environ["GOVFLOW_LLM_PROVIDER"] = "mock"
