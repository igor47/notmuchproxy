import secrets
from collections.abc import Generator
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


def require_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), settings.api_key.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


class BearerAuthMiddleware:
    """ASGI middleware enforcing the same bearer token on the mounted MCP app,
    which doesn't go through FastAPI's dependency system."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] != "OPTIONS":
            token = Headers(scope=scope).get("authorization", "")
            expected = f"Bearer {get_settings().api_key}"
            if not secrets.compare_digest(token.encode(), expected.encode()):
                response = JSONResponse(
                    {"detail": "Missing or invalid bearer token"},
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class InternalBearerAuth(httpx.Auth):
    """Used by the embedded MCP server's in-process client when it calls the
    REST endpoints; reads the key lazily so the app imports without env set."""

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response]:
        request.headers["Authorization"] = f"Bearer {get_settings().api_key}"
        yield request
