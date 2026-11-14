"""Snowflake-backed tools exercised in process against a fake QueryRunner."""

from collections.abc import Sequence
from typing import Any

import pytest
from mcp import Client

from mcp_server.server import build_mcp
from mcp_server.snowflake import QueryResult, SnowflakeUnavailable

pytestmark = pytest.mark.anyio


class FakeRunner:
    """Records statements and returns canned rows, or raises a given error."""

    def __init__(self, rows: list[dict[str, Any]] | None = None, error: Exception | None = None):
        self.rows = rows or []
        self.error = error
        self.calls: list[tuple[str, list[Any], int]] = []

    async def run(self, sql: str, params: Sequence[Any] = (), timeout_s: int = 60) -> QueryResult:
        self.calls.append((sql, list(params), timeout_s))
        if self.error:
            raise self.error
        return QueryResult(rows=self.rows, query_id="qid-fake", elapsed_ms=1.0)


WHOAMI_ROW = {"U": "SVC_USER", "R": "MCP_DEMO_ROLE", "W": "MCP_DEMO_WH", "A": "ACCT", "G": "AWS_US_EAST_1"}


async def test_whoami_returns_session_identity():
    runner = FakeRunner(rows=[WHOAMI_ROW])
    async with Client(build_mcp(runner)) as client:
        result = await client.call_tool("snowflake_whoami", {})
    assert not result.is_error, result.content
    assert result.structured_content == {
        "user": "SVC_USER",
        "role": "MCP_DEMO_ROLE",
        "warehouse": "MCP_DEMO_WH",
        "account": "ACCT",
        "region": "AWS_US_EAST_1",
        "query_id": "qid-fake",
    }
    assert "CURRENT_ROLE()" in runner.calls[0][0]


async def test_whoami_reports_missing_configuration_as_tool_error():
    runner = FakeRunner(error=SnowflakeUnavailable("Snowflake is not configured here"))
    async with Client(build_mcp(runner)) as client:
        result = await client.call_tool("snowflake_whoami", {})
    assert result.is_error
    assert "not configured" in result.content[0].text


async def test_add_still_works_alongside_snowflake_tools():
    async with Client(build_mcp(FakeRunner())) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        result = await client.call_tool("add", {"a": 2, "b": 3})
    assert {"add", "snowflake_whoami"} <= names
    assert result.structured_content == {"result": 5}
