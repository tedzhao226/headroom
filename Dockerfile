FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini config.toml ./
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --system --no-create-home --uid 1000 headroom \
    && chown -R headroom:headroom /app
USER headroom

EXPOSE 8000
CMD ["uvicorn", "headroom.main:app", "--host", "0.0.0.0", "--port", "8000"]
