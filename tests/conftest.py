"""单测：清除配置缓存，避免 .env 与 monkeypatch 串味。"""

import pytest

from govflow.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
