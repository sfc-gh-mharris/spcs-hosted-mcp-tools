"""Snowflake access for tools: the one place that knows how to connect locally and inside SPCS.

Tools receive a QueryRunner, so unit tests swap in a fake and never touch Snowflake.

- In SPCS, Snowflake mounts a short-lived OAuth token at /snowflake/session/token and sets
  SNOWFLAKE_HOST and SNOWFLAKE_ACCOUNT. Sessions run as the service user under the service
  owner role, and pick up the service's QUERY_WAREHOUSE. No egress setup is needed.
- Locally, SNOW_CONNECTION names a Snowflake CLI connection. The session pins MCP_DEMO_ROLE and
  MCP_DEMO_WH and turns secondary roles off, so local runs see the same grants SPCS enforces.
"""

import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import anyio
from mcp.server.mcpserver.exceptions import ToolError

SPCS_TOKEN_PATH = "/snowflake/session/token"
QUERY_TAG = "spcs-mcp-demo"


class SnowflakeUnavailable(ToolError):
    """No way to reach Snowflake from this process (for example, plain Docker Compose)."""


@dataclass(frozen=True)
class QueryResult:
    rows: list[dict[str, Any]]
    query_id: str
    elapsed_ms: float


class QueryRunner(Protocol):
    async def run(self, sql: str, params: Sequence[Any] = (), timeout_s: int = 60) -> QueryResult: ...


@dataclass(frozen=True)
class ConnectionPlan:
    mode: str
    kwargs: dict[str, Any] = field(repr=False)  # holds the token; never print it
    setup: list[str]


def plan_connection(env: Mapping[str, str] = os.environ, token_path: str = SPCS_TOKEN_PATH) -> ConnectionPlan:
    """Decide how to connect. Re-reads the SPCS token every time because Snowflake rotates it."""
    common: dict[str, Any] = {
        "paramstyle": "qmark",  # server-side binding: user text never becomes SQL
        "session_parameters": {"QUERY_TAG": QUERY_TAG},
        "enable_server_session_keep_alive_auto_detection": False,
    }
    if os.path.exists(token_path):
        if not env.get("SNOWFLAKE_HOST") or not env.get("SNOWFLAKE_ACCOUNT"):
            raise SnowflakeUnavailable("SPCS token found but SNOWFLAKE_HOST or SNOWFLAKE_ACCOUNT is not set")
        with open(token_path) as f:
            token = f.read().strip()
        kwargs = {
            **common,
            "host": env["SNOWFLAKE_HOST"],
            "account": env["SNOWFLAKE_ACCOUNT"],
            "authenticator": "oauth",
            "token": token,
        }
        if env.get("SNOWFLAKE_WAREHOUSE"):
            kwargs["warehouse"] = env["SNOWFLAKE_WAREHOUSE"]
        return ConnectionPlan(mode="spcs", kwargs=kwargs, setup=[])

    connection_name = env.get("SNOW_CONNECTION")
    if not connection_name:
        raise SnowflakeUnavailable(
            "Snowflake is not configured here: no SPCS session token and SNOW_CONNECTION is not set"
        )
    kwargs = {
        **common,
        "connection_name": connection_name,
        "role": env.get("SNOWFLAKE_ROLE", "MCP_DEMO_ROLE"),
        "warehouse": env.get("SNOWFLAKE_WAREHOUSE", "MCP_DEMO_WH"),
    }
    return ConnectionPlan(mode="local", kwargs=kwargs, setup=["USE SECONDARY ROLES NONE"])


def _default_connect(**kwargs: Any) -> Any:
    import snowflake.connector  # imported lazily so unit tests and Compose do not need a connection

    return snowflake.connector.connect(**kwargs)


def _dict_cursor(conn: Any) -> Any:
    try:
        from snowflake.connector import DictCursor
    except ImportError:  # fakes in tests
        return conn.cursor()
    return conn.cursor(DictCursor)


def _describe_error(exc: Exception) -> str:
    errno = getattr(exc, "errno", None)
    msg = getattr(exc, "msg", None) or str(exc)
    qid = getattr(exc, "sfqid", None)
    code = f"{errno:06d}" if isinstance(errno, int) else "unknown"
    return f"Snowflake error {code}: {msg}" + (f" (query_id {qid})" if qid else "")


class SnowflakeRunner:
    """Runs one statement per call on a fresh connection, off the event loop.

    A new connection per call is simple and always uses the current SPCS token. Pooling is a
    later optimization if login latency ever matters next to Cortex call times.
    """

    def __init__(
        self,
        connect: Callable[..., Any] = _default_connect,
        plan: Callable[[], ConnectionPlan] = plan_connection,
    ):
        self._connect = connect
        self._plan = plan

    async def run(self, sql: str, params: Sequence[Any] = (), timeout_s: int = 60) -> QueryResult:
        return await anyio.to_thread.run_sync(self._run_sync, sql, list(params), timeout_s)

    def _run_sync(self, sql: str, params: list[Any], timeout_s: int) -> QueryResult:
        plan = self._plan()
        try:
            conn = self._connect(**plan.kwargs)
        except Exception as exc:
            raise ToolError(f"Could not connect to Snowflake ({plan.mode}): {_describe_error(exc)}") from exc
        try:
            cur = _dict_cursor(conn)
            for statement in plan.setup:
                cur.execute(statement)
            start = time.perf_counter()
            try:
                cur.execute(sql, params, timeout=timeout_s)
                rows = cur.fetchall()
            except Exception as exc:
                raise ToolError(_describe_error(exc)) from exc
            return QueryResult(rows=rows, query_id=cur.sfqid, elapsed_ms=round((time.perf_counter() - start) * 1000, 1))
        finally:
            conn.close()
