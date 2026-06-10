from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from notmuchproxy.config import get_settings
from notmuchproxy.fixtures import create_archive
from notmuchproxy.main import app

API_KEY = "test-secret-key"
AUTH = {"Authorization": f"Bearer {API_KEY}"}


@pytest.fixture(scope="session")
def mail_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return create_archive(tmp_path_factory.mktemp("archive"))


@pytest.fixture
def client(mail_root: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("NOTMUCHPROXY_API_KEY", API_KEY)
    monkeypatch.setenv("NOTMUCH_DATABASE", str(mail_root))
    get_settings.cache_clear()
    # context manager runs the lifespan, which the mounted MCP app needs
    with TestClient(app) as test_client:
        yield test_client
