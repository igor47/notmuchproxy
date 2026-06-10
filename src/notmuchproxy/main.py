from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from . import __version__
from .auth import require_api_key
from .config import Settings, get_settings
from .models import HealthResponse, SearchResponse, TagsResponse, Thread
from .models import Message as MessageModel
from .notmuch import Notmuch, NotmuchError


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncGenerator[None]:
    # mcp_app is created below, after the routes it derives its tools from
    async with mcp_app.lifespan(mcp_app):
        yield


app = FastAPI(
    title="notmuchproxy",
    version=__version__,
    description=(
        "Read-only API over a notmuch email archive. "
        "Search email with notmuch query syntax, then fetch full threads or "
        "individual messages. All endpoints except /healthz require a bearer token."
    ),
    lifespan=_lifespan,
)


def get_notmuch(settings: Annotated[Settings, Depends(get_settings)]) -> Notmuch:
    return Notmuch(settings)


NotmuchDep = Annotated[Notmuch, Depends(get_notmuch)]


@app.exception_handler(NotmuchError)
def notmuch_error_handler(request: Request, exc: NotmuchError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"detail": f"notmuch failed: {exc.stderr or f'exit code {exc.returncode}'}"},
    )


class SortOrder(StrEnum):
    newest_first = "newest-first"
    oldest_first = "oldest-first"


@app.get(
    "/search",
    operation_id="search_email",
    summary="Search email threads",
    response_model=SearchResponse,
    dependencies=[Depends(require_api_key)],
)
def search_email(
    nm: NotmuchDep,
    q: Annotated[
        str,
        Query(
            description=(
                "notmuch query string. Plain words search message bodies and subjects. "
                "Useful prefixes: from:alice@example.com, to:bob, subject:invoice, "
                "tag:inbox, date:2024-01-01..2024-02-01 (or date:yesterday.., "
                "date:3months..). Combine terms with 'and', 'or', 'not' and parentheses. "
                "Use '*' to match all mail."
            ),
            examples=["from:alice@example.com date:1month.. subject:invoice"],
        ),
    ],
    limit: Annotated[int, Query(ge=1, le=100, description="max threads to return")] = 20,
    offset: Annotated[int, Query(ge=0, description="threads to skip, for pagination")] = 0,
    sort: Annotated[SortOrder, Query(description="result order")] = SortOrder.newest_first,
) -> SearchResponse:
    """Search the email archive and return matching thread summaries.

    Results are conversation threads, not individual messages. Use the
    returned thread_id with get_thread to read the full conversation.
    """
    return SearchResponse(
        query=q,
        total=nm.count(q, output="threads"),
        offset=offset,
        limit=limit,
        threads=nm.search(q, limit=limit, offset=offset, sort=sort.value),
    )


@app.get(
    "/threads/{thread_id}",
    operation_id="get_thread",
    summary="Get a full email thread",
    response_model=Thread,
    dependencies=[Depends(require_api_key)],
)
def get_thread(thread_id: str, nm: NotmuchDep) -> Thread:
    """Fetch every message in a thread (oldest first) with plain-text bodies.

    thread_id comes from search_email results.
    """
    messages = nm.thread_messages(thread_id)
    if not messages:
        raise HTTPException(status_code=404, detail=f"no thread with id {thread_id!r}")
    return Thread(thread_id=thread_id, messages=messages)


@app.get(
    "/messages/{message_id}",
    operation_id="get_message",
    summary="Get a single email message",
    response_model=MessageModel,
    dependencies=[Depends(require_api_key)],
)
def get_message(message_id: str, nm: NotmuchDep) -> MessageModel:
    """Fetch one message by its Message-ID (without angle brackets)."""
    message = nm.message(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail=f"no message with id {message_id!r}")
    return message


@app.get(
    "/tags",
    operation_id="list_tags",
    summary="List all tags",
    response_model=TagsResponse,
    dependencies=[Depends(require_api_key)],
)
def list_tags(nm: NotmuchDep) -> TagsResponse:
    """List every tag in the archive; tags can be used in queries as tag:name."""
    return TagsResponse(tags=nm.list_tags())


@app.get("/healthz", operation_id="health", summary="Health check", include_in_schema=False)
def healthz(nm: NotmuchDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        notmuch_version=nm.version(),
        message_count=nm.count("*"),
    )


# Expose the same endpoints as MCP tools at /mcp. The tools are derived from
# the OpenAPI schema, so the REST routes above stay the single source of truth;
# tool calls are dispatched to them in-process.
from fastmcp import FastMCP  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402

from .auth import BearerAuthMiddleware, InternalBearerAuth  # noqa: E402

mcp = FastMCP.from_fastapi(app=app, httpx_client_kwargs={"auth": InternalBearerAuth()})
mcp_app = mcp.http_app(
    path="/",
    stateless_http=True,
    json_response=True,
    middleware=[Middleware(BearerAuthMiddleware)],
)
app.mount("/mcp", mcp_app)
