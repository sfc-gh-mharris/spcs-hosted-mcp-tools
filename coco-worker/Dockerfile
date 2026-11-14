# Built for linux/amd64, the only platform SPCS runs.
FROM ghcr.io/astral-sh/uv:0.13.8 AS uv

FROM python:3.11-slim AS cli
# Pinned Cortex Code CLI build, verified against the release manifest's SHA-256. This replays
# what the official install script does, minus "install whatever is latest".
ARG COCO_VERSION=1.2.45+061229.2a20c0482251
ARG COCO_SHA256=67edba6f369fbaf474a387e5c036cbb33955593567520dbd56d9119c21ca0e6e
ARG COCO_BASE=https://sfc-repo.snowflakecomputing.com/cortex-code-cli/a4643c4278
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN set -eu; \
    enc=$(printf '%s' "$COCO_VERSION" | sed 's/+/%2B/g'); \
    curl -qfsSL "$COCO_BASE/$enc/coco-$enc-linux-amd64.tar.gz" -o /tmp/coco.tgz; \
    echo "$COCO_SHA256  /tmp/coco.tgz" | sha256sum -c -; \
    mkdir -p /opt/cortex; \
    tar -xzf /tmp/coco.tgz -C /opt/cortex --strip-components=1; \
    rm /tmp/coco.tgz; \
    /opt/cortex/cortex --version

FROM python:3.11-slim
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=cli /opt/cortex /opt/cortex
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

# Non-root user with a writable home: the CLI keeps settings, sessions, and caches under
# ~/.snowflake/cortex. Auto-update is off so the pinned build is what runs.
RUN useradd --uid 10001 --create-home --home-dir /home/app app \
    && mkdir -p /home/app/.snowflake/cortex /tmp/coco-work \
    && printf '{\n  "autoUpdate": false\n}\n' > /home/app/.snowflake/cortex/settings.json \
    && chown -R app:app /home/app /tmp/coco-work
USER app
ENV HOME=/home/app \
    PATH="/app/.venv/bin:/opt/cortex:$PATH" \
    CORTEX_CODE_CLI_PATH=/opt/cortex/cortex \
    HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000
CMD ["python", "-m", "coco_worker"]
