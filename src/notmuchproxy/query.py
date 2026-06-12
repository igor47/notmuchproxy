"""Validation of query strings before they reach xapian.

Xapian treats an unknown prefix (status:unread), a capitalized prefix
(From:alice), or a nonexistent tag (tag:handled) as ordinary terms that no
message contains — the query "succeeds" with zero results and the caller
concludes the mailbox is empty. LLM callers in particular improvise
Gmail-style syntax, and a silent zero confirms the mistake instead of
correcting it. Rejecting these queries with an instructive 400 is the only
feedback such callers reliably notice.
"""

import re
from collections.abc import Callable

# every prefix notmuch-search-terms(7) defines, including the is:->tag: and
# mid:->id: aliases; xapian only recognizes them in lowercase
KNOWN_PREFIXES = frozenset(
    {
        "attachment",
        "body",
        "date",
        "folder",
        "from",
        "id",
        "is",
        "lastmod",
        "mid",
        "mimetype",
        "path",
        "property",
        "query",
        "sexp",
        "subject",
        "tag",
        "thread",
        "to",
    }
)

# common inventions (mostly Gmail/IMAP vocabulary) mapped to corrections
_PREFIX_HINTS = {
    "status": "for unread mail use tag:unread",
    "label": "labels are tags here: use tag:<name> (see list_tags)",
    "in": "use tag:<name>, e.g. tag:inbox",
    "flag": "flags are tags here: use tag:<name> (see list_tags)",
    "has": "to find mail with attachments use attachment:<filename-word>",
    "filename": "use attachment:<filename-word>",
    "cc": "to: matches To, Cc, and Bcc recipients",
    "bcc": "to: matches To, Cc, and Bcc recipients",
    "sender": "use from:<name-or-address>",
    "newer_than": "use a date range, e.g. date:7days..",
    "older_than": "use a date range, e.g. date:..7days",
    "after": "use date:<when>.., e.g. date:2024-01-01..",
    "before": "use date:..<when>, e.g. date:..2024-01-01",
}

_PREFIX_LIST = (
    "from:, to: (matches To/Cc/Bcc), subject:, body:, tag: (alias is:), "
    "date:, attachment:, mimetype:, id:, thread:, path:, folder:, lastmod:"
)

# a word followed by ':' at the start of a term — i.e. at the beginning of the
# query or after whitespace, '(' or '-'; colons inside a term (the value of
# subject:re:foo, or the tail of a URL) are not prefixes
_PREFIX_RE = re.compile(r"(?:^|(?<=[\s(-]))([A-Za-z][A-Za-z0-9_]*):")

# tag:/is: values: bare (tag:inbox) on the quote-masked query, quoted
# (tag:"foo bar") on the raw query; /regex/ values are left to xapian
_BARE_TAG_RE = re.compile(r"(?:^|(?<=[\s(-]))(?:tag|is):([^\s()\"/][^\s()\"]*)")
_QUOTED_TAG_RE = re.compile(r"(?:^|(?<=[\s(-]))(?:tag|is):\"([^\"]*)\"")


class QueryValidationError(Exception):
    """The query uses prefixes or tag names that don't exist."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def _mask_quoted(query: str) -> str:
    """Blank out double-quoted spans (preserving length) so their contents
    are never mistaken for prefixes or tag values."""
    return re.sub(r'"[^"]*"', lambda m: " " * len(m.group()), query)


def _check_prefixes(masked: str) -> None:
    problems: list[str] = []
    for match in _PREFIX_RE.finditer(masked):
        prefix = match.group(1)
        if prefix in KNOWN_PREFIXES:
            continue
        if prefix.lower() in KNOWN_PREFIXES:
            problems.append(f"'{prefix}:' — prefixes are lowercase: use {prefix.lower()}:")
        elif hint := _PREFIX_HINTS.get(prefix.lower()):
            problems.append(f"'{prefix}:' does not exist — {hint}")
        else:
            problems.append(f"'{prefix}:' does not exist")
    if problems:
        raise QueryValidationError(
            f"unknown search prefix: {'; '.join(problems)}. "
            f"Valid prefixes: {_PREFIX_LIST}. Plain lowercase words search "
            "subject and body (stemmed). To search for literal text containing "
            "a colon, wrap it in double quotes."
        )


def _check_tags(query: str, masked: str, known_tags: Callable[[], list[str]]) -> None:
    requested = {m.group(1) for m in _BARE_TAG_RE.finditer(masked)}
    requested |= {m.group(1) for m in _QUOTED_TAG_RE.finditer(query)}
    # '*' could be a wildcard attempt; let xapian deal with it
    requested = {tag for tag in requested if "*" not in tag}
    if not requested:
        return
    tags = known_tags()
    if unknown := sorted(requested - set(tags)):
        names = ", ".join(f"'{tag}'" for tag in unknown)
        raise QueryValidationError(
            f"no such tag: {names}. Tags are labels the user has assigned, not "
            "message properties — never guess tag names. Tags in this archive: "
            f"{', '.join(tags)}."
        )


def validate_query(query: str, known_tags: Callable[[], list[str]]) -> None:
    """Raise QueryValidationError if the query references unknown prefixes or
    nonexistent tags. known_tags is only called when the query mentions tags."""
    masked = _mask_quoted(query)
    _check_prefixes(masked)
    _check_tags(query, masked, known_tags)
