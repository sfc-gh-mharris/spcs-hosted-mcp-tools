"""MCP wiring: two toolsets, a health route for the SPCS readiness probe, and the HTTP apps.

- private: everything, for MCP_CLIENT and probe jobs over the SPCS internal network.
- public: only the tools Snowflake consumers (CoCo, Cortex Agents) should see. Keeping
  Cortex-calling tools off this endpoint means an agent pointed at us cannot call back
  into an agent through us.
"""

import logging
import os
import socket
import time

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server import tools
from mcp_server.calllog import CallRecorder
from mcp_server.cortex_tools import register_cortex_tools
from mcp_server.snowflake import QueryRunner, SnowflakeRunner

SERVER_NAME = "spcs-add-server"
PUBLIC_SERVER_NAME = "spcs-demo-public"
# Host headers we accept. "mcp-server" is the short DNS name other services in the
# same SPCS schema use; override with MCP_ALLOWED_HOSTS to add the full svc.spcs.internal name.
DEFAULT_ALLOWED_HOSTS = "localhost:*,127.0.0.1:*,[::1]:*,mcp-server:*"
# The public endpoint is reached through SPCS ingress; add the ingress hostname via
# MCP_PUBLIC_ALLOWED_HOSTS once SHOW ENDPOINTS reports it.
DEFAULT_PUBLIC_ALLOWED_HOSTS = "localhost:*,127.0.0.1:*,[::1]:*"
INSTANCE = socket.gethostname()

logger = logging.getLogger("mcp_server")


class Whoami(BaseModel):
    user: str
    role: str
    warehouse: str | None
    account: str
    region: str
    query_id: str


def add(a: float, b: float) -> float:
    """Add two numbers and return the sum."""
    start = time.perf_counter()
    result = tools.add(a, b)
    logger.info("tool=add a=%r b=%r result=%r ms=%.2f", a, b, result, (time.perf_counter() - start) * 1000)
    return result


def register_consumer_tools(mcp: MCPServer) -> None:
    """Tools safe to expose to Snowflake callers. Step 3 adds the Factory tools here."""
    mcp.add_tool(add)


def register_snowflake_tools(mcp: MCPServer, runner: QueryRunner) -> None:
    async def snowflake_whoami() -> Whoami:
        """Show the Snowflake user, role, and warehouse this server's Cortex calls run as."""
        res = await runner.run(
            "SELECT CURRENT_USER() AS U, CURRENT_ROLE() AS R, CURRENT_WAREHOUSE() AS W, "
            "CURRENT_ACCOUNT() AS A, CURRENT_REGION() AS G",
            timeout_s=30,
        )
        row = res.rows[0]
        logger.info("tool=snowflake_whoami role=%s warehouse=%s query_id=%s", row["R"], row["W"], res.query_id)
        return Whoami(user=row["U"], role=row["R"], warehouse=row["W"], account=row["A"], region=row["G"],
                      query_id=res.query_id)

    mcp.add_tool(snowflake_whoami)


def build_mcp(runner: QueryRunner | None = None, toolset: str = "private",
              recorder: CallRecorder | None = None) -> MCPServer:
    if toolset not in ("private", "public"):
        raise ValueError(f"unknown toolset {toolset!r}")
    public = toolset == "public"
    mcp = MCPServer(
        name=PUBLIC_SERVER_NAME if public else SERVER_NAME,
        version="0.3.0",
        instructions="Demo tools hosted in Snowpark Container Services." if public
        else "Adds numbers and calls Snowflake Cortex.",
        middleware=[recorder.middleware(toolset)] if recorder else None,
    )
    register_consumer_tools(mcp)
    if not public:
        runner = runner or SnowflakeRunner()
        register_snowflake_tools(mcp, runner)
        register_cortex_tools(mcp, runner)

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": mcp.name, "endpoint": toolset, "instance": INSTANCE})

    if recorder and not public:
        # Private port only: the monitor reads what Snowflake called without exposing it publicly.
        @mcp.custom_route("/calls", methods=["GET"])
        async def calls(request: Request) -> JSONResponse:
            try:
                since = int(request.query_params.get("since", "0"))
            except ValueError:
                since = 0
            return JSONResponse({"entries": recorder.since(since), "last_id": recorder.last_id})

    return mcp


def _hosts(var: str, default: str) -> list[str]:
    return [h.strip() for h in os.environ.get(var, default).split(",") if h.strip()]


def transport_security_from_env(toolset: str = "private") -> TransportSecuritySettings:
    if toolset == "public":
        hosts = _hosts("MCP_PUBLIC_ALLOWED_HOSTS", DEFAULT_PUBLIC_ALLOWED_HOSTS)
        origins = [f"https://{h}" for h in hosts] + [f"http://{h}" for h in hosts]
    else:
        hosts = _hosts("MCP_ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS)
        origins = [f"http://{h}" for h in hosts]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts,
                                     allowed_origins=origins)


def create_app(toolset: str = "private", recorder: CallRecorder | None = None,
               runner: QueryRunner | None = None) -> Starlette:
    # Stateless + JSON responses: every request stands alone, so any instance can serve it
    # and no SSE stream has to survive the SPCS network path.
    return build_mcp(runner, toolset, recorder).streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=transport_security_from_env(toolset),
    )
