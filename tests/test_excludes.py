"""NOTMUCHPROXY_EXCLUDE_TAGS hides tagged messages from every result,
even when a query asks for them explicitly."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import API_KEY, AUTH
from notmuchproxy.config import get_settings
from notmuchproxy.main import app


def test_excluded_from_search_all(exclude_client: TestClient) -> None:
    body = exclude_client.get("/search", params={"q": "*"}, headers=AUTH).json()
    assert body["total"] == 4  # the spam thread is gone
    assert all("lottery" not in t["subject"].lower() for t in body["threads"])


def test_explicit_tag_query_is_rejected(exclude_client: TestClient) -> None:
    # excluded tags are hidden from list_tags, so query validation treats them
    # as nonexistent: an instructive 400 rather than a misleading empty result
    resp = exclude_client.get("/search", params={"q": "tag:spam"}, headers=AUTH)
    assert resp.status_code == 400
    assert "spam" not in resp.json()["detail"].split("Tags in this archive: ")[1]


def test_excluded_message_is_404(exclude_client: TestClient) -> None:
    resp = exclude_client.get("/messages/spam-1@example.com", headers=AUTH)
    assert resp.status_code == 404


def test_excluded_tag_not_advertised(exclude_client: TestClient) -> None:
    tags = exclude_client.get("/tags", headers=AUTH).json()["tags"]
    assert "spam" not in tags
    assert "inbox" in tags


def test_excluded_thread_is_404(mail_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTMUCHPROXY_API_KEY", API_KEY)
    monkeypatch.setenv("NOTMUCH_DATABASE", str(mail_root))

    # find the spam thread id with exclusions off
    monkeypatch.delenv("NOTMUCHPROXY_EXCLUDE_TAGS", raising=False)
    get_settings.cache_clear()
    with TestClient(app) as client:
        body = client.get("/search", params={"q": "tag:spam"}, headers=AUTH).json()
        thread_id = body["threads"][0]["thread_id"]
        assert client.get(f"/threads/{thread_id}", headers=AUTH).status_code == 200

    # with exclusions on, the same thread is unreachable
    monkeypatch.setenv("NOTMUCHPROXY_EXCLUDE_TAGS", "spam")
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get(f"/threads/{thread_id}", headers=AUTH).status_code == 404


def test_without_excludes_spam_is_visible(client: TestClient) -> None:
    body = client.get("/search", params={"q": "tag:spam"}, headers=AUTH).json()
    assert body["total"] == 1
    assert "lottery" in body["threads"][0]["subject"].lower()
