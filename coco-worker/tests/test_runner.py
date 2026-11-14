"""run_task with a fake query(): shaping, caps, errors. Uses the SDK's own message classes."""

import anyio
import pytest
from cortex_agent_sdk.cortexcode import AssistantMessage, ResultMessage, SystemMessage, TextBlock, ToolUseBlock

from coco_worker.runner import RunSettings, run_task

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _result(**overrides):
    fields = dict(subtype="success", duration_ms=1200, duration_api_ms=900, is_error=False, num_turns=2,
                  session_id="s1", result="0 tables, 0 views, 0 functions",
                  usage={"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 300})
    fields.update(overrides)
    return ResultMessage(**fields)


def fake_query(messages, seen=None, delay=0.0):
    async def query(*, prompt, options):
        if seen is not None:
            seen.append((prompt, options))
        for message in messages:
            if delay:
                await anyio.sleep(delay)
            yield message
    return query


SETTINGS = RunSettings(connection="default", model="claude-sonnet-5", cli_path="/usr/local/bin/cortex", workdir="/tmp")


async def test_shapes_a_successful_run():
    messages = [
        SystemMessage(subtype="init", data={"model": "claude-sonnet-5", "tools": ["sql_execute", "read"]}),
        AssistantMessage(content=[ToolUseBlock(id="t1", name="sql_execute", input={"sql": "SHOW TABLES"})], model="m"),
        AssistantMessage(content=[TextBlock(text="0 tables, 0 views, 0 functions")], model="m"),
        _result(),
    ]
    seen = []
    out = await run_task("count objects", max_turns=5, timeout_s=30, settings=SETTINGS, query_fn=fake_query(messages, seen))
    assert out["ok"] is True
    assert out["answer"] == "0 tables, 0 views, 0 functions"
    assert out["turns"] == 2
    assert out["tool_uses"] == [{"name": "sql_execute", "input": {"sql": "SHOW TABLES"}}]
    assert out["model"] == "claude-sonnet-5"
    assert out["usage"]["output_tokens"] == 20
    assert out["denials"] == []

    prompt, options = seen[0]
    assert prompt == "count objects"
    assert options.max_turns == 5
    assert options.connection == "default"
    assert options.model == "claude-sonnet-5"
    assert options.can_use_tool is not None
    assert "ask_user_question" in options.disallowed_tools
    assert options.no_mcp is True


async def test_cli_env_overrides_reach_the_cli_options():
    settings = RunSettings(connection="default", model="m", cli_path=None, workdir="/tmp",
                           cli_env={"SNOWFLAKE_HOME": "/home/app/.snowflake"})
    seen = []
    await run_task("x", max_turns=1, timeout_s=30, settings=settings, query_fn=fake_query([_result()], seen))
    assert seen[0][1].env == {"SNOWFLAKE_HOME": "/home/app/.snowflake"}


async def test_error_results_are_reported_not_raised():
    out = await run_task("x", max_turns=2, timeout_s=30, settings=SETTINGS,
                         query_fn=fake_query([_result(subtype="error_max_turns", is_error=True, result=None)]))
    assert out["ok"] is False
    assert out["subtype"] == "error_max_turns"


async def test_runs_that_exceed_the_wall_clock_cap_are_stopped():
    slow = fake_query([AssistantMessage(content=[TextBlock(text="thinking")], model="m"), _result()], delay=0.5)
    out = await run_task("x", max_turns=2, timeout_s=0.2, settings=SETTINGS, query_fn=slow)
    assert out["ok"] is False
    assert out["subtype"] == "timeout"


async def test_cli_failures_are_reported_with_their_message():
    async def broken(*, prompt, options):
        raise RuntimeError("Cortex Code not found at: /nope")
        yield  # pragma: no cover

    out = await run_task("x", max_turns=2, timeout_s=30, settings=SETTINGS, query_fn=broken)
    assert out["ok"] is False
    assert out["subtype"] == "exception"
    assert "not found" in out["error"]


async def test_cli_stderr_is_included_when_the_process_fails():
    async def broken(*, prompt, options):
        options.stderr("Error: connection 'default' could not authenticate")
        raise RuntimeError("Command failed with exit code 1")
        yield  # pragma: no cover

    out = await run_task("x", max_turns=2, timeout_s=30, settings=SETTINGS, query_fn=broken)
    assert "could not authenticate" in out["error"]


async def test_a_missing_result_message_is_an_error():
    out = await run_task("x", max_turns=2, timeout_s=30, settings=SETTINGS,
                         query_fn=fake_query([AssistantMessage(content=[TextBlock(text="partial")], model="m")]))
    assert out["ok"] is False
    assert out["answer"] == "partial"
