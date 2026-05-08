#!/usr/bin/env python3
"""Backfill real embeddings for service_embedding.vector_text.

Supports:
1) OpenAI-compatible embeddings API
2) Local sentence-transformers model (recommended for offline/local use)
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import httpx
import psycopg

try:
    from govflow.config import get_settings
except ModuleNotFoundError:
    sys.path.append(str(__file__).rsplit("/scripts/", 1)[0] + "/src")
    from govflow.config import get_settings

from govflow.services.gov_types import EMBEDDING_DIM


def _vec_literal(values: list[float]) -> str:
    if len(values) != EMBEDDING_DIM:
        raise ValueError(f"embedding 维度必须为 {EMBEDDING_DIM}，当前 {len(values)}")
    return "[" + ",".join(str(float(x)) for x in values) + "]"


def _embed(text: str, *, api_key: str, base_url: str, model: str, timeout: int) -> list[float]:
    url = base_url.rstrip("/")
    if not url.endswith("/embeddings"):
        url = f"{url}/embeddings"
    payload: dict[str, Any] = {
        "model": model,
        "input": text,
        "dimensions": EMBEDDING_DIM,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
    data = resp.json()
    emb = (data.get("data") or [{}])[0].get("embedding")
    if not isinstance(emb, list) or len(emb) != EMBEDDING_DIM:
        raise RuntimeError("embedding 返回格式或维度不正确")
    return [float(x) for x in emb]


def _load_local_model(model_name: str, device: str, local_files_only: bool):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "缺少 sentence-transformers 依赖，请执行: ./.venv/bin/pip install sentence-transformers torch"
        ) from exc
    return SentenceTransformer(model_name, device=device, local_files_only=local_files_only)


def _embed_local_batch(model: Any, texts: list[str], batch_size: int) -> list[list[float]]:
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    out: list[list[float]] = []
    for vec in vectors:
        row = [float(x) for x in vec.tolist()]
        if len(row) != EMBEDDING_DIM:
            raise RuntimeError(
                f"本地模型输出维度为 {len(row)}，但数据库要求 {EMBEDDING_DIM}。"
                "请改用 768 维模型（如 BAAI/bge-base-zh-v1.5）。"
            )
        out.append(row)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill embeddings in service_embedding table.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--service-id", type=int, default=None)
    parser.add_argument("--region-code", default=None)
    parser.add_argument(
        "--all",
        action="store_true",
        help="回填所有记录（默认仅回填当前为 0 向量的记录）",
    )
    parser.add_argument(
        "--provider",
        choices=["local", "api"],
        default="local",
        help="向量来源：local（本地模型）或 api（OpenAI兼容API）",
    )
    parser.add_argument(
        "--local-model",
        default="BAAI/bge-base-zh-v1.5",
        help="本地 sentence-transformers 模型名（建议 768 维）",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="本地模型设备：auto/cuda/cpu",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="本地模型批大小",
    )
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="仅使用本地缓存模型文件（不访问网络）",
    )
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    settings = get_settings()
    dsn = os.environ.get("GOVFLOW_DATABASE_URL") or settings.database_url
    api_key = settings.embedding_api_key or os.environ.get("GOVFLOW_EMBEDDING_API_KEY")
    base_url = settings.embedding_base_url
    api_model = settings.embedding_model

    where = ["1=1"]
    query_args: list[Any] = []
    if args.service_id is not None:
        where.append("se.service_id = %s")
        query_args.append(args.service_id)
    if args.region_code:
        where.append("gs.source_region_code = %s")
        query_args.append(args.region_code)
    if not args.all:
        where.append("se.embedding = %s::vector")
    limit_sql = f"LIMIT {int(args.limit)}" if args.limit else ""

    select_sql = f"""
SELECT se.id, se.service_id, se.vector_text
FROM service_embedding se
JOIN gov_service gs ON gs.id = se.service_id
WHERE {' AND '.join(where)}
ORDER BY se.id
{limit_sql}
"""

    zero_literal = "[" + ",".join(["0"] * EMBEDDING_DIM) + "]"
    if not args.all:
        query_args.append(zero_literal)

    local_model = None
    if args.provider == "local":
        device = args.device
        if device == "auto":
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"
        print(f"Loading local embedding model: {args.local_model} on {device}")
        local_model = _load_local_model(
            args.local_model,
            device=device,
            local_files_only=args.local_files_only,
        )
    else:
        if not api_key:
            raise RuntimeError("缺少 embedding_api_key（GOVFLOW_EMBEDDING_API_KEY）")

    updated = 0
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(select_sql, query_args)
            rows = cur.fetchall()

        total = len(rows)
        if args.provider == "local":
            assert local_model is not None
            for start in range(0, total, args.batch_size):
                batch_rows = rows[start : start + args.batch_size]
                texts = [(r[2] or "").strip() for r in batch_rows]
                try:
                    vectors = _embed_local_batch(local_model, texts, batch_size=args.batch_size)
                    with conn.cursor() as cur:
                        for (eid, _service_id, _), emb in zip(batch_rows, vectors):
                            cur.execute(
                                "UPDATE service_embedding SET embedding = %s::vector WHERE id = %s",
                                (_vec_literal(emb), eid),
                            )
                    conn.commit()
                    updated += len(batch_rows)
                    end = min(start + len(batch_rows), total)
                    print(f"[{end}/{total}] updated")
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    for i, (_, service_id, _) in enumerate(batch_rows, start=start + 1):
                        print(f"[{i}/{total}] ERROR service_id={service_id}: {exc}", file=sys.stderr)
        else:
            for i, (eid, service_id, vector_text) in enumerate(rows, start=1):
                try:
                    emb = _embed(
                        vector_text or "",
                        api_key=api_key,  # type: ignore[arg-type]
                        base_url=base_url,
                        model=api_model,
                        timeout=args.timeout,
                    )
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE service_embedding SET embedding = %s::vector WHERE id = %s",
                            (_vec_literal(emb), eid),
                        )
                    conn.commit()
                    updated += 1
                    print(f"[{i}/{total}] updated service_id={service_id}")
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    print(f"[{i}/{total}] ERROR service_id={service_id}: {exc}", file=sys.stderr)
    print(f"Done. updated={updated}/{total}")


if __name__ == "__main__":
    main()
