# syntax=docker/dockerfile:1

FROM python:3.13-slim-trixie AS base
RUN apt-get update \
    && apt-get install -y --no-install-recommends notmuch \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

FROM base AS build
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# run checks + tests inside docker: docker build --target test .
FROM build AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-groups
COPY tests ./tests
CMD ["sh", "-c", "uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest"]

FROM base AS production
RUN useradd --system --create-home --uid 1000 notmuch
COPY --from=build --chown=notmuch:notmuch /app /app
USER notmuch
ENV PATH="/app/.venv/bin:$PATH" \
    NOTMUCH_DATABASE=/mail
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
CMD ["uvicorn", "notmuchproxy.main:app", "--host", "0.0.0.0", "--port", "8000"]
