-- Add crawler/source metadata fields to existing gov_service tables.
-- Usage: psql "$DATABASE_URL" -f sql/migrations/001_add_gov_service_source_fields.sql

ALTER TABLE gov_service
    ADD COLUMN IF NOT EXISTS source_platform VARCHAR(100),
    ADD COLUMN IF NOT EXISTS source_region_code VARCHAR(50),
    ADD COLUMN IF NOT EXISTS source_item_id VARCHAR(200),
    ADD COLUMN IF NOT EXISTS source_url TEXT,
    ADD COLUMN IF NOT EXISTS raw_payload JSONB,
    ADD COLUMN IF NOT EXISTS last_crawled_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_gov_service_source
    ON gov_service(source_platform, source_region_code, source_item_id);
