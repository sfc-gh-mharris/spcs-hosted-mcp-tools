"""AI SQL function tools (pattern B1) against a fake QueryRunner: SQL shape, binds, caps, parsing."""

import json

import pytest
from fakes import FakeRunner
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.cortex_tools import DEFAULT_MODEL, MAX_PROMPT_CHARS, MODELS
from mcp_server.server import build_mcp

pytestmark = pytest.mark.anyio

COMPLETE_ROW = {"R": json.dumps({
    "choices": [{"messages": "Snowflake is a data cloud."}],
    "model": "claude-haiku-4-5",
    "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
})}


async def _call(runner, tool, args):
    async with Client(build_mcp(runner)) as client:
        return await client.call_tool(tool, args)


async def test_private_toolset_lists_cortex_tools():
    async with Client(build_mcp(FakeRunner())) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert {"cortex_complete", "cortex_classify", "cortex_sentiment"} <= set(tools)
    # The allow-list is part of the schema, so clients can offer it as a choice.
    assert tools["cortex_complete"].input_schema["properties"]["model"]["enum"] == list(MODELS)


async def test_complete_binds_everything_and_parses_text_and_usage():
    runner = FakeRunner(rows=[COMPLETE_ROW])
    result = await _call(runner, "cortex_complete", {"prompt": "What is Snowflake?", "max_tokens": 50})
    assert not result.is_error, result.content
    assert result.structured_content == {
        "text": "Snowflake is a data cloud.",
        "model": DEFAULT_MODEL,
        "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
        "query_id": "qid-fake",
    }
    sql, params, timeout_s = runner.calls[0]
    assert "AI_COMPLETE" in sql and "show_details => TRUE" in sql
    assert "What is Snowflake?" not in sql  # user text is bound, never spliced
    assert params[:2] == [DEFAULT_MODEL, "What is Snowflake?"]
    assert json.loads(params[2]) == {"max_tokens": 50, "temperature": 0}
    assert timeout_s == 120


async def test_complete_accepts_another_allow_listed_model():
    runner = FakeRunner(rows=[COMPLETE_ROW])
    result = await _call(runner, "cortex_complete", {"prompt": "hi", "model": "llama3.3-70b"})
    assert not result.is_error
    assert runner.calls[0][1][0] == "llama3.3-70b"


async def test_complete_rejects_models_outside_the_allow_list_without_running_sql():
    runner = FakeRunner(rows=[COMPLETE_ROW])
    result = await _call(runner, "cortex_complete", {"prompt": "hi", "model": "some-expensive-model"})
    assert result.is_error
    assert runner.calls == []


async def test_complete_rejects_oversized_prompts_without_running_sql():
    runner = FakeRunner(rows=[COMPLETE_ROW])
    result = await _call(runner, "cortex_complete", {"prompt": "x" * (MAX_PROMPT_CHARS + 1)})
    assert result.is_error
    assert runner.calls == []


async def test_complete_reports_null_results_as_errors():
    result = await _call(FakeRunner(rows=[{"R": None}]), "cortex_complete", {"prompt": "hi"})
    assert result.is_error
    assert "no result" in result.content[0].text.lower()


async def test_classify_returns_the_label():
    runner = FakeRunner(rows=[{"R": json.dumps({"labels": ["billing"]})}])
    result = await _call(runner, "cortex_classify", {"text": "Charged twice", "categories": ["billing", "shipping"]})
    assert not result.is_error, result.content
    assert result.structured_content == {"label": "billing", "query_id": "qid-fake"}
    sql, params, _ = runner.calls[0]
    assert "AI_CLASSIFY(?, PARSE_JSON(?)::ARRAY)" in sql
    assert params == ["Charged twice", json.dumps(["billing", "shipping"])]


@pytest.mark.parametrize("categories", [["only-one"], [f"c{i}" for i in range(21)], ["same", "same"]])
async def test_classify_validates_categories_without_running_sql(categories):
    runner = FakeRunner(rows=[{"R": json.dumps({"labels": ["x"]})}])
    result = await _call(runner, "cortex_classify", {"text": "t", "categories": categories})
    assert result.is_error
    assert runner.calls == []


async def test_sentiment_returns_overall_sentiment():
    runner = FakeRunner(rows=[{"R": json.dumps({"categories": [{"name": "overall", "sentiment": "negative"}]})}])
    result = await _call(runner, "cortex_sentiment", {"text": "It broke on day one"})
    assert not result.is_error, result.content
    assert result.structured_content == {"sentiment": "negative", "query_id": "qid-fake"}
    assert runner.calls[0][0].startswith("SELECT AI_SENTIMENT(?)")


async def test_snowflake_errors_surface_with_code_and_query_id():
    runner = FakeRunner(error=ToolError("Snowflake error 001015: bad argument (query_id q-1)"))
    result = await _call(runner, "cortex_sentiment", {"text": "fine"})
    assert result.is_error
    assert "001015" in result.content[0].text and "q-1" in result.content[0].text
