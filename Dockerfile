# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first, in their own layer keyed only on the lockfile — a
# code-only change then skips reinstalling every dependency. No
# --mount=type=cache here: Railway's builder rejects cache mount ids
# without a platform-specific prefix it doesn't document, so this trades
# a warmer uv cache between builds for a Dockerfile that actually builds.
RUN --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . /app

RUN uv sync --locked --no-dev

FROM python:3.12-slim-bookworm

RUN groupadd --system app && useradd --system --gid app --no-create-home app

COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app
USER app

EXPOSE 8000

# Shell form, not exec-form JSON array: Railway injects $PORT at runtime,
# and only shell form expands environment variables in CMD.
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
