"""ask_coding_agent (pattern B3): AGENT_RUN with an inline code_toolset_all spec."""

import json
from pathlib import Path

import pytest
from fakes import FakeRunner
from mcp import Client

from mcp_server.agent_tools import CODING_MODEL, MAX_CODING_SECONDS, parse_agent_response
from mcp_server.server import build_mcp

pytestmark = pytest.mark.anyio

CODING_RAW = (Path(__file__).parent / "fixtures" / "agent_run_coding.json").read_text()


def test_parses_sandbox_tool_calls_from_a_real_coding_agent_run():
    parsed = parse_agent_response(CODING_RAW)
    assert [u.name for u in parsed.tool_uses] == ["snowflake_sql_execute"] * 4
    assert all(u.status == "success" for u in parsed.tool_uses)
    assert any(u.input.get("sql", "").startswith("SHOW TABLES") for u in parsed.tool_uses)
    assert "0" in parsed.answer
    assert parsed.model == "claude-sonnet-5"
    assert parsed.input_tokens > 100_000


async def _call(runner, args):
    async with Client(build_mcp(runner)) as client:
        return await client.call_tool("ask_coding_agent", args)


async def test_sends_an_inline_read_only_spec_with_always_allow_and_a_budget():
    runner = FakeRunner(rows=[{"R": CODING_RAW}])
    result = await _call(runner, {"task": "List and count the tables in MCP_SPCS_DEMO.APP.", "max_seconds": 120})
    assert not result.is_error, result.content
    data = result.structured_content
    assert data["tool_uses"][0]["name"] == "snowflake_sql_execute"
    assert data["query_id"] == "qid-fake"

    sql, params, timeout_s = runner.calls[0]
    assert sql == "SELECT SNOWFLAKE.CORTEX.AGENT_RUN(?) AS R"
    body = json.loads(params[0])
    assert body["tools"] == [{"tool_spec": {"type": "code_toolset_all", "name": "code_toolset_all"}}]
    assert body["tool_resources"]["code_toolset_all"]["permission_policy"] == {"type": "always_allow"}
    assert body["orchestration"]["budget"]["seconds"] == 120
    assert body["models"] == {"orchestration": CODING_MODEL}
    assert "read-only" in body["instructions"]["system"].lower()
    assert body["messages"][0]["content"][0]["text"] == "List and count the tables in MCP_SPCS_DEMO.APP."
    # The SQL timeout leaves headroom over the agent's own budget.
    assert timeout_s > 120


async def test_budget_is_capped():
    runner = FakeRunner(rows=[{"R": CODING_RAW}])
    result = await _call(runner, {"task": "t", "max_seconds": MAX_CODING_SECONDS + 1})
    assert result.is_error
    assert runner.calls == []


async def test_ask_coding_agent_is_not_on_the_public_toolset():
    async with Client(build_mcp(FakeRunner(), toolset="public")) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert "ask_coding_agent" not in names
