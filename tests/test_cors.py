"""CORS lets browser-based clients (Open WebUI user tools, web MCP clients)
call the API; with the default NOTMUCHPROXY_CORS_ORIGINS='*' any origin works."""

from fastapi.testclient import TestClient

from conftest import AUTH

ORIGIN = "https://openwebui.example.com"


def test_preflight_search(client: TestClient) -> None:
    resp = client.options(
        "/search",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"
    assert "authorization" in resp.headers["access-control-allow-headers"].lower()


def test_preflight_allows_unanticipated_headers(client: TestClient) -> None:
    """Clients send headers we can't predict (Open WebUI does); the preflight
    must echo them back rather than 400 on anything outside an allowlist."""
    resp = client.options(
        "/search",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-requested-with,x-openwebui-chat",
        },
    )
    assert resp.status_code == 200
    allowed = resp.headers["access-control-allow-headers"].lower()
    for header in ("authorization", "x-requested-with", "x-openwebui-chat"):
        assert header in allowed


def test_preflight_mcp_needs_no_auth(client: TestClient) -> None:
    resp = client.options(
        "/mcp",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"


def test_actual_request_gets_cors_headers(client: TestClient) -> None:
    resp = client.get("/search", params={"q": "*"}, headers={**AUTH, "Origin": ORIGIN})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"
