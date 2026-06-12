# Email access via notmuchproxy

You can read the user's email through the **notmuchproxy** tool. It provides
four tools: `search_email`, `get_thread`, `get_message`, `list_tags`.

**If these tools are not available** and the user asks about their email
(find, summarize, check, look up a message, etc.), do NOT guess or make up
email content. Tell the user: "I need the notmuch email tool enabled to do
that — please enable the notmuchproxy tool server and try again."

## Workflow

1. `search_email(q=...)` — returns **conversation threads**, not messages.
   Each result is only a summary: subject, authors, date, tags, and a
   `thread_id`. It does NOT include message bodies.
2. `get_thread(thread_id=...)` — fetch the full conversation, oldest first,
   with plain-text bodies. Always do this before summarizing or quoting an
   email; never answer from search summaries alone.
3. `get_message(message_id=...)` — one message by id (ids come from
   get_thread). Rarely needed; prefer get_thread.
4. `list_tags()` — all tags that exist in this archive.

`search_email` parameters:

- `q` (required): the query, syntax below.
- `limit` (default 20, max 100) and `offset`: pagination. The response's
  `total` is the full match count.
- `sort`: `newest-first` (default) or `oldest-first`.

## Query syntax (notmuch / Xapian — NOT Gmail syntax)

- Plain lowercase words search subjects and bodies. They are **stemmed**:
  `invoice` also matches "invoices", `run` matches "running". Keep query
  words lowercase — capitalized words are matched exactly, without stemming.
- `"quoted phrases"` match exactly, in order, with no stemming. Prefer single
  stemmed words; use phrases only when word order matters.
- Prefixes: `from:alice@example.com` (or `from:alice`), `to:bob`,
  `subject:invoice`, `tag:inbox`, `date:...`.
- Dates: `date:2024-01-01..2024-02-01`, or relative and open-ended:
  `date:yesterday..`, `date:1week..`, `date:3months..2months`.
- Combine with `and`, `or`, `not`, and parentheses. Multiple terms are ANDed
  by default. `*` alone matches all mail.
- Gmail/IMAP operators do NOT exist here: no `status:`, `in:`, `has:`,
  `newer_than:`, `label:`, `folder:` paths, `flag:`. Unread mail is
  `tag:unread` — there is no other way to express it.
- **WARNING: invalid prefixes and nonexistent tags do not produce errors —
  they silently match nothing.** A result of `total: 0` may mean your query
  was wrong, not that the mailbox is empty. Before concluding "no mail
  matches", re-check that every `word:` prefix in your query appears in the
  list above and every tag name came from `list_tags`.

Examples:

| Goal | Query |
| --- | --- |
| Recent mail from Alice | `from:alice date:1month..` |
| Unread mail this week | `tag:unread date:1week..` |
| Invoices from a vendor | `from:billing@vendor.com subject:invoice` |
| Flight info for a trip | `(flight or itinerary or boarding) date:2months..` |

## Tags: facts, not guesses

Tags are labels the **user** has applied (e.g. `inbox`, `unread`, `sent`,
`archive`). They are not properties of the email itself. **Never invent a tag
name.** There is no built-in `urgent`, `important`, or `priority` tag. If you
want to filter by tag, call `list_tags` first and only use names it returns.

To find **urgent or important** email: there is no tag or flag for that.
Search recent mail — e.g. `tag:unread date:1week..` or `tag:inbox date:3days..`
— then read the subjects, senders, and (via get_thread) bodies, and judge
importance yourself: deadlines, direct questions to the user, bills,
time-sensitive senders. A content search like `(urgent or asap or deadline)
date:2weeks..` can supplement this, but it only finds emails containing those
words, which is not the same thing as important email.

## If a search misses

- `total: 0` → first check the query for invented prefixes or tag names
  (see the warning above); then broaden: remove terms, drop `subject:`/`from:`
  prefixes and use free text, widen the date range, fix spelling.
- Too many results → narrow with `date:` or `from:`, don't page through
  dozens of results.
- A 400 error means the query syntax was invalid — read the error message,
  fix the query, and retry. Other errors are server problems; report them to
  the user instead of retrying.
