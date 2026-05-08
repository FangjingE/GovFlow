#!/usr/bin/env python3
"""Debug ranking for a query text: embed locally/API and print Top-N vector matches."""
# ./.venv/bin/python scripts/debug_vector_rank.py 办社保 --top-k 10

from __future__ import annotations

import argparse
import os
import sys

import psycopg
from psycopg.rows import dict_row

try:
    from govflow.config import get_settings
    from govflow.services.embedding_client import embed_query
    from govflow.services.gov_types import EMBEDDING_DIM
except ModuleNotFoundError:
    sys.path.append(str(__file__).rsplit("/scripts/", 1)[0] + "/src")
    from govflow.config import get_settings
    from govflow.services.embedding_client import embed_query
    from govflow.services.gov_types import EMBEDDING_DIM


def _vec_literal(values: list[float]) -> str:
    if len(values) != EMBEDDING_DIM:
        raise ValueError(f"query embedding 维度必须为 {EMBEDDING_DIM}，当前 {len(values)}")
    return "[" + ",".join(str(float(x)) for x in values) + "]"


def main() -> None:
    parser = argparse.ArgumentParser(description="Print vector rank results for one query text.")
    parser.add_argument("query", help="要查询的文本，例如：办社保")
    parser.add_argument("--top-k", type=int, default=10, help="返回前 N 条（默认 10）")
    parser.add_argument("--region-code", default=None, help="仅查看某个 source_region_code")
    parser.add_argument("--show-vector", action="store_true", help="打印完整 768 维向量")
    parser.add_argument(
        "--vector-head",
        type=int,
        default=12,
        help="未开启 --show-vector 时，打印向量前 N 维（默认 12）",
    )
    args = parser.parse_args()

    settings = get_settings()
    dsn = os.environ.get("GOVFLOW_DATABASE_URL") or settings.database_url

    vec = embed_query(args.query, settings)
    if not vec:
        raise RuntimeError(
            "查询向量生成失败。请检查本地 embedding 模型配置/缓存（或 API 配置）。"
        )
    if len(vec) != EMBEDDING_DIM:
        raise RuntimeError(f"查询向量维度错误，期望 {EMBEDDING_DIM}，实际 {len(vec)}")

    print(f"query: {args.query}")
    print(f"embedding_dim: {len(vec)}")
    if args.show_vector:
        print("embedding:")
        print(_vec_literal(vec))
    else:
        head = max(1, int(args.vector_head))
        preview = ", ".join(f"{x:.6f}" for x in vec[:head])
        print(f"embedding_head[{head}]: [{preview}]")
    print("")

    where = ["gs.status = true"]
    sql_args: dict[str, object] = {"vec": _vec_literal(vec), "limit": int(args.top_k)}
    if args.region_code:
        where.append("gs.source_region_code = %(region_code)s")
        sql_args["region_code"] = args.region_code

    stmt = f"""
SELECT
    gs.id,
    gs.service_name,
    gs.department,
    gs.source_region_code,
    (se.embedding <=> %(vec)s::vector) AS distance
FROM service_embedding se
JOIN gov_service gs ON gs.id = se.service_id
WHERE {' AND '.join(where)}
ORDER BY distance ASC, gs.id ASC
LIMIT %(limit)s;
"""

    with psycopg.connect(dsn) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, sql_args)
            rows = cur.fetchall()

    if not rows:
        print("No rows matched.")
        return

    print(f"Top {len(rows)} by vector distance (smaller is better):")
    for i, row in enumerate(rows, start=1):
        dist = float(row["distance"])
        score = 1.0 - dist
        print(
            f"{i:>2}. distance={dist:.6f} score~={score:.6f} "
            f"id={row['id']} service={row['service_name']} "
            f"department={row['department'] or '-'} region={row['source_region_code'] or '-'}"
        )


if __name__ == "__main__":
    main()
