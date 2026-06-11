"""The /mcp endpoint exposes the REST API as MCP tools (streamable HTTP,
stateless, JSON responses)."""

from typing import Any

from fastapi.testclient import TestClient

from conftest import AUTH

MCP_HEADERS = {
    **AUTH,
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _rpc(client: TestClient, method: str, params: dict[str, Any] | None = None) -> Any:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    resp = client.post("/mcp", headers=MCP_HEADERS, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "error" not in body, body
    return body["result"]


def test_mcp_requires_auth(client: TestClient) -> None:
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resp.status_code == 401


def test_initialize(client: TestClient) -> None:
    result = _rpc(
        client,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    )
    assert result["serverInfo"]["name"] == "notmuchproxy"
    assert "tools" in result["capabilities"]


def test_tools_list(client: TestClient) -> None:
    tools = _rpc(client, "tools/list")["tools"]
    assert {t["name"] for t in tools} == {
        "search_email",
        "get_thread",
        "get_message",
        "list_tags",
    }
    search = next(t for t in tools if t["name"] == "search_email")
    assert "q" in search["inputSchema"]["properties"]
    # param descriptions survive the OpenAPI -> MCP conversion
    assert "notmuch query" in search["inputSchema"]["properties"]["q"]["description"]


def test_tools_call_search(client: TestClient) -> None:
    result = _rpc(
        client,
        "tools/call",
        {"name": "search_email", "arguments": {"q": "subject:invoice"}},
    )
    assert not result.get("isError")
    structured = result["structuredContent"]
    assert structured["total"] == 1
    assert structured["threads"][0]["subject"] == "Invoice #1234 for January"


def test_tools_call_invalid_query_explains_error(client: TestClient) -> None:
    resp = client.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search_email", "arguments": {"q": "date:bogus..nonsense"}},
        },
    )
    result = resp.json()["result"]
    assert result["isError"]
    text = result["content"][0]["text"]
    # the model gets an actionable explanation, not just a status code
    assert "invalid notmuch query" in text
    assert "date specification" in text


def test_tools_call_thread_roundtrip(client: TestClient) -> None:
    search = _rpc(
        client,
        "tools/call",
        {"name": "search_email", "arguments": {"q": "subject:planning"}},
    )
    thread_id = search["structuredContent"]["threads"][0]["thread_id"]
    thread = _rpc(
        client,
        "tools/call",
        {"name": "get_thread", "arguments": {"thread_id": thread_id}},
    )
    messages = thread["structuredContent"]["messages"]
    assert len(messages) == 3
    assert "Let's plan Q1" in messages[0]["body"]
