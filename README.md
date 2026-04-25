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

启动后可打开交互式 API 文档：

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

## 更多说明

架构与模块划分见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。分阶段完善清单见 [docs/PLAN.md](docs/PLAN.md)。
