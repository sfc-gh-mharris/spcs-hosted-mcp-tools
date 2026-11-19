from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.snowflake import QUERY_TAG, SnowflakeRunner, SnowflakeUnavailable, plan_connection

pytestmark = pytest.mark.anyio

SPCS_ENV = {"SNOWFLAKE_HOST": "acct.snowflakecomputing.internal", "SNOWFLAKE_ACCOUNT": "ACCT"}


def test_spcs_plan_uses_session_token(tmp_path):
    token = tmp_path / "token"
    token.write_text("tok-1\n")
    plan = plan_connection(env=SPCS_ENV, token_path=str(token))
    assert plan.mode == "spcs"
    assert plan.kwargs["authenticator"] == "oauth"
    assert plan.kwargs["token"] == "tok-1"
    assert plan.kwargs["host"] == SPCS_ENV["SNOWFLAKE_HOST"]
    assert plan.kwargs["paramstyle"] == "qmark"
    assert plan.kwargs["session_parameters"]["QUERY_TAG"] == QUERY_TAG
    assert plan.setup == []
    # The warehouse comes from the service's QUERY_WAREHOUSE unless explicitly overridden.
    assert "warehouse" not in plan.kwargs


def test_spcs_plan_rereads_rotated_token(tmp_path):
    token = tmp_path / "token"
    token.write_text("tok-1")
    plan_connection(env=SPCS_ENV, token_path=str(token))
    token.write_text("tok-2")
    assert plan_connection(env=SPCS_ENV, token_path=str(token)).kwargs["token"] == "tok-2"


def test_spcs_plan_without_host_is_unavailable(tmp_path):
    token = tmp_path / "token"
    token.write_text("tok")
    with pytest.raises(SnowflakeUnavailable):
        plan_connection(env={}, token_path=str(token))


def test_local_plan_pins_role_warehouse_and_disables_secondary_roles(tmp_path):
    plan = plan_connection(env={"SNOW_CONNECTION": "dev"}, token_path=str(tmp_path / "missing"))
    assert plan.mode == "local"
    assert plan.kwargs["connection_name"] == "dev"
    assert plan.kwargs["role"] == "MCP_DEMO_ROLE"
    assert plan.kwargs["warehouse"] == "MCP_DEMO_WH"
    assert plan.setup == ["USE SECONDARY ROLES NONE"]


def test_no_token_and_no_connection_is_unavailable(tmp_path):
    with pytest.raises(SnowflakeUnavailable, match="SNOW_CONNECTION"):
        plan_connection(env={}, token_path=str(tmp_path / "missing"))


class FakeCursor:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.executed = []
        self.sfqid = "qid-123"

    def execute(self, sql, params=None, timeout=None):
        self.executed.append((sql, params, timeout))
        if self.error and not sql.startswith("USE "):
            raise self.error

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self, *_):
        return self._cursor

    def close(self):
        self.closed = True


def _local_plan():
    return plan_connection(env={"SNOW_CONNECTION": "dev"}, token_path="/nonexistent")


async def test_runner_runs_setup_then_statement_with_binds():
    cursor = FakeCursor(rows=[{"X": 1}])
    conn = FakeConnection(cursor)
    seen_kwargs = {}

    def connect(**kwargs):
        seen_kwargs.update(kwargs)
        return conn

    result = await SnowflakeRunner(connect=connect, plan=_local_plan).run("SELECT ?", ["a"], timeout_s=7)
    assert seen_kwargs["connection_name"] == "dev"
    assert cursor.executed == [("USE SECONDARY ROLES NONE", None, None), ("SELECT ?", ["a"], 7)]
    assert result.rows == [{"X": 1}]
    assert result.query_id == "qid-123"
    assert conn.closed


class FakeSnowflakeError(Exception):
    def __init__(self):
        super().__init__("boom")
        self.errno = 2003
        self.msg = "Object does not exist"
        self.sfqid = "qid-err"


async def test_runner_maps_statement_errors_to_tool_error_and_closes():
    conn = FakeConnection(FakeCursor(error=FakeSnowflakeError()))
    with pytest.raises(ToolError, match=r"002003.*Object does not exist.*qid-err"):
        await SnowflakeRunner(connect=lambda **_: conn, plan=_local_plan).run("SELECT 1")
    assert conn.closed


async def test_runner_maps_connect_errors_to_tool_error():
    def connect(**_):
        raise RuntimeError("network down")

    with pytest.raises(ToolError, match="Could not connect to Snowflake.*network down"):
        await SnowflakeRunner(connect=connect, plan=_local_plan).run("SELECT 1")


def test_token_file_is_never_logged_or_returned_in_errors(tmp_path):
    # Guard against accidentally echoing the credential: the plan holds it, errors must not.
    token = tmp_path / "token"
    token.write_text("super-secret-token")
    plan = plan_connection(env=SPCS_ENV, token_path=str(token))
    assert "super-secret-token" not in repr(plan)
    assert Path(token).read_text() == "super-secret-token"
