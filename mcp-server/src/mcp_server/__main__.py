"""Entrypoint: python -m mcp_server.

Serves two MCP endpoints from one process:
  HOST:PORT         private, full toolset, plus GET /calls (default 8000)
  HOST:PUBLIC_PORT  public, consumer toolset only, for Snowflake callers (default 8001)

Also reads LOG_LEVEL, MCP_ALLOWED_HOSTS, MCP_PUBLIC_ALLOWED_HOSTS.
"""

import asyncio
import contextlib
import logging
import os
import signal

import uvicorn


class _SkipHealthz(logging.Filter):
    """Keep the readiness probe from flooding the access log."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/healthz" not in record.getMessage()


class _SharedSignalServer(uvicorn.Server):
    """uvicorn installs its own signal handlers per server; two servers would fight over them."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield


async def _serve_all(servers: list[uvicorn.Server]) -> None:
    loop = asyncio.get_running_loop()

    def stop() -> None:
        for server in servers:
            server.should_exit = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop)
    await asyncio.gather(*(server.serve() for server in servers))


def main() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Imported after basicConfig so the SDK's own logging setup leaves this format in place.
    from mcp_server.calllog import CallRecorder
    from mcp_server.server import create_app
    from mcp_server.snowflake import SnowflakeRunner

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    public_port = int(os.environ.get("PUBLIC_PORT", "8001"))
    recorder = CallRecorder()
    runner = SnowflakeRunner()

    servers = [
        _SharedSignalServer(uvicorn.Config(create_app("private", recorder, runner), host=host, port=port,
                                           log_level=level.lower())),
        _SharedSignalServer(uvicorn.Config(create_app("public", recorder, runner), host=host, port=public_port,
                                           log_level=level.lower())),
    ]
    logging.getLogger("uvicorn.access").addFilter(_SkipHealthz())
    asyncio.run(_serve_all(servers))


if __name__ == "__main__":
    main()
