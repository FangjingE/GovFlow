# GovFlow 项目完善计划清单

**编写日期**：2026-04-13  
**基线**：P0 骨架已具备（FastAPI `/v1/chat`、`ChatOrchestrator`、内存会话、Mock 检索与 LLM、烟测 + Stub 契约测试）。详细架构见 [ARCHITECTURE.md](./ARCHITECTURE.md)。

说明：下列条目以 `[ ]` 为未完成，完成后可改为 `[x]`；优先级仅为建议顺序，可按资源调整。

**评测集**：用例数据 [`tests/fixtures/eval_cases.json`](../tests/fixtures/eval_cases.json)，运行 `pytest tests/test_eval_cases.py -v`（驱动见 `tests/test_eval_cases.py`）。

**Cursor / AI 回复风格**：本仓库在 [`.cursor/rules/assistant-communication.mdc`](../.cursor/rules/assistant-communication.mdc) 中约定「面向开发新手、尽量详细具体」；用 Cursor 打开本项目时，规则会对 Agent 生效。若希望**所有项目**都使用同一风格，把该文件中的正文复制到 Cursor **Settings → Rules → User Rules**（或新建全局 Skill，内容一致即可）。

---

## A. P0 闭环（质量与行为）

| 状态 | 项 | 说明 |
|------|----|------|
| [ ] | **槽位级多轮澄清** | 编排器在 `NEEDS_CLARIFICATION` 之外，用 `ClarificationState.pending_slots` / `SlotClarificationEngine.still_missing` 驱动「未填满则继续追问」，避免仅依赖意图启发式一次 READY。 |
| [ ] | **澄清追问模板配置化** | 从 YAML/DB 加载「主题 → 必填槽位 → 追问模板」（`slot_engine.py` 已标注 TODO）。 |
| [ ] | **查询改写（QR）** | `_build_rag_query` 在合并多轮用户话术后，增加轻量改写或关键词抽取，提高召回稳定性。 |
| [x] | **答案审核可配置** | `GOVFLOW_ANSWER_AUDITOR_MODE=pass_through|grounded`，`GOVFLOW_ANSWER_AUDITOR_MIN_ANSWER_LENGTH`；工厂 `build_answer_auditor`；`grounded` 拒绝证据中未出现的连续 4 位以上数字。见 `services/llm/auditors.py`。 |
| [x] | **TOP 意图 / 问答评测集** | 基础集：`tests/fixtures/eval_cases.json` + `pytest tests/test_eval_cases.py`；后续扩 case、接 CI 全量回归。 |
| [ ] | **敏感词与合规** | 可配置词库路径、白名单、命中审计日志占位；可选对接第三方审核 API 抽象。 |

---

## B. 检索与知识（RAG）

| 状态 | 项 | 说明 |
|------|----|------|
| [ ] | **向量索引 + 持久化** | 替换或并存 `MockKeywordRetriever`：Chroma（或同类）+ `Settings` 中持久化目录；文档切片与 metadata（部门、发布日期、文号）。 |
| [ ] | **嵌入模型** | 实现 `Embedder` 协议（如 BGE-zh）；构建与更新索引的脚本或 Makefile 目标。 |
| [ ] | **混合检索** | BM25 + 向量或关键词召回融合；调参记录在 `docs/` 或配置注释中。 |
| [ ] | **知识库运维** | 增量更新、版本号、坏链检测；示例 `knowledge_base/` 结构与生产规范对齐。 |

---

## C. 模型与生成（LLM）

| 状态 | 项 | 说明 |
|------|----|------|
| [ ] | **真实 LLM 客户端** | OpenAI 兼容 API（本地 vLLM / Ollama / 云厂商）；`deps.py` 从环境变量选择实现（与现有 TODO 一致）。 |
| [ ] | **System prompt 与拒答** | 严格 grounded：无证据不编造；与编排器 `fallback` 策略一致。 |
| [ ] | **流式响应（可选）** | SSE 或 chunked；需与前端约定及超时策略一并设计。 |

---

## D. 工程化与 API

| 状态 | 项 | 说明 |
|------|----|------|
| [ ] | **异步编排** | `orchestrator` / 路由改为 `async`，检索与 LLM 使用 `httpx.AsyncClient` 等，配合超时（目标 ≤3s 见需求）。 |
| [ ] | **依赖注入与生命周期** | 替换 `@lru_cache` 单例为显式 lifespan 或工厂，便于测试与多实现切换。 |
| [ ] | **CORS、请求 ID、限流** | `main.py` 已列 TODO；生产需白名单与可追踪 request id。 |
| [ ] | **健康检查深化** | `/healthz` 可扩展依赖探测（可选：仅进程存活 vs 深度检查）。 |
| [ ] | **OpenAPI 鉴权** | API Key 或 OAuth2 占位，与网关策略对齐。 |
| [ ] | **容器与部署** | Dockerfile + compose（可选含本地 Chroma）；文档中写明环境变量。 |

---

## E. 可观测性与韧性

| 状态 | 项 | 说明 |
|------|----|------|
| [ ] | **结构化日志** | 按 `session_id` / `stages_executed` 打点；敏感字段脱敏。 |
| [ ] | **OpenTelemetry** | 按 `PipelineStage` span（编排器文件头 TODO）。 |
| [ ] | **熔断与降级** | 检索失败、LLM 超时时的明确策略与对外文案（与现有 `fallback` 区分或合并文档）。 |

---

## F. 数据与会话

| 状态 | 项 | 说明 |
|------|----|------|
| [ ] | **外置会话存储** | Redis / PostgreSQL + TTL；抽象 `SessionStore` 接口，保留内存实现供测试。 |
| [ ] | **审计轨迹** | 用户问题摘要（可哈希）、命中策略、`kind` 结果写入存储或日志管道（合规前置）。 |

---

## G. P1 / P2（需求矩阵中的后续能力）

| 状态 | 项 | 说明 |
|------|----|------|
| [ ] | **材料预审（P1）** | 上传、OCR、与办事指南字段校验；新模块建议 `services/documents/`。 |
| [ ] | **精准导航（P1）** | 大厅窗口、楼层、地图链接；metadata 或独立结构化表。 |
| [ ] | **行动闭环（P2）** | 预约、办件进度等与外部政务系统对接（接口与安全评审）。 |

---

## H. 意图与产品

| 状态 | 项 | 说明 |
|------|----|------|
| [ ] | **意图识别升级** | 小样本分类或 prompt 路由，替代纯关键词 `IntentService`（代码中 TODO）。 |
| [ ] | **多主题切换** | 用户中途换主题时重置澄清状态（`slot_engine` TODO）。 |

---

## 建议执行顺序（摘要）

1. **评测集 + 审核与澄清逻辑**（不依赖外网即可提升 P0 可信度）  
2. **向量 RAG + 真实 LLM**（核心体验）  
3. **异步、超时、会话外置**（上线前置）  
4. **观测、限流、鉴权、容器**（运维与安全）  
5. **P1/P2 能力**（按业务优先级排期）

---

本文档随迭代更新日期与勾选状态；重大架构变更请同步 [ARCHITECTURE.md](./ARCHITECTURE.md)。
