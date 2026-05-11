#!/usr/bin/env python3
"""Rebuild service_embedding.vector_text from structured service fields."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import psycopg
from psycopg.rows import dict_row

try:
    from govflow.config import get_settings
    from import_gxzwfw_services import build_vector_text_parts
except ModuleNotFoundError:
    sys.path.append(str(__file__).rsplit("/scripts/", 1)[0] + "/src")
    from govflow.config import get_settings
    sys.path.append(str(__file__).rsplit("/scripts/", 1)[0] + "/scripts")
    from import_gxzwfw_services import build_vector_text_parts


def _load_rows(conn: Any, *, region_code: str | None, limit: int | None) -> list[dict[str, Any]]:
    where = ["1=1"]
    args: list[Any] = []
    if region_code:
        where.append("gs.source_region_code = %s")
        args.append(region_code)
    limit_sql = f"LIMIT {int(limit)}" if limit else ""
    stmt = f"""
SELECT
    se.id AS embedding_id,
    gs.id AS service_id,
    gs.service_name,
    gs.department,
    gs.service_object,
    gs.accept_condition,
    gs.item_type,
    gs.handle_form
FROM service_embedding se
JOIN gov_service gs ON gs.id = se.service_id
WHERE {' AND '.join(where)}
ORDER BY se.id
{limit_sql}
"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(stmt, args)
        return cur.fetchall()


def _load_materials(conn: Any, service_id: int) -> list[dict[str, Any]]:
    stmt = """
SELECT material_name
FROM service_material
WHERE service_id = %s
ORDER BY id
"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(stmt, (service_id,))
        return cur.fetchall()


def _load_processes(conn: Any, service_id: int) -> list[dict[str, Any]]:
    stmt = """
SELECT step_name
FROM service_process
WHERE service_id = %s
ORDER BY sort NULLS LAST, id
"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(stmt, (service_id,))
        return cur.fetchall()


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild service_embedding.vector_text from current structured data.")
    parser.add_argument("--region-code", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    dsn = os.environ.get("GOVFLOW_DATABASE_URL") or settings.database_url

    updated = 0
    with psycopg.connect(dsn) as conn:
        rows = _load_rows(conn, region_code=args.region_code, limit=args.limit)
        total = len(rows)
        if total == 0:
            print("No rows matched.")
            return
        for index, row in enumerate(rows, start=1):
            materials = _load_materials(conn, int(row["service_id"]))
            processes = _load_processes(conn, int(row["service_id"]))
            service = {
                "service_name": row.get("service_name"),
                "department": row.get("department"),
                "service_object": row.get("service_object"),
                "accept_condition": row.get("accept_condition"),
                "item_type": row.get("item_type"),
                "handle_form": row.get("handle_form"),
            }
            main_text, aux_text = build_vector_text_parts(service, materials, processes)
            vector_text = main_text if main_text.strip() else aux_text
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE service_embedding SET vector_text = %s WHERE id = %s",
                    (vector_text, row["embedding_id"]),
                )
            updated += 1
            if index % 100 == 0 or index == total:
                conn.commit()
                print(f"[{index}/{total}] updated vector_text")
    print(f"Done. updated={updated}")


if __name__ == "__main__":
    main()
