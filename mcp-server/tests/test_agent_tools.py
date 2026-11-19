"""ask_agent (pattern B2): DATA_AGENT_RUN on an allow-listed agent, parsed into a small result."""

import json
from pathlib import Path

import pytest
from fakes import FakeRunner
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.agent_tools import AGENTS, DEFAULT_AGENT, parse_agent_response
from mcp_server.server import build_mcp

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).parent / "fixtures"
ADD_RAW = (FIXTURES / "data_agent_run_add.json").read_text()
WARNING_RAW = (FIXTURES / "data_agent_run_warning.json").read_text()


def test_parses_a_real_response_with_an_mcp_tool_call():
    parsed = parse_agent_response(ADD_RAW)
    assert "42" in parsed.answer
    assert parsed.status == "completed"
    assert parsed.model == "claude-opus-5-5"
    assert parsed.warnings == []
    assert len(parsed.tool_uses) == 1
    use = parsed.tool_uses[0]
    assert use.name == "mcp_server_public_add"
    assert use.mcp_server == "MCP_SPCS_DEMO.APP.MCP_SERVER_PUBLIC"
    assert use.input == {"a": 19.5, "b": 22.5, "description": "Add 19.5 and 22.5"}
    assert use.status == "success"
    assert parsed.input_tokens == 37230
    assert parsed.output_tokens == 256


def test_parses_warnings_with_their_codes():
    parsed = parse_agent_response(WARNING_RAW)
    assert parsed.tool_uses == []
    assert len(parsed.warnings) == 1
    assert parsed.warnings[0].startswith("399540: Custom MCP server")


def test_answer_is_empty_when_the_agent_returns_no_text():
    parsed = parse_agent_response(json.dumps({"content": [{"type": "thinking", "thinking": {"text": "hmm"}}]}))
    assert parsed.answer == ""


def test_multiple_text_parts_are_joined():
    raw = json.dumps({"content": [{"type": "text", "text": "Part one."}, {"type": "text", "text": "Part two."}]})
    assert parse_agent_response(raw).answer == "Part one.\n\nPart two."


@pytest.mark.parametrize("raw", [
    json.dumps({"code": "399504", "message": "Error during execution"}),
    json.dumps({"status": "failed", "error": {"code": "399504", "message": "Error during execution"}}),
])
def test_error_payloads_raise_tool_errors(raw):
    with pytest.raises(ToolError, match="399504"):
        parse_agent_response(raw)


def test_null_or_non_json_responses_raise_tool_errors():
    with pytest.raises(ToolError):
        parse_agent_response(None)
    with pytest.raises(ToolError):
        parse_agent_response("not json")


async def test_ask_agent_binds_agent_and_body_and_returns_the_parsed_answer():
    runner = FakeRunner(rows=[{"R": ADD_RAW}])
    async with Client(build_mcp(runner)) as client:
        result = await client.call_tool("ask_agent", {"question": "What is 19.5 + 22.5? Use the add tool."})
    assert not result.is_error, result.content
    data = result.structured_content
    assert "42" in data["answer"]
    assert data["agent"] == DEFAULT_AGENT
    assert data["tool_uses"][0]["name"] == "mcp_server_public_add"
    assert data["query_id"] == "qid-fake"

    sql, params, timeout_s = runner.calls[0]
    assert sql == "SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(?, ?) AS R"
    assert params[0] == DEFAULT_AGENT
    body = json.loads(params[1])
    assert body["messages"][0]["content"][0]["text"] == "What is 19.5 + 22.5? Use the add tool."
    assert "19.5" not in sql
    assert timeout_s == 900


async def test_ask_agent_rejects_agents_outside_the_allow_list():
    runner = FakeRunner(rows=[{"R": ADD_RAW}])
    async with Client(build_mcp(runner)) as client:
        result = await client.call_tool("ask_agent", {"question": "hi", "agent": "OTHER_DB.PUBLIC.SOME_AGENT"})
    assert result.is_error
    assert runner.calls == []


async def test_ask_agent_is_not_on_the_public_toolset():
    # A Cortex Agent pointed at the public endpoint must not be able to call back into an agent.
    async with Client(build_mcp(FakeRunner(), toolset="public")) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert "ask_agent" not in names
    assert DEFAULT_AGENT in AGENTS
