# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first, in their own layer keyed only on the lockfile — a
# code-only change then skips reinstalling every dependency. Plain COPY,
# not --mount=type=bind/cache: Railway's builder doesn't support bind
# mounts at all, and its cache mounts require a Railway service id
# hardcoded into the id argument, which would tie this file to one
# specific deployment. Not worth it for a build-speed optimization.
COPY uv.lock pyproject.toml ./
RUN uv sync --locked --no-install-project --no-dev

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
