# GovFlow 接口手动测试报告

| 项目 | 内容 |
|------|------|
| 测试时间 | 2026-04-12 |
| 服务地址 | http://127.0.0.1:8000 |
| 测试方式 | 运行中实例 + `curl` 手工请求 |
| 仓库路径 | GovFlow（本地） |

## 结论摘要

共执行 **9** 项请求级用例：**8 项符合预期**，**1 项**为对根路径 `GET /` 的探测性请求，返回 **404**（应用未挂载根路由，属预期行为）。

核心业务路径 **健康检查**、**OpenAPI**、**对话（新建会话 / 澄清多轮 / 敏感词拦截 / 校验错误 / 无效会话）** 均与设计与烟测用例一致。

## 用例明细

| ID | 方法 | 路径 | 请求摘要 | HTTP | 结果 |
|----|------|------|----------|------|------|
| T1 | GET | `/healthz` | 无 body | 200 | 通过。响应 `{"status":"ok"}` |
| T2 | GET | `/openapi.json` | 无 body | 200 | 通过。可拉取 OpenAPI 模式 |
| T3 | POST | `/v1/chat` | `{"message":"你好"}` | 200 | 通过。`kind=fallback`，无知识库命中时的兜底话术 |
| T4 | POST | `/v1/chat` | `{"message":"办社保"}` | 200 | 通过。`kind=clarification`，返回追问文案 |
| T5 | POST | `/v1/chat` | 携带 T4 返回的 `session_id` + 办理社保卡材料问句 | 200 | 通过。`kind=answer`，含 `sources`（Mock 检索 + Mock LLM） |
| T6 | POST | `/v1/chat` | `{"message":"暴力测试"}` | 200 | 通过。`kind=blocked`，敏感词占位规则命中 |
| T7 | POST | `/v1/chat` | 无效 `session_id` + `message` | 404 | 通过。`{"detail":"session not found"}`，与路由实现一致 |
| T8 | POST | `/v1/chat` | `{"message":""}` | 422 | 通过。Pydantic 校验：`message` 最小长度 1 |
| T9 | GET | `/` | 无 body | 404 | 预期外仅作探测：未定义根路由，非功能缺陷 |

## 与自动化烟测的对照

仓库内 [tests/test_chat_smoke.py](../tests/test_chat_smoke.py) 中的场景与本报告 **T1、T4+T5、T6** 一致；本次额外覆盖了 OpenAPI、通用兜底、无效会话与空消息校验。

## 关于 `POST /v1/chat` 返回 404 的说明

若请求体中带 **`session_id`**，但该 ID 在服务端内存会话中不存在（拼写错误、进程重启后旧 ID、或从未创建），接口会返回 **404** + `session not found`。这与访问日志中出现 `POST /v1/chat` → 404 的情况一致，**不属于路由未注册**；新建对话时应省略 `session_id` 或使用上一轮响应中的有效 ID。

## 观察与备注（非阻塞）

- **T3** 响应中 `stages_executed` 含 `llm` 字段，但实际在「无检索结果」分支提前返回，未调用 LLM 生成；若需与真实执行阶段严格一致，可在后续迭代中调整阶段打点命名（产品/可观测性层面）。
- 当前为 **内存会话**，服务重启后会话丢失，再次使用旧 `session_id` 会得到 **404**。

## 复现命令示例

```bash
BASE=http://127.0.0.1:8000

curl -s "$BASE/healthz"

curl -s -X POST "$BASE/v1/chat" -H "Content-Type: application/json" \
  -d '{"message":"办社保"}'

curl -s -X POST "$BASE/v1/chat" -H "Content-Type: application/json" \
  -d '{"message":"暴力测试"}'
```

（多轮场景需将首轮响应中的 `session_id` 填入后续请求的 JSON。）

## 附录：同仓库 Pytest 烟测

在本地执行：

```bash
python -m pytest tests/test_chat_smoke.py -q
```

本次记录：**3 passed**（`test_healthz`、`test_clarification_then_answer`、`test_sensitive_block`）。
