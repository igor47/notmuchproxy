from pydantic import BaseModel, Field


class ThreadSummary(BaseModel):
    thread_id: str = Field(description="notmuch thread id; use with the get_thread tool")
    subject: str
    authors: str = Field(description="comma/pipe separated list of thread participants")
    date: str = Field(description="date of the newest matched message, ISO 8601")
    date_relative: str = Field(description="human-friendly relative date, e.g. 'Yest. 14:30'")
    matched: int = Field(description="number of messages in the thread matching the query")
    total: int = Field(description="total number of messages in the thread")
    tags: list[str]


class SearchResponse(BaseModel):
    query: str = Field(description="the notmuch query that was executed")
    total: int = Field(description="total number of threads matching the query")
    offset: int
    limit: int
    threads: list[ThreadSummary]


class Message(BaseModel):
    message_id: str = Field(description="notmuch message id; use with the get_message tool")
    thread_id: str
    subject: str
    sender: str = Field(description="the From header")
    to: str | None = Field(default=None, description="the To header")
    cc: str | None = Field(default=None, description="the Cc header")
    date: str = Field(description="the Date header")
    tags: list[str]
    depth: int = Field(description="reply depth within the thread; 0 for top-level messages")
    body: str = Field(
        description="message body as plain text (extracted from text/plain, "
        "falling back to stripped text/html)"
    )
    attachments: list[str] = Field(
        default_factory=list,
        description="filenames of attachments (content not included)",
    )


class Thread(BaseModel):
    thread_id: str
    messages: list[Message] = Field(description="all messages in the thread, oldest first")


class TagsResponse(BaseModel):
    tags: list[str] = Field(description="all tags present in the mail archive")


class HealthResponse(BaseModel):
    status: str
    notmuch_version: str
    message_count: int
