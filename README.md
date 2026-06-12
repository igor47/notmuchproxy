# notmuchproxy

[![ci](https://github.com/igor47/notmuchproxy/actions/workflows/ci.yml/badge.svg)](https://github.com/igor47/notmuchproxy/actions/workflows/ci.yml)

Give an LLM read-only access to your email.

notmuchproxy is a small API server over a [notmuch](https://notmuchmail.org/)
email archive. It exposes the same four tools two ways:

- an **OpenAPI/REST API** (schema at `/openapi.json`), usable as an
  [Open WebUI tool server](https://docs.openwebui.com/openapi-servers/)
- an **MCP endpoint** (streamable HTTP at `/mcp/`), usable from Claude Code,
  claude.ai, and any other MCP client

There is no UI and no write path: the server only ever reads the archive, so
the worst an over-eager LLM can do is search your email too enthusiastically.

## The tools

| Tool | REST endpoint | Description |
| --- | --- | --- |
| `search_email` | `GET /search?q=...` | Search threads with notmuch query syntax (`from:`, `to:`, `subject:`, `tag:`, `date:`, free text) |
| `get_thread` | `GET /threads/{thread_id}` | Every message in a thread, oldest first, bodies as plain text |
| `get_message` | `GET /messages/{message_id}` | A single message by Message-ID |
| `list_tags` | `GET /tags` | All tags in the archive |

Plus an unauthenticated `GET /healthz`. Everything else requires
`Authorization: Bearer $NOTMUCHPROXY_API_KEY` — including the MCP endpoint.
The MCP tools are derived from the OpenAPI schema at startup, so the two
surfaces can't drift apart.

Search queries are validated before they reach xapian. Unknown prefixes
(`status:unread`), capitalized prefixes (`From:alice`), and nonexistent tags
(`tag:handled`) would otherwise silently match nothing — to xapian they are
just terms no message contains — so a mistyped query looks exactly like an
empty mailbox. The proxy instead rejects them with a 400 naming the problem
and suggesting the fix (`for unread mail use tag:unread`; `Tags in this
archive: ...`), which is the kind of feedback LLM callers actually act on.
`docs/email-assistant-knowledge.md` has a system-prompt blurb teaching small
models to use the tools well.

## Configuration

Everything is environment variables:

| Variable | Required | Description |
| --- | --- | --- |
| `NOTMUCH_DATABASE` | yes¹ | path to the notmuch database root (the directory containing `.notmuch`); the docker image defaults it to `/mail` |
| `NOTMUCHPROXY_NOTMUCH_BIN` | no | notmuch executable (default: `notmuch`) |
| `NOTMUCHPROXY_EXCLUDE_TAGS` | no | comma-separated tags (e.g. `spam,deleted`) whose messages are excluded from *all* results — searches (even explicit `tag:spam` queries), threads, single messages, and the tag list. Useful for noise and for keeping adversarial spam content away from the model. |
| `NOTMUCHPROXY_CORS_ORIGINS` | no | comma-separated origins allowed for CORS; `*` (the default) allows any origin, empty string disables CORS. Needed when a browser calls the API directly, e.g. tool servers added in Open WebUI's *user* settings. The auth token remains the actual access control. |

### Authentication

Pick exactly one mechanism (the server refuses to start with both or neither);
it applies to both the REST API and the MCP endpoint.

**Static bearer token** — simplest; what Open WebUI's OpenAPI tool servers and
Claude Code's `--header` flag speak. claude.ai custom connectors can *not* use
this mode (they only support OAuth).

| Variable | Description |
| --- | --- |
| `NOTMUCHPROXY_API_KEY` | the bearer token clients must present |

**OIDC via an external identity provider** — works with any OIDC IdP
(authentik, Keycloak, Google, ...). notmuchproxy presents a spec-compliant
MCP authorization server to clients — including the dynamic client
registration claude.ai requires — while acting as an ordinary OIDC client of
your IdP upstream (your IdP does not need to support DCR itself). Tokens
issued through the flow are accepted on both the MCP and REST endpoints.

| Variable | Description |
| --- | --- |
| `NOTMUCHPROXY_OIDC_CONFIG_URL` | the IdP's OIDC discovery URL, e.g. `https://auth.example.com/application/o/notmuchproxy/.well-known/openid-configuration` for authentik |
| `NOTMUCHPROXY_OIDC_CLIENT_ID` | client id of the app registered at the IdP |
| `NOTMUCHPROXY_OIDC_CLIENT_SECRET` | client secret of that app |
| `NOTMUCHPROXY_PUBLIC_URL` | public base URL of this server, e.g. `https://notmuch.example.com` — used for OAuth callbacks and discovery metadata; claude.ai requires HTTPS |

IdP setup (authentik example): create an OAuth2/OpenID provider with a
confidential client and redirect URI `$NOTMUCHPROXY_PUBLIC_URL/auth/callback`,
scopes `openid profile email`. Who may authorize is controlled by your IdP's
own policies (in authentik, bind the application to users/groups).

¹ optional if the host has a notmuch config that already points at the database.

## Running in production

The server is distributed as a docker image. Mount your maildir — which must
already contain the `.notmuch` index — read-only at `/mail`:

```sh
docker run -d -p 8000:8000 \
  -e NOTMUCHPROXY_API_KEY=some-long-random-string \
  -v /path/to/your/mail:/mail:ro \
  ghcr.io/igor47/notmuchproxy:latest
```

Indexing (`notmuch new`) is *not* done by this container — keep running it
wherever your mail is delivered. The container picks up index updates
automatically since xapian readers don't block writers.

### docker compose, as a non-root user

The image runs as a built-in non-root user (uid 1000) by default. If your
maildir is owned by a different user, override `user:` so the container can
read the mount — no rebuild needed:

```yaml
services:
  notmuchproxy:
    image: ghcr.io/igor47/notmuchproxy:latest
    restart: unless-stopped
    # run as the uid/gid that owns your maildir (`id -u`/`id -g`);
    # omit entirely if uid 1000 can read your mail
    user: "1000:1000"
    ports:
      - "8000:8000"
    environment:
      NOTMUCHPROXY_API_KEY: ${NOTMUCHPROXY_API_KEY:?set this in .env}
    volumes:
      - /path/to/your/mail:/mail:ro
```

The app never writes to the archive (and the `:ro` mount enforces that), so
read permission on the maildir is all it needs.

## Connecting clients

### Open WebUI

In static mode, add an OpenAPI tool server (Admin Settings → Tools):

- URL: `http://your-host:8000`
- Auth: Bearer, key = your `NOTMUCHPROXY_API_KEY`

Open WebUI fetches `/openapi.json` (which is unauthenticated, like `/healthz`)
to discover the tools, then sends the bearer token on each call.

In OIDC mode, use Open WebUI's MCP tool server type instead, pointed at
`https://your-host/mcp` with OAuth 2.1 auth — it performs the same discovery
and login flow as claude.ai.

Tool servers added under **Admin** Settings are called from the Open WebUI
backend, but ones added in a user's own Settings → Tools are called directly
from the browser — that path needs CORS, which is enabled for all origins by
default (lock it down with `NOTMUCHPROXY_CORS_ORIGINS=https://your-webui-host`).

### claude.ai (OIDC mode only)

Settings → Connectors → Add custom connector, URL `https://your-host/mcp`.
Claude discovers the OAuth endpoints, registers itself dynamically, and sends
you through your IdP's login/consent in the browser. No client id/secret needs
to be entered on the claude.ai side.

### Claude Code

Static mode:

```sh
claude mcp add --transport http notmuch http://your-host:8000/mcp \
  --header "Authorization: Bearer $NOTMUCHPROXY_API_KEY"
```

OIDC mode — omit the header; Claude Code runs the OAuth flow in your browser:

```sh
claude mcp add --transport http notmuch https://your-host/mcp
```

### Other MCP clients

Any client that speaks streamable HTTP can connect to `http://your-host:8000/mcp`,
authenticating with the static bearer token or the OAuth flow depending on
the server's configured mode.

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

CI runs the same mise tasks, then runs the suite again inside the docker image
(against Debian's notmuch rather than the host's) before pushing to
`ghcr.io/igor47/notmuchproxy` on pushes to main and `v*` tags.

## Architecture notes

- **notmuch access**: shells out to the `notmuch` CLI using `--format=json`
  output, via a thin wrapper in `src/notmuchproxy/notmuch.py`. No Python
  bindings, so there is no libnotmuch version-matching to worry about; the
  database path is passed via the `NOTMUCH_DATABASE` environment variable.
- **one definition, two protocols**: the FastAPI routes are the source of
  truth; [fastmcp](https://gofastmcp.com)'s `FastMCP.from_fastapi()` converts
  the OpenAPI schema into MCP tools at startup and dispatches tool calls to
  the routes in-process.
- **bodies**: `text/plain` parts are preferred; HTML-only messages get a naive
  tag-stripped rendering. Attachments are listed by filename but not served.
- **fixtures**: `python -m notmuchproxy.fixtures <dir>` generates a small
  synthetic maildir + notmuch index, used by the tests and `mise run dev`.

## License

[MIT](LICENSE)
