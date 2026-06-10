"""Thin wrapper around the notmuch CLI, using its JSON output format."""

import html
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, cast

from .config import Settings
from .models import Message, ThreadSummary


class NotmuchError(Exception):
    """The notmuch CLI exited non-zero."""

    def __init__(self, args_: list[str], returncode: int, stderr: str) -> None:
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"notmuch {' '.join(args_)} failed ({returncode}): {self.stderr}")


@lru_cache
def _empty_config() -> str:
    """notmuch refuses to run without *some* config file, even when
    NOTMUCH_DATABASE supplies the database path; an empty file satisfies it."""
    fd, path = tempfile.mkstemp(prefix="notmuchproxy-", suffix=".config")
    os.close(fd)
    return path


class Notmuch:
    def __init__(self, settings: Settings) -> None:
        self._bin = settings.notmuch_bin
        self._env = dict(os.environ)
        if settings.notmuch_database:
            self._env["NOTMUCH_DATABASE"] = settings.notmuch_database
            self._env.setdefault("NOTMUCH_CONFIG", _empty_config())

    def _run(self, *args: str) -> str:
        argv = [self._bin, *args]
        result = subprocess.run(argv, capture_output=True, text=True, env=self._env)
        if result.returncode != 0:
            raise NotmuchError(list(args), result.returncode, result.stderr)
        return result.stdout

    def _run_json(self, *args: str) -> Any:
        return json.loads(self._run(*args))

    def version(self) -> str:
        return self._run("--version").strip()

    def count(self, query: str, output: str = "messages") -> int:
        return int(self._run("count", f"--output={output}", "--", query).strip())

    def search(self, query: str, limit: int, offset: int, sort: str) -> list[ThreadSummary]:
        results = self._run_json(
            "search",
            "--format=json",
            "--output=summary",
            f"--limit={limit}",
            f"--offset={offset}",
            f"--sort={sort}",
            "--",
            query,
        )
        return [
            ThreadSummary(
                thread_id=r["thread"],
                subject=r["subject"] or "(no subject)",
                authors=r["authors"],
                date=datetime.fromtimestamp(r["timestamp"], tz=UTC).isoformat(),
                date_relative=r["date_relative"],
                matched=r["matched"],
                total=r["total"],
                tags=r["tags"],
            )
            for r in results
        ]

    def list_tags(self) -> list[str]:
        return sorted(self._run_json("search", "--format=json", "--output=tags", "--", "*"))

    def thread_messages(self, thread_id: str) -> list[Message]:
        """All messages in a thread, oldest first."""
        messages = self._show(f"thread:{thread_id}", entire_thread=True)
        for message in messages:
            message.thread_id = thread_id
        return messages

    def message(self, message_id: str) -> Message | None:
        messages = self._show(f"id:{message_id}", entire_thread=False)
        if not messages:
            return None
        message = messages[0]
        # notmuch show doesn't include the thread id; look it up separately
        threads = self._run_json(
            "search", "--output=threads", "--format=json", "--", f"id:{message_id}"
        )
        if threads:
            message.thread_id = threads[0].removeprefix("thread:")
        return message

    def _show(self, query: str, entire_thread: bool) -> list[Message]:
        threads = self._run_json(
            "show",
            "--format=json",
            "--include-html",
            f"--entire-thread={'true' if entire_thread else 'false'}",
            "--",
            query,
        )
        messages: list[Message] = []
        for thread in threads:
            _walk_message_forest(thread, depth=0, out=messages)
        messages.sort(key=lambda m: m.date)
        return messages


def _walk_message_forest(pairs: list[Any], depth: int, out: list[Message]) -> None:
    """notmuch show emits each thread as a forest of [message, replies] pairs."""
    for msg, replies in pairs:
        if msg:  # null for messages excluded from the output
            out.append(_parse_message(msg, depth))
        _walk_message_forest(replies, depth + 1, out)


def _parse_message(msg: dict[str, Any], depth: int) -> Message:
    headers = msg.get("headers", {})
    plain: list[str] = []
    html_parts: list[str] = []
    attachments: list[str] = []
    _walk_body_parts(msg.get("body", []), plain, html_parts, attachments)
    body = "\n".join(plain).strip() if plain else _strip_html("\n".join(html_parts)).strip()
    return Message(
        message_id=msg["id"],
        thread_id=msg.get("thread", ""),
        subject=headers.get("Subject", "") or "(no subject)",
        sender=headers.get("From", ""),
        to=headers.get("To"),
        cc=headers.get("Cc"),
        date=headers.get("Date", ""),
        tags=msg.get("tags", []),
        depth=depth,
        body=body,
        attachments=attachments,
    )


def _walk_body_parts(
    parts: list[Any],
    plain: list[str],
    html_parts: list[str],
    attachments: list[str],
) -> None:
    for part in parts:
        ctype = part.get("content-type", "").lower()
        content: Any = part.get("content")
        if part.get("content-disposition") == "attachment" or (
            part.get("filename") and not ctype.startswith("text/")
        ):
            attachments.append(part.get("filename") or f"({ctype})")
        elif ctype.startswith("multipart/") and isinstance(content, list):
            _walk_body_parts(cast(list[Any], content), plain, html_parts, attachments)
        elif ctype == "message/rfc822" and isinstance(content, list):
            for sub in cast(list[dict[str, Any]], content):
                _walk_body_parts(sub.get("body", []), plain, html_parts, attachments)
        elif ctype == "text/plain" and isinstance(content, str):
            plain.append(content)
        elif ctype == "text/html" and isinstance(content, str):
            html_parts.append(content)


_HTML_DROP = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_HTML_TAG = re.compile(r"<[^>]+>")
_BLANK_LINES = re.compile(r"\n\s*\n+")


def _strip_html(markup: str) -> str:
    text = _HTML_DROP.sub("", markup)
    text = _HTML_TAG.sub(" ", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
