"""Authentication for both API surfaces (REST and MCP).

Exactly one mechanism is active, picked by configuration:

- static mode (NOTMUCHPROXY_API_KEY): every request must carry the key as a
  bearer token. This is what Open WebUI's OpenAPI tool servers speak.
- OIDC mode (NOTMUCHPROXY_OIDC_* + NOTMUCHPROXY_PUBLIC_URL): fastmcp's OIDC
  proxy fronts the external IdP, presenting a spec-compliant MCP authorization
  server (incl. dynamic client registration) to clients while acting as a
  plain OIDC client upstream. The proxy issues its own JWTs, which both the
  MCP endpoint and the REST endpoints verify.

The embedded MCP server dispatches tool calls to the REST endpoints through an
in-process HTTP client; that hop authenticates with a random per-process token
so it works identically in both modes.
"""

import secrets
from collections.abc import Generator
from typing import TYPE_CHECKING, Annotated

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import Settings, get_settings, oidc_config

if TYPE_CHECKING:
    from fastmcp.server.auth.oidc_proxy import OIDCProxy

_bearer = HTTPBearer(auto_error=False)

_INTERNAL_TOKEN = secrets.token_urlsafe(32)


def _build_mcp_auth() -> "OIDCProxy | None":
    cfg = oidc_config()
    if cfg is None:
        return None
    from fastmcp.server.auth.oidc_proxy import OIDCProxy

    return OIDCProxy(
        config_url=cfg.config_url,
        client_id=cfg.client_id,
        client_secret=cfg.client_secret,
        base_url=cfg.public_url,
    )


# constructed at import; fetches the IdP discovery document in OIDC mode
MCP_AUTH = _build_mcp_auth()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if credentials is None:
        raise _unauthorized()
    token = credentials.credentials
    if secrets.compare_digest(token.encode(), _INTERNAL_TOKEN.encode()):
        return  # in-process call from the embedded MCP server
    if MCP_AUTH is not None:
        if await MCP_AUTH.verify_token(token) is None:
            raise _unauthorized()
        return
    if settings.api_key is None or not secrets.compare_digest(
        token.encode(), settings.api_key.encode()
    ):
        raise _unauthorized()


class StaticBearerMiddleware:
    """Static-mode guard for the mounted MCP app, which doesn't go through
    FastAPI's dependency system. Unused in OIDC mode (fastmcp verifies there)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] != "OPTIONS"
            and scope["path"].startswith("/mcp")
        ):
            token = Headers(scope=scope).get("authorization", "")
            api_key = get_settings().api_key
            if api_key is None or not secrets.compare_digest(
                token.encode(), f"Bearer {api_key}".encode()
            ):
                response = JSONResponse(
                    {"detail": "Missing or invalid bearer token"},
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class InternalBearerAuth(httpx.Auth):
    """Authenticates the embedded MCP server's in-process calls to the REST
    endpoints with the per-process internal token."""

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response]:
        request.headers["Authorization"] = f"Bearer {_INTERNAL_TOKEN}"
        yield request
