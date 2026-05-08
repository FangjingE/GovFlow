"""需可用 PostgreSQL（默认 docker-compose 5433）。无库时跳过。"""

import os

import pytest
from fastapi.testclient import TestClient

psycopg = pytest.importorskip("psycopg")

from govflow.config import get_settings  # noqa: E402
from govflow.main import app  # noqa: E402


def _db_reachable() -> bool:
    url = os.environ.get(
        "GOVFLOW_DATABASE_URL",
        "postgresql://govflow:govflow@127.0.0.1:5433/govflow",
    )
    try:
        psycopg.connect(url, connect_timeout=2).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_reachable(), reason="PostgreSQL 不可用，跳过集成测试")
def test_healthz() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}


@pytest.mark.skipif(not _db_reachable(), reason="PostgreSQL 不可用，跳过集成测试")
def test_chat_finds_sample_service() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        r = client.post("/v1/chat", json={"message": "我要办身份证"})
        assert r.status_code == 200
        data = r.json()
        assert data["kind"] == "answer"
        assert "居民身份证" in data["reply"]


@pytest.mark.skipif(not _db_reachable(), reason="PostgreSQL 不可用，跳过集成测试")
def test_chat_fallback_contains_suggestions() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        r = client.post("/v1/chat", json={"message": "随便测试一个极不相关的查询词"})
        assert r.status_code == 200
        data = r.json()
        if data["kind"] == "fallback":
            assert "你要查询的是否是：" in data["reply"]
            assert "请尝试更准确地描述" in data["reply"]
