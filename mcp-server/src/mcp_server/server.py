"""MCP wiring: the add tool, a health route for the SPCS readiness probe, and the HTTP app."""

import logging
import os
import socket
import time

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server import tools

SERVER_NAME = "spcs-add-server"
# Host headers we accept. "mcp-server" is the short DNS name other services in the
# same SPCS schema use; override with MCP_ALLOWED_HOSTS to add the full svc.spcs.internal name.
DEFAULT_ALLOWED_HOSTS = "localhost:*,127.0.0.1:*,[::1]:*,mcp-server:*"
INSTANCE = socket.gethostname()

logger = logging.getLogger("mcp_server")

mcp = MCPServer(name=SERVER_NAME, version="0.1.0", instructions="Exposes an add tool that sums two numbers.")


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers and return the sum."""
    start = time.perf_counter()
    result = tools.add(a, b)
    logger.info("tool=add a=%r b=%r result=%r ms=%.2f", a, b, result, (time.perf_counter() - start) * 1000)
    return result


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": SERVER_NAME, "instance": INSTANCE})


def transport_security_from_env() -> TransportSecuritySettings:
    raw = os.environ.get("MCP_ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS)
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[f"http://{h}" for h in hosts],
    )


def create_app() -> Starlette:
    # Stateless + JSON responses: every request stands alone, so any instance can serve it
    # and no SSE stream has to survive the SPCS network path.
    return mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=transport_security_from_env(),
    )
