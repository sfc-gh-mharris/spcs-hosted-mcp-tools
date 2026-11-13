"""Entrypoint: python -m mcp_server. Configured by HOST, PORT, LOG_LEVEL, MCP_ALLOWED_HOSTS."""

import logging
import os

import uvicorn


class _SkipHealthz(logging.Filter):
    """Keep the readiness probe from flooding the access log."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/healthz" not in record.getMessage()


def main() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Imported after basicConfig so the SDK's own logging setup leaves this format in place.
    from mcp_server.server import create_app

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    config = uvicorn.Config(create_app(), host=host, port=port, log_level=level.lower())
    server = uvicorn.Server(config)
    logging.getLogger("uvicorn.access").addFilter(_SkipHealthz())
    server.run()


if __name__ == "__main__":
    main()
