"""Embedding client (OpenAI-compatible API)."""

from __future__ import annotations

from functools import lru_cache
import os
from typing import Any

import httpx

from govflow.config import Settings
from govflow.services.gov_types import EMBEDDING_DIM


def _build_url(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith("/embeddings"):
        return base
    return f"{base}/embeddings"


@lru_cache
def _get_local_model(model_name: str, device: str, local_files_only: bool):
    # Force offline behavior to avoid background hub/network calls in restricted envs.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, device=device, local_files_only=local_files_only)


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _embed_query_local(text: str, settings: Settings) -> list[float] | None:
    device = _resolve_device(settings.embedding_local_device)
    try:
        model = _get_local_model(
            settings.embedding_local_model,
            device,
            settings.embedding_local_files_only,
        )
        vec = model.encode(
            text,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        row = [float(x) for x in vec.tolist()]
        if len(row) != EMBEDDING_DIM:
            return None
        return row
    except Exception:
        return None


def _embed_query_api(text: str, settings: Settings) -> list[float] | None:
    if not settings.embedding_api_key:
        return None

    url = _build_url(settings.embedding_base_url)
    headers = {
        "Authorization": f"Bearer {settings.embedding_api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": settings.embedding_model,
        "input": text,
        "dimensions": EMBEDDING_DIM,
    }

    try:
        with httpx.Client(timeout=settings.embedding_timeout_seconds) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
        data = resp.json()
        arr = data.get("data") or []
        if not arr:
            return None
        embedding = arr[0].get("embedding")
        if not isinstance(embedding, list) or len(embedding) != EMBEDDING_DIM:
            return None
        return [float(x) for x in embedding]
    except Exception:
        return None


def embed_query(text: str, settings: Settings) -> list[float] | None:
    """Return 768-dim vector when embedding is available; otherwise None."""
    if not settings.embedding_enabled:
        return None

    text = text.strip()
    if not text:
        return None

    if settings.embedding_provider == "local":
        return _embed_query_local(text, settings)
    return _embed_query_api(text, settings)
