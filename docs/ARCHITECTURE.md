# PostgreSQL + pgvector 政务事项存储与检索方案

## 一、项目说明

本方案用于 **AI政务助手**：

- 仅使用 **PostgreSQL + pgvector**
- 不做意图识别
- 用户输入任意文本 → 向量检索 → 返回**关联度最高的1条政务事项**
- 支持事项、材料、流程一体化查询

---

## 二、数据库表结构

### 1. 开启 pgvector 扩展

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 2. 政务事项主表

```sql
-- 1. 政务事项主表（已按需求完整补充字段）
CREATE TABLE gov_service (
    id BIGSERIAL PRIMARY KEY,
    service_name VARCHAR(500) NOT NULL, -- 事项标准名称
    department VARCHAR(255), -- 办理部门
    service_object VARCHAR(100), -- 服务对象
    promise_days INT, -- 承诺时限
    legal_days INT, -- 法定时限
    on_site_times INT, -- 到现场次数
    is_charge BOOLEAN DEFAULT false, -- 是否收费
    accept_condition TEXT, -- 受理条件
    general_scope VARCHAR(255) DEFAULT '-', -- 通办范围
    handle_form VARCHAR(255), -- 办理形式：窗口办理,网上办理,自助办理
    item_type VARCHAR(100), -- 办件类型：即办件/承诺件
    handle_address TEXT, -- 办理地点
    handle_time TEXT, -- 办理时间
    consult_way TEXT, -- 咨询方式
    complaint_way TEXT, -- 监督投诉方式
    query_way TEXT, -- 查询方式
    source_platform VARCHAR(100), -- 数据来源平台，如 gxzwfw
    source_region_code VARCHAR(50), -- 来源地区编码
    source_item_id VARCHAR(200), -- 来源事项唯一标识/接口主键
    source_url TEXT, -- 来源页面 URL
    raw_payload JSONB, -- 来源接口原始数据，便于追溯和重跑映射
    last_crawled_at TIMESTAMP, -- 最近采集时间
    status BOOLEAN NOT NULL DEFAULT true, -- 是否对外检索（示例 SQL 中 WHERE gs.status = true）
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
CREATE INDEX idx_gov_service_name ON gov_service(service_name);
CREATE INDEX idx_gov_service_source ON gov_service(source_platform, source_region_code, source_item_id);
CREATE UNIQUE INDEX uq_gov_service_source_item
    ON gov_service(source_platform, source_region_code, source_item_id)
    WHERE source_platform IS NOT NULL
      AND source_region_code IS NOT NULL
      AND source_item_id IS NOT NULL;
```

### 3. 事项向量表（核心检索表）

```sql
CREATE TABLE service_embedding (
    id BIGSERIAL PRIMARY KEY,
    service_id BIGINT NOT NULL REFERENCES gov_service(id),
    service_name VARCHAR(500) NOT NULL,
    -- 向量文本：标题+受理条件，用于语义匹配
    vector_text TEXT NOT NULL,
    -- 向量维度：使用 bge-small-zh 则 512 / bge-base-zh 则 768
    embedding vector(768) NOT NULL,
    created_at TIMESTAMP DEFAULT now()
);

-- 向量相似度索引
CREATE INDEX idx_service_embedding ON service_embedding USING ivfflat (embedding vector_cosine_ops) WITH (lists = 1000);
```

### 4. 申请材料表

```sql
CREATE TABLE service_material (
    id BIGSERIAL PRIMARY KEY,
    service_id BIGINT REFERENCES gov_service(id),
    material_name TEXT NOT NULL,
    is_required BOOLEAN DEFAULT true,
    material_form VARCHAR(50), -- 纸质/电子
    original_num INT,
    copy_num INT,
    note TEXT
);
```

### 5. 办理流程表

```sql
CREATE TABLE service_process (
    id BIGSERIAL PRIMARY KEY,
    service_id BIGINT REFERENCES gov_service(id),
    step_name VARCHAR(255),
    step_desc TEXT,
    sort INT DEFAULT 0
);
```

---

## 三、核心接口逻辑

### 1. 插入/更新事项向量

流程：

1. 拼接 `vector_text` = 事项名称 + 受理条件
2. 调用 embedding 模型生成向量
3. 存入 `service_embedding`

### 2. 用户查询 → 向量检索

输入：用户问题字符串
输出：**关联度最高的1条事项完整信息**

SQL 模板：

```sql
SELECT
    gs.id,
    gs.service_name,
    gs.department,
    gs.handle_address,
    gs.promise_days,
    gs.on_site_times,
    gs.is_charge,
    gs.accept_condition,
    se.embedding <=> (%s) AS similarity
FROM service_embedding se
JOIN gov_service gs ON se.service_id = gs.id
WHERE gs.status = true
ORDER BY similarity ASC
LIMIT 1;
```

- `%s` = 用户问题生成的向量
- `similarity ASC` = 相似度最高优先
- 只返回 **TOP 1** 最匹配事项

### 3. 获取事项完整信息

```sql
-- 主信息
SELECT * FROM gov_service WHERE id = ?;

-- 材料
SELECT * FROM service_material WHERE service_id = ?;

-- 流程
SELECT * FROM service_process WHERE service_id = ? ORDER BY sort;
```

---

## 四、对话工作流程

1. 用户输入任意问题
2. 后端把问题转为向量
3. 执行 pgvector 相似度查询
4. 取出 **相似度最高的1个事项**
5. 加载该事项的：名称、部门、时限、材料、流程
6. 返回给用户

---

## 五、推荐技术配置

- 向量模型：`BAAI/bge-base-zh-v1.5`（维度768）
- 向量距离：**余弦距离 cosine**
- 返回条数：**LIMIT 1**
- 无意图识别 / 无分类 / 无NLU

---

## 六、输出模板

```
事项名称：{{service_name}}
办理部门：{{department}}
办理地点：{{handle_address}}
通办范围：{{general_scope}}
服务对象：{{service_object}}
法定时限：{{legal_days}}个工作日
承诺时限：{{promise_days}}个工作日
到现场次数：{{on_site_times}}次
是否收费：{{is_charge}}{% if is_charge == '是' %}
办理方式：{{handle_way}}（线上/线下/自助）
是否网办：{{is_online}}
查询方式：{{query_way}}
办件类型: {{item_type}}
办理时间: {{handle_time}}
咨询方式: {{consult_way}}
监督投诉方式: {{complaint_way}}

【申请材料】
{% for item in materials %}
- {{item.material_name}}
{% endfor %}

【办理流程】
{% for step in processes %}
- {{loop.index}}. {{step.step_name}}：{{step.step_desc}}
{% endfor %}

用户问题：{{query}}
```

---
