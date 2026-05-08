-- Ensure crawled services can be updated idempotently by source item id.
-- Usage: psql "$DATABASE_URL" -f sql/migrations/002_add_gov_service_source_unique.sql

CREATE UNIQUE INDEX IF NOT EXISTS uq_gov_service_source_item
    ON gov_service(source_platform, source_region_code, source_item_id)
    WHERE source_platform IS NOT NULL
      AND source_region_code IS NOT NULL
      AND source_item_id IS NOT NULL;
