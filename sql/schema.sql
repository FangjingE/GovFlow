-- GovFlow: PostgreSQL + pgvector（见 docs/ARCHITECTURE.md）
-- 使用：psql "$DATABASE_URL" -f sql/schema.sql

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 政务事项主表（含文档检索所需的 status）
CREATE TABLE IF NOT EXISTS gov_service (
    id BIGSERIAL PRIMARY KEY,
    service_name VARCHAR(500) NOT NULL,
    department VARCHAR(255),
    service_object VARCHAR(100),
    promise_days INT,
    legal_days INT,
    on_site_times INT,
    is_charge BOOLEAN DEFAULT false,
    accept_condition TEXT,
    general_scope VARCHAR(255) DEFAULT '-',
    handle_form VARCHAR(255),
    item_type VARCHAR(100),
    handle_address TEXT,
    handle_time TEXT,
    consult_way TEXT,
    complaint_way TEXT,
    query_way TEXT,
    source_platform VARCHAR(100),
    source_region_code VARCHAR(50),
    source_item_id VARCHAR(200),
    source_url TEXT,
    raw_payload JSONB,
    last_crawled_at TIMESTAMP,
    status BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_gov_service_name ON gov_service(service_name);
CREATE INDEX IF NOT EXISTS idx_gov_service_status ON gov_service(status) WHERE status = true;
CREATE INDEX IF NOT EXISTS idx_gov_service_name_trgm ON gov_service USING gin (service_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_gov_service_source
    ON gov_service(source_platform, source_region_code, source_item_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_gov_service_source_item
    ON gov_service(source_platform, source_region_code, source_item_id)
    WHERE source_platform IS NOT NULL
      AND source_region_code IS NOT NULL
      AND source_item_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS service_embedding (
    id BIGSERIAL PRIMARY KEY,
    service_id BIGINT NOT NULL REFERENCES gov_service(id) ON DELETE CASCADE,
    service_name VARCHAR(500) NOT NULL,
    vector_text TEXT NOT NULL,
    embedding vector(768) NOT NULL,
    created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_service_embedding_service_id ON service_embedding(service_id);
CREATE INDEX IF NOT EXISTS idx_se_vtext_trgm ON service_embedding USING gin (vector_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_service_embedding_ivf
    ON service_embedding USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE IF NOT EXISTS service_material (
    id BIGSERIAL PRIMARY KEY,
    service_id BIGINT REFERENCES gov_service(id) ON DELETE CASCADE,
    material_name TEXT NOT NULL,
    is_required BOOLEAN DEFAULT true,
    material_form VARCHAR(50),
    original_num INT,
    copy_num INT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_service_material_service_id ON service_material(service_id);

CREATE TABLE IF NOT EXISTS service_process (
    id BIGSERIAL PRIMARY KEY,
    service_id BIGINT REFERENCES gov_service(id) ON DELETE CASCADE,
    step_name VARCHAR(255),
    step_desc TEXT,
    sort INT DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_service_process_service_id ON service_process(service_id);
