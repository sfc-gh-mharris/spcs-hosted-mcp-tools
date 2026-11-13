# Built for linux/amd64, the only platform SPCS runs.
FROM ghcr.io/astral-sh/uv:0.13.8 AS uv

FROM python:3.11-slim
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1
WORKDIR /app

# Dependencies first so code changes do not invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

RUN useradd --uid 10001 --no-create-home app
USER app
ENV PATH="/app/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000
CMD ["python", "-m", "mcp_server"]
