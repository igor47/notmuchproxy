# notmuchproxy

A read-only OpenAPI server over a [notmuch](https://notmuchmail.org/) email archive,
designed to be used as an [Open WebUI tool server](https://docs.openwebui.com/openapi-servers/)
so an LLM can search and read your email.

No UI — API only. The OpenAPI schema is served at `/openapi.json`, which is how
OpenAPI tool clients (like Open WebUI) discover the available tools.

## API

| Endpoint | Tool | Description |
| --- | --- | --- |
| `GET /search?q=...` | `search_email` | Search threads with notmuch query syntax |
| `GET /threads/{thread_id}` | `get_thread` | Full thread, plain-text bodies, oldest first |
| `GET /messages/{message_id}` | `get_message` | Single message by Message-ID |
| `GET /tags` | `list_tags` | All tags in the archive |
| `GET /healthz` | — | Unauthenticated health check |

All endpoints except `/healthz` and `/openapi.json` require a bearer token:
`Authorization: Bearer $NOTMUCHPROXY_API_KEY`.

## Configuration

Everything is environment variables:

| Variable | Required | Description |
| --- | --- | --- |
| `NOTMUCHPROXY_API_KEY` | yes | the bearer token clients must present |
| `NOTMUCH_DATABASE` | yes¹ | path to the notmuch database root (the directory containing `.notmuch`) |
| `NOTMUCHPROXY_NOTMUCH_BIN` | no | notmuch executable (default: `notmuch`) |

¹ technically optional if the container/host has a notmuch config that already points at the database.

## Running in production (docker)

Mount your maildir (which must already contain the `.notmuch` index) read-only:

```sh
docker run -d -p 8000:8000 \
  -e NOTMUCHPROXY_API_KEY=some-long-random-string \
  -v /path/to/your/mail:/mail:ro \
  ghcr.io/igor47/notmuchproxy:latest
```

The image sets `NOTMUCH_DATABASE=/mail` by default. Indexing (`notmuch new`) is
*not* done by this container — keep running that wherever your mail is delivered.

### Open WebUI setup

Admin Settings → Tools → add a tool server with URL `http://your-host:8000`,
auth type Bearer, key = your `NOTMUCHPROXY_API_KEY`. Open WebUI fetches
`/openapi.json` to discover the tools.

## Development

Tooling is managed by [mise](https://mise.jdx.dev/); the notmuch CLI must be on
your PATH (it's in every distro's repos).

```sh
mise install        # python + uv
mise run install    # create venv, sync deps
mise run test       # run the test suite (builds a throwaway notmuch archive)
mise run check      # ruff lint + format check + pyright (CI mode)
mise run check:fix  # same, but auto-fix what's fixable
mise run dev        # serve on :8000 against generated fixtures (key: dev-key)
```

Other tasks: `mise run fixtures` (regenerate the local dev archive),
`mise run docker:build`, `mise run docker:test` (run the suite inside docker),
`mise run docker:run`. See `mise tasks` for the full list.

## Architecture notes

- **notmuch access**: shells out to the `notmuch` CLI using `--format=json`
  output, via a thin wrapper in `src/notmuchproxy/notmuch.py`. No Python
  bindings, so there is no libnotmuch version-matching to worry about; the
  database path is passed via the `NOTMUCH_DATABASE` environment variable.
- **read-only**: the API never writes to the database; mount your mail read-only.
- **bodies**: `text/plain` parts are preferred; HTML-only messages get a naive
  tag-stripped rendering. Attachments are listed by filename but not served.
