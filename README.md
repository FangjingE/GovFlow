# GovFlow

政务事项 **PostgreSQL + pgvector** 存储与 **Top-1** 检索：命中后按 `docs/ARCHITECTURE.md` 第六节模板直接返回正文，**不接大模型生成**。

## 环境

- Python 3.11+
- PostgreSQL（建议 [pgvector 镜像](https://github.com/pgvector/pgvector)）

## 数据库

1. 启动数据库（若本机 5432 已被占用，默认映射 **5433**，见 `docker-compose.yml`）：

   ```bash
   docker compose up -d
   ```

2. 建表与扩展：

   ```bash
   docker exec -i govflow-db-1 psql -U govflow -d govflow -f - < sql/schema.sql
   ```

3. （可选）示例数据：

   ```bash
   docker exec -i govflow-db-1 psql -U govflow -d govflow -f - < sql/seed_dev.sql
   ```

连接串见 `.env.example`（`GOVFLOW_DATABASE_URL`）。

## 安装与运行

```bash
cd /path/to/GovFlow
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

推荐一条命令启动（会先拉起数据库和 Adminer）：

```bash
bash scripts/dev_run.sh
```

若你只想单独启动 API，也可以：

```bash
python -m uvicorn govflow.main:app --reload --app-dir src
```

浏览器地址：

- API/UI：`http://127.0.0.1:8000/`
- OpenAPI 文档：`http://127.0.0.1:8000/docs`
- 数据库管理平台（Adminer）：`http://127.0.0.1:8081/`

## 测试

```bash
pytest -q
```

只跑某个测试文件：

```bash
pytest -q tests/test_api_smoke.py
```

## 检索说明

- 后端默认会尝试用**本地 embedding 模型**把用户问题自动转成 **768 维向量**，并执行 `pgvector` 余弦距离 Top-1 检索。
- 当前默认使用**严格向量检索**（`GOVFLOW_RETRIEVAL_MODE=vector`），不回退文本检索。
- 向量检索使用 `ivfflat` 索引，默认 `GOVFLOW_VECTOR_IVFFLAT_PROBES=100` 以提升召回准确率（可按时延继续调优）。
- 若请求体提供 `query_vector`（768 维），则优先使用该向量。
- 若后端自动向量化不可用，会直接返回错误提示（请检查本地模型配置或直接传 `query_vector`）。

自动向量化配置（`.env`，默认本地）：

```bash
GOVFLOW_EMBEDDING_ENABLED=true
GOVFLOW_EMBEDDING_PROVIDER=local
GOVFLOW_EMBEDDING_LOCAL_MODEL=BAAI/bge-base-zh-v1.5
GOVFLOW_EMBEDDING_LOCAL_DEVICE=auto
GOVFLOW_EMBEDDING_LOCAL_FILES_ONLY=true
GOVFLOW_VECTOR_IVFFLAT_PROBES=100
GOVFLOW_EMBEDDING_TIMEOUT_SECONDS=20
```

若你要切回在线 API：

```bash
GOVFLOW_EMBEDDING_PROVIDER=api
GOVFLOW_EMBEDDING_API_KEY=sk-...
GOVFLOW_EMBEDDING_BASE_URL=https://api.openai.com/v1
GOVFLOW_EMBEDDING_MODEL=text-embedding-3-small
```

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 公开事项采集入库（广西政务服务示例）

已提供脚本：

- [scripts/import_gxzwfw_services.py](/home/fanglaozu/projects/GovFlow/scripts/import_gxzwfw_services.py)
- [scripts/backfill_embeddings.py](/home/fanglaozu/projects/GovFlow/scripts/backfill_embeddings.py)

目标页面默认是 **防城港市公安局网上办事窗口**，会批量采集该窗口所有事项，并写入：

- `gov_service`（主事项）
- `service_material`（申请材料）
- `service_process`（办理流程）
- `service_embedding`（检索文本 + 0 向量占位）

### 执行前准备

1. 启动数据库：

```bash
docker compose up -d
```

2. 初始化或更新库结构：

```bash
docker exec -i govflow-db-1 psql -U govflow -d govflow -f - < sql/schema.sql
docker exec -i govflow-db-1 psql -U govflow -d govflow -f - < sql/migrations/001_add_gov_service_source_fields.sql
docker exec -i govflow-db-1 psql -U govflow -d govflow -f - < sql/migrations/002_add_gov_service_source_unique.sql
```

3. 安装项目依赖（脚本入库需要 `psycopg`）：

```bash
pip install -e .
```

### 先查看会采集哪些事项（不写库）

```bash
python scripts/import_gxzwfw_services.py --dry-run
```

如需同时验证详情页解析：

```bash
python scripts/import_gxzwfw_services.py --dry-run --fetch-details --limit 1
```

### 正式导入

```bash
python scripts/import_gxzwfw_services.py
```

### 从导出 JSON 入库

```bash
python scripts/import_gxzwfw_services.py --import-json data/exports/gxzwfw_services_3113105254.json
```

### 仅导出 JSON（不写数据库）

```bash
python scripts/import_gxzwfw_services.py --export-json
```

默认会导出到项目根目录 `data/`。也可以手动指定路径：

```bash
python scripts/import_gxzwfw_services.py --export-json /tmp/gxzwfw_items.json
```

### 回填真实向量（用于 pgvector 检索）

导入脚本默认写入 0 向量占位，完成公开事项导入后建议执行：

```bash
python scripts/backfill_embeddings.py --region-code 3113105254
```

全量回填：

```bash
python scripts/backfill_embeddings.py
```

导出的每条记录包含：

- `service`：可直接映射 `gov_service` 的主字段
- `materials`：可映射 `service_material`
- `processes`：可映射 `service_process`
- `vector_text`：检索拼接文本
- `raw_payload`：采集原始数据与追溯信息

可选参数：

- `--region-code`：部门窗口编码（默认 `3113105254`）
- `--limit`：只导入前 N 条（调试用）
- `--export-json`：导出 JSON 文件而不是写库
- `--continue-on-error`：单条失败时继续
- `--database-url`：显式指定库连接

### 字段映射（与库字段一一对应）

- `service_name` ← 详情页标题（事项名称）
- `department` ← 办理部门
- `service_object` ← 服务对象
- `promise_days` ← 承诺办结时限（数字）
- `legal_days` ← 法定办结时限（数字）
- `on_site_times` ← 到现场次数（数字）
- `is_charge` ← 是否收费（是/否）
- `accept_condition` ← 受理条件
- `general_scope` ← 通办范围
- `handle_form` ← 办理形式
- `item_type` ← 办件类型
- `handle_address` ← 办理地点
- `handle_time` ← 办理时间
- `consult_way` ← 咨询方式
- `complaint_way` ← 监督投诉方式
- `query_way` ← 查询方式（页面有值时）
- `source_platform` ← 固定 `gxzwfw`
- `source_region_code` ← 采集参数 `regionCode`
- `source_item_id` ← 事项详情 ID（`itemDetailId`）
- `source_url` ← 事项详情 URL
- `raw_payload` ← 列表节点 + 材料接口原始 JSON + 解析元数据
- `last_crawled_at` ← 导入时写入 `now()`

材料映射：

- `service_material.material_name` ← `materialName`
- `service_material.is_required` ← `necessity`
- `service_material.material_form` ← `materialFormal` 字典值（纸质/电子等）
- `service_material.original_num` ← `materialNum`
- `service_material.copy_num` ← `copyAmount`
- `service_material.note` ← 填报须知、受理标准、来源渠道等拼接文本

流程映射：

- `service_process.step_name` ← 办理流程步骤名（如收件与受理）
- `service_process.step_desc` ← 步骤说明 + 办理结果 + 审查标准
- `service_process.sort` ← 页面顺序（1..N）
