import httpx
from fastapi.testclient import TestClient

from conftest import AUTH


class TestAuth:
    def test_no_token_is_rejected(self, client: TestClient) -> None:
        assert client.get("/search", params={"q": "*"}).status_code == 401

    def test_wrong_token_is_rejected(self, client: TestClient) -> None:
        resp = client.get("/search", params={"q": "*"}, headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401

    def test_healthz_needs_no_token(self, client: TestClient) -> None:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["message_count"] == 7

    def test_openapi_schema_needs_no_token(self, client: TestClient) -> None:
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        ops = {op["operationId"] for path in resp.json()["paths"].values() for op in path.values()}
        assert ops == {"search_email", "get_thread", "get_message", "list_tags"}


class TestSearch:
    def test_search_all(self, client: TestClient) -> None:
        resp = client.get("/search", params={"q": "*"}, headers=AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5  # 5 threads (one has 3 messages)
        assert len(body["threads"]) == 5

    def test_search_by_subject(self, client: TestClient) -> None:
        resp = client.get("/search", params={"q": "subject:invoice"}, headers=AUTH)
        body = resp.json()
        assert body["total"] == 1
        thread = body["threads"][0]
        assert thread["subject"] == "Invoice #1234 for January"
        assert "billing" in thread["tags"]
        assert thread["matched"] == 1
        assert thread["total"] == 1

    def test_search_thread_counts(self, client: TestClient) -> None:
        resp = client.get("/search", params={"q": "subject:planning"}, headers=AUTH)
        thread = resp.json()["threads"][0]
        assert thread["total"] == 3

    def test_pagination(self, client: TestClient) -> None:
        resp = client.get("/search", params={"q": "*", "limit": 2}, headers=AUTH)
        body = resp.json()
        assert len(body["threads"]) == 2
        assert body["total"] == 5

        resp2 = client.get("/search", params={"q": "*", "limit": 2, "offset": 2}, headers=AUTH)
        body2 = resp2.json()
        assert len(body2["threads"]) == 2
        first_page_ids = {t["thread_id"] for t in body["threads"]}
        second_page_ids = {t["thread_id"] for t in body2["threads"]}
        assert not first_page_ids & second_page_ids

    def test_sort_order(self, client: TestClient) -> None:
        newest = client.get("/search", params={"q": "*"}, headers=AUTH).json()
        oldest = client.get(
            "/search", params={"q": "*", "sort": "oldest-first"}, headers=AUTH
        ).json()
        assert newest["threads"][0]["thread_id"] == oldest["threads"][-1]["thread_id"]

    def test_no_results(self, client: TestClient) -> None:
        body = client.get("/search", params={"q": "subject:nonexistent"}, headers=AUTH).json()
        assert body["total"] == 0
        assert body["threads"] == []

    def test_invalid_query_is_400_with_reason(self, client: TestClient) -> None:
        resp = client.get("/search", params={"q": "date:bogus..nonsense"}, headers=AUTH)
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail.startswith("invalid notmuch query:")
        # the xapian reason is surfaced so the caller can fix the query
        assert "date specification" in detail


class TestQueryValidation:
    """Unknown prefixes and tags silently match nothing in xapian; the proxy
    rejects them with a corrective 400 instead of returning a misleading 0."""

    def _search(self, client: TestClient, q: str) -> httpx.Response:
        return client.get("/search", params={"q": q}, headers=AUTH)

    def test_unknown_prefix_is_400_with_hint(self, client: TestClient) -> None:
        resp = self._search(client, "tag:inbox and status:unread")
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "'status:'" in detail
        assert "tag:unread" in detail  # the gmail-ism gets a targeted correction

    def test_unknown_prefix_without_hint_lists_valid_ones(self, client: TestClient) -> None:
        resp = self._search(client, "frmo:alice")
        assert resp.status_code == 400
        assert "Valid prefixes" in resp.json()["detail"]

    def test_capitalized_prefix_is_400(self, client: TestClient) -> None:
        resp = self._search(client, "From:alice")
        assert resp.status_code == 400
        assert "lowercase" in resp.json()["detail"]

    def test_nonexistent_tag_is_400_with_tag_list(self, client: TestClient) -> None:
        resp = self._search(client, "tag:inbox and not tag:handled")
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "'handled'" in detail
        assert "inbox" in detail  # real tags are listed so the caller can pick one

    def test_is_alias_tag_is_validated(self, client: TestClient) -> None:
        assert self._search(client, "is:urgent").status_code == 400

    def test_quoted_tag_value_is_validated(self, client: TestClient) -> None:
        assert self._search(client, 'tag:"handled"').status_code == 400

    def test_real_tags_pass(self, client: TestClient) -> None:
        resp = self._search(client, "tag:inbox and is:unread")
        assert resp.status_code == 200

    def test_colon_text_in_quotes_passes(self, client: TestClient) -> None:
        resp = self._search(client, '"re: budget" date:1year..')
        assert resp.status_code == 200

    def test_unquoted_colon_text_is_400(self, client: TestClient) -> None:
        resp = self._search(client, "re: budget")
        assert resp.status_code == 400
        assert "double quotes" in resp.json()["detail"]

    def test_regex_values_pass(self, client: TestClient) -> None:
        resp = self._search(client, 'from:"/alice@.*[.]example[.]com/"')
        assert resp.status_code == 200


class TestThread:
    def _planning_thread_id(self, client: TestClient) -> str:
        resp = client.get("/search", params={"q": "subject:planning"}, headers=AUTH)
        return resp.json()["threads"][0]["thread_id"]

    def test_get_thread(self, client: TestClient) -> None:
        thread_id = self._planning_thread_id(client)
        resp = client.get(f"/threads/{thread_id}", headers=AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["thread_id"] == thread_id
        messages = body["messages"]
        assert len(messages) == 3
        # oldest first, with reply depth
        assert [m["message_id"] for m in messages] == [
            "planning-1@example.com",
            "planning-2@example.com",
            "planning-3@example.com",
        ]
        assert [m["depth"] for m in messages] == [0, 1, 2]
        assert all(m["thread_id"] == thread_id for m in messages)
        assert messages[0]["sender"] == "Alice Anderson <alice@example.com>"
        assert "Let's plan Q1" in messages[0]["body"]

    def test_unknown_thread_is_404(self, client: TestClient) -> None:
        assert client.get("/threads/0000000000000000", headers=AUTH).status_code == 404


class TestMessage:
    def test_get_message(self, client: TestClient) -> None:
        resp = client.get("/messages/lunch-1@example.com", headers=AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["subject"] == "Lunch tomorrow?"
        assert body["body"] == "Tacos at noon?"
        assert body["depth"] == 0
        assert body["thread_id"]  # resolved via a separate notmuch search

    def test_html_body_is_stripped(self, client: TestClient) -> None:
        body = client.get("/messages/newsletter-7@example.com", headers=AUTH).json()
        assert "<" not in body["body"]
        assert "color: red" not in body["body"]  # style blocks dropped
        assert "Shiny things" in body["body"]
        assert "three" in body["body"]

    def test_attachments_listed(self, client: TestClient) -> None:
        body = client.get("/messages/invoice-1234@example.com", headers=AUTH).json()
        assert body["attachments"] == ["invoice-1234.pdf"]
        assert "invoice #1234 for $42.00" in body["body"].lower()

    def test_unknown_message_is_404(self, client: TestClient) -> None:
        assert client.get("/messages/nope@example.com", headers=AUTH).status_code == 404


class TestTags:
    def test_list_tags(self, client: TestClient) -> None:
        resp = client.get("/tags", headers=AUTH)
        assert resp.status_code == 200
        tags = resp.json()["tags"]
        assert {"inbox", "unread", "billing", "newsletter"} <= set(tags)
        assert tags == sorted(tags)
