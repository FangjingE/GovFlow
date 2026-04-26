# GovFlow

本地政务 AI 办事助手 MVP（P0：准确问答 + 意图澄清）。HTTP API 基于 FastAPI。

## 环境要求

- Python 3.11 或更高版本

## 安装

建议在项目根目录使用虚拟环境：

```bash
cd /path/to/GovFlow
python -m venv .venv
source .venv/bin/activate
```

在 Windows 上激活虚拟环境：

```powershell
.\.venv\Scripts\activate
```

安装本项目（可编辑模式）：

```bash
pip install -e .
```

若需要运行测试或开发辅助工具，可安装可选依赖：

```bash
pip install -e ".[dev]"
```

## 启动服务

**必须在仓库根目录执行**，以便 `--app-dir src` 能正确解析包路径：

```bash
uvicorn govflow.main:app --reload --app-dir src
```

默认监听 `http://127.0.0.1:8000`。若 8000 端口已被占用，可指定其他端口：

```bash
uvicorn govflow.main:app --reload --app-dir src --port 8001
```

启动后可在浏览器打开 **简单 Web 聊天界面**（与 API 同端口）：

- 聊天 UI: http://127.0.0.1:8000/（**边民通**互市申报演示：http://127.0.0.1:8000/bmt ）

交互式 API 文档：

- Swagger UI: http://127.0.0.1:8000/docs

## 快速校验

健康检查：

```bash
curl -s http://127.0.0.1:8000/healthz
```

预期返回类似：`{"status":"ok"}`。

对话接口（首次不传 `session_id`，响应中会返回 `session_id` 供多轮复用）：

```bash
curl -s -X POST http://127.0.0.1:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"你好"}'
```

## 接入 DeepSeek（大模型回答）

默认使用内置 **Mock** 生成，不连外网。在仓库根目录的 `.env` 中（可参考 `.env.example`）配置：

- `GOVFLOW_LLM_PROVIDER=deepseek`
- `GOVFLOW_LLM_API_KEY=<在 DeepSeek 开放平台申请的 key>`
- 可选：`GOVFLOW_LLM_MODEL=deepseek-chat`（或 `deepseek-reasoner` 等，缺省为 `deepseek-chat`）
- 可选：`GOVFLOW_LLM_BASE_URL=…`（缺省为 `https://api.deepseek.com`，与官方 OpenAI 兼容接口一致）

服务仍按 RAG 检索到的【知识库摘录】约束回答；答案再经审核器。若 `provider=deepseek` 但缺少有效 API Key，首请求会报错，请检查环境变量。  
单测在 `tests/conftest.py` 中强制 `GOVFLOW_LLM_PROVIDER=mock`，避免本地 `.env` 里写了 DeepSeek 却误打真实外网。

## 边民通（互市申报演示）

- **对话填报**：`POST /v1/bmt/turn`；浏览器可打开 **http://127.0.0.1:8000/bmt** 使用简单对话 + 申报表文字预览。JSON 可含 `session_id`（多轮必带）、`message`（用户话）、`locale`（`zh-CN` 已完整；`vi-VN` 预留，未译句会回退中文并带「越文待发布」前缀）、`start_only: true` 时仅返开场白。
- **实现方式**：固定分步计划 + 每轮采一个槽（P&E 风格，无 LLM 工具环）；**非**主站 `POST /v1/chat` 的 RAG 流程。ASR/拍照/海关实联、真二维码未接，回执号为演示。

## 更多说明

架构与模块划分见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。分阶段完善清单见 [docs/PLAN.md](docs/PLAN.md)。
